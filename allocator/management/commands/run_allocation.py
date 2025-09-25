# allocator/management/commands/run_allocation.py
from django.core.management.base import BaseCommand
from django.utils import timezone
import datetime

from allocator.services import AllocationService
from allocator.models import AllocationRun

class Command(BaseCommand):
    help = "Run allocation for given date. Usage: python manage.py run_allocation --date YYYY-MM-DD [--delete] [--visit ID]"

    def add_arguments(self, parser):
        parser.add_argument("--date", type=str, required=True, help="Date to run allocation for (YYYY-MM-DD)")
        parser.add_argument("--delete", action="store_true", help="Delete existing allocations for that date before running")
        parser.add_argument("--visit", type=int, help="(Optional) allocate a single Visit by id (realtime)")

    def handle(self, *args, **options):
        ds = options.get("date")
        delete_flag = options.get("delete", False)
        visit_id = options.get("visit", None)

        try:
            run_date = datetime.date.fromisoformat(ds)
        except Exception:
            self.stdout.write(self.style.ERROR("Invalid date format. Use YYYY-MM-DD"))
            return

        self.stdout.write(f"Starting allocation for {run_date.isoformat()}...")

        svc = AllocationService(run_date)

        # Optional delete old assignments for this date
        if delete_flag:
            deleted = svc.delete_allocations_for_date(run_date)
            self.stdout.write(self.style.WARNING(f"Deleted {deleted} previous assignments for {run_date}"))

        if visit_id:
            res = svc.allocate_visit(visit_id=visit_id)
            if res.get("status") == "success":
                self.stdout.write(self.style.SUCCESS(f"Realtime allocation successful: {res}"))
            else:
                self.stdout.write(self.style.ERROR(f"Realtime allocation failed: {res}"))
            return

        # Batch run
        run = AllocationRun.objects.create(run_date=run_date, status="running")
        try:
            result = svc.assign_all(allocation_run=run)
            created = result.get("created", 0)
            failures = result.get("failures", 0)
            self.stdout.write(self.style.SUCCESS(f"Completed. Created: {created}, Failures: {failures}"))
            if failures:
                fl = result.get("fail_list", [])[:20]
                self.stdout.write("Failure details (up to 20):")
                for f in fl:
                    booking, reason = f
                    preg = booking.get("preg_no") if isinstance(booking, dict) else getattr(booking, "pat_reg_no", "")
                    therapy = (booking.get("therapy_name") if isinstance(booking, dict) else getattr(booking, "therapy_name", "")) or ""
                    self.stdout.write(f" - preg:{preg}      therapy:{therapy}\n\n\t\t\t\t\t-> {reason}")
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"Allocation failed: {e}"))
            try:
                run.status = "failed"
                run.save()
            except Exception:
                pass
