import os
import django
from django.db import transaction
from django.db.models import Q # Not strictly necessary here, but often useful for complex filtering

# 1. Set up the Django Environment
# Replace 'your_project_name.settings' with the actual path to your settings module.
# (e.g., if your project is 'AVCRI', it would be 'AVCRI.settings')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'AVCRI.settings')
django.setup()

# one-off script
from MySql_Data_pull.models import store_TherapyItem, store_TherapyItemDay

items = store_TherapyItem.objects.all()
created_total = 0
for it in items:
    created = store_TherapyItemDay.expand_for_item(it)
    created_total += (created or 0)
print("Created day rows:", created_total)
