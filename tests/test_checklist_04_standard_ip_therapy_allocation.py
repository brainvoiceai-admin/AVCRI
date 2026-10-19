"""
Checklist #4: Standard IP Therapy Slot Allocation (Happy Path) Test Suite

Validates that:
- Inpatients (pat_type='IP') are allocated primary operating slots (06:30, 08:30, 10:00, 14:30, 16:00).
- bulk_allocate_for_date() schedules draft IP bookings into 'scheduled' status.
- Synchronized TherapistBooking and RoomBooking records are committed with matching date and slot.
- Treatment room assigned corresponds to the patient's staying room mapping (e.g. DS-1 maps to TR-1/TR-2/TR-3/TR-4/TR-7/TR-8).
- BookingAssignment records are created linking therapist to booking.
"""
import pytest
from datetime import date, time, timedelta
from unittest.mock import patch
from django.test import TestCase

from Sheduling.models import (
    PatientSnapshot,
    TherapyAllocation,
    Booking,
    BookingAssignment,
)
from masters.models import (
    SlotMaster,
    TherapistGrade,
    TherapistMaster,
    TherapyMaster,
)
from Patient.models import TreatmentRoom, RoomName, TherapistBooking, RoomBooking
from final_allocation import (
    bulk_allocate_for_date,
    therapy_cache,
    get_treatment_rooms_for_staying_room,
)
from reshedule import get_allowed_slot_values

TARGET_DATE = date(2099, 9, 22)
TARGET_DATE_STR = TARGET_DATE.isoformat()

IP_PRIMARY_SLOT_TIMES = ["06:30", "08:30", "10:00", "14:30", "16:00"]


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


