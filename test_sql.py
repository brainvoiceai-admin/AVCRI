import os
import django

# Setup Django environment
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "AVCRI.settings")
django.setup()

from MySql_Data_pull.models import store_Therapy

def clear_therapydata():
    store_Therapy.objects.all().delete()
    print("✅ All TherapyDetails records cleared!")

if __name__ == "__main__":
    clear_therapydata()
