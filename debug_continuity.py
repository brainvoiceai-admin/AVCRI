import os
import django
from datetime import date, timedelta
from django.conf import settings

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'AVCRI.settings')
django.setup()

from Patient.models import TherapistBooking
from masters.models import TherapistLeaveMaster, EmergencyLeave
from Sheduling.models import PatientSnapshot

def test_continuity_logic():
    print("Starting test...")
    try:
        from_date = date.today() - timedelta(days=7)
        to_date = date.today()
        
        print(f"Fetching bookings from {from_date} to {to_date}")
        
        # Mirroring the view query
        bookings = TherapistBooking.objects.filter(
            date__range=[from_date, to_date],
            status__in=['BOOKED', 'scheduled', 'COMPLETED']
        ).select_related('therapist', 'visit__patient').order_by('date')
        
        print(f"Found {bookings.count()} bookings")
        
        for i, b in enumerate(bookings):
            # Test field access
            d_str = b.date.strftime('%Y-%m-%d')
            t_name = b.therapist.therapist_name
            pat_id = b.patient_id
            
            # Test related access that might fail
            if b.visit:
                # print(f"Booking {i} has visit: {b.visit.id}")
                if b.visit.patient:
                    p_name = b.visit.patient.pat_name
                    # print(f"  Patient: {p_name}")
                else:
                    print(f"Booking {i} has visit {b.visit.id} BUT NO PATIENT")
            else:
                # print(f"Booking {i} has NO visit. Pat ID: {pat_id}")
                pass
                
        print("Booking iteration success.")
        
        # Test Leave Query
        print("Testing leave queries...")
        # Emergency
        e_leaves = EmergencyLeave.objects.filter(from_date__lte=to_date, to_date__gte=from_date)
        print(f"Found {e_leaves.count()} emergency leaves")
        
        # Weekly
        weekly = TherapistLeaveMaster.objects.all().values('therapist_id', 'leave_day')
        print(f"Found {len(weekly)} weekly leaves")
        
        print("Test COMPLETE - SUCCESS")
        
    except Exception as e:
        print("\n\n!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!")
        print(f"CRASHED: {e}")
        import traceback
        traceback.print_exc()
        print("!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!\n\n")

if __name__ == "__main__":
    test_continuity_logic()
