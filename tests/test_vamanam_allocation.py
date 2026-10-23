"""
Test Suite: Vamanam Therapy 5:30 Slot & TR-12 Room Allocation

Requirements Verified:
1. When therapy is Vamanam (THEB126 or 'vamanam' in therapy name):
   - Only 5:30 slot (17:30 / 05:30) is allowed and exposed.
   - get_allowed_slot_values() strictly returns only the 5:30 slot.
   - In allocate_treatment_room:
     - Treatment room is strictly fixed to TR-12.
     - If TR-12 is occupied, returns None (never falls back to TR-9, TR-1, etc.).
   - In expand_therapies_for_visit:
     - Timeslot is strictly locked to 17:30.
     - Room is strictly locked to TR-12.
     - Does not switch slots or rooms if TR-12 is booked.
"""

import pytest
from datetime import date, time
from unittest.mock import patch
from django.test import TestCase

from masters.models import TherapyMaster, SlotMaster, TherapistMaster, TherapistGrade
from Patient.models import TreatmentRoom, RoomName, RoomBooking
from Sheduling.models import PatientSnapshot, TherapyAllocation, Booking
from reshedule import get_allowed_slot_values, is_vamanam_treatment
from final_allocation import allocate_treatment_room, expand_therapies_for_visit
from Patient.views import compute_available_slots_for_date


