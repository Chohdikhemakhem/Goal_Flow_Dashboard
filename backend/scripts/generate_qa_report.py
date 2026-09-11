from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[2]
REPORT_DIR = ROOT_DIR / "docs" / "reports"


def _run(command: list[str], *, cwd: Path) -> dict[str, object]:
    completed = subprocess.run(
        command,
        cwd=str(cwd),
        capture_output=True,
        text=True,
        check=False,
    )
    return {
        "command": command,
        "returncode": completed.returncode,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
    }


def main() -> None:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    generated_at = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_path = REPORT_DIR / f"qa_summary_{generated_at}.json"

    results = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "security_tests": _run(
            [sys.executable, "-m", "unittest", "backend.tests.test_security_controls", "-v"],
            cwd=ROOT_DIR,
        ),
        "frontend_build": _run(["npm", "run", "build"], cwd=ROOT_DIR / "frontend"),
    }

    output_path.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"QA summary written to {output_path}")

    if results["security_tests"]["returncode"] != 0 or results["frontend_build"]["returncode"] != 0:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
