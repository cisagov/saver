"""Imported certificate validity times retain the UTC instants in SSLyze CSV."""

# Standard Python Libraries
import calendar
import csv
from datetime import datetime, timedelta, timezone
import io
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch

# Third-Party Libraries
from bson import BSON
from bson.codec_options import CodecOptions

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

# cisagov Libraries
import sslyze_csv2mongo as importer  # noqa: E402 - import the standalone script

FIELDS = [
    "Domain",
    "Base Domain",
    "Scanned Hostname",
    "Scanned Port",
    "STARTTLS SMTP",
    "SSLv2",
    "SSLv3",
    "TLSv1.0",
    "TLSv1.1",
    "TLSv1.2",
    "TLSv1.3",
    "Any Forward Secrecy",
    "All Forward Secrecy",
    "Any RC4",
    "All RC4",
    "Any 3DES",
    "Key Type",
    "Key Length",
    "Signature Algorithm",
    "SHA-1 in Served Chain",
    "SHA-1 in Constructed Chain",
    "Not Before",
    "Not After",
    "Highest Served Issuer",
    "Highest Constructed Issuer",
    "Is Symantec Cert",
    "Symantec Distrust Date",
    "Errors",
]


def make_row(before, after, scanned_port="443"):
    """Supply every field read by the real importer."""
    row = dict.fromkeys(FIELDS, "")
    row.update(
        {
            "Domain": "www.example.test",
            "Base Domain": "example.test",
            "Scanned Hostname": "www.example.test",
            "Scanned Port": scanned_port,
            "Key Length": "2048",
            "TLSv1.2": "True",
            "SSLv3": "False",
            "Not Before": before,
            "Not After": after,
        }
    )
    return row


class CertificateTimesTest(unittest.TestCase):
    """Exercise CSV conversion and BSON encoding without a database connection."""

    def import_rows(self, rows):
        """Capture actual inserted documents at the MongoDB boundary."""
        stream = io.StringIO(newline="")
        writer = csv.DictWriter(stream, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)
        stream.seek(0)
        database = Mock()
        database.name = "fixture"
        database.client.address = ("unused", 27017)
        database.sslyze_scan.delete_many.return_value.deleted_count = 0
        with patch.object(
            importer, "db_from_config", return_value=database
        ), patch.object(importer, "open", return_value=stream), patch(
            "sys.stdout", new=io.StringIO()
        ):
            importer.store_data(
                [["example.test", "Fixture Agency"]],
                {"Fixture Agency": "EXAMPLE"},
                "unused.yml",
            )
        return database, [
            call.args[0] for call in database.sslyze_scan.insert_one.call_args_list
        ]

    def test_validity_endpoints_preserve_utc_in_winter_and_summer(self):
        """Calendar season must not add a local DST-dependent offset."""
        for month in [1, 7]:
            before = f"2026-{month:02d}-02T03:04:05"
            after = f"2026-{month:02d}-03T04:05:06"
            with self.subTest(month=month):
                _, docs = self.import_rows([make_row(before, after)])
                self.assertEqual(len(docs), 1)
                for field, text in [("not_before", before), ("not_after", after)]:
                    expected = datetime.strptime(text, "%Y-%m-%dT%H:%M:%S").replace(
                        tzinfo=timezone.utc
                    )
                    self.assertEqual(docs[0][field], expected)
                    self.assertEqual(docs[0][field].utcoffset(), timedelta(0))

    def test_bson_round_trip_preserves_input_epoch(self):
        """The wire-format timestamp, not just displayed wall time, is correct."""
        _, docs = self.import_rows(
            [make_row("2026-01-02T03:04:05", "2026-07-03T04:05:06")]
        )
        decoded = BSON.encode(docs[0]).decode(codec_options=CodecOptions(tz_aware=True))
        self.assertEqual(
            decoded["not_before"].timestamp(), calendar.timegm((2026, 1, 2, 3, 4, 5))
        )
        self.assertEqual(
            decoded["not_after"].timestamp(), calendar.timegm((2026, 7, 3, 4, 5, 6))
        )

    def test_validity_interval_does_not_gain_or_lose_a_dst_hour(self):
        """Intervals crossing daylight saving changes retain their duration."""
        for before, after in [
            ("2026-03-07T12:00:00", "2026-03-09T12:00:00"),
            ("2026-10-31T12:00:00", "2026-11-02T12:00:00"),
        ]:
            with self.subTest(before=before):
                _, docs = self.import_rows([make_row(before, after)])
                elapsed = (
                    docs[0]["not_after"].timestamp() - docs[0]["not_before"].timestamp()
                )
                self.assertEqual(elapsed, 2 * 24 * 3600)

    def test_certificate_is_expired_immediately_after_its_real_expiry(self):
        """An Eastern-time reinterpretation must not extend certificate validity."""
        _, docs = self.import_rows(
            [make_row("2026-01-01T00:00:00", "2026-01-02T03:04:05")]
        )
        observation = datetime(2026, 1, 2, 3, 4, 6, tzinfo=timezone.utc)
        self.assertLess(docs[0]["not_after"], observation)

    def test_missing_times_and_existing_non_time_fields_are_preserved(self):
        """The correction does not change null, boolean or ownership handling."""
        database, docs = self.import_rows([make_row("", "")])
        self.assertIsNone(docs[0]["not_before"])
        self.assertIsNone(docs[0]["not_after"])
        self.assertIs(docs[0]["tlsv1_2"], True)
        self.assertIs(docs[0]["sslv3"], False)
        self.assertEqual(docs[0]["scanned_port"], 443)
        self.assertEqual(docs[0]["agency"], {"id": "EXAMPLE", "name": "Fixture Agency"})
        self.assertIs(docs[0]["latest"], True)
        database.sslyze_scan.update_many.assert_called_once()
        database.sslyze_scan.delete_many.assert_called_once()

    def test_unscanned_rows_are_still_skipped(self):
        """Rows without a scanned port do not create certificate records."""
        _, docs = self.import_rows([make_row("", "", scanned_port="")])
        self.assertEqual(docs, [])


if __name__ == "__main__":
    unittest.main()