def _ensure_therapist(code, name, gender, grade, emp_code, is_bathing=True):
    obj, _ = TherapistMaster.objects.get_or_create(
        therapist_code=code,
        defaults={
            "therapist_name": name,
            "therapist_gender": gender,
            "therapist_grade": grade,
            "employee_code": emp_code,
            "is_bathing_therapist": is_bathing,
            "is_helping_therapist": False,
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


def _ensure_therapy(code, name, grade_counts, bathing="No", room_req="Yes", category="General"):
    obj, _ = TherapyMaster.objects.get_or_create(
        therapy_code=code,
        defaults={
            "therapy_name": name,
            "therapy_category": category,
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


@pytest.mark.django_db(transaction=True)
class TestChecklist04StandardIPTherapyAllocation(TestCase):
    """
    Checklist #4:
    Standard IP Therapy Slot Allocation (Happy Path):
    Inpatients (pat_type='IP') are allocated primary operating slots (06:30, 08:30, 10:00, 14:30, 16:00),
    creating synchronized TherapistBooking and RoomBooking records.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # Ensure standard primary IP slots exist in SlotMaster
        cls.slot_0630 = _ensure_slot(1, time(6, 30))
        cls.slot_0830 = _ensure_slot(2, time(8, 30))
        cls.slot_1000 = _ensure_slot(3, time(10, 0))
        cls.slot_1430 = _ensure_slot(4, time(14, 30))
        cls.slot_1600 = _ensure_slot(5, time(16, 0))

        # Ensure Senior grade exists
        cls.grade_senior = _ensure_grade("Senior Therapist", 2)

        # Ensure Male Senior Therapist exists
        cls.therapist_male_senior = _ensure_therapist(
            code="TH_IP_SNR_M",
            name="Male Senior IP Therapist",
            gender="Male",
            grade=cls.grade_senior,
            emp_code="EMP_IP_SNR_M",
        )

        # Ensure treatment room TR-1 (matching DS-1 staying room) exists
        cls.room_tr1 = _ensure_room("TR-1")

        # Ensure therapy needing 1 Senior therapist and 1 room exists
        cls.therapy = _ensure_therapy(
            code="TH_IP_STD",
            name="Standard Abhyangam IP",
            grade_counts={"senior": 1},
            bathing="No",
            room_req="Yes",
            category="General",
        )

    def setUp(self):
        therapy_cache.clear()

    def tearDown(self):
        therapy_cache.clear()
        BookingAssignment.objects.filter(booking__date=TARGET_DATE).delete()
        TherapistBooking.objects.filter(date=TARGET_DATE).delete()
        RoomBooking.objects.filter(date=TARGET_DATE).delete()
        Booking.objects.filter(date=TARGET_DATE).delete()
        TherapyAllocation.objects.filter(therapy_code=self.therapy.therapy_code).delete()
        PatientSnapshot.objects.filter(pat_reg_no__startswith="6000").delete()

    def test_ip_allowed_slots_match_primary_operating_range(self):
        """Validates that get_allowed_slot_values returns the 5 primary IP operating slots."""
        allowed_slots = get_allowed_slot_values(patient_type="IP", therapy_category="General")
        assert allowed_slots == IP_PRIMARY_SLOT_TIMES, (
            f"Expected primary IP slots {IP_PRIMARY_SLOT_TIMES}, got {allowed_slots}"
        )

    @patch("final_allocation.is_patient_active")
    def test_checklist_04_standard_ip_therapy_slot_allocation_happy_path(self, mock_is_active):
        """
        Checklist #4 Scenario:
        Inpatient (pat_type='IP'), Male, Room DS-1. Therapy needs 1 Male Senior, 1 Room.
        1. Create TherapyAllocation for target date with primary IP operating slot (10:00).
        2. Trigger bulk_allocate_for_date().
        3. Inspect Booking and linked tables:
           - Booking created with status='scheduled'.
           - Slot assigned is from primary IP range (06:30, 08:30, 10:00, 14:30, 16:00).
           - TherapistBooking and RoomBooking committed with matching date and slot.
           - Room matches DS-1 staying room mapping (TR-1).
           - BookingAssignment record created.
        """
        mock_is_active.return_value = True

        # 1. Create Inpatient (pat_type='IP' via 6-digit pat_reg_no), Male, staying room DS-1
        pat = PatientSnapshot.objects.create(
            pat_reg_no="600001",
            pat_name="Rahul Sharma",
            pat_sex="Male",
            pat_age="38",
            pat_room_no="DS-1",
        )
        assert pat.is_op() is False, "Patient should be identified as Inpatient (is_op=False)"

        # 2. Ingest draft TherapyAllocation for target date
        alloc = TherapyAllocation.objects.create(
            patient=pat,
            therapy_code=self.therapy.therapy_code,
            therapy_name=self.therapy.therapy_name,
            from_date=TARGET_DATE,
            to_date=TARGET_DATE,
            days=1,
            timeslot=self.slot_1000,
            room=self.room_tr1,
            required_therapist_roles=[{"role": "senior", "count": 1}],
            status="draft",
        )
        bk = Booking.objects.create(
            allocation=alloc,
            date=TARGET_DATE,
            timeslot=self.slot_1000,
            room=self.room_tr1,
            status="draft",
        )

        # 3. Trigger bulk_allocate_for_date()
        response = bulk_allocate_for_date(TARGET_DATE_STR)
        assert response.get("success") is True, f"bulk_allocate_for_date failed: {response}"

        # 4. Assert: Booking created with status='scheduled'
        bk.refresh_from_db()
        assert bk.status == "scheduled", (
            f"Expected booking status 'scheduled', got: '{bk.status}' (failure_reason: {bk.failure_reason})"
        )

        # 5. Assert: Slot assigned from primary IP range
        assigned_slot_str = bk.timeslot.slot_time.strftime("%H:%M")
        assert assigned_slot_str in IP_PRIMARY_SLOT_TIMES, (
            f"Slot {assigned_slot_str} not in primary IP operating range: {IP_PRIMARY_SLOT_TIMES}"
        )
        assert assigned_slot_str == "10:00"

        # 6. Assert: Synchronized TherapistBooking committed with matching date and slot
        tb = TherapistBooking.objects.filter(
            patient_id=pat.id,
            date=TARGET_DATE,
            status="BOOKED",
        ).first()
        assert tb is not None, "TherapistBooking was not created!"
        assert tb.therapist == self.therapist_male_senior
        assert tb.date == TARGET_DATE
        assert tb.time_slot == bk.timeslot
        assert tb.therapist.therapist_gender == "Male"
        assert tb.therapist.therapist_grade.name == "Senior Therapist"

        # 7. Assert: Synchronized RoomBooking committed with matching date and slot
        rb = RoomBooking.objects.filter(
            patient_id=pat.id,
            date=TARGET_DATE,
            status="BOOKED",
        ).first()
        assert rb is not None, "RoomBooking was not created!"
        assert rb.date == TARGET_DATE
        assert rb.time_slot == bk.timeslot
        assert rb.room == self.room_tr1
        # Confirm room is in DS-1 staying room allowed list
        ds1_allowed_rooms = get_treatment_rooms_for_staying_room("DS-1")
        assert rb.room.room_no in ds1_allowed_rooms, (
            f"Room {rb.room.room_no} not in DS-1 mapped rooms: {ds1_allowed_rooms}"
        )

        # 8. Assert: BookingAssignment links therapist to booking
        ba = BookingAssignment.objects.filter(booking=bk).first()
        assert ba is not None, "BookingAssignment was not created!"
        assert ba.therapist.therapist_code == self.therapist_male_senior.therapist_code

    @patch("final_allocation.is_patient_active")
    def test_ip_therapy_allocation_across_all_primary_operating_slots(self, mock_is_active):
        """
        Validates happy-path allocation across each of the primary operating slots
        (06:30, 08:30, 10:00, 14:30, 16:00) with matching TherapistBooking and RoomBooking.
        """
        mock_is_active.return_value = True

        slots = [self.slot_0630, self.slot_0830, self.slot_1430, self.slot_1600]
        for idx, slot in enumerate(slots, start=2):
            pat = PatientSnapshot.objects.create(
                pat_reg_no=f"60000{idx}",
                pat_name=f"IP Patient {idx}",
                pat_sex="Male",
                pat_age="40",
                pat_room_no="DS-1",
            )
            assert pat.is_op() is False
            alloc = TherapyAllocation.objects.create(
                patient=pat,
                therapy_code=self.therapy.therapy_code,
                therapy_name=self.therapy.therapy_name,
                from_date=TARGET_DATE,
                to_date=TARGET_DATE,
                days=1,
                timeslot=slot,
                room=self.room_tr1,
                required_therapist_roles=[{"role": "senior", "count": 1}],
                status="draft",
            )
            bk = Booking.objects.create(
                allocation=alloc,
                date=TARGET_DATE,
                timeslot=slot,
                room=self.room_tr1,
                status="draft",
            )

            response = bulk_allocate_for_date(TARGET_DATE_STR)
            assert response.get("success") is True

            bk.refresh_from_db()
            assert bk.status == "scheduled"
            assert bk.timeslot.slot_time.strftime("%H:%M") in IP_PRIMARY_SLOT_TIMES

            # Synchronized TherapistBooking check
            tb = TherapistBooking.objects.filter(patient_id=pat.id, date=TARGET_DATE, status="BOOKED").first()
            assert tb is not None
            assert tb.time_slot == slot

            # Synchronized RoomBooking check
            rb = RoomBooking.objects.filter(patient_id=pat.id, date=TARGET_DATE, status="BOOKED").first()
            assert rb is not None
            assert rb.time_slot == slot
            assert rb.room.room_no in get_treatment_rooms_for_staying_room("DS-1")
