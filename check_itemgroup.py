import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'AVCRI.settings')
django.setup()

from django.db import connection

cursor = connection.cursor()

# Check for masters_itemgroup table
cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='masters_itemgroup';")
result = cursor.fetchone()

if result:
    print("✓ masters_itemgroup table EXISTS")
    
    # Check the structure
    cursor.execute("PRAGMA table_info(masters_itemgroup);")
    columns = cursor.fetchall()
    print("\nTable structure:")
    for col in columns:
        print(f"  - {col[1]} ({col[2]})")
else:
    print("✗ masters_itemgroup table NOT FOUND")
    
    # List all masters tables
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'masters_%' ORDER BY name;")
    tables = cursor.fetchall()
    print("\nAvailable masters tables:")
    for table in tables:
        print(f"  - {table[0]}")
