from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[2]


def main() -> None:
    command = [sys.executable, "-m", "unittest", "backend.tests.test_security_controls", "-v"]
    completed = subprocess.run(command, cwd=str(ROOT_DIR), check=False)
    if completed.returncode != 0:
        raise SystemExit(completed.returncode)
    print("Security control suite completed successfully.")


if __name__ == "__main__":
    main()
