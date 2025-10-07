from django.core.management.base import BaseCommand
from predictor.forecast import run_prophet_and_store

class Command(BaseCommand):
    help = "Run daily patient forecast (next 30 days)."

    def handle(self, *args, **options):
        res = run_prophet_and_store(freq="D", periods=30, prediction_type="daily")
        self.stdout.write(str(res))
