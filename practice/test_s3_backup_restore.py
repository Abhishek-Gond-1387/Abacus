"""Offline checks for safe S3 backup restore verification."""

from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path
from subprocess import CompletedProcess
from unittest.mock import patch

from db.verify_s3_backup_restore import (
    _download_verified,
    _latest_archive_key,
    _latest_local_archive,
    _restore_in_disposable_postgres,
)


class S3BackupRestoreTests(unittest.TestCase):
    def test_latest_archive_ignores_non_archive_objects_and_respects_prefix(self) -> None:
        class S3:
            def list_objects_v2(self, **kwargs):
                self.request = kwargs
                return {
                    "Contents": [
                        {"Key": "prod/db/notes.txt"},
                        {"Key": "prod/db/abacus-20261103T120000Z.dump"},
                        {"Key": "prod/db/abacus-20261104T120000Z.dump"},
                        {"Key": "prod/other/abacus-20261105T120000Z.dump"},
                    ]
                }

        client = S3()
        self.assertEqual(
            _latest_archive_key(client, bucket="backups", prefix="prod/db"),
            "prod/db/abacus-20261104T120000Z.dump",
        )
        self.assertEqual(client.request["Prefix"], "prod/db/")

    def test_missing_backup_is_an_explicit_error(self) -> None:
        class EmptyS3:
            def list_objects_v2(self, **_kwargs):
                return {"Contents": []}

        with self.assertRaises(FileNotFoundError):
            _latest_archive_key(EmptyS3(), bucket="backups", prefix="")

    def test_latest_local_archive_ignores_temporary_or_unrelated_files(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            (directory / "abacus-20261103T120000Z.dump").write_bytes(b"older")
            (directory / "abacus-20261104T120000Z.dump.tmp").write_bytes(b"unfinished")
            (directory / "notes.txt").write_text("not a backup", encoding="utf-8")
            latest = directory / "abacus-20261104T120000Z.dump"
            latest.write_bytes(b"newer")
            self.assertEqual(_latest_local_archive(directory), latest)

    def test_download_checks_size_and_sha256_metadata(self) -> None:
        payload = b"a valid backup fixture"
        digest = hashlib.sha256(payload).hexdigest()

        class S3:
            def head_object(self, **_kwargs):
                return {"ContentLength": len(payload), "Metadata": {"abacus-sha256": digest}}

            def download_file(self, _bucket, _key, destination):
                Path(destination).write_bytes(payload)

        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / "archive.dump"
            _download_verified(S3(), bucket="backups", key="archive.dump", destination=destination)
            self.assertEqual(destination.read_bytes(), payload)

    def test_corrupt_download_is_removed_and_rejected(self) -> None:
        class S3:
            def head_object(self, **_kwargs):
                return {"ContentLength": 4, "Metadata": {"abacus-sha256": "0" * 64}}

            def download_file(self, _bucket, _key, destination):
                Path(destination).write_bytes(b"bad!")

        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / "archive.dump"
            with self.assertRaisesRegex(ValueError, "failed size or SHA-256"):
                _download_verified(S3(), bucket="backups", key="archive.dump", destination=destination)
            self.assertFalse(destination.exists())

    def test_missing_checksum_metadata_is_rejected_before_download(self) -> None:
        class S3:
            def head_object(self, **_kwargs):
                return {"ContentLength": 4, "Metadata": {}}

            def download_file(self, *_args):
                raise AssertionError("A metadata failure must not download an object.")

        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / "archive.dump"
            with self.assertRaisesRegex(ValueError, "no valid abacus-sha256"):
                _download_verified(S3(), bucket="backups", key="archive.dump", destination=destination)

    def test_restore_uses_an_isolated_container_and_removes_it(self) -> None:
        completed = CompletedProcess(args=["docker"], returncode=0, stdout="4\n", stderr="")
        archive = Path("backup.dump")
        with patch("db.verify_s3_backup_restore._docker", return_value=completed) as docker:
            self.assertEqual(_restore_in_disposable_postgres(archive), 4)

        start = docker.call_args_list[0]
        self.assertEqual(start.args[:3], ("run", "--detach", "--rm"))
        self.assertIn("--network", start.args)
        network_index = start.args.index("--network")
        self.assertEqual(start.args[network_index + 1], "none")
        self.assertEqual(docker.call_args_list[-1].args[0:3], ("rm", "--force", "--volumes"))


if __name__ == "__main__":
    unittest.main()
