from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]


def main() -> None:
    pip_audit = shutil.which("pip-audit")
    if not pip_audit:
        raise SystemExit(
            "pip-audit is not installed. Install it with 'pip install pip-audit' and rerun this script."
        )

    command = [pip_audit, "-r", "requirements.txt"]
    completed = subprocess.run(command, cwd=str(BACKEND_DIR), check=False)
    raise SystemExit(completed.returncode)


if __name__ == "__main__":
    main()
