
import os
import django
from django.db import connections

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'AVCRI.settings')
django.setup()

# Check 1: Information Schema
print("\n--- Checking INFORMATION_SCHEMA.TABLES ---")
with connections['therapy_db'].cursor() as cursor:
    cursor.execute("SELECT TABLE_SCHEMA, TABLE_NAME FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME LIKE 'Prescri%' ORDER BY TABLE_NAME")
    rows = cursor.fetchall()
    for row in rows:
        print(f"  {row[0]}.{row[1]}")

# Check 2: Try SELECT on 'Prescription'
print("\n--- Trying SELECT on [dbo].[Prescription] ---")
try:
    with connections['therapy_db'].cursor() as cursor:
        cursor.execute("SELECT TOP 1 * FROM [dbo].[Prescription]")
        cols = [c[0] for c in cursor.description]
        print(f"  SUCCESS! Columns found: {cols}")
except Exception as e:
    print(f"  FAILED: {e}")

# Check 3: Try SELECT on 'Prescribtion' (just to compare)
print("\n--- Trying SELECT on [dbo].[Prescribtion] ---")
try:
    with connections['therapy_db'].cursor() as cursor:
        cursor.execute("SELECT TOP 1 * FROM [dbo].[Prescribtion]")
        cols = [c[0] for c in cursor.description]
        print(f"  SUCCESS! Columns found: {cols}")
except Exception as e:
    print(f"  FAILED: {e}")
