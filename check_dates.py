
import os
import django
from django.db import connections

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'AVCRI.settings')
django.setup()

reg_no = '105122011'
print(f"Checking Medication_History for Reg No: {reg_no}")

with connections['therapy_db'].cursor() as cursor:
    # Check columns first
    try:
        cursor.execute("SELECT TOP 1 * FROM [dbo].[Medication_History]")
        columns = [col[0] for col in cursor.description]
        print(f"Columns: {columns}")
        
        # Check data
        cursor.execute("SELECT TOP 5 * FROM [dbo].[Medication_History] WHERE Pat_Reg_No = %s", [reg_no])
        rows = cursor.fetchall()
        if rows:
            print("Found history rows:")
            for row in rows:
                print(row) # Dump raw row to see dates
        else:
            print("No history rows found for this patient.")
            
    except Exception as e:
        print(f"Error: {e}")
