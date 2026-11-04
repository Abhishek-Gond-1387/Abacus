"""Upload completed PostgreSQL backup archives to an SSE-KMS S3 prefix."""

from __future__ import annotations

import hashlib
import logging
import os
import re
import time
from pathlib import Path
from urllib.parse import urlparse

LOGGER = logging.getLogger("abacus.s3_backup_uploader")
ARCHIVE_NAME = re.compile(r"^abacus-\d{8}T\d{6}Z\.dump$")


def _required(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise ValueError(f"{name} must be configured for the offsite backup profile.")
    return value


def _target() -> tuple[str, str]:
    parsed = urlparse(_required("S3_BACKUP_URI"))
    if parsed.scheme != "s3" or not parsed.netloc or parsed.query or parsed.fragment:
        raise ValueError("S3_BACKUP_URI must be an s3://bucket/optional-prefix URI.")
    prefix = parsed.path.strip("/")
    return parsed.netloc, prefix


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as archive:
        for chunk in iter(lambda: archive.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _remote_matches(client, *, bucket: str, key: str, path: Path, digest: str) -> bool:
    try:
        response = client.head_object(Bucket=bucket, Key=key)
    except Exception as error:
        response = getattr(error, "response", {})
        code = response.get("Error", {}).get("Code")
        status = response.get("ResponseMetadata", {}).get("HTTPStatusCode")
        if code in {"404", "NoSuchKey", "NotFound"} or status == 404:
            return False
        raise
    metadata = response.get("Metadata", {})
    return response.get("ContentLength") == path.stat().st_size and metadata.get("abacus-sha256") == digest


def main() -> None:
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    region = _required("AWS_REGION")
    kms_key_id = _required("S3_KMS_KEY_ID")
    bucket, prefix = _target()
    interval = int(os.getenv("S3_BACKUP_INTERVAL_SECONDS", "300"))
    if interval < 30:
        raise ValueError("S3_BACKUP_INTERVAL_SECONDS must be at least 30 seconds.")
    backup_dir = Path(os.getenv("BACKUP_DIRECTORY", "/backups"))
    import boto3

    session = boto3.Session(region_name=region)
    if session.get_credentials() is None:
        raise ValueError("Configure AWS credentials or an attached AWS task role for the offsite uploader.")
    client = session.client("s3")

    while True:
        for archive in sorted(backup_dir.glob("abacus-*.dump")):
            if not ARCHIVE_NAME.fullmatch(archive.name) or not archive.is_file():
                continue
            digest = _sha256(archive)
            key = "/".join(part for part in (prefix, archive.name) if part)
            try:
                if _remote_matches(client, bucket=bucket, key=key, path=archive, digest=digest):
                    continue
                client.upload_file(
                    str(archive), bucket, key,
                    ExtraArgs={
                        "ServerSideEncryption": "aws:kms",
                        "SSEKMSKeyId": kms_key_id,
                        "Metadata": {"abacus-sha256": digest},
                    },
                )
                LOGGER.info("Uploaded validated backup archive %s", archive.name)
            except Exception as error:
                LOGGER.error(
                    "Could not upload backup archive %s (%s)",
                    archive.name,
                    type(error).__name__,
                )
        time.sleep(interval)


if __name__ == "__main__":
    main()
