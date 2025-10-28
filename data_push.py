#!/usr/bin/env python3
"""
data_push_slots.py

Deletes all existing SlotMaster rows and recreates them
using fixed time slots (24-hour format, as per your screenshot).

Usage:
    python data_push_slots.py
"""
import os
import sys
from pathlib import Path
from datetime import time

# --- Django setup ---
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

if not os.environ.get('DJANGO_SETTINGS_MODULE'):
    # auto-detect project folder with settings.py
    for item in HERE.iterdir():
        if item.is_dir() and (item / "settings.py").exists():
            os.environ.setdefault("DJANGO_SETTINGS_MODULE", f"{item.name}.settings")
            break

os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")

try:
    import django
    django.setup()
    from django.apps import apps
except Exception as e:
    print("❌ Django setup failed. Make sure this file is next to manage.py and virtualenv is active.")
    raise

# --- Locate model ---
SlotMaster = None
for model in apps.get_models():
    if model.__name__ == "SlotMaster":
        SlotMaster = model
        break

if not SlotMaster:
    raise RuntimeError("Could not find SlotMaster model. Check your model name and app registration.")

print("✅ Using model:", SlotMaster)

# --- Define slot data (24-hour format) ---
SLOTS = [
    (1, time(6, 30, 0),  time(8, 0, 0)),   # 06:30–08:00
    (2, time(8, 30, 0),  time(10, 0, 0)),  # 08:30–10:00
    (3, time(10, 0, 0),  time(11, 30, 0)), # 10:00–11:30
    (4, time(11, 30, 0), time(13, 0, 0)),  # 11:30–13:00
    (5, time(14, 30, 0), time(16, 0, 0)),  # 14:30–16:00
    (6, time(16, 0, 0),  time(17, 30, 0)), # 16:00–17:30
    (7, time(17, 30, 0), time(19, 0, 0)),  # 17:30–19:00
]

# --- Main logic ---
def main():
    print("\n⚙️  Deleting existing slots...")
    count = SlotMaster.objects.count()
    SlotMaster.objects.all().delete()
    print(f"🗑️  Deleted {count} existing SlotMaster records.\n")

    created = []
    for num, start, end in SLOTS:
        obj = SlotMaster.objects.create(
            slot_number=num,
            start_time=start,
            end_time=end,
            slot_name=f"Slot {num}",
            is_active=True
        )
        created.append(obj)

    print(f"✅ Inserted {len(created)} new slots:\n")
    for s in created:
        print(f"  • Slot {s.slot_number}: {s.start_time} - {s.end_time}")

    print("\n🎯 SlotMaster table successfully updated.")

if __name__ == "__main__":
    main()
