import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

TOTAL_TESTS = 146

project_root = Path(__file__).resolve().parents[1]
timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
output_file = project_root / f"test_results_{timestamp}.txt"

env = os.environ.copy()
env["PYTHONPATH"] = str(project_root)

cmd = [
    sys.executable,
    "-u",
    str(project_root / "tests" / "test_patient_brain_all.py"),
]

completed = 0

with output_file.open("w", encoding="utf-8") as f:
    process = subprocess.Popen(
        cmd,
        cwd=project_root,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )

    for line in process.stdout:
        f.write(line)
        f.flush()

        if re.search(r"\b(PASS|FAIL):", line):
            completed += 1
            percent = min((completed / TOTAL_TESTS) * 100, 100)
            print(
                f"\rRunning tests... {completed}/{TOTAL_TESTS} completed ({percent:.1f}%)",
                end="",
                flush=True,
            )

    return_code = process.wait()

print()
print(f"Done. Full test result saved to: {output_file.name}")

if return_code != 0:
    print(f"Test runner exited with error code: {return_code}")
else:
    print("Test runner completed.")

print()
print("To see failures only, run:")
print(f"grep -n 'FAIL:' {output_file.name}")