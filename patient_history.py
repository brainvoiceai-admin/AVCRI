import os
import django
import pandas as pd

# ---------------- SETUP DJANGO ----------------
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "AVCRI.settings")  # update to your project
django.setup()

# ---------------- IMPORT MODEL ----------------
from Patient.models import TreatmentRoom  # update your app name

# ---------------- LOAD EXCEL ----------------
file_path = r"C:\\Users\\jaise\\OneDrive\\Desktop\\AVCRI-old\\dbo.Room_Master.csv"
df = pd.read_csv(file_path)

# ---------------- INSERT DATA ----------------
for _, row in df.iterrows():
    room_no = str(row['Room_No']).strip()
    floor = str(row['Room_floor']).strip() if not pd.isna(row['Room_floor']) else None
    description = str(row['Room_Desc']).strip() if not pd.isna(row['Room_Desc']) else None
    rent = float(row['Room_Rent']) if not pd.isna(row['Room_Rent']) else None

    obj, created = TreatmentRoom.objects.get_or_create(
        room_no=room_no,
        defaults={
            'floor': floor,
            'description': description,
            'rent': rent
        }
    )
    if created:
        print(f"Created room: {room_no}")
    else:
        print(f"Room {room_no} already exists")

print("All treatment rooms processed!")
