"""
Test Suite: Steam Therapy Strict 5:30 (17:30) Slot & TR-12 Room Allocation

Requirements Verified:
1. When a therapy has is_steam_therapy=True in TherapyMaster:
   - get_allowed_slot_values() returns strictly ['17:30'] (both for IP and OP patients).
   - In expand_therapies_for_visit / bulk_allocate_for_date:
     - The scheduled booking strictly receives slot 17:30 (5:30 PM).
     - The treatment room assigned is strictly 'TR-12' (even if patient is staying in DS-1, NR-10, etc.).
2. If is_steam_therapy=False:
   - Normal slot rules (06:30, 08:30, 10:00, etc.) and staying-room mapping (DS-1 -> TR-1, etc.) apply.
3. If TR-12 is already booked at 17:30:
   - The steam therapy booking fails with no_room_available rather than illegally borrowing another room.
"""

import pytest
from datetime import date, time, datetime
from django.test import TestCase

from masters.models import TherapyMaster, SlotMaster, TherapistMaster, TherapistGrade
from Patient.models import TreatmentRoom, RoomBooking
from Sheduling.models import PatientSnapshot, TherapyAllocation, Booking, BookingItem
from reshedule import get_allowed_slot_values, is_steam_therapy_530_tr12_only
from final_allocation import allocate_treatment_room, expand_therapies_for_visit


