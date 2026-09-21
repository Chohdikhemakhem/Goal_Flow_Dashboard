from datetime import date
from pathlib import Path
import sys
import unittest

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.restructured import (
    CLOSURE_STATUS_ASSUMED_CLOSED,
    CLOSURE_STATUS_IN_PROGRESS,
    CLOSURE_STATUS_NA,
    build_restructured_analysis_frames,
)


class RestructuredAnalysisTests(unittest.TestCase):
    REFERENCE_DATE = date(2026, 7, 15)

    def _contracts_frame(self, rows):
        return pd.DataFrame(rows)

    def _schedule_frame(self, rows):
        return pd.DataFrame(rows)

    def _paid_last_four_status(self, contract_row, schedule_rows):
        analysis, _gaps = build_restructured_analysis_frames(
            self._contracts_frame([contract_row]),
            self._schedule_frame(schedule_rows),
            reference_date=self.REFERENCE_DATE,
        )
        return analysis.iloc[0]["paid_last_four_status"]

    def test_contract_without_delay_date_is_flagged(self):
        contracts = self._contracts_frame(
            [
                {
                    "contract_no": "1400-0001",
                    "delay_date": None,
                    "total_due": 1000,
                    "loan_duration": 4,
                }
            ]
        )
        schedule = self._schedule_frame(
            [
                {
                    "account_number": "1400-0001",
                    "installment_no": 1,
                    "due_date": date(2025, 1, 10),
                    "principal_due": 100,
                    "principal_paid": 100,
                    "agency_name": "AG 1",
                    "agent_name": "GP 1",
                }
            ]
        )
        analysis, _gaps = build_restructured_analysis_frames(contracts, schedule)
        self.assertEqual(analysis.iloc[0]["schedule_status"], "Date de d\u00e9calage manquante")

    def test_contract_missing_from_schedule_is_reported(self):
        contracts = self._contracts_frame(
            [
                {
                    "contract_no": "1400-0002",
                    "delay_date": date(2025, 1, 1),
                    "total_due": 1000,
                    "loan_duration": 3,
                }
            ]
        )
        analysis, _gaps = build_restructured_analysis_frames(contracts, self._schedule_frame([]))
        self.assertEqual(analysis.iloc[0]["schedule_status"], "Contrat introuvable dans fichier 2")
        self.assertEqual(analysis.iloc[0]["closure_status"], CLOSURE_STATUS_NA)

    def test_contract_without_paid_installment_after_delay_keeps_zero_streak(self):
        contracts = self._contracts_frame(
            [
                {
                    "contract_no": "1400-0003",
                    "delay_date": date(2025, 4, 1),
                    "total_due": 1000,
                    "loan_duration": 6,
                }
            ]
        )
        schedule = self._schedule_frame(
            [
                {
                    "account_number": "1400-0003",
                    "installment_no": 4,
                    "due_date": date(2025, 4, 15),
                    "principal_due": 100,
                    "principal_paid": 0,
                    "agency_name": "AG 1",
                    "agent_name": "GP 1",
                },
                {
                    "account_number": "1400-0003",
                    "installment_no": 5,
                    "due_date": date(2025, 5, 15),
                    "principal_due": 100,
                    "principal_paid": 20,
                    "agency_name": "AG 1",
                    "agent_name": "GP 1",
                },
            ]
        )
        analysis, _gaps = build_restructured_analysis_frames(contracts, schedule)
        self.assertEqual(analysis.iloc[0]["consecutive_paid_count"], 0)
        self.assertEqual(
            analysis.iloc[0]["schedule_status"],
            "OK - aucune \u00e9ch\u00e9ance pay\u00e9e apr\u00e8s d\u00e9calage",
        )
        self.assertEqual(analysis.iloc[0]["closure_status"], CLOSURE_STATUS_NA)

    def test_non_contiguous_paid_installments_raise_anomaly(self):
        contracts = self._contracts_frame(
            [
                {
                    "contract_no": "1400-0004",
                    "delay_date": date(2025, 1, 1),
                    "total_due": 1000,
                    "loan_duration": 10,
                }
            ]
        )
        schedule = self._schedule_frame(
            [
                {
                    "account_number": "1400-0004",
                    "installment_no": 15,
                    "due_date": date(2025, 2, 10),
                    "principal_due": 100,
                    "principal_paid": 100,
                    "agency_name": "AG 1",
                    "agent_name": "GP 1",
                },
                {
                    "account_number": "1400-0004",
                    "installment_no": 16,
                    "due_date": date(2025, 3, 10),
                    "principal_due": 100,
                    "principal_paid": 0,
                    "agency_name": "AG 1",
                    "agent_name": "GP 1",
                },
                {
                    "account_number": "1400-0004",
                    "installment_no": 17,
                    "due_date": date(2025, 4, 10),
                    "principal_due": 100,
                    "principal_paid": 100,
                    "agency_name": "AG 1",
                    "agent_name": "GP 1",
                },
            ]
        )
        analysis, _gaps = build_restructured_analysis_frames(contracts, schedule)
        self.assertTrue(bool(analysis.iloc[0]["anomaly_detected"]))
        self.assertIn("[15]", analysis.iloc[0]["anomaly_detail"])
        self.assertIn("[17]", analysis.iloc[0]["anomaly_detail"])

    def test_closure_status_is_assumed_closed_when_last_paid_matches_duration(self):
        contracts = self._contracts_frame(
            [
                {
                    "contract_no": "1400-0005",
                    "delay_date": date(2025, 1, 1),
                    "total_due": 1000,
                    "loan_duration": 3,
                }
            ]
        )
        schedule = self._schedule_frame(
            [
                {
                    "account_number": "1400-0005",
                    "installment_no": 1,
                    "due_date": date(2025, 1, 10),
                    "principal_due": 100,
                    "principal_paid": 100,
                    "agency_name": "AG 1",
                    "agent_name": "GP 1",
                },
                {
                    "account_number": "1400-0005",
                    "installment_no": 2,
                    "due_date": date(2025, 2, 10),
                    "principal_due": 100,
                    "principal_paid": 100,
                    "agency_name": "AG 1",
                    "agent_name": "GP 1",
                },
                {
                    "account_number": "1400-0005",
                    "installment_no": 3,
                    "due_date": date(2025, 3, 10),
                    "principal_due": 100,
                    "principal_paid": 100,
                    "agency_name": "AG 1",
                    "agent_name": "GP 1",
                },
            ]
        )
        analysis, _gaps = build_restructured_analysis_frames(contracts, schedule)
        self.assertEqual(analysis.iloc[0]["closure_status"], CLOSURE_STATUS_ASSUMED_CLOSED)

    def test_closure_status_is_in_progress_when_last_paid_is_below_duration(self):
        contracts = self._contracts_frame(
            [
                {
                    "contract_no": "1400-0006",
                    "delay_date": date(2025, 1, 1),
                    "total_due": 1000,
                    "loan_duration": 4,
                }
            ]
        )
        schedule = self._schedule_frame(
            [
                {
                    "account_number": "1400-0006",
                    "installment_no": 1,
                    "due_date": date(2025, 1, 10),
                    "principal_due": 100,
                    "principal_paid": 100,
                    "agency_name": "AG 1",
                    "agent_name": "GP 1",
                },
                {
                    "account_number": "1400-0006",
                    "installment_no": 3,
                    "due_date": date(2025, 3, 10),
                    "principal_due": 100,
                    "principal_paid": 100,
                    "agency_name": "AG 1",
                    "agent_name": "GP 1",
                },
            ]
        )
        analysis, _gaps = build_restructured_analysis_frames(contracts, schedule)
        self.assertEqual(analysis.iloc[0]["last_paid_installment_no"], 3)
        self.assertEqual(analysis.iloc[0]["closure_status"], CLOSURE_STATUS_IN_PROGRESS)

    def test_closure_status_is_na_when_loan_duration_is_missing(self):
        contracts = self._contracts_frame(
            [
                {
                    "contract_no": "1400-0007",
                    "delay_date": date(2025, 1, 1),
                    "total_due": 1000,
                    "loan_duration": None,
                }
            ]
        )
        schedule = self._schedule_frame(
            [
                {
                    "account_number": "1400-0007",
                    "installment_no": 2,
                    "due_date": date(2025, 2, 10),
                    "principal_due": 100,
                    "principal_paid": 100,
                    "agency_name": "AG 1",
                    "agent_name": "GP 1",
                }
            ]
        )
        analysis, _gaps = build_restructured_analysis_frames(contracts, schedule)
        self.assertEqual(analysis.iloc[0]["closure_status"], CLOSURE_STATUS_NA)

    def test_closure_status_is_na_when_no_valid_paid_installment_exists(self):
        contracts = self._contracts_frame(
            [
                {
                    "contract_no": "1400-0008",
                    "delay_date": date(2025, 1, 1),
                    "total_due": 1000,
                    "loan_duration": 3,
                }
            ]
        )
        schedule = self._schedule_frame(
            [
                {
                    "account_number": "1400-0008",
                    "installment_no": 1,
                    "due_date": date(2025, 1, 10),
                    "principal_due": 100,
                    "principal_paid": 0,
                    "agency_name": "AG 1",
                    "agent_name": "GP 1",
                }
            ]
        )
        analysis, _gaps = build_restructured_analysis_frames(contracts, schedule)
        self.assertIsNone(analysis.iloc[0]["last_paid_installment_no"])
        self.assertEqual(analysis.iloc[0]["closure_status"], CLOSURE_STATUS_NA)

    def test_closure_status_normalizes_text_and_excel_decimal_values(self):
        contracts = self._contracts_frame(
            [
                {
                    "contract_no": "1400-0009",
                    "delay_date": date(2025, 1, 1),
                    "total_due": 1000,
                    "loan_duration": "3.0",
                }
            ]
        )
        schedule = self._schedule_frame(
            [
                {
                    "account_number": "1400-0009",
                    "installment_no": "1.0",
                    "due_date": date(2025, 1, 10),
                    "principal_due": "100",
                    "principal_paid": "100",
                    "agency_name": "AG 1",
                    "agent_name": "GP 1",
                },
                {
                    "account_number": "1400-0009",
                    "installment_no": "3.0",
                    "due_date": date(2025, 3, 10),
                    "principal_due": "100",
                    "principal_paid": "100",
                    "agency_name": "AG 1",
                    "agent_name": "GP 1",
                },
            ]
        )
        analysis, _gaps = build_restructured_analysis_frames(contracts, schedule)
        self.assertEqual(analysis.iloc[0]["loan_duration"], 3)
        self.assertEqual(analysis.iloc[0]["last_paid_installment_no"], 3)
        self.assertEqual(analysis.iloc[0]["closure_status"], CLOSURE_STATUS_ASSUMED_CLOSED)

    def test_contract_1000_00047746_uses_same_closure_rule(self):
        contracts = self._contracts_frame(
            [
                {
                    "contract_no": "1000-00047746",
                    "delay_date": date(2025, 1, 1),
                    "total_due": 1000,
                    "loan_duration": "4.0",
                }
            ]
        )
        schedule = self._schedule_frame(
            [
                {
                    "account_number": "1000-00047746",
                    "installment_no": "1.0",
                    "due_date": date(2025, 1, 10),
                    "principal_due": "100",
                    "principal_paid": "100",
                    "agency_name": "AG 1",
                    "agent_name": "GP 1",
                },
                {
                    "account_number": "1000-00047746",
                    "installment_no": "4.0",
                    "due_date": date(2025, 4, 10),
                    "principal_due": "100",
                    "principal_paid": "100",
                    "agency_name": "AG 1",
                    "agent_name": "GP 1",
                },
            ]
        )
        analysis, _gaps = build_restructured_analysis_frames(contracts, schedule)
        self.assertEqual(analysis.iloc[0]["last_paid_installment_no"], 4)
        self.assertEqual(analysis.iloc[0]["closure_status"], CLOSURE_STATUS_ASSUMED_CLOSED)

    def test_paid_last_four_is_yes_when_march_to_june_are_all_paid_for_july_reference(self):
        status = self._paid_last_four_status(
            {
                "contract_no": "2400-0001",
                "delay_date": date(2025, 1, 1),
                "total_due": 1000,
                "loan_duration": 12,
            },
            [
                {"account_number": "2400-0001", "installment_no": 3, "due_date": date(2026, 3, 10), "principal_due": 100, "principal_paid": 100},
                {"account_number": "2400-0001", "installment_no": 4, "due_date": date(2026, 4, 10), "principal_due": 100, "principal_paid": 100},
                {"account_number": "2400-0001", "installment_no": 5, "due_date": date(2026, 5, 10), "principal_due": 100, "principal_paid": 100},
                {"account_number": "2400-0001", "installment_no": 6, "due_date": date(2026, 6, 10), "principal_due": 100, "principal_paid": 100},
                {"account_number": "2400-0001", "installment_no": 7, "due_date": date(2026, 7, 10), "principal_due": 100, "principal_paid": 0},
            ],
        )
        self.assertEqual(status, "Oui")

    def test_paid_last_four_is_non_when_march_is_missing_from_target_calendar_window(self):
        status = self._paid_last_four_status(
            {
                "contract_no": "2400-0002",
                "delay_date": date(2025, 1, 1),
                "total_due": 1000,
                "loan_duration": 12,
            },
            [
                {"account_number": "2400-0002", "installment_no": 4, "due_date": date(2026, 4, 10), "principal_due": 100, "principal_paid": 100},
                {"account_number": "2400-0002", "installment_no": 5, "due_date": date(2026, 5, 10), "principal_due": 100, "principal_paid": 100},
                {"account_number": "2400-0002", "installment_no": 6, "due_date": date(2026, 6, 10), "principal_due": 100, "principal_paid": 100},
                {"account_number": "2400-0002", "installment_no": 7, "due_date": date(2026, 7, 10), "principal_due": 100, "principal_paid": 100},
            ],
        )
        self.assertEqual(status, "Non")

    def test_paid_last_four_is_non_when_april_is_missing_in_july_window(self):
        status = self._paid_last_four_status(
            {
                "contract_no": "2400-0003",
                "delay_date": date(2025, 1, 1),
                "total_due": 1000,
                "loan_duration": 12,
            },
            [
                {"account_number": "2400-0003", "installment_no": 3, "due_date": date(2026, 3, 10), "principal_due": 100, "principal_paid": 100},
                {"account_number": "2400-0003", "installment_no": 5, "due_date": date(2026, 5, 10), "principal_due": 100, "principal_paid": 100},
                {"account_number": "2400-0003", "installment_no": 6, "due_date": date(2026, 6, 10), "principal_due": 100, "principal_paid": 100},
                {"account_number": "2400-0003", "installment_no": 7, "due_date": date(2026, 7, 10), "principal_due": 100, "principal_paid": 100},
            ],
        )
        self.assertEqual(status, "Non")

    def test_paid_last_four_is_non_when_gap_exists_in_target_calendar_months(self):
        status = self._paid_last_four_status(
            {
                "contract_no": "2400-0004",
                "delay_date": date(2025, 1, 1),
                "total_due": 1000,
                "loan_duration": 12,
            },
            [
                {"account_number": "2400-0004", "installment_no": 3, "due_date": date(2026, 3, 10), "principal_due": 100, "principal_paid": 100},
                {"account_number": "2400-0004", "installment_no": 5, "due_date": date(2026, 5, 10), "principal_due": 100, "principal_paid": 100},
                {"account_number": "2400-0004", "installment_no": 6, "due_date": date(2026, 6, 10), "principal_due": 100, "principal_paid": 100},
                {"account_number": "2400-0004", "installment_no": 7, "due_date": date(2026, 7, 10), "principal_due": 100, "principal_paid": 100},
            ],
        )
        self.assertEqual(status, "Non")

    def test_paid_last_four_is_na_when_no_installment_falls_in_recent_control_scope(self):
        status = self._paid_last_four_status(
            {
                "contract_no": "2400-0005",
                "delay_date": date(2026, 6, 20),
                "total_due": 1000,
                "loan_duration": 12,
            },
            [
                {"account_number": "2400-0005", "installment_no": 9, "due_date": date(2026, 9, 10), "principal_due": 100, "principal_paid": 100},
                {"account_number": "2400-0005", "installment_no": 10, "due_date": date(2026, 10, 10), "principal_due": 100, "principal_paid": 100},
            ],
        )
        self.assertEqual(status, "N/A")

    def test_paid_last_four_is_non_when_one_month_is_present_but_not_paid(self):
        status = self._paid_last_four_status(
            {
                "contract_no": "2400-0006",
                "delay_date": date(2025, 1, 1),
                "total_due": 1000,
                "loan_duration": 12,
            },
            [
                {"account_number": "2400-0006", "installment_no": 4, "due_date": date(2026, 4, 10), "principal_due": 100, "principal_paid": 100},
                {"account_number": "2400-0006", "installment_no": 5, "due_date": date(2026, 5, 10), "principal_due": 100, "principal_paid": 100},
                {"account_number": "2400-0006", "installment_no": 6, "due_date": date(2026, 6, 10), "principal_due": 100, "principal_paid": 50},
                {"account_number": "2400-0006", "installment_no": 7, "due_date": date(2026, 7, 10), "principal_due": 100, "principal_paid": 100},
            ],
        )
        self.assertEqual(status, "Non")

    def test_paid_last_four_is_non_when_only_three_target_months_exist_after_delay(self):
        status = self._paid_last_four_status(
            {
                "contract_no": "2400-0007",
                "delay_date": date(2026, 3, 20),
                "total_due": 1000,
                "loan_duration": 12,
            },
            [
                {"account_number": "2400-0007", "installment_no": 4, "due_date": date(2026, 4, 10), "principal_due": 100, "principal_paid": 100},
                {"account_number": "2400-0007", "installment_no": 5, "due_date": date(2026, 5, 10), "principal_due": 100, "principal_paid": 100},
                {"account_number": "2400-0007", "installment_no": 6, "due_date": date(2026, 6, 10), "principal_due": 100, "principal_paid": 100},
            ],
        )
        self.assertEqual(status, "Non")

    def test_paid_last_four_ignores_current_month_and_uses_previous_four_calendar_months(self):
        status = self._paid_last_four_status(
            {
                "contract_no": "2400-0008",
                "delay_date": date(2025, 1, 1),
                "total_due": 1000,
                "loan_duration": 12,
            },
            [
                {"account_number": "2400-0008", "installment_no": 3, "due_date": date(2026, 3, 10), "principal_due": 100, "principal_paid": 100},
                {"account_number": "2400-0008", "installment_no": 4, "due_date": date(2026, 4, 10), "principal_due": 100, "principal_paid": 100},
                {"account_number": "2400-0008", "installment_no": 5, "due_date": date(2026, 5, 10), "principal_due": 100, "principal_paid": 100},
                {"account_number": "2400-0008", "installment_no": 6, "due_date": date(2026, 6, 10), "principal_due": 100, "principal_paid": 100},
                {"account_number": "2400-0008", "installment_no": 8, "due_date": date(2026, 8, 10), "principal_due": 100, "principal_paid": 100},
            ],
        )
        self.assertEqual(status, "Oui")

    def test_paid_last_four_uses_tolerance_for_small_decimal_difference(self):
        status = self._paid_last_four_status(
            {
                "contract_no": "2400-0009",
                "delay_date": date(2025, 1, 1),
                "total_due": 1000,
                "loan_duration": 12,
            },
            [
                {"account_number": "2400-0009", "installment_no": 3, "due_date": date(2026, 3, 10), "principal_due": 100.00, "principal_paid": 99.995},
                {"account_number": "2400-0009", "installment_no": 4, "due_date": date(2026, 4, 10), "principal_due": 100.00, "principal_paid": 100.009},
                {"account_number": "2400-0009", "installment_no": 5, "due_date": date(2026, 5, 10), "principal_due": 100.00, "principal_paid": 100.001},
                {"account_number": "2400-0009", "installment_no": 6, "due_date": date(2026, 6, 10), "principal_due": 100.00, "principal_paid": 100.001},
            ],
        )
        self.assertEqual(status, "Oui")

    def test_paid_last_four_is_non_when_difference_is_equal_or_above_tolerance(self):
        status = self._paid_last_four_status(
            {
                "contract_no": "2400-0010",
                "delay_date": date(2025, 1, 1),
                "total_due": 1000,
                "loan_duration": 12,
            },
            [
                {"account_number": "2400-0010", "installment_no": 3, "due_date": date(2026, 3, 10), "principal_due": 100.00, "principal_paid": 100.00},
                {"account_number": "2400-0010", "installment_no": 4, "due_date": date(2026, 4, 10), "principal_due": 100.00, "principal_paid": 99.99},
                {"account_number": "2400-0010", "installment_no": 5, "due_date": date(2026, 5, 10), "principal_due": 100.00, "principal_paid": 100.00},
                {"account_number": "2400-0010", "installment_no": 6, "due_date": date(2026, 6, 10), "principal_due": 100.00, "principal_paid": 100.00},
            ],
        )
        self.assertEqual(status, "Non")

    def test_paid_last_four_deduplicates_same_installment_without_false_non(self):
        status = self._paid_last_four_status(
            {
                "contract_no": "2400-0011",
                "delay_date": date(2025, 1, 1),
                "total_due": 1000,
                "loan_duration": 12,
            },
            [
                {"account_number": "2400-0011", "installment_no": 3, "due_date": date(2026, 3, 10), "principal_due": 100, "principal_paid": 100, "is_active": True, "all_paid": True, "schedule_id": "1", "value_date": date(2026, 3, 10)},
                {"account_number": "2400-0011", "installment_no": 4, "due_date": date(2026, 4, 10), "principal_due": 100, "principal_paid": 0, "is_active": False, "all_paid": False, "schedule_id": "2", "value_date": date(2026, 4, 9)},
                {"account_number": "2400-0011", "installment_no": 4, "due_date": date(2026, 4, 10), "principal_due": 100, "principal_paid": 100, "is_active": True, "all_paid": True, "schedule_id": "3", "value_date": date(2026, 4, 10)},
                {"account_number": "2400-0011", "installment_no": 5, "due_date": date(2026, 5, 10), "principal_due": 100, "principal_paid": 100, "is_active": True, "all_paid": True, "schedule_id": "4", "value_date": date(2026, 5, 10)},
                {"account_number": "2400-0011", "installment_no": 6, "due_date": date(2026, 6, 10), "principal_due": 100, "principal_paid": 100, "is_active": True, "all_paid": True, "schedule_id": "5", "value_date": date(2026, 6, 10)},
            ],
        )
        self.assertEqual(status, "Oui")

    def test_paid_last_four_is_non_when_same_month_contains_one_unpaid_row(self):
        status = self._paid_last_four_status(
            {
                "contract_no": "2400-0012",
                "delay_date": date(2025, 1, 1),
                "total_due": 1000,
                "loan_duration": 12,
            },
            [
                {"account_number": "2400-0012", "installment_no": 3, "due_date": date(2026, 3, 5), "principal_due": 100, "principal_paid": 100},
                {"account_number": "2400-0012", "installment_no": 4, "due_date": date(2026, 4, 5), "principal_due": 100, "principal_paid": 100},
                {"account_number": "2400-0012", "installment_no": 5, "due_date": date(2026, 5, 5), "principal_due": 100, "principal_paid": 0},
                {"account_number": "2400-0012", "installment_no": 6, "due_date": date(2026, 5, 20), "principal_due": 100, "principal_paid": 100},
                {"account_number": "2400-0012", "installment_no": 7, "due_date": date(2026, 6, 5), "principal_due": 100, "principal_paid": 100},
            ],
        )
        self.assertEqual(status, "Non")


if __name__ == "__main__":
    unittest.main()
