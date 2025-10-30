from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import date, timedelta
from predictor.models import ForecastRun
from predictor.forecast import run_prophet_for_date_range
from django.contrib.auth import get_user_model

User = get_user_model()

class Command(BaseCommand):
    help = "Run automated daily forecast for the next 30 days"

    def add_arguments(self, parser):
        parser.add_argument(
            '--run-type',
            type=str,
            default='daily',
            choices=['daily', 'weekly', 'monthly', 'all'],
            help='Type of forecast to run'
        )
        parser.add_argument(
            '--periods',
            type=int,
            default=30,
            help='Number of periods to forecast'
        )
        parser.add_argument(
            '--user-id',
            type=int,
            help='User ID to associate with the forecast run (defaults to system)'
        )

    def handle(self, *args, **options):
        run_type = options['run_type']
        periods = options['periods']
        user_id = options.get('user_id')
        
        # Get user or use system user
        try:
            if user_id:
                user = User.objects.get(id=user_id)
            else:
                # Try to get a superuser, or create a system user
                user = User.objects.filter(is_superuser=True).first()
                if not user:
                    self.stdout.write(
                        self.style.WARNING('No superuser found. Forecast run will not be associated with any user.')
                    )
                    user = None
        except User.DoesNotExist:
            self.stdout.write(
                self.style.ERROR(f'User with ID {user_id} not found.')
            )
            return

        # Calculate date range
        start_date = date.today()
        if run_type == 'daily':
            end_date = start_date + timedelta(days=periods - 1)
        elif run_type == 'weekly':
            end_date = start_date + timedelta(weeks=periods)
        elif run_type == 'monthly':
            end_date = start_date + timedelta(days=30 * periods)
        else:
            end_date = start_date + timedelta(days=periods - 1)

        # Create forecast run record
        forecast_run = ForecastRun.objects.create(
            run_type=run_type,
            started_by=user,
            start_date=start_date,
            end_date=end_date,
            periods=periods,
            aggregate_by='day' if run_type == 'daily' else ('week' if run_type == 'weekly' else 'month'),
            status='running'
        )

        self.stdout.write(f"Starting {run_type} forecast run (ID: {forecast_run.id})...")

        try:
            if run_type == 'daily':
                result = run_prophet_for_date_range(
                    start_date=start_date,
                    end_date=end_date,
                    aggregate_by='day',
                    freq='D',
                    prediction_type='daily'
                )
            elif run_type == 'weekly':
                result = run_prophet_for_date_range(
                    start_date=start_date,
                    end_date=end_date,
                    aggregate_by='week',
                    freq='W-MON',
                    prediction_type='weekly'
                )
            elif run_type == 'monthly':
                result = run_prophet_for_date_range(
                    start_date=start_date,
                    end_date=end_date,
                    aggregate_by='month',
                    freq='MS',
                    prediction_type='monthly'
                )
            elif run_type == 'all':
                # Run all three types
                daily_result = run_prophet_for_date_range(
                    start_date=start_date,
                    end_date=end_date,
                    aggregate_by='day',
                    freq='D',
                    prediction_type='daily'
                )
                weekly_result = run_prophet_for_date_range(
                    start_date=start_date,
                    end_date=end_date,
                    aggregate_by='week',
                    freq='W-MON',
                    prediction_type='weekly'
                )
                monthly_result = run_prophet_for_date_range(
                    start_date=start_date,
                    end_date=end_date,
                    aggregate_by='month',
                    freq='MS',
                    prediction_type='monthly'
                )
                
                # Combine results
                result = {
                    'status': 'ok',
                    'stored': (daily_result.get('stored', 0) + 
                             weekly_result.get('stored', 0) + 
                             monthly_result.get('stored', 0)),
                    'skipped_missing': (daily_result.get('skipped_missing', 0) + 
                                      weekly_result.get('skipped_missing', 0) + 
                                      monthly_result.get('skipped_missing', 0)),
                    'skipped_outliers': (daily_result.get('skipped_outliers', 0) + 
                                       weekly_result.get('skipped_outliers', 0) + 
                                       monthly_result.get('skipped_outliers', 0))
                }

            # Mark as completed
            forecast_run.mark_completed(
                predictions_created=result.get('stored', 0),
                predictions_updated=0,  # We're using overwrite=True
                outliers_skipped=result.get('skipped_outliers', 0)
            )

            self.stdout.write(
                self.style.SUCCESS(
                    f"Forecast completed successfully! "
                    f"Created {result.get('stored', 0)} predictions, "
                    f"skipped {result.get('skipped_outliers', 0)} outliers."
                )
            )

        except Exception as e:
            forecast_run.mark_failed(str(e))
            self.stdout.write(
                self.style.ERROR(f"Forecast failed: {str(e)}")
            )
            raise
