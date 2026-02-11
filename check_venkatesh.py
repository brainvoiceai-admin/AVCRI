
import os
import django
from django.db import connections

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'AVCRI.settings')
django.setup()

print("Searching for patients with the MOST prescription history...")

with connections['therapy_db'].cursor() as cursor:
    query = """
    SELECT TOP 10 Pres_Reg_No, COUNT(DISTINCT Pres_Date) as DateCount
    FROM [dbo].[Prescribtion]
    GROUP BY Pres_Reg_No
    ORDER BY DateCount DESC
    """
    cursor.execute(query)
    rows = cursor.fetchall()
    
    if rows:
        print("\nTop 10 Patients with most history:")
        for row in rows:
            reg_no = row[0]
            count = row[1]
            print(f"Reg No: {reg_no} - {count} distinct dates")
            
            # Get name
            cursor.execute("SELECT Pat_Name FROM [dbo].[Registration] WHERE Pat_Reg_No = %s", [reg_no])
            name_row = cursor.fetchone()
            name = name_row[0] if name_row else "Unknown Name"
            print(f"  Name: {name}")
            
    else:
        print("No data found in Prescribtion table.")
