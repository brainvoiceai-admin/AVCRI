from django.core.management.base import BaseCommand
from predictor.forecast import run_prophet_and_store

class Command(BaseCommand):
    help = "Run weekly patient forecast (next 12 weeks)."

    def handle(self, *args, **options):
        res = run_prophet_and_store(freq="W", periods=12, prediction_type="weekly")
        self.stdout.write(str(res))
