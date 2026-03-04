import os
import django
import sys

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'AVCRI.settings')
django.setup()

from masters.models import TherapistMaster
import json

try:
    unlinked = TherapistMaster.objects.filter(is_active=True, user__isnull=True).order_by('therapist_name')
    data = [
        {
            'code': tm.therapist_code,
            'name': tm.therapist_name,
            'employee_code': tm.employee_code or '',
            'label': f"{tm.therapist_code} - {tm.therapist_name}",
        }
        for tm in unlinked
    ]
    print(json.dumps(data, indent=2))
except Exception as e:
    print('Error:', e)
