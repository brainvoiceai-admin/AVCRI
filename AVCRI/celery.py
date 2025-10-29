import os

from celery import Celery


os.environ.setdefault("DJANGO_SETTINGS_MODULE", "AVCRI.settings")

app = Celery("AVCRI")

# Load config from Django settings, namespace CELERY_
app.config_from_object("django.conf:settings", namespace="CELERY")

# Autodiscover tasks in installed apps
app.autodiscover_tasks()


@app.task(bind=True)
def debug_task(self):
    return f"Request: {self.request!r}"


