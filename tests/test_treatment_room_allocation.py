"""
Treatment Room Allocation, Double-Booking & Staying Room Mapping Test Suite

Validates treatment room allocation:
- therapy_needs_room helper check.
- Staying room to treatment room mapping rules (get_treatment_rooms_for_staying_room):
  * DS-1..6 -> TR-1, TR-2, TR-3, TR-4, TR-7, TR-8
  * NR-7..14 -> TR-3, TR-4, TR-7, TR-8, TR-11, TR-12
  * NR-15..21 -> TR-5, TR-6, TR-7, TR-8, TR-11, TR-12, TR-9, TR-10, TR-13, TR-14
  * NR-22..27 -> TR-7, TR-8, TR-5, TR-6, TR-11, TR-12, TR-9, TR-10, TR-13, TR-14
  * NR-28..33 -> TR-15, TR-16
  * MG-1..10, CB-1..2, FG-1..12 -> TR-9..14, TR-7, TR-8
  * CT-1..N -> TRC-1..N
- Double-booking prevention: A room cannot be occupied by two patients at the same date + timeslot.
- Alternative room fallback when preferred room is already booked.
"""
import pytest
from datetime import date, time, timedelta
from unittest.mock import patch
from django.test import TestCase

from Sheduling.models import PatientSnapshot, TherapyAllocation, Booking
from masters.models import SlotMaster, TherapistGrade, TherapistMaster, TherapyMaster
from Patient.models import TreatmentRoom, RoomName, RoomBooking, TherapistBooking
from final_allocation import (
    bulk_allocate_for_date,
    therapy_needs_room,
    get_treatment_rooms_for_staying_room,
)

TARGET_DATE = date(2099, 9, 22)
TARGET_DATE_STR = TARGET_DATE.isoformat()


def _ensure_slot(number, slot_time):
    obj, _ = SlotMaster.objects.get_or_create(
        slot_number=number,
        defaults={"slot_time": slot_time, "is_active": True},
    )
    if obj.slot_time != slot_time:
        obj.slot_time = slot_time
        obj.save(update_fields=["slot_time"])
    return obj


def _ensure_grade(name, order):
    obj, _ = TherapistGrade.objects.get_or_create(
        name=name,
        defaults={"display_order": order, "is_active": True},
    )
    return obj


def _ensure_therapy(code, name, grade_counts, bathing="No", room_req="Yes", category="General", group=None):
    obj, _ = TherapyMaster.objects.get_or_create(
        therapy_code=code,
        defaults={
            "therapy_name": name,
            "therapy_category": category,
            "therapy_group": group,
            "therapy_duration": "30",
            "bathing_required": bathing,
            "treatment_room_required": room_req,
            "no_of_super_senior_therapist": grade_counts.get("super_senior", 0),
            "no_of_senior_therapist": grade_counts.get("senior", 0),
            "no_of_junior_therapist": grade_counts.get("junior", 0),
            "no_of_trainee_therapist": grade_counts.get("trainee", 0),
            "total_no_of_therapist": sum(grade_counts.values()),
            "is_active": True,
        },
    )
    return obj


def _ensure_therapist(code, name, gender, grade, emp_code, is_bathing=True, is_helping=False):
    obj, _ = TherapistMaster.objects.get_or_create(
        therapist_code=code,
        defaults={
            "therapist_name": name,
            "therapist_gender": gender,
            "therapist_grade": grade,
            "employee_code": emp_code,
            "is_bathing_therapist": is_bathing,
            "is_helping_therapist": is_helping,
            "is_active": True,
        },
    )
    return obj


def _ensure_room(room_no):
    room_name, _ = RoomName.objects.get_or_create(name=f"Room {room_no}", defaults={"is_active": True})
    obj, _ = TreatmentRoom.objects.get_or_create(
        room_no=room_no,
        defaults={"room_name": room_name, "floor": "G", "is_active": True},
    )
    return obj


