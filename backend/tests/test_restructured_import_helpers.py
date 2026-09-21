import tempfile
import unittest
from pathlib import Path
import os
import sys

from openpyxl import Workbook

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

os.environ.setdefault("JWT_SECRET_KEY", "RestructuredHelpersNeedAVeryStrongSecret!2026")
os.environ.setdefault("DATABASE_URL", f"sqlite:///{(BACKEND_DIR / 'tmp_restructured_helpers.db').as_posix()}")

from app.services.restructured import (
    CONSOLIDATED_FAMILY,
    RESTRUCTURED_FAMILY,
    _credit_family_from_category,
    _normalize_contract_key,
    _stream_schedule_csv_to_csv,
    _stream_schedule_xlsx_to_csv,
    _tracked_mcr_credit_family,
)


class RestructuredImportHelpersTest(unittest.TestCase):
    def test_normalize_contract_key_strips_spaces_and_excel_suffix(self):
        self.assertEqual(_normalize_contract_key(" 000123.0 "), "000123")
        self.assertEqual(_normalize_contract_key("AB 45 67"), "AB4567")

    def test_credit_family_detects_consolidated_label(self):
        self.assertEqual(
            _credit_family_from_category("Credits Consolidés"),
            CONSOLIDATED_FAMILY,
        )
        self.assertEqual(
            _credit_family_from_category("credits consolides"),
            CONSOLIDATED_FAMILY,
        )
        self.assertEqual(
            _credit_family_from_category("Micro crédit"),
            RESTRUCTURED_FAMILY,
        )

    def test_tracked_mcr_family_ignores_non_target_categories(self):
        self.assertEqual(
            _tracked_mcr_credit_family("Credits Consolidés"),
            CONSOLIDATED_FAMILY,
        )
        self.assertEqual(
            _tracked_mcr_credit_family("Credits Restructurés"),
            RESTRUCTURED_FAMILY,
        )
        self.assertIsNone(_tracked_mcr_credit_family("Commerce"))

    def test_stream_schedule_xlsx_to_csv_keeps_only_useful_contracts(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            source_path = Path(tmp_dir) / "schedule.xlsx"
            csv_path = Path(tmp_dir) / "filtered.csv"
            workbook = Workbook()
            sheet = workbook.active
            sheet.append(
                [
                    "Numéro Contrat Abacus (AccountNumber)",
                    "N° d'Echéance",
                    "Date d'échéance",
                    "Échéance payée en capital",
                    "Capital dû",
                    "Nom Agence",
                    "Nom du GP",
                ]
            )
            sheet.append(["000123.0", 1, "2026-01-10", 100, 100, "AG 1", "GP 1"])
            sheet.append(["999999", 1, "2026-01-10", 50, 100, "AG 2", "GP 2"])
            workbook.save(source_path)
            workbook.close()

            row_count, metrics = _stream_schedule_xlsx_to_csv(
                source_path,
                csv_path,
                useful_contracts={"000123"},
            )

            self.assertEqual(row_count, 1)
            self.assertEqual(metrics["source_rows"], 2)
            self.assertEqual(metrics["accepted_rows"], 1)
            self.assertEqual(metrics["ignored_rows"], 1)
            csv_lines = csv_path.read_text(encoding="utf-8").strip().splitlines()
            self.assertEqual(len(csv_lines), 1)
            self.assertIn("000123", csv_lines[0])
            self.assertNotIn("999999", csv_lines[0])

    def test_stream_schedule_csv_to_csv_keeps_only_useful_contracts(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            source_path = Path(tmp_dir) / "schedule.csv"
            csv_path = Path(tmp_dir) / "filtered.csv"
            source_path.write_text(
                "\n".join(
                    [
                        "AccountNumber,N° d'Echéance,Date d'échéance,Échéance payée en capital,Capital dû,Nom Agence,Nom du GP",
                        "000123.0,1,2026-01-10,100,100,AG 1,GP 1",
                        "999999,1,2026-01-10,50,100,AG 2,GP 2",
                    ]
                ),
                encoding="utf-8",
            )

            row_count, metrics = _stream_schedule_csv_to_csv(
                source_path,
                csv_path,
                useful_contracts={"000123"},
            )

            self.assertEqual(row_count, 1)
            self.assertEqual(metrics["source_rows"], 2)
            self.assertEqual(metrics["accepted_rows"], 1)
            self.assertEqual(metrics["ignored_rows"], 1)
            csv_lines = csv_path.read_text(encoding="utf-8").strip().splitlines()
            self.assertEqual(len(csv_lines), 1)
            self.assertIn("000123", csv_lines[0])
            self.assertNotIn("999999", csv_lines[0])


if __name__ == "__main__":
    unittest.main()
