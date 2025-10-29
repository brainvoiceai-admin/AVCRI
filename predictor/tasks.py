from celery import shared_task
from django.core.management import call_command


@shared_task
def task_predictor_daily():
    call_command('run_daily_forecast')


@shared_task
def task_predictor_weekly():
    call_command('run_weekly_forecast')


@shared_task
def task_predictor_monthly():
    call_command('run_monthly_forecast')


@shared_task
def task_predictor_automated():
    """Optional combined automated run if needed."""
    call_command('run_automated_forecast')