@pytest.mark.django_db(transaction=True)
class TestTreatmentRoomAllocationAndConflicts(TestCase):
    """
    Validates room allocation:
    - therapy_needs_room helper returns True when treatment_room_required == 'Yes'.
    - get_treatment_rooms_for_staying_room accurately routes patient staying rooms to treatment rooms.
    - Double-booking prevention: A room cannot be occupied by two patients at the same date + slot.
    - Automatic room fallback: When Room 1 is booked, Room 2 is allocated.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.slot = _ensure_slot(91, time(14, 30))
        cls.grade = _ensure_grade("Senior Therapist", 2)

        cls.therapy = _ensure_therapy(
            "T_ROOM_TEST", "Room Requirement Therapy", {"senior": 1}, room_req="Yes"
        )
        cls.th = _ensure_therapist("TH_RM_1", "Room Therapist 1", "Male", cls.grade, "EMP_RM_1")
        cls.th2 = _ensure_therapist("TH_RM_2", "Room Therapist 2", "Male", cls.grade, "EMP_RM_2")

        cls.room1 = _ensure_room("ROOM_TEST_1")
        cls.room2 = _ensure_room("ROOM_TEST_2")

    def tearDown(self):
        RoomBooking.objects.filter(date=TARGET_DATE).delete()
        TherapistBooking.objects.filter(date=TARGET_DATE).delete()
        Booking.objects.filter(date=TARGET_DATE).delete()
        TherapyAllocation.objects.filter(therapy_code=self.therapy.therapy_code).delete()
        PatientSnapshot.objects.filter(pat_reg_no__startswith="3000").delete()

    def test_therapy_needs_room_helper(self):
        """therapy_needs_room returns True when master has treatment_room_required == 'Yes'."""
        assert therapy_needs_room(self.therapy) is True

    def test_staying_room_mapping_rules(self):
        """
        Validates the staying room to treatment room mapping logic:
        - DS-1 to DS-6 -> TR-1/TR-2 -> TR-3/TR-4 -> TR-7/TR-8
        - NR-7 to NR-14 -> TR-3/TR-4 -> TR-7/TR-8 -> TR-11/TR-12
        - NR-15 to NR-21 -> TR-5/6 -> TR-7/8 -> TR-11/12 -> TR-9/10/13/14
        - NR-22 to NR-27 -> TR-7/8 -> TR-5/6 -> TR-11/12 -> TR-9/10/13/14
        - NR-28 to NR-33 -> TR-15/TR-16
        - MG-1 to MG-10, CB-1/2, FG-1 to FG-12 -> TR-9 to TR-14 -> TR-7/TR-8
        - CT-1, CT-2 -> TRC-1, TRC-2
        """
        assert get_treatment_rooms_for_staying_room("DS-1") == ['TR-1', 'TR-2', 'TR-3', 'TR-4', 'TR-7', 'TR-8']
        assert get_treatment_rooms_for_staying_room("NR-10") == ['TR-3', 'TR-4', 'TR-7', 'TR-8', 'TR-11', 'TR-12']
        assert get_treatment_rooms_for_staying_room("NR-18") == ['TR-5', 'TR-6', 'TR-7', 'TR-8', 'TR-11', 'TR-12', 'TR-9', 'TR-10', 'TR-13', 'TR-14']
        assert get_treatment_rooms_for_staying_room("NR-25") == ['TR-7', 'TR-8', 'TR-5', 'TR-6', 'TR-11', 'TR-12', 'TR-9', 'TR-10', 'TR-13', 'TR-14']
        assert get_treatment_rooms_for_staying_room("NR-28") == ['TR-15', 'TR-16']
        assert get_treatment_rooms_for_staying_room("MG-5") == ['TR-9', 'TR-10', 'TR-11', 'TR-12', 'TR-13', 'TR-14', 'TR-7', 'TR-8']
        assert get_treatment_rooms_for_staying_room("CB-2") == ['TR-9', 'TR-10', 'TR-11', 'TR-12', 'TR-13', 'TR-14', 'TR-7', 'TR-8']
        assert get_treatment_rooms_for_staying_room("FG-7") == ['TR-9', 'TR-10', 'TR-11', 'TR-12', 'TR-13', 'TR-14', 'TR-7', 'TR-8']
        assert get_treatment_rooms_for_staying_room("CT-1") == ['TRC-1']
        assert get_treatment_rooms_for_staying_room("CT-4") == ['TRC-4']
        assert get_treatment_rooms_for_staying_room(None) == []
        assert get_treatment_rooms_for_staying_room("UNKNOWN_ROOM") == []

    @patch("final_allocation.is_patient_active")
    def test_room_double_booking_prevention_and_fallback(self, mock_is_active):
        """
        When Room 1 is already BOOKED for Patient A at slot 14:30,
        Patient B's booking automatically selects alternative Room 2.
        """
        mock_is_active.return_value = True

        # Pre-book Room 1 for Patient A at TARGET_DATE + slot
        pat_a = PatientSnapshot.objects.create(
            pat_reg_no="300001", pat_name="Patient Occupying Room", pat_sex="Male", pat_age="30"
        )
        RoomBooking.objects.create(
            room=self.room1,
            patient_id=pat_a.id,
            date=TARGET_DATE,
            time_slot=self.slot,
            status="BOOKED",
        )

        # Patient B needs allocation at same date and slot, initially requesting Room 1
        pat_b = PatientSnapshot.objects.create(
            pat_reg_no="300002", pat_name="Patient Needing Room", pat_sex="Male", pat_age="30"
        )
        alloc_b = TherapyAllocation.objects.create(
            patient=pat_b,
            therapy_code=self.therapy.therapy_code,
            therapy_name=self.therapy.therapy_name,
            from_date=TARGET_DATE,
            to_date=TARGET_DATE + timedelta(days=6),
            days=7,
            timeslot=self.slot,
            room=self.room1,  # Conflicts with pat_a!
            required_therapist_roles=[{"role": "senior", "count": 1}],
            status="draft",
        )
        bk_b = Booking.objects.create(
            allocation=alloc_b,
            date=TARGET_DATE,
            timeslot=self.slot,
            room=self.room1,
            status="draft",
        )

        bulk_allocate_for_date(TARGET_DATE_STR)

        bk_b.refresh_from_db()
        # Booking should succeed by choosing alternative room (Room 2)
        assert bk_b.status == "scheduled", f"Booking failed with reason: {bk_b.failure_reason}"
        assert bk_b.room is not None
        assert bk_b.room.room_no != self.room1.room_no, (
            "Double-booking prevention failed: Patient B was assigned the already-booked Room 1!"
        )
