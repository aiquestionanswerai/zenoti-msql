import subprocess
import sys
import os

SCRIPTS = [
    "sql_helper.py",
    "appointments.py",
    "block_out_update.py",
    "cost_of_goods.py",
    "cash.py",
]

script_dir = os.path.dirname(os.path.abspath(__file__))

for script in SCRIPTS:
    path = os.path.join(script_dir, script)
    print(f"\n{'='*60}")
    print(f"Running: {script}")
    print(f"{'='*60}")

    result = subprocess.run(
        [sys.executable, path],
        cwd=script_dir,
    )

    if result.returncode != 0:
        print(f"\nFAILED: {script} exited with code {result.returncode}")
        print("Stopping. Fix the error above before continuing.")
        sys.exit(result.returncode)

    print(f"DONE: {script}")

print(f"\n{'='*60}")
print("All scripts completed successfully.")
print(f"{'='*60}")
