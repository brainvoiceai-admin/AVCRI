import os
import django
import pandas as pd

# Setup Django environment
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "AVCRI.settings")
django.setup()

from    Patient.models import Therapist

# Load Excel
file_path = "C:\\Users\\jaise\\OneDrive\\Desktop\\AVCRI-old\\Therapist List.xlsx"
df = pd.read_excel(file_path, sheet_name="Sheet3")

# Insert into Therapist table
for _, row in df.iterrows():
    Therapist.objects.update_or_create(
        therapist_code=row["Therapist Code"],
        defaults={
            "therapist_name": row["Therapist Name"],
            "therapist_grade": row["Therapist Grade"],
        }
    )

print("✅ Therapist data imported successfully")
