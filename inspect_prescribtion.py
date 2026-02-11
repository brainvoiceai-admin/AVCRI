
import os
import django
from django.db import connections

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'AVCRI.settings')
django.setup()

with connections['therapy_db'].cursor() as cursor:
    cursor.execute("SELECT TOP 1 * FROM Prescribtion")
    columns = [col[0] for col in cursor.description]
    print(columns)
