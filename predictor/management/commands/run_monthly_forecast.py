from django.core.management.base import BaseCommand
from predictor.forecast import run_prophet_and_store

class Command(BaseCommand):
    help = "Run monthly patient forecast (next 6 months)."

    def handle(self, *args, **options):
        res = run_prophet_and_store(freq="ME", periods=6, prediction_type="monthly")
        self.stdout.write(str(res))
        
