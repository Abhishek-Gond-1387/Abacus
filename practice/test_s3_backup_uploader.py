"""Offline checks for the optional S3 backup uploader helpers."""

from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from db.s3_backup_uploader import _remote_matches, _target


class S3BackupUploaderTests(unittest.TestCase):
    def test_target_parses_bucket_and_prefix(self) -> None:
        with patch.dict("os.environ", {"S3_BACKUP_URI": "s3://abacus-backups/prod/db"}):
            self.assertEqual(_target(), ("abacus-backups", "prod/db"))

    def test_target_rejects_non_s3_uris(self) -> None:
        with patch.dict("os.environ", {"S3_BACKUP_URI": "https://example.com/backups"}):
            with self.assertRaisesRegex(ValueError, "s3://"):
                _target()

    def test_existing_archive_is_verified_by_size_and_sha256_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            archive = Path(temporary) / "abacus-20261104T120000Z.dump"
            archive.write_bytes(b"verified backup bytes")
            digest = hashlib.sha256(archive.read_bytes()).hexdigest()

            class ExistingS3Object:
                def head_object(self, **_kwargs):
                    return {
                        "ContentLength": archive.stat().st_size,
                        "Metadata": {"abacus-sha256": digest},
                    }

            self.assertTrue(_remote_matches(
                ExistingS3Object(), bucket="abacus-backups", key=archive.name,
                path=archive, digest=digest,
            ))

    def test_missing_remote_object_is_uploaded_again(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            archive = Path(temporary) / "abacus-20261104T120000Z.dump"

            class MissingS3Object:
                def head_object(self, **_kwargs):
                    error = RuntimeError("Not found")
                    error.response = {
                        "Error": {"Code": "404"},
                        "ResponseMetadata": {"HTTPStatusCode": 404},
                    }
                    raise error

            self.assertFalse(_remote_matches(
                MissingS3Object(), bucket="abacus-backups", key=archive.name,
                path=archive, digest="unused",
            ))


if __name__ == "__main__":
    unittest.main()
