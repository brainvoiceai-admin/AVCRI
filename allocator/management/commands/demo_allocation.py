# allocator/management/commands/demo_allocation.py
import csv
import datetime
from django.core.management.base import BaseCommand
from allocator.services import AllocationService
from allocator.models import AllocationRun

class Command(BaseCommand):
    help = "Demo allocation using CSV of patients. CSV columns: id,name,therapy_code,therapy_name,date,visit_type,is_vip"

    def add_arguments(self, parser):
        parser.add_argument("--csv", required=True, help="Path to CSV file with demo patients")
        parser.add_argument("--date", required=False, help="Run date (YYYY-MM-DD). If omitted, use date column from CSV or today")

    def handle(self, *args, **options):
        csv_path = options["csv"]
        run_date_arg = options.get("date")
        bookings = []
        with open(csv_path, newline='', encoding='utf-8') as fh:
            reader = csv.DictReader(fh)
            for row in reader:
                # ensure minimal required fields exist
                date_str = row.get("date") or run_date_arg or datetime.date.today().isoformat()
                try:
                    run_date = datetime.date.fromisoformat(date_str)
                except Exception:
                    run_date = datetime.date.today()
                bookings.append({
                    "preg_no": row.get("id") or row.get("preg_no") or "",
                    "therapy_code": row.get("therapy_code") or "",
                    "therapy_name": row.get("therapy_name") or "",
                    "preferred_slot_label": row.get("preferred_slot_label","") or "",
                    "preferred_room": row.get("preferred_room","") or None,
                    "visit_type": row.get("visit_type","IP"),
                    "is_vip": bool(int(row.get("is_vip","0"))) if str(row.get("is_vip","0")).isdigit() else (row.get("is_vip","").strip().lower() in ("1","true","yes")),
                    "raw": row
                })

        if not bookings:
            self.stdout.write(self.style.ERROR("No rows found in CSV"))
            return

        # Use first booking's date (or passed date) as run_date for AllocationService
        if run_date_arg:
            run_date = datetime.date.fromisoformat(run_date_arg)
        else:
            # take date from first CSV row if present
            first_date = None
            try:
                first_date = datetime.date.fromisoformat(reader.fieldnames and bookings[0].get("raw",{}).get("date","") or "")
            except Exception:
                first_date = None
            run_date = first_date or datetime.date.today()

        svc = AllocationService(run_date)
        # load initial state
        svc.load_slots_from_db(); svc.load_therapists_from_db(); svc.load_rooms_from_db(); svc.load_leaves_from_db(); svc.load_therapy_and_repeats()

        # create allocation run
        run = AllocationRun.objects.create(run_date=run_date, status="running")

        self.stdout.write(f"Running demo allocation for {run_date.isoformat()}\n")
        self.stdout.write(f"{'Patient ID':<12} {'Name':<20} {'Therapy':<18} {'Slot':<8} {'Therapists':<30} {'Room':<8}")

        # allocate each booking in real-time using allocate_visit (we pass a dict)
        for b in bookings:
            res = svc.allocate_visit(visit_obj=b)
            pid = b.get("preg_no") or b.get("raw", {}).get("id", "")
            name = b.get("raw", {}).get("name", "")
            therapy = b.get("therapy_name", "")
            if res.get("status") == "success":
                therapists = ", ".join(res.get("therapists") or [])
                slot = res.get("slot") or ""
                room = res.get("room") or ""
                self.stdout.write(f"{pid:<12} {name:<20} {therapy:<18} {slot:<8} {therapists:<30} {room:<8}")
            else:
                reason = res.get("reason") or res.get("trace") or "failed"
                self.stdout.write(f"{pid:<12} {name:<20} {therapy:<18} FAILED   {reason}")
