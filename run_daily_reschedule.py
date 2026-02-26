"""
Run the emergency leave reschedule daily at two set times.
- 5:30 AM: reschedule_morning (today's treatments)
- 8:00 PM: reschedule_night (tomorrow's treatments)

Usage:
    python run_daily_reschedule.py

To stop: Press Ctrl+C in the terminal.
"""

import os
import subprocess
import sys
import time
from datetime import datetime, date

# ========== CONFIGURE TIMES HERE (24-hour format) ==========
MORNING_HOUR, MORNING_MINUTE = 5, 30   # 5:30 AM - today's reschedule
NIGHT_HOUR, NIGHT_MINUTE = 20, 00       # 8:00 PM - tomorrow's reschedule
# ==========================================================

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


def run_reschedule_morning():
    """Execute the morning reschedule command (today)."""
    print(f"\n[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Running reschedule_morning...")
    try:
        result = subprocess.run(
            [sys.executable, "manage.py", "reschedule_morning"],
            cwd=PROJECT_ROOT,
            capture_output=False,
        )
        if result.returncode == 0:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] Morning completed successfully.\n")
        else:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] Morning finished with return code {result.returncode}.\n")
    except Exception as e:
        print(f"[{datetime.now().strftime('%H:%M:%S')}] Error: {e}\n")


def run_reschedule_night():
    """Execute the night reschedule command (tomorrow)."""
    print(f"\n[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Running reschedule_night...")
    try:
        result = subprocess.run(
            [sys.executable, "manage.py", "reschedule_night"],
            cwd=PROJECT_ROOT,
            capture_output=False,
        )
        if result.returncode == 0:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] Night completed successfully.\n")
        else:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] Night finished with return code {result.returncode}.\n")
    except Exception as e:
        print(f"[{datetime.now().strftime('%H:%M:%S')}] Error: {e}\n")


def main():
    print("=" * 60)
    print("Daily reschedule runner (VS Code)")
    print("  • {}:{:02d} – reschedule_morning (today)".format(MORNING_HOUR, MORNING_MINUTE))
    print("  • {}:{:02d} – reschedule_night (tomorrow)".format(NIGHT_HOUR, NIGHT_MINUTE))
    print("Stop with Ctrl+C")
    print("=" * 60)

    last_morning_date = None
    last_night_date = None

    while True:
        now = datetime.now()

        if (now.hour == MORNING_HOUR and now.minute == MORNING_MINUTE and
                (last_morning_date is None or last_morning_date != now.date())):
            run_reschedule_morning()
            last_morning_date = now.date()

        if (now.hour == NIGHT_HOUR and now.minute == NIGHT_MINUTE and
                (last_night_date is None or last_night_date != now.date())):
            run_reschedule_night()
            last_night_date = now.date()

        time.sleep(30)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nStopped.")