@pytest.mark.django_db
class TestVamanamAllocation(TestCase):
    def setUp(self):
        # 1. Ensure Slots exist
        self.slot_0830, _ = SlotMaster.objects.get_or_create(
            slot_number=2,
            defaults={"slot_time": time(8, 30), "slot_name": "08:30 AM", "is_active": True}
        )
        self.slot_1000, _ = SlotMaster.objects.get_or_create(
            slot_number=3,
            defaults={"slot_time": time(10, 0), "slot_name": "10:00 AM", "is_active": True}
        )
        self.slot_1730, _ = SlotMaster.objects.get_or_create(
            slot_number=7,
            defaults={"slot_time": time(17, 30), "slot_name": "05:30 PM", "is_active": True}
        )

        # 2. Ensure Treatment Rooms exist (TR-1 for DS-1 default, TR-12 for Vamanam)
        rn1, _ = RoomName.objects.get_or_create(name="Room TR-1", defaults={"is_active": True})
        self.tr1, _ = TreatmentRoom.objects.get_or_create(
            room_no="TR-1",
            defaults={"room_name": rn1, "floor": "G", "is_active": True}
        )

        rn12, _ = RoomName.objects.get_or_create(name="Room TR-12", defaults={"is_active": True})
        self.tr12, _ = TreatmentRoom.objects.get_or_create(
            room_no="TR-12",
            defaults={"room_name": rn12, "floor": "G", "is_active": True}
        )

        rn9, _ = RoomName.objects.get_or_create(name="Room TR-9", defaults={"is_active": True})
        self.tr9, _ = TreatmentRoom.objects.get_or_create(
            room_no="TR-9",
            defaults={"room_name": rn9, "floor": "G", "is_active": True}
        )

        # 3. Create Therapist
        self.grade_sr, _ = TherapistGrade.objects.get_or_create(
            name="Senior Therapist",
            defaults={"display_order": 2, "is_active": True}
        )
        self.therapist_male = TherapistMaster.objects.create(
            therapist_code="TH_VAM_M1",
            therapist_name="Suresh Kumar",
            therapist_gender="Male",
            therapist_grade=self.grade_sr,
            employee_code="EMP_VAM_01",
            is_bathing_therapist=True,
            is_active=True
        )

        # 4. Create Standard Therapy vs Vamanam Therapy
        self.regular_therapy = TherapyMaster.objects.create(
            therapy_code="THEB901",
            therapy_name="Abhyanga Regular",
            therapy_category="Medium",
            therapy_duration="45 mins",
            bathing_required="No",
            treatment_room_required="Yes",
            cost_of_therapy=1000,
            patient_type="IP",
            is_steam_therapy=False,
            no_of_senior_therapist=1,
            total_no_of_therapist=1,
            is_active=True
        )

        self.vamanam_therapy = TherapyMaster.objects.create(
            therapy_code="THEB126",
            therapy_name="Vamanam ( 1 T)",
            therapy_category="Hard",
            therapy_duration="60 mins",
            bathing_required="No",
            treatment_room_required="Yes",
            cost_of_therapy=2500,
            patient_type="IP",
            no_of_senior_therapist=1,
            total_no_of_therapist=1,
            is_active=True
        )

        # 5. Create Patient staying in DS-1
        self.patient = PatientSnapshot.objects.create(
            pat_reg_no="PAT_VAM_001",
            pat_name="Arun Varma",
            pat_sex="Male",
            pat_age="35",
            pat_room_no="DS-1"
        )
        self.target_date = date(2026, 11, 10)

    def test_is_vamanam_treatment_identification(self):
        """Validates is_vamanam_treatment correctly identifies Vamanam by code and name."""
        self.assertTrue(is_vamanam_treatment(therapy_code="THEB126"))
        self.assertTrue(is_vamanam_treatment(therapy_name="Vamanam ( 1 T)"))
        self.assertTrue(is_vamanam_treatment(therapy_name="vamanam"))
        self.assertFalse(is_vamanam_treatment(therapy_name="Abhyanga Regular", therapy_code="THEB901"))

    def test_get_allowed_slot_values_returns_only_530_slot(self):
        """Validates get_allowed_slot_values restricts slots strictly to 17:30 (5:30 PM)."""
        allowed = get_allowed_slot_values(
            patient_type="IP",
            therapy_category="Hard",
            therapy_name="Vamanam ( 1 T)",
            therapy_code="THEB126"
        )
        self.assertEqual(allowed, ["17:30"])

    def test_compute_available_slots_returns_only_530_slot(self):
        """Validates compute_available_slots_for_date in Patient/views.py candidate slots return strictly 17:30."""
        slots = compute_available_slots_for_date(
            date_obj=self.target_date,
            therapy_name="Vamanam ( 1 T)",
            patient_type="IP",
            therapy_code="THEB126"
        )
        slot_values = [s["value"] for s in slots]
        # In this mock date, if therapists/rooms qualify for 17:30, only 17:30 can appear
        for s in slot_values:
            self.assertEqual(s, "17:30")

    def test_allocate_treatment_room_strictly_assigns_tr12(self):
        """Validates allocate_treatment_room assigns TR-12 for Vamanam, ignoring DS-1 staying room (TR-1)."""
        # For regular therapy, DS-1 gets TR-1
        room_regular = allocate_treatment_room(
            date=self.target_date,
            time_slot=self.slot_1730,
            therapy_name=self.regular_therapy.therapy_name,
            patient_staying_room=self.patient.pat_room_no,
            patient=self.patient
        )
        self.assertEqual(room_regular.room_no, "TR-1")

        # For Vamanam, strictly TR-12
        room_vamanam = allocate_treatment_room(
            date=self.target_date,
            time_slot=self.slot_1730,
            therapy_name=self.vamanam_therapy.therapy_name,
            patient_staying_room=self.patient.pat_room_no,
            patient=self.patient
        )
        self.assertEqual(room_vamanam.room_no, "TR-12")

    def test_allocate_treatment_room_returns_none_if_tr12_occupied(self):
        """Validates allocate_treatment_room returns None if TR-12 is occupied, never falling back to other rooms."""
        RoomBooking.objects.create(
            room=self.tr12,
            date=self.target_date,
            time_slot=self.slot_1730,
            status='BOOKED'
        )
        room_vamanam = allocate_treatment_room(
            date=self.target_date,
            time_slot=self.slot_1730,
            therapy_name=self.vamanam_therapy.therapy_name,
            patient_staying_room=self.patient.pat_room_no,
            patient=self.patient
        )
        self.assertIsNone(room_vamanam)

    @patch("final_allocation.is_patient_active")
    def test_expand_therapies_for_visit_allocates_1730_and_tr12(self, mock_is_active):
        """Validates expand_therapies_for_visit successfully schedules Vamanam to slot 17:30 and room TR-12."""
        mock_is_active.return_value = True
        alloc = TherapyAllocation.objects.create(
            patient=self.patient,
            therapy_name=self.vamanam_therapy.therapy_name,
            therapy_code=self.vamanam_therapy.therapy_code,
            from_date=self.target_date,
            to_date=self.target_date,
            days=1,
            timeslot=self.slot_1730,
            required_therapist_roles=[{"role": "senior", "count": 1}],
            status='draft'
        )
        b = Booking.objects.create(
            allocation=alloc,
            date=self.target_date,
            timeslot=self.slot_1730,
            status='draft'
        )

        tasks = expand_therapies_for_visit(
            therapy_allocation_id=alloc.pk,
            target_date=self.target_date,
            create_bookings=True
        )

        b.refresh_from_db()
        self.assertEqual(b.status, 'scheduled')
        self.assertEqual(b.timeslot.slot_time, time(17, 30))
        self.assertEqual(b.room.room_no, 'TR-12')
        self.assertEqual(len(tasks), 1)
        self.assertIn(tasks[0]["status"], ["BOOKED", "SUCCESS", "SCHEDULED"])
        self.assertEqual(tasks[0]["room_no"], "TR-12")

    @patch("final_allocation.is_patient_active")
    def test_expand_therapies_for_visit_forces_1730_even_if_draft_has_other_slot(self, mock_is_active):
        """Validates expand_therapies_for_visit forces 17:30 slot for Vamanam even if draft had 10:00."""
        mock_is_active.return_value = True
        alloc = TherapyAllocation.objects.create(
            patient=self.patient,
            therapy_name=self.vamanam_therapy.therapy_name,
            therapy_code=self.vamanam_therapy.therapy_code,
            from_date=self.target_date,
            to_date=self.target_date,
            days=1,
            timeslot=self.slot_1000,
            required_therapist_roles=[{"role": "senior", "count": 1}],
            status='draft'
        )
        b = Booking.objects.create(
            allocation=alloc,
            date=self.target_date,
            timeslot=self.slot_1000,
            status='draft'
        )

        tasks = expand_therapies_for_visit(
            therapy_allocation_id=alloc.pk,
            target_date=self.target_date,
            create_bookings=True
        )

        b.refresh_from_db()
        self.assertEqual(b.status, 'scheduled')
        self.assertEqual(b.timeslot.slot_time, time(17, 30))
        self.assertEqual(b.room.room_no, 'TR-12')
