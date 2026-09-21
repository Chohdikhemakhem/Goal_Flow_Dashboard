from pathlib import Path

import pandas as pd

rows = [
    {
        "CONTRACT_NO": "MC-1001",
        "CLIENT_NO": "CL-001",
        "BRANCH": "AGENCE DEMO A",
        "DAO_NAME": "Amina Bello",
        "DISBURSEMENT_AMOUNT": 500000,
        "PRINCIPAL_OUTSTANDING": 450000,
        "TOTAL_PRINCIPAL_DUE_AMT": 0,
        "TOTAL_CUR_NO_OF_DAYS_OVERDUE": 0,
        "TOTAL_DUE_AMT": 0,
        "DISBURSEMENT_DATE": "2026-05-01",
        "DateEOD": "2026-05-10",
    },
    {
        "CONTRACT_NO": "MC-1002",
        "CLIENT_NO": "CL-002",
        "BRANCH": "AGENCE DEMO A",
        "DAO_NAME": "Chinedu Okafor",
        "DISBURSEMENT_AMOUNT": 750000,
        "PRINCIPAL_OUTSTANDING": 710000,
        "TOTAL_PRINCIPAL_DUE_AMT": 25000,
        "TOTAL_CUR_NO_OF_DAYS_OVERDUE": 12,
        "TOTAL_DUE_AMT": 35000,
        "DISBURSEMENT_DATE": "2026-05-02",
        "DateEOD": "2026-05-10",
    },
    {
        "CONTRACT_NO": "MC-1003",
        "CLIENT_NO": "CL-003",
        "BRANCH": "AGENCE DEMO B",
        "DAO_NAME": "Mariam Musa",
        "DISBURSEMENT_AMOUNT": 900000,
        "PRINCIPAL_OUTSTANDING": 880000,
        "TOTAL_PRINCIPAL_DUE_AMT": 90000,
        "TOTAL_CUR_NO_OF_DAYS_OVERDUE": 45,
        "TOTAL_DUE_AMT": 120000,
        "DISBURSEMENT_DATE": "2026-04-20",
        "DateEOD": "2026-05-10",
    },
]

output = Path(__file__).resolve().parents[1] / "sample_data" / "loans_snapshot_2026-05-10.xlsx"
output.parent.mkdir(exist_ok=True)
pd.DataFrame(rows).to_excel(output, index=False)
print(output)
