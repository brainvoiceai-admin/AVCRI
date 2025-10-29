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
        # Determine target date
        if options['date']:
            try:
                target_date = datetime.strptime(options['date'], '%Y-%m-%d').date()
            except ValueError:
                self.stdout.write(self.style.ERROR(f'Invalid date format: {options["date"]}. Use YYYY-MM-DD.'))
                return
        else:
            target_date = timezone.localtime(timezone.now()).date()
        
        dry_run = options.get('dry_run', False)
        
        self.stdout.write(self.style.SUCCESS(f'Starting morning reschedule for date: {target_date.isoformat()}'))
        
        # Step 1: Update emergency leave data via api.py
        self.stdout.write(self.style.WARNING('Step 1: Updating emergency leave data...'))
        try:
            import api
            api.enable_django_for_scheduling()
            
            date_str = target_date.strftime('%Y-%m-%d')
            employees_on_leave = api.get_employees_on_leave_and_save(
                target_date=date_str,
                save_to_db=True
            )
            
            self.stdout.write(self.style.SUCCESS(
                f'✓ Emergency leave updated: {len(employees_on_leave)} employees on leave'
            ))
            logger.info(f"Emergency leave updated for {target_date}: {len(employees_on_leave)} employees")
            
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'✗ Error updating emergency leave: {str(e)}'))
            logger.exception(f"Error updating emergency leave for {target_date}: {e}")
            # Continue anyway - the rescheduling algorithm can work with existing leave data
        
        # Step 2: Run rescheduling algorithm
        self.stdout.write(self.style.WARNING('Step 2: Running rescheduling algorithm...'))
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
            
            self.stdout.write(self.style.SUCCESS(
                f'✓ Rescheduling complete: Checked={checked}, Reassigned={reassigned}, Cancelled={cancelled}, Failed={failed}'
            ))
            
            if dry_run:
                self.stdout.write(self.style.WARNING('DRY RUN MODE - No changes were committed'))
            
            logger.info(
                f"Morning reschedule completed for {target_date}: "
                f"checked={checked}, reassigned={reassigned}, cancelled={cancelled}, failed={failed}"
            )
            
            # Print summary details
            if summary.get('reassigned'):
                self.stdout.write(f'\nReassigned bookings ({min(10, len(summary["reassigned"]))} of {len(summary["reassigned"])}):')
                for item in summary['reassigned'][:10]:
                    self.stdout.write(f'  - Booking {item[0]}: {item[1]} → {item[2]}')
            
            if summary.get('cancelled'):
                self.stdout.write(f'\nCancelled bookings ({min(10, len(summary["cancelled"]))} of {len(summary["cancelled"])}):')
                for c in summary['cancelled'][:10]:
                    self.stdout.write(f'  - {c}')
                    
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'✗ Error running rescheduling algorithm: {str(e)}'))
            logger.exception(f"Error running rescheduling algorithm for {target_date}: {e}")
            return
        
        self.stdout.write(self.style.SUCCESS(f'\nMorning reschedule process completed for {target_date.isoformat()}'))

