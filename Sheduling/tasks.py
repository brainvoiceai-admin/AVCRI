from celery import shared_task
from django.core.management import call_command
from django.utils import timezone


@shared_task
def task_reschedule_morning(dry_run: bool = False):
    """Update emergency leave for today and run reassignment for today."""
    from datetime import date
    import api
    api.enable_django_for_scheduling()
    today_str = date.today().strftime('%Y-%m-%d')
    # Update leave
    api.get_employees_on_leave_and_save(target_date=today_str, save_to_db=True)
    # Run the same logic as management command
    call_command('reschedule_morning', dry_run=dry_run)


@shared_task
def task_reschedule_night(dry_run: bool = False):
    """Update emergency leave for tomorrow and run reassignment for tomorrow."""
    from datetime import date, timedelta
    import api
    api.enable_django_for_scheduling()
    tomorrow = date.today() + timedelta(days=1)
    # Update leave
    api.get_employees_on_leave_and_save(target_date=tomorrow.strftime('%Y-%m-%d'), save_to_db=True)
    # Run the same logic as management command
    call_command('reschedule_night', dry_run=dry_run)


