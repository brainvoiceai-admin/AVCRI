import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'AVCRI.settings')
django.setup()

from django.db import connection

cursor = connection.cursor()
cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'masters_%' ORDER BY name;")
tables = cursor.fetchall()

print("Masters tables found:")
for table in tables:
    print(f"  - {table[0]}")

print(f"\nTotal: {len(tables)} tables")
