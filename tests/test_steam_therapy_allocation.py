"""
Test Suite: Steam Therapy TR-12 & TR-9 Room Allocation (No Slot Restriction)

Requirements Verified:
1. When a therapy has is_steam_therapy=True in TherapyMaster:
   - There are NO forced slot restrictions; slots are allocated according to user selection / standard patient rules.
   - get_allowed_slot_values() follows standard rules (no forced 17:30 constraint).
   - In allocate_treatment_room / expand_therapies_for_visit:
     - Treatment rooms eligible are strictly TR-12 and TR-9 (even if patient is staying in DS-1, NR-10, etc.).
     - If TR-12 is available, it is allocated.
     - If TR-12 is occupied, TR-9 is allocated as alternative.
     - If both TR-12 and TR-9 are occupied, allocation fails with no_room_available (no other rooms like TR-1, TR-2 borrowed).
"""

import pytest
from datetime import date, time
from unittest.mock import patch
from django.test import TestCase

from masters.models import TherapyMaster, SlotMaster, TherapistMaster, TherapistGrade
from Patient.models import TreatmentRoom, RoomName, RoomBooking
from Sheduling.models import PatientSnapshot, TherapyAllocation, Booking
from reshedule import get_allowed_slot_values, is_steam_therapy_treatment, get_steam_therapy_rooms
from final_allocation import allocate_treatment_room, expand_therapies_for_visit


