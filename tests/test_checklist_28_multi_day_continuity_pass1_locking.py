"""
Checklist #28: Multi-Day Continuity of Care (Pass 1 Therapist Locking) Test Suite

Validates that:
- Prior-day therapists are prioritized during Pass 1 locking to ensure patients
  retain the same practitioner across multi-day treatment plans.
- T_prev is locked and assigned to the patient before general candidate search.
- Continuity of bathing therapist is maintained across consecutive days.
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
    TherapistContinuityPlan,
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
    assign_continuity_therapists_pass1,
    therapy_cache,
)

TARGET_DATE = date(2099, 9, 22)
TARGET_DATE_STR = TARGET_DATE.isoformat()
YESTERDAY = TARGET_DATE - timedelta(days=1)


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
    if obj.is_bathing_therapist != is_bathing:
        obj.is_bathing_therapist = is_bathing
        obj.save(update_fields=["is_bathing_therapist"])
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
class TestChecklist28MultiDayContinuityPass1Locking(TestCase):
    """
    Checklist #28:
    Multi-Day Continuity of Care (Pass 1 Therapist Locking)
    Prior-day therapists are prioritized during Pass 1 locking to ensure patients
    retain the same practitioner and bathing therapist across multi-day treatment plans.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.slot = _ensure_slot(141, time(10, 0))
        cls.grade_senior = _ensure_grade("Senior Therapist", 2)

        # Prior-day primary therapist
        cls.t_prev = _ensure_therapist(
            code="TH_PREV_01",
            name="Previous Day Therapist",
            gender="Male",
            grade=cls.grade_senior,
            emp_code="EMP_PREV_01",
            is_bathing=True,
        )
        # Another eligible therapist (competitor in candidate search)
        cls.t_other = _ensure_therapist(
            code="TH_OTHER_02",
            name="Other Available Therapist",
            gender="Male",
            grade=cls.grade_senior,
            emp_code="EMP_OTHER_02",
            is_bathing=True,
        )

        cls.room = _ensure_room("TR-1")

        # Standard therapy
        cls.therapy = _ensure_therapy(
            code="T_CONT_01",
            name="Abhyangam Continuity Therapy",
            grade_counts={"senior": 1},
            bathing="No",
            room_req="Yes",
        )
        # Bathing required therapy
        cls.therapy_bath = _ensure_therapy(
            code="T_CONT_BATH",
            name="Abhyangam Bath Continuity Therapy",
            grade_counts={"senior": 1},
            bathing="Yes",
            room_req="Yes",
        )

    def setUp(self):
        therapy_cache.clear()

    def tearDown(self):
        therapy_cache.clear()
        BookingAssignment.objects.filter(booking__date__in=[YESTERDAY, TARGET_DATE]).delete()
        TherapistContinuityPlan.objects.filter(date=TARGET_DATE).delete()
        TherapistBooking.objects.filter(date__in=[YESTERDAY, TARGET_DATE]).delete()
        RoomBooking.objects.filter(date__in=[YESTERDAY, TARGET_DATE]).delete()
        Booking.objects.filter(date__in=[YESTERDAY, TARGET_DATE]).delete()
        TherapyAllocation.objects.filter(therapy_code__in=["T_CONT_01", "T_CONT_BATH"]).delete()
        PatientSnapshot.objects.filter(pat_reg_no__startswith="7000").delete()

    @patch("final_allocation.is_patient_active")
    def test_prior_day_therapist_locked_in_pass1_before_general_search(self, mock_is_active):
        """
        Checklist #28:
        1. Patient received therapy yesterday from Therapist T_prev.
        2. T_prev is free today at target slot. Another candidate T_other is also free.
        3. Trigger bulk_allocate_for_date().
        4. Engine locks T_prev in Pass 1 and assigns T_prev to patient (retaining continuity).
        """
        mock_is_active.return_value = True

        pat = PatientSnapshot.objects.create(
            pat_reg_no="700001",
            pat_name="Continuity Patient One",
            pat_sex="Male",
            pat_age="35",
            pat_room_no="DS-1",
        )

        alloc = TherapyAllocation.objects.create(
            patient=pat,
            therapy_code=self.therapy.therapy_code,
            therapy_name=self.therapy.therapy_name,
            from_date=YESTERDAY,
            to_date=TARGET_DATE,
            days=2,
            timeslot=self.slot,
            room=self.room,
            required_therapist_roles=[{"role": "senior", "count": 1}],
            status="draft",
        )

        # Yesterday's completed booking and TherapistBooking record
        bk_yesterday = Booking.objects.create(
            allocation=alloc,
            date=YESTERDAY,
            timeslot=self.slot,
            room=self.room,
            status="scheduled",
        )
        TherapistBooking.objects.create(
            therapist=self.t_prev,
            patient_id=pat.id,
            visit=alloc,
            therapy=self.therapy,
            date=YESTERDAY,
            time_slot=self.slot,
            status="BOOKED",
            is_bathing=False,
        )

        # Today's draft booking
        bk_today = Booking.objects.create(
            allocation=alloc,
            date=TARGET_DATE,
            timeslot=self.slot,
            room=self.room,
            status="draft",
        )

        # Run allocation for today
        response = bulk_allocate_for_date(TARGET_DATE_STR)
        assert response.get("success") is True, f"Allocation failed: {response}"

        bk_today.refresh_from_db()
        assert bk_today.status == "scheduled"

        # Assert: T_prev was assigned to today's booking (maintaining continuity instead of T_other)
        tb_today = TherapistBooking.objects.filter(
            patient_id=pat.id,
            date=TARGET_DATE,
            status="BOOKED",
        ).first()
        assert tb_today is not None, "TherapistBooking for today was not created!"
        assert tb_today.therapist == self.t_prev, (
            f"Expected continuity therapist {self.t_prev.therapist_code}, got {tb_today.therapist.therapist_code}"
        )

    @patch("final_allocation.is_patient_active")
    def test_bathing_continuity_maintained_across_consecutive_days(self, mock_is_active):
        """
        Checklist #28:
        Continuity of bathing therapist is maintained across consecutive days.
        Yesterday: T_prev was the bathing therapist (is_bathing=True).
        Today: T_prev is locked and continues as bathing therapist (is_bathing=True).
        """
        mock_is_active.return_value = True

        pat = PatientSnapshot.objects.create(
            pat_reg_no="700002",
            pat_name="Bathing Continuity Patient",
            pat_sex="Male",
            pat_age="45",
            pat_room_no="DS-1",
        )

        alloc = TherapyAllocation.objects.create(
            patient=pat,
            therapy_code=self.therapy_bath.therapy_code,
            therapy_name=self.therapy_bath.therapy_name,
            from_date=YESTERDAY,
            to_date=TARGET_DATE,
            days=2,
            timeslot=self.slot,
            room=self.room,
            required_therapist_roles=[{"role": "senior", "count": 1}],
            status="draft",
        )

        # Yesterday's TherapistBooking with is_bathing=True
        TherapistBooking.objects.create(
            therapist=self.t_prev,
            patient_id=pat.id,
            visit=alloc,
            therapy=self.therapy_bath,
            date=YESTERDAY,
            time_slot=self.slot,
            status="BOOKED",
            is_bathing=True,
        )

        # Today's draft booking
        bk_today = Booking.objects.create(
            allocation=alloc,
            date=TARGET_DATE,
            timeslot=self.slot,
            room=self.room,
            status="draft",
        )

        # Run bulk allocation for today
        response = bulk_allocate_for_date(TARGET_DATE_STR)
        assert response.get("success") is True

        bk_today.refresh_from_db()
        assert bk_today.status == "scheduled"

        # Assert: T_prev was assigned AND is_bathing is True for today as well
        tb_today = TherapistBooking.objects.filter(
            patient_id=pat.id,
            date=TARGET_DATE,
            status="BOOKED",
        ).first()
        assert tb_today is not None
        assert tb_today.therapist == self.t_prev
        assert tb_today.is_bathing is True, (
            "Bathing therapist continuity failed: is_bathing is False for today's booking!"
        )

    def test_direct_assign_continuity_therapists_pass1_locks_prior_day_therapist(self):
        """
        Directly validates assign_continuity_therapists_pass1():
        - Reads T_prev from TherapistContinuityPlan (priority=0, source_date=yesterday).
        - Locks T_prev into locked_therapist_slots.
        - Creates a TherapistBooking record to lock the slot before Pass 2 general search.
        """
        pat = PatientSnapshot.objects.create(
            pat_reg_no="700003",
            pat_name="Pass 1 Unit Patient",
            pat_sex="Male",
            pat_age="30",
            pat_room_no="DS-1",
        )

        alloc = TherapyAllocation.objects.create(
            patient=pat,
            therapy_code=self.therapy.therapy_code,
            therapy_name=self.therapy.therapy_name,
            from_date=YESTERDAY,
            to_date=TARGET_DATE,
            days=2,
            timeslot=self.slot,
            room=self.room,
            required_therapist_roles=[{"role": "senior", "count": 1}],
            status="draft",
        )

        bk_today = Booking.objects.create(
            allocation=alloc,
            date=TARGET_DATE,
            timeslot=self.slot,
            room=self.room,
            status="draft",
        )

        # Build TherapistContinuityPlan representing prior-day attendance
        TherapistContinuityPlan.objects.create(
            date=TARGET_DATE,
            time_slot=self.slot,
            patient=pat,
            allocation=alloc,
            therapist=self.t_prev,
            therapy_name=self.therapy.therapy_name,
            is_bathing=False,
            priority=0,
            source_date=YESTERDAY,
        )

        locked_slots = set()
        result = assign_continuity_therapists_pass1(
            booking=bk_today,
            allocation=alloc,
            target_date=TARGET_DATE,
            locked_therapist_slots=locked_slots,
        )

        # 1. Pass 1 succeeds in assigning continuity therapist
        assert result["success"] is True
        assert self.t_prev in result["assigned_therapists"]

        # 2. Slot is added to locked_therapist_slots
        assert (self.t_prev.id, self.slot.id) in locked_slots

        # 3. TherapistBooking record created to LOCK the slot
        tb_locked = TherapistBooking.objects.filter(
            therapist=self.t_prev,
            date=TARGET_DATE,
            time_slot=self.slot,
            status="BOOKED",
        ).first()
        assert tb_locked is not None, "Pass 1 failed to create TherapistBooking lock record!"
