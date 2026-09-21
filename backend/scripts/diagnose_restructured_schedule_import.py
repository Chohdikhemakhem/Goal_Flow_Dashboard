from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.db.session import SessionLocal
from app.services.restructured import _normalize_contract_frame, diagnose_restructured_schedule_import


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Diagnostique l'import SCHEDULE restructure/consolide sur un echantillon."
    )
    parser.add_argument("--file", required=True, help="Chemin du fichier SCHEDULE (.xlsx ou .csv)")
    parser.add_argument(
        "--sample-rows",
        type=int,
        default=50000,
        help="Nombre maximum de lignes a scanner pour le diagnostic",
    )
    parser.add_argument(
        "--contracts-file",
        help="Fichier liste_restructure_all.xlsx pour charger les contrats utiles sans connexion base",
    )
    args = parser.parse_args()

    source_path = Path(args.file).expanduser().resolve()
    if not source_path.exists():
        raise SystemExit(f"Fichier introuvable: {source_path}")

    useful_contracts = None
    if args.contracts_file:
        contracts_path = Path(args.contracts_file).expanduser().resolve()
        if not contracts_path.exists():
            raise SystemExit(f"Fichier contrats introuvable: {contracts_path}")
        frame = _normalize_contract_frame(contracts_path.read_bytes())
        useful_contracts = {
            contract_no
            for contract_no in frame["normalized_contract_no"].dropna().tolist()
            if contract_no
        }

    with SessionLocal() as db:
        result = diagnose_restructured_schedule_import(
            db,
            source_path=str(source_path),
            sample_rows=max(1, int(args.sample_rows)),
            useful_contracts=useful_contracts,
        )
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
