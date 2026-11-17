import pytest
from datetime import date, time
from django.test import TestCase

from masters.models import TherapistMaster, TherapistGrade, SlotMaster, EmergencyLeave, TherapistLeaveMaster, TherapyMaster
from Sheduling.models import (
    PatientSnapshot,
    TherapyAllocation,
    Booking,
    BookingAssignment,
    PatientPreferredTherapistRoster,
    DoctorPatientPreferenceAllowance,
    TreatmentRoom
)
from Patient.models import TherapistBooking
from final_allocation import assign_continuity_therapists_pass1, allocate_therapists, expand_therapies_for_visit, therapist_requirements
from Sheduling.preferred_therapist_service import get_active_preferred_roster, pick_bathing_therapist_from_roster


class PreferredBathingTherapistAllocationTest(TestCase):
    def setUp(self):
        # Create therapy master
        self.therapy_master, _ = TherapyMaster.objects.get_or_create(
            therapy_code="THEB017",
            defaults={
                'therapy_name': 'Dhanyamala Dhara (3)',
                'bathing_required': 'Yes',
                'no_of_super_senior_therapist': 0,
                'no_of_senior_therapist': 1,
                'no_of_junior_therapist': 1,
                'no_of_trainee_therapist': 1,
                'total_no_of_therapist': 3,
                'is_active': True,
            }
        )

        # Create grades
        self.grade_ss, _ = TherapistGrade.objects.get_or_create(name="Super Senior Therapist")
        self.grade_sr, _ = TherapistGrade.objects.get_or_create(name="Senior Therapist")
        self.grade_jr, _ = TherapistGrade.objects.get_or_create(name="Junior Therapist")
        self.grade_tr, _ = TherapistGrade.objects.get_or_create(name="Trainee Therapist")

        # Create slots
        self.slot1, _ = SlotMaster.objects.get_or_create(slot_name="Slot 1: 08:00 AM", defaults={'slot_number': 1, 'slot_time': time(8, 0), 'is_active': True})
        self.slot2, _ = SlotMaster.objects.get_or_create(slot_name="Slot 2: 09:00 AM", defaults={'slot_number': 2, 'slot_time': time(9, 0), 'is_active': True})
        self.slot3, _ = SlotMaster.objects.get_or_create(slot_name="Slot 3: 10:00 AM", defaults={'slot_number': 3, 'slot_time': time(10, 0), 'is_active': True})

        # Create treatment room
        self.room, _ = TreatmentRoom.objects.get_or_create(room_no="TR-TEST")

        # Create 7 preferred female therapists
        # 1. Primary Bathing: Trainee, Bathing=True, Helping=False
        self.th_primary, _ = TherapistMaster.objects.get_or_create(
            therapist_code="THP_PRIM",
            defaults={
                'therapist_name': 'Primary Bathing',
                'therapist_gender': 'Female',
                'therapist_grade': self.grade_tr,
                'is_bathing_therapist': True,
                'is_helping_therapist': False,
                'is_active': True,
            }
        )
        # 2. Secondary Bathing: Trainee, Bathing=True, Helping=True (like Aishwarya THP1317)
        self.th_secondary, _ = TherapistMaster.objects.get_or_create(
            therapist_code="THP_SEC",
            defaults={
                'therapist_name': 'Secondary Bathing',
                'therapist_gender': 'Female',
                'therapist_grade': self.grade_tr,
                'is_bathing_therapist': True,
                'is_helping_therapist': True,
                'is_active': True,
            }
        )
        # 3. Senior 1: Bathing=True, Helping=False
        self.th_sr1, _ = TherapistMaster.objects.get_or_create(
            therapist_code="THP_SR1",
            defaults={
                'therapist_name': 'Senior One',
                'therapist_gender': 'Female',
                'therapist_grade': self.grade_sr,
                'is_bathing_therapist': True,
                'is_helping_therapist': False,
                'is_active': True,
            }
        )
        # 4. Senior 2: Bathing=True, Helping=False
        self.th_sr2, _ = TherapistMaster.objects.get_or_create(
            therapist_code="THP_SR2",
            defaults={
                'therapist_name': 'Senior Two',
                'therapist_gender': 'Female',
                'therapist_grade': self.grade_sr,
                'is_bathing_therapist': True,
                'is_helping_therapist': False,
                'is_active': True,
            }
        )
        # 5. Trainee 3: Bathing=True, Helping=False
        self.th_tr3, _ = TherapistMaster.objects.get_or_create(
            therapist_code="THP_TR3",
            defaults={
                'therapist_name': 'Trainee Three',
                'therapist_gender': 'Female',
                'therapist_grade': self.grade_tr,
                'is_bathing_therapist': True,
                'is_helping_therapist': False,
                'is_active': True,
            }
        )
        # 6. Trainee 4: Bathing=False, Helping=False
        self.th_tr4, _ = TherapistMaster.objects.get_or_create(
            therapist_code="THP_TR4",
            defaults={
                'therapist_name': 'Trainee Four',
                'therapist_gender': 'Female',
                'therapist_grade': self.grade_tr,
                'is_bathing_therapist': False,
                'is_helping_therapist': False,
                'is_active': True,
            }
        )
        # 7. Super Senior: Bathing=True, Helping=False
        self.th_ss, _ = TherapistMaster.objects.get_or_create(
            therapist_code="THP_SS",
            defaults={
                'therapist_name': 'Super Senior',
                'therapist_gender': 'Female',
                'therapist_grade': self.grade_ss,
                'is_bathing_therapist': True,
                'is_helping_therapist': False,
                'is_active': True,
            }
        )

        self.pref_codes = [
            "THP_PRIM", "THP_SEC", "THP_SR1", "THP_SR2", "THP_TR3", "THP_TR4", "THP_SS"
        ]

        # Create patient
        self.patient, _ = PatientSnapshot.objects.get_or_create(
            pat_reg_no="999082022",
            defaults={
                'pat_name': 'Preferred Patient Test',
                'pat_age': '45',
                'pat_sex': 'Female',
                'pat_room_no': 'NR-10',
                'is_vip': True,
            }
        )

        # Setup Preferred Roster
        self.roster, _ = PatientPreferredTherapistRoster.objects.get_or_create(
            patient_reg_no=self.patient.pat_reg_no,
            defaults={
                'therapist_codes': self.pref_codes,
                'primary_bathing_code': "THP_PRIM",
                'secondary_bathing_code': "THP_SEC",
                'is_active': True,
            }
        )

        # Setup Therapy Allocation (needs bathing, requires 3 therapists: Senior, Junior, Trainee)
        self.target_date = date(2026, 11, 17)  # Tuesday
        self.allocation, _ = TherapyAllocation.objects.get_or_create(
            patient=self.patient,
            therapy_code="THEB017",
            defaults={
                'therapy_name': 'Dhanyamala Dhara (3)',
                'from_date': self.target_date,
                'to_date': self.target_date,
                'days': 1,
                'timeslot': self.slot3,
                'room': self.room,
                'items_groups': [],
            }
        )

        self.booking, _ = Booking.objects.get_or_create(
            allocation=self.allocation,
            date=self.target_date,
            defaults={
                'timeslot': self.slot3,
                'room': self.room,
                'status': 'draft',
            }
        )

    def test_secondary_bathing_allocated_when_primary_on_leave(self):
        """
        When Primary Bathing Therapist is on emergency leave,
        Secondary Bathing Therapist (even if is_helping_therapist=True)
        MUST be allocated as the bathing therapist (*).
        """
        # Put Primary on Emergency Leave for target date
        EmergencyLeave.objects.create(
            therapist=self.th_primary,
            from_date=self.target_date,
            to_date=self.target_date,
            leave_type="emergency",
        )

        # Check pick_bathing_therapist_from_roster
        roster_info = get_active_preferred_roster(self.patient.pat_reg_no)
        picked_bath, role = pick_bathing_therapist_from_roster(roster_info, self.target_date, self.slot3)
        self.assertEqual(picked_bath, self.th_secondary)
        self.assertEqual(role, 'secondary')

        # Run Pass 1
        locked_slots = set()
        p1 = assign_continuity_therapists_pass1(self.booking, self.allocation, self.target_date, locked_slots)
        self.assertTrue(p1['success'])
        self.assertIn(self.th_secondary, p1['assigned_therapists'])
        self.assertEqual(p1['bath_assigned'], self.th_secondary)

        # Run allocate_therapists directly when free
        TherapistBooking.objects.filter(visit=self.allocation, date=self.target_date).delete()
        cand = allocate_therapists(
            self.target_date,
            self.slot3,
            therapist_requirements(self.allocation),
            needs_bathing=True,
            patient_gender="Female",
            patient_id=self.patient.pat_reg_no,
            patient_age="45",
        )
        cand_codes = [t.therapist_code for t in cand]
        self.assertIn("THP_SEC", cand_codes)
        # All allocated therapists must be from the preferred pool
        for code in cand_codes:
            self.assertIn(code, self.pref_codes)

    def test_primary_bathing_allocated_when_available(self):
        """
        When Primary Bathing Therapist is available,
        Primary Bathing Therapist MUST be allocated as the bathing therapist.
        """
        # Ensure no leaves
        EmergencyLeave.objects.filter(therapist=self.th_primary).delete()

        roster_info = get_active_preferred_roster(self.patient.pat_reg_no)
        picked_bath, role = pick_bathing_therapist_from_roster(roster_info, self.target_date, self.slot3)
        self.assertEqual(picked_bath, self.th_primary)
        self.assertEqual(role, 'primary')

        locked_slots = set()
        p1 = assign_continuity_therapists_pass1(self.booking, self.allocation, self.target_date, locked_slots)
        self.assertTrue(p1['success'])
        self.assertIn(self.th_primary, p1['assigned_therapists'])
        self.assertEqual(p1['bath_assigned'], self.th_primary)

    def test_end_to_end_expand_therapies_with_secondary_bathing(self):
        """
        End-to-end test with Primary on Emergency Leave:
        Pass 1 locks Secondary Bathing, Pass 2 fills remaining slots,
        and verifies that Secondary Bathing (Aishwarya-equivalent) is assigned
        with is_bathing=True in TherapistBooking.
        """
        EmergencyLeave.objects.create(
            therapist=self.th_primary,
            from_date=self.target_date,
            to_date=self.target_date,
            leave_type="emergency",
        )
        TherapistBooking.objects.filter(visit=self.allocation, date=self.target_date).delete()

        locked_slots = set()
        p1 = assign_continuity_therapists_pass1(self.booking, self.allocation, self.target_date, locked_slots)
        self.assertTrue(p1['success'])
        booking_continuity_map = {self.booking.pk: p1}

        tasks = expand_therapies_for_visit(
            self.allocation.id,
            self.target_date.strftime('%Y-%m-%d'),
            create_bookings=True,
            booking_continuity_map=booking_continuity_map,
        )
        self.assertIsInstance(tasks, list)
        self.assertEqual(len(tasks), 1)
        self.assertEqual(tasks[0]['status'], 'BOOKED')

        # Check therapists assigned in TherapistBooking
        tbs = list(TherapistBooking.objects.filter(
            visit=self.allocation,
            date=self.target_date,
            status='BOOKED'
        ))
        self.assertEqual(len(tbs), 3)
        assigned_codes = [tb.therapist.therapist_code for tb in tbs]
        self.assertIn("THP_SEC", assigned_codes)
        for code in assigned_codes:
            self.assertIn(code, self.pref_codes)

        # Ensure THP_SEC has is_bathing=True
        sec_tb = TherapistBooking.objects.get(
            visit=self.allocation,
            date=self.target_date,
            therapist__therapist_code="THP_SEC",
            status='BOOKED'
        )
        self.assertTrue(sec_tb.is_bathing)

        # Other therapists must have is_bathing=False
        other_tbs = TherapistBooking.objects.filter(
            visit=self.allocation,
            date=self.target_date,
            status='BOOKED'
        ).exclude(therapist__therapist_code="THP_SEC")
        for tb in other_tbs:
            self.assertFalse(tb.is_bathing)