@pytest.mark.django_db
class TestSteamTherapyAllocation(TestCase):
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

        # 2. Ensure Treatment Rooms exist (TR-1 for DS-1 mapping, TR-12 and TR-9 for Steam)
        rn1, _ = RoomName.objects.get_or_create(name="Room TR-1", defaults={"is_active": True})
        self.tr1, _ = TreatmentRoom.objects.get_or_create(
            room_no="TR-1",
            defaults={"room_name": rn1, "floor": "G", "is_active": True, "is_steam_room": False}
        )
        self.tr1.is_steam_room = False
        self.tr1.save()

        rn9, _ = RoomName.objects.get_or_create(name="Room TR-9", defaults={"is_active": True})
        self.tr9, _ = TreatmentRoom.objects.get_or_create(
            room_no="TR-9",
            defaults={"room_name": rn9, "floor": "G", "is_active": True, "is_steam_room": True}
        )
        self.tr9.is_steam_room = True
        self.tr9.save()

        rn12, _ = RoomName.objects.get_or_create(name="Room TR-12", defaults={"is_active": True})
        self.tr12, _ = TreatmentRoom.objects.get_or_create(
            room_no="TR-12",
            defaults={"room_name": rn12, "floor": "G", "is_active": True, "is_steam_room": True}
        )
        self.tr12.is_steam_room = True
        self.tr12.save()

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
        """Validates is_steam_therapy_treatment detects flag by name and code."""
        assert is_steam_therapy_treatment(therapy_code="THEB902") is True
        assert is_steam_therapy_treatment(therapy_name="Bashpa Sweda (Steam Therapy)") is True
        assert is_steam_therapy_treatment(therapy_code="THEB901") is False
        assert is_steam_therapy_treatment(therapy_name="Abhyanga Regular") is False

    def test_no_slot_restriction_for_steam_therapy(self):
        """Steam therapy has NO forced 17:30 slot restriction; follows standard allowed slots."""
        steam_slots = get_allowed_slot_values(
            patient_type="IP",
            therapy_category="Medium",
            therapy_name=self.steam_therapy.therapy_name,
            therapy_code=self.steam_therapy.therapy_code
        )
        # Should have standard IP slots (06:30, 08:30, 10:00, etc.), not locked only to 17:30
        assert len(steam_slots) > 1
        assert "08:30" in steam_slots
        assert "10:00" in steam_slots

    def test_allocate_treatment_room_assigns_tr12_first_for_steam_therapy(self):
        """Validates allocate_treatment_room assigns TR-12 first for steam therapy, bypassing staying room DS-1."""
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

        # For steam therapy at selected slot (e.g. 08:30 AM), it assigns TR-12
        room_steam = allocate_treatment_room(
            date=self.target_date,
            time_slot=self.slot_0830,
            therapy_name=self.steam_therapy.therapy_name,
            patient_staying_room="DS-1",
            patient=self.patient
        )
        assert room_steam is not None
        assert room_steam.room_no == "TR-12"

    def test_allocate_treatment_room_falls_back_to_tr9_if_tr12_occupied(self):
        """Validates allocate_treatment_room assigns TR-9 when TR-12 is booked at the selected slot."""
        # Block TR-12 at 10:00
        RoomBooking.objects.create(
            room=self.tr12,
            date=self.target_date,
            time_slot=self.slot_1000,
            status="BOOKED"
        )

        room_steam = allocate_treatment_room(
            date=self.target_date,
            time_slot=self.slot_1000,
            therapy_name=self.steam_therapy.therapy_name,
            patient_staying_room="DS-1",
            patient=self.patient
        )
        assert room_steam is not None
        assert room_steam.room_no == "TR-9"

    def test_steam_therapy_fails_if_both_tr12_and_tr9_are_booked(self):
        """Validates that steam therapy will NOT borrow other rooms (e.g. TR-1) if both TR-12 and TR-9 are occupied."""
        # Block both TR-12 and TR-9 at 08:30
        RoomBooking.objects.create(
            room=self.tr12,
            date=self.target_date,
            time_slot=self.slot_0830,
            status="BOOKED"
        )
        RoomBooking.objects.create(
            room=self.tr9,
            date=self.target_date,
            time_slot=self.slot_0830,
            status="BOOKED"
        )

        room = allocate_treatment_room(
            date=self.target_date,
            time_slot=self.slot_0830,
            therapy_name=self.steam_therapy.therapy_name,
            patient_staying_room="DS-1",
            patient=self.patient
        )
        assert room is None

    @patch("final_allocation.is_patient_active")
    def test_expand_therapies_for_visit_respects_selected_slot_and_steam_room(self, mock_is_active):
        """Full execution test: Steam therapy retains user-selected slot (10:00 AM) and gets TR-12."""
        mock_is_active.return_value = True
        allocation = TherapyAllocation.objects.create(
            patient=self.patient,
            therapy_code=self.steam_therapy.therapy_code,
            therapy_name=self.steam_therapy.therapy_name,
            from_date=self.target_date,
            to_date=self.target_date,
            days=1,
            timeslot=self.slot_1000,  # User selected 10:00 AM!
            room=self.tr12,
            required_therapist_roles=[{"role": "senior", "count": 1}],
            status="draft"
        )

        draft_booking = Booking.objects.create(
            allocation=allocation,
            date=self.target_date,
            timeslot=self.slot_1000,  # User selected 10:00 AM!
            room=self.tr12,
            status="draft"
        )

        tasks = expand_therapies_for_visit(allocation.id, self.target_date, create_bookings=True)
        assert len(tasks) > 0
        assert tasks[0]["status"] in ["BOOKED", "SUCCESS"], f"expand_therapies_for_visit failed with: {tasks[0].get('reason')}"

        draft_booking.refresh_from_db()
        assert draft_booking.status == "scheduled"
        # Slot must remain 10:00 AM (the user's selected slot, NOT forced to 17:30)
        assert draft_booking.timeslot == self.slot_1000
        assert draft_booking.room in [self.tr12, self.tr9]
        assert draft_booking.room.room_no == "TR-12"

    def test_dynamic_steam_room_toggle_allocation(self):
        """Validates that turning on steam therapy room toggle in room master dynamically considers the new room."""
        # Initially, steam rooms are TR-12 and TR-9
        steam_rooms = get_steam_therapy_rooms()
        assert "TR-12" in steam_rooms
        assert "TR-9" in steam_rooms
        assert "TR-1" not in steam_rooms

        # Turn ON steam therapy room toggle for TR-1 in room master
        self.tr1.is_steam_room = True
        self.tr1.save()

        # Dynamic query reflects new steam room TR-1
        updated_steam_rooms = get_steam_therapy_rooms()
        assert "TR-1" in updated_steam_rooms

        # When TR-12 and TR-9 are both booked at 08:30:
        RoomBooking.objects.create(
            room=self.tr12,
            date=self.target_date,
            time_slot=self.slot_0830,
            status="BOOKED"
        )
        RoomBooking.objects.create(
            room=self.tr9,
            date=self.target_date,
            time_slot=self.slot_0830,
            status="BOOKED"
        )

        # Allocate room for steam therapy: should now dynamically pick newly toggled TR-1!
        room = allocate_treatment_room(
            date=self.target_date,
            time_slot=self.slot_0830,
            therapy_name=self.steam_therapy.therapy_name,
            patient_staying_room="DS-1",
            patient=self.patient
        )
        assert room is not None
        assert room.room_no == "TR-1"

        # If we toggle TR-1 back OFF:
        self.tr1.is_steam_room = False
        self.tr1.save()

        # It should no longer be eligible for steam therapy when TR-12 and TR-9 are booked
        room_after_toggle_off = allocate_treatment_room(
            date=self.target_date,
            time_slot=self.slot_0830,
            therapy_name=self.steam_therapy.therapy_name,
            patient_staying_room="DS-1",
            patient=self.patient
        )
        assert room_after_toggle_off is None

    def test_treatment_room_master_toggle_steam_view(self):
        """Validates the toggle view endpoint changes is_steam_room status."""
        from django.contrib.auth import get_user_model
        from django.test import Client
        from django.urls import reverse

        User = get_user_model()
        admin_user, _ = User.objects.get_or_create(
            username="test_superadmin",
            defaults={"is_superuser": True, "is_staff": True, "role": "super_admin"}
        )
        if getattr(admin_user, 'role', None) != 'super_admin':
            admin_user.role = 'super_admin'
            admin_user.save()
        client = Client()
        client.force_login(admin_user)

        # Ensure TR-1 starts with is_steam_room=False
        self.tr1.is_steam_room = False
        self.tr1.save()

        url = reverse("treatment_room_master_toggle_steam", kwargs={"pk": self.tr1.room_no})
        response = client.get(url, follow=True)
        assert response.status_code == 200

        self.tr1.refresh_from_db()
        assert self.tr1.is_steam_room is True

        # Toggle back
        response2 = client.get(url, follow=True)
        assert response2.status_code == 200

        self.tr1.refresh_from_db()
        assert self.tr1.is_steam_room is False
