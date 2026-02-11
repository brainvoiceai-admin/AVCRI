
import os
import django
from django.db import connections

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'AVCRI.settings')
django.setup()

with connections['therapy_db'].cursor() as cursor:
    cursor.execute("SELECT TABLE_NAME FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_TYPE='BASE TABLE'")
    tables = [row[0] for row in cursor.fetchall()]
    print("All Tables related to Prescr or Med:")
    for table in tables:
        if 'prescri' in table.lower() or 'medic' in table.lower():
            print(table)
