"""
Run the emergency leave reschedule daily at a set time.
Start this in VS Code terminal and leave it running; it will run
'python manage.py reschedule_morning' at the configured time every day.

Usage:
    python run_daily_reschedule.py

To stop: Press Ctrl+C in the terminal.
"""

import os
import subprocess
import sys
import time
from datetime import datetime, date

# ========== CONFIGURE TIME HERE (24-hour format) ==========
RUN_HOUR = 12   # 2 PM
RUN_MINUTE = 20  # 2:02 PM
# ==========================================================

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


def run_reschedule():
    """Execute the morning reschedule command."""
    print(f"\n[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Running reschedule_morning...")
    try:
        result = subprocess.run(
            [sys.executable, "manage.py", "reschedule_morning"],
            cwd=PROJECT_ROOT,
            capture_output=False,  # show output in terminal
        )
        if result.returncode == 0:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] Completed successfully.\n")
        else:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] Finished with return code {result.returncode}.\n")
    except Exception as e:
        print(f"[{datetime.now().strftime('%H:%M:%S')}] Error: {e}\n")


def next_run_time():
    """Next occurrence of RUN_HOUR:RUN_MINUTE today or tomorrow."""
    now = datetime.now()
    today = now.replace(hour=RUN_HOUR, minute=RUN_MINUTE, second=0, microsecond=0)
    if now >= today:
        from datetime import timedelta
        return today + timedelta(days=1)
    return today


def main():
    print("=" * 60)
    print("Daily reschedule runner (VS Code)")
    print("Time: {}:{:02d} every day".format(RUN_HOUR, RUN_MINUTE))
    print("Stop with Ctrl+C")
    print("=" * 60)

    last_run_date = None

    while True:
        now = datetime.now()
        if (now.hour == RUN_HOUR and now.minute == RUN_MINUTE and
                (last_run_date is None or last_run_date != now.date())):
            run_reschedule()
            last_run_date = now.date()

        next_run = next_run_time()
        # Sleep until next minute to avoid busy loop
        time.sleep(30)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nStopped.")
