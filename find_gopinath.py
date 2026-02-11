
import os
import django
from django.db import connections

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'AVCRI.settings')
django.setup()

name_part = 'Gopinath'
print(f"Searching Registration for name like: {name_part}")

with connections['therapy_db'].cursor() as cursor:
    cursor.execute("SELECT Pat_Reg_No, Pat_Name FROM [dbo].[Registration] WHERE Pat_Name LIKE %s", ['%Gopinath%'])
    rows = cursor.fetchall()
    
    print("\n--- Registration Results ---")
    if not rows:
        print("No matches.")
    else:
        for row in rows:
            reg_no = row[0]
            name = row[1]
            print(f"Reg: {reg_no}, Name: {name}")
            
            # Check Prescribtion for this reg
            cursor.execute("SELECT COUNT(DISTINCT Pres_Date) FROM [dbo].[Prescribtion] WHERE Pres_Reg_No = %s", [reg_no])
            count_reg = cursor.fetchone()[0]
            print(f"  > Prescribtion count: {count_reg}")
            if count_reg > 0:
                 cursor.execute("SELECT DISTINCT Pres_Date FROM [dbo].[Prescribtion] WHERE Pres_Reg_No = %s ORDER BY Pres_Date DESC", [reg_no])
                 dates = cursor.fetchall()
                 for d in dates:
                     print(f"    - {d[0]}")
            
            # Check Prescribtion_Special for this reg
            try:
                cursor.execute("SELECT COUNT(DISTINCT Pres_Date) FROM [dbo].[Prescribtion_Special] WHERE Pres_Reg_No = %s", [reg_no])
                count_special = cursor.fetchone()[0]
                if count_special > 0:
                    print(f"  > Prescribtion_Special count: {count_special}")
            except Exception as e:
                pass