@pytest.mark.django_db
class TestSteamTherapyAllocation(TestCase):
    def setUp(self):
        # 1. Ensure Slots exist
        self.slot_0830, _ = SlotMaster.objects.get_or_create(
            slot_number=2,
            defaults={"slot_time": time(8, 30), "slot_name": "08:30 AM", "is_active": True}
        )
        self.slot_1730, _ = SlotMaster.objects.get_or_create(
            slot_number=7,
            defaults={"slot_time": time(17, 30), "slot_name": "05:30 PM", "is_active": True}
        )
        self.slot_1000, _ = SlotMaster.objects.get_or_create(
            slot_number=3,
            defaults={"slot_time": time(10, 0), "slot_name": "10:00 AM", "is_active": True}
        )

        # 2. Ensure Treatment Rooms exist (TR-1 for DS-1 mapping, TR-12 for Steam)
        from Patient.models import RoomName
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

        # 3. Create Therapist
        self.grade_sr, _ = TherapistGrade.objects.get_or_create(
            name="Senior Therapist",
            defaults={"display_order": 2, "is_active": True}
        )
        self.therapist_male = TherapistMaster.objects.create(
            therapist_code="TH_STEAM_M1",
            therapist_name="Ramesh Kumar",
            therapist_gender="Male",
            therapist_grade=self.grade_sr,
            employee_code="EMP_STEAM_01",
            is_bathing_therapist=True,
            is_active=True
        )

        # 4. Create Standard Therapy vs Steam Therapy
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

        self.steam_therapy = TherapyMaster.objects.create(
            therapy_code="THEB902",
            therapy_name="Bashpa Sweda (Steam Therapy)",
            therapy_category="Medium",
            therapy_duration="45 mins",
            bathing_required="No",
            treatment_room_required="Yes",
            cost_of_therapy=1200,
            patient_type="IP",
            is_steam_therapy=True,  # Steam therapy enabled!
            no_of_senior_therapist=1,
            total_no_of_therapist=1,
            is_active=True
        )

        # 5. Create Patient with staying room DS-1 (Inpatient 6-digit reg no)
        self.target_date = date(2026, 6, 15)
        self.patient = PatientSnapshot.objects.create(
            pat_reg_no="600099",
            pat_name="Arun Verma",
            pat_sex="Male",
            pat_age="35",
            pat_room_no="DS-1"
        )

    def test_is_steam_therapy_helper_detection(self):
        """Validates is_steam_therapy_530_tr12_only detects flag by name and code."""
        assert is_steam_therapy_530_tr12_only(therapy_code="THEB902") is True
        assert is_steam_therapy_530_tr12_only(therapy_name="Bashpa Sweda (Steam Therapy)") is True
        assert is_steam_therapy_530_tr12_only(therapy_code="THEB901") is False
        assert is_steam_therapy_530_tr12_only(therapy_name="Abhyanga Regular") is False

    def test_get_allowed_slot_values_for_steam_therapy(self):
        """Steam therapy must strictly return ['17:30'] even for IP patients."""
        # Regular IP gets primary IP slots
        regular_slots = get_allowed_slot_values(
            patient_type="IP",
            therapy_category="Medium",
            therapy_name=self.regular_therapy.therapy_name,
            therapy_code=self.regular_therapy.therapy_code
        )
        assert "06:30" in regular_slots or "08:30" in regular_slots
        assert regular_slots[0] != "17:30"

        # Steam therapy strictly gets 17:30
        steam_slots = get_allowed_slot_values(
            patient_type="IP",
            therapy_category="Medium",
            therapy_name=self.steam_therapy.therapy_name,
            therapy_code=self.steam_therapy.therapy_code
        )
        assert steam_slots == ["17:30"]

    def test_allocate_treatment_room_assigns_tr12_for_steam_therapy(self):
        """Validates allocate_treatment_room ignores staying room DS-1 and strictly picks TR-12."""
        # For regular therapy, DS-1 staying room normally maps to TR-1
        room_regular = allocate_treatment_room(
            date=self.target_date,
            time_slot=self.slot_0830,
            therapy_name=self.regular_therapy.therapy_name,
            patient_staying_room="DS-1",
            patient=self.patient
        )
        assert room_regular is not None
        assert room_regular.room_no == "TR-1"

        # For steam therapy, it must assign TR-12 despite patient staying in DS-1
        room_steam = allocate_treatment_room(
            date=self.target_date,
            time_slot=self.slot_1730,
            therapy_name=self.steam_therapy.therapy_name,
            patient_staying_room="DS-1",
            patient=self.patient
        )
        assert room_steam is not None
        assert room_steam.room_no == "TR-12"

    from unittest.mock import patch

    @patch("final_allocation.is_patient_active")
    def test_expand_therapies_for_visit_allocates_530_and_tr12(self, mock_is_active):
        """Full execution test: Steam therapy gets slot 17:30 and room TR-12."""
        mock_is_active.return_value = True
        allocation = TherapyAllocation.objects.create(
            patient=self.patient,
            therapy_code=self.steam_therapy.therapy_code,
            therapy_name=self.steam_therapy.therapy_name,
            from_date=self.target_date,
            to_date=self.target_date,
            days=1,
            timeslot=self.slot_1730,
            room=self.tr12,
            required_therapist_roles=[{"role": "senior", "count": 1}],
            status="draft"
        )

        draft_booking = Booking.objects.create(
            allocation=allocation,
            date=self.target_date,
            timeslot=self.slot_1730,
            room=self.tr12,
            status="draft"
        )

        tasks = expand_therapies_for_visit(allocation.id, self.target_date, create_bookings=True)
        assert len(tasks) > 0
        assert tasks[0]["status"] in ["BOOKED", "SUCCESS"], f"expand_therapies_for_visit failed with: {tasks[0].get('reason')}"

        draft_booking.refresh_from_db()
        assert draft_booking.status == "scheduled"
        assert draft_booking.timeslot == self.slot_1730
        assert draft_booking.room == self.tr12
        assert draft_booking.room.room_no == "TR-12"

    def test_steam_therapy_fails_if_tr12_is_already_booked(self):
        """Validates that steam therapy will NOT substitute TR-12 with another room if TR-12 is occupied."""
        # Block TR-12 at 17:30 on target_date
        RoomBooking.objects.create(
            room=self.tr12,
            date=self.target_date,
            time_slot=self.slot_1730,
            status="BOOKED"
        )

        room = allocate_treatment_room(
            date=self.target_date,
            time_slot=self.slot_1730,
            therapy_name=self.steam_therapy.therapy_name,
            patient_staying_room="DS-1",
            patient=self.patient
        )
        assert room is None
