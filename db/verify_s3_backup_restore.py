"""Restore a local or S3 PostgreSQL archive in a disposable test database."""

from __future__ import annotations

import argparse
import hashlib
import logging
import os
import re
import secrets
import subprocess
import tempfile
import time
import uuid
from pathlib import Path

from db.s3_backup_uploader import ARCHIVE_NAME, _required, _target

LOGGER = logging.getLogger("abacus.s3_backup_restore_check")
SHA256_HEX = re.compile(r"^[0-9a-f]{64}$")
DEFAULT_POSTGRES_IMAGE = "postgres:17-alpine"


def _latest_archive_key(client, *, bucket: str, prefix: str) -> str:
    """Find the lexicographically newest timestamped archive in the configured prefix."""
    list_prefix = f"{prefix}/" if prefix else ""
    continuation_token: str | None = None
    candidates: list[str] = []

    while True:
        request: dict[str, str] = {"Bucket": bucket, "Prefix": list_prefix}
        if continuation_token:
            request["ContinuationToken"] = continuation_token
        response = client.list_objects_v2(**request)
        for item in response.get("Contents", []):
            key = item.get("Key", "")
            name = key.rsplit("/", 1)[-1]
            if key.startswith(list_prefix) and ARCHIVE_NAME.fullmatch(name):
                candidates.append(key)
        if not response.get("IsTruncated"):
            break
        continuation_token = response.get("NextContinuationToken")
        if not continuation_token:
            raise RuntimeError("S3 returned a truncated listing without a continuation token.")

    if not candidates:
        raise FileNotFoundError(
            f"No validated Abacus backup archives found under s3://{bucket}/{list_prefix}"
        )
    return max(candidates, key=lambda key: key.rsplit("/", 1)[-1])


def _latest_local_archive(directory: Path) -> Path:
    """Find the newest completed archive in a local or cloud-synced directory."""
    archives = [
        path for path in directory.glob("abacus-*.dump")
        if path.is_file() and ARCHIVE_NAME.fullmatch(path.name)
    ]
    if not archives:
        raise FileNotFoundError(f"No completed Abacus backup archives found in {directory}.")
    return max(archives, key=lambda path: path.name)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as archive:
        for chunk in iter(lambda: archive.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _download_verified(client, *, bucket: str, key: str, destination: Path) -> None:
    """Download one archive and verify its size and uploader-written SHA-256 metadata."""
    head = client.head_object(Bucket=bucket, Key=key)
    expected_digest = head.get("Metadata", {}).get("abacus-sha256", "").lower()
    if not SHA256_HEX.fullmatch(expected_digest):
        raise ValueError(f"S3 object {key!r} has no valid abacus-sha256 metadata.")

    client.download_file(bucket, key, str(destination))
    actual_size = destination.stat().st_size
    if actual_size != head.get("ContentLength") or _sha256(destination) != expected_digest:
        destination.unlink(missing_ok=True)
        raise ValueError(f"Downloaded archive {key!r} failed size or SHA-256 verification.")


def _docker(*arguments: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        ["docker", *arguments],
        check=False,
        capture_output=True,
        text=True,
        timeout=3600,
    )
    if check and result.returncode:
        detail = result.stderr.strip() or result.stdout.strip() or f"exit code {result.returncode}"
        raise RuntimeError(f"Docker command failed: {detail}")
    return result


def _restore_in_disposable_postgres(archive: Path, *, image: str = DEFAULT_POSTGRES_IMAGE) -> int:
    """Restore an archive in a temporary, isolated container without publishing ports."""
    container = f"abacus-restore-check-{uuid.uuid4().hex[:12]}"
    password = secrets.token_urlsafe(24)
    created = False
    try:
        _docker(
            "run", "--detach", "--rm", "--network", "none", "--name", container,
            "--env", f"POSTGRES_PASSWORD={password}",
            "--env", "POSTGRES_DB=abacus_restore",
            image,
        )
        created = True

        for _ in range(60):
            ready = _docker(
                "exec", container, "pg_isready", "--username=postgres",
                "--dbname=abacus_restore", check=False,
            )
            if ready.returncode == 0:
                break
            time.sleep(1)
        else:
            raise TimeoutError("Disposable PostgreSQL did not become ready within 60 seconds.")

        _docker("cp", str(archive), f"{container}:/tmp/abacus-backup.dump")
        _docker(
            "exec", container, "pg_restore", "--exit-on-error", "--no-owner", "--no-acl",
            "--username=postgres", "--dbname=abacus_restore", "/tmp/abacus-backup.dump",
        )
        result = _docker(
            "exec", container, "psql", "--no-psqlrc", "--set=ON_ERROR_STOP=1",
            "--username=postgres", "--dbname=abacus_restore", "--tuples-only", "--no-align",
            "--command=SELECT count(*) FROM information_schema.tables "
            "WHERE table_schema = 'public' AND table_type = 'BASE TABLE';",
        )
        try:
            table_count = int(result.stdout.strip())
        except ValueError as error:
            raise RuntimeError("Restored database did not return a valid public-table count.") from error
        if table_count < 1:
            raise RuntimeError("Archive restored, but the disposable database contains no public tables.")
        return table_count
    finally:
        if created:
            _docker("rm", "--force", "--volumes", container, check=False)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--local-dir",
        type=Path,
        help="Restore the newest completed archive from a local or OneDrive-synced folder (no AWS needed).",
    )
    arguments = parser.parse_args()

    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    image = os.getenv("POSTGRES_RESTORE_IMAGE", DEFAULT_POSTGRES_IMAGE).strip()
    if not image:
        raise ValueError("POSTGRES_RESTORE_IMAGE cannot be empty.")

    if arguments.local_dir is not None:
        archive = _latest_local_archive(arguments.local_dir.expanduser().resolve())
        LOGGER.info("Checking local backup %s (SHA-256 %s)", archive.name, _sha256(archive))
        table_count = _restore_in_disposable_postgres(archive, image=image)
        LOGGER.info("Restore check passed: %s public tables restored from %s", table_count, archive.name)
        return

    region = _required("AWS_REGION")
    bucket, prefix = _target()

    import boto3

    session = boto3.Session(region_name=region)
    if session.get_credentials() is None:
        raise ValueError("Configure AWS credentials or an attached AWS role before checking S3 restores.")
    client = session.client("s3")
    key = _latest_archive_key(client, bucket=bucket, prefix=prefix)
    with tempfile.TemporaryDirectory(prefix="abacus-restore-check-") as temporary:
        archive = Path(temporary) / Path(key).name
        _download_verified(client, bucket=bucket, key=key, destination=archive)
        LOGGER.info("Downloaded and SHA-256 verified s3://%s/%s", bucket, key)
        table_count = _restore_in_disposable_postgres(archive, image=image)
        LOGGER.info("Restore check passed: %s public tables restored from %s", table_count, Path(key).name)


if __name__ == "__main__":
    main()
