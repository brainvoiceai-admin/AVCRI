"""
Django management command to run morning rescheduling process.

This command:
1. Updates emergency leave data via api.py for today's date
2. Runs resheduleMorningandNight.py algorithm for today's date

Scheduled to run daily at 5:30 AM via cron or task scheduler.
"""

from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import datetime, timedelta
import logging

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Run morning rescheduling: update emergency leave and reassign affected bookings for today'

    def add_arguments(self, parser):
        parser.add_argument(
            '--date',
            type=str,
            default=None,
            help='Date to process (YYYY-MM-DD). Defaults to today.',
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Run in dry-run mode (no database changes)',
        )

    def handle(self, *args, **options):
        print("\n" + "="*80)
        print("="*80)
        print(">>> EMERGENCY LEAVE REASSIGNMENT ALGORITHM - STARTING")
        print("="*80)
        print("="*80 + "\n")
        
        # Determine target date
        if options['date']:
            try:
                target_date = datetime.strptime(options['date'], '%Y-%m-%d').date()
            except ValueError:
                error_msg = f'Invalid date format: {options["date"]}. Use YYYY-MM-DD.'
                self.stdout.write(self.style.ERROR(error_msg))
                print(f"❌ ERROR: {error_msg}")
                return
        else:
            target_date = timezone.localtime(timezone.now()).date()
        
        dry_run = options.get('dry_run', False)
        
        start_msg = f'Starting morning reschedule for date: {target_date.isoformat()}'
        self.stdout.write(self.style.SUCCESS(start_msg))
        print(f"[DATE] {start_msg}")
        if dry_run:
            print("[WARNING] DRY RUN MODE - No database changes will be made")
        
        # Step 1: Update emergency leave data via api.py
        step1_msg = 'Step 1: Updating emergency leave data...'
        self.stdout.write(self.style.WARNING(step1_msg))
        print(f"\n[STEP 1] {step1_msg}")
        try:
            import api
            api.enable_django_for_scheduling()
            
            date_str = target_date.strftime('%Y-%m-%d')
            print(f"   Fetching emergency leave data for {date_str}...")
            employees_on_leave = api.get_employees_on_leave_and_save(
                target_date=date_str,
                save_to_db=True
            )
            
            success_msg = f'[OK] Emergency leave updated: {len(employees_on_leave)} employees on leave'
            self.stdout.write(self.style.SUCCESS(success_msg))
            print(f"   [OK] {success_msg}")
            if employees_on_leave:
                # Handle both dict and string formats
                employee_list = []
                for e in employees_on_leave[:5]:
                    if isinstance(e, dict):
                        emp_code = e.get('employee_code') or e.get('name') or 'Unknown'
                    else:
                        emp_code = str(e)
                    employee_list.append(emp_code)
                emp_str = ', '.join(employee_list)
                if len(employees_on_leave) > 5:
                    emp_str += '...'
                print(f"   [INFO] Employees on leave: {emp_str}")
            logger.info(f"Emergency leave updated for {target_date}: {len(employees_on_leave)} employees")
            
        except Exception as e:
            error_msg = f'[ERROR] Error updating emergency leave: {str(e)}'
            self.stdout.write(self.style.ERROR(error_msg))
            print(f"   [ERROR] {error_msg}")
            logger.exception(f"Error updating emergency leave for {target_date}: {e}")
            # Continue anyway - the rescheduling algorithm can work with existing leave data
        
        # Step 2: Run rescheduling algorithm
        step2_msg = 'Step 2: Running rescheduling algorithm...'
        self.stdout.write(self.style.WARNING(step2_msg))
        print(f"\n[STEP 2] {step2_msg}")
        print("   Checking bookings with therapists on emergency leave...")
        try:
            # Import necessary modules and setup
            import sys
            import os
            from resheduleMorningandNight import process_reassignments
            
            # Create a mock args object for compatibility if needed
            class MockArgs:
                def __init__(self, dry_run_flag):
                    self.dry_run = dry_run_flag
            
            # Store original args if it exists
            original_args = getattr(sys.modules.get('resheduleMorningandNight', None), 'args', None)
            
            # Set mock args for the module
            if 'resheduleMorningandNight' in sys.modules:
                sys.modules['resheduleMorningandNight'].args = MockArgs(dry_run)
            
            print("   Processing reassignments with continuity logic...")
            summary = process_reassignments(
                target_date=target_date,
                dry_run=dry_run,
                max_daily_normal=5,
                max_daily_overtime_extra=2
            )
            
            checked = summary.get('checked', 0)
            reassigned = len(summary.get('reassigned', []))
            cancelled = len(summary.get('cancelled', []))
            failed = len(summary.get('failed', []))
            
            print("\n" + "-"*80)
            print("[SUMMARY] REASSIGNMENT SUMMARY")
            print("-"*80)
            success_msg = f'[OK] Rescheduling complete: Checked={checked}, Reassigned={reassigned}, Cancelled={cancelled}, Failed={failed}'
            self.stdout.write(self.style.SUCCESS(success_msg))
            print(f"   [OK] Checked bookings: {checked}")
            print(f"   [REASSIGN] Reassigned: {reassigned}")
            print(f"   [CANCEL] Cancelled: {cancelled}")
            print(f"   [FAILED] Failed: {failed}")
            print("-"*80)
            
            if dry_run:
                dry_run_msg = 'DRY RUN MODE - No changes were committed'
                self.stdout.write(self.style.WARNING(dry_run_msg))
                print(f"\n[WARNING] {dry_run_msg}")
            
            logger.info(
                f"Morning reschedule completed for {target_date}: "
                f"checked={checked}, reassigned={reassigned}, cancelled={cancelled}, failed={failed}"
            )
            
            # Print summary details
            if summary.get('reassigned'):
                print(f"\n[REASSIGNED] REASSIGNED BOOKINGS ({min(10, len(summary['reassigned']))} of {len(summary['reassigned'])}):")
                self.stdout.write(f'\nReassigned bookings ({min(10, len(summary["reassigned"]))} of {len(summary["reassigned"])}):')
                for item in summary['reassigned'][:10]:
                    item_msg = f'  - Booking {item[0]}: {item[1]} -> {item[2]}'
                    self.stdout.write(item_msg)
                    print(f"   {item_msg}")
            
            if summary.get('cancelled'):
                print(f"\n[CANCELLED] CANCELLED BOOKINGS ({min(10, len(summary['cancelled']))} of {len(summary['cancelled'])}):")
                self.stdout.write(f'\nCancelled bookings ({min(10, len(summary["cancelled"]))} of {len(summary["cancelled"])}):')
                for c in summary['cancelled'][:10]:
                    cancel_msg = f'  - {c}'
                    self.stdout.write(cancel_msg)
                    print(f"   {cancel_msg}")
            
            if summary.get('failed'):
                print(f"\n[FAILED] FAILED REASSIGNMENTS ({min(10, len(summary['failed']))} of {len(summary['failed'])}):")
                for f in summary['failed'][:10]:
                    print(f"   - {f}")
                    
        except Exception as e:
            error_msg = f'[ERROR] Error running rescheduling algorithm: {str(e)}'
            self.stdout.write(self.style.ERROR(error_msg))
            print(f"\n[ERROR] {error_msg}")
            import traceback
            print(traceback.format_exc())
            logger.exception(f"Error running rescheduling algorithm for {target_date}: {e}")
            return
        
        completion_msg = f'\nMorning reschedule process completed for {target_date.isoformat()}'
        self.stdout.write(self.style.SUCCESS(completion_msg))
        print("\n" + "="*80)
        print("="*80)
        print(f">>> EMERGENCY LEAVE REASSIGNMENT ALGORITHM - COMPLETED")
        print("="*80)
        print("="*80 + "\n")

