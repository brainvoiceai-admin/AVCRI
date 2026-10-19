"""
Regression Test: Bathing Specialist Leave Recovery - Reassign to Start-of-Therapy Bathing Therapist

Specification Reference:
    Checklist #11:
    When an assigned bathing therapist takes emergency leave,
    find_bathing_therapist_from_start_of_therapy() prioritizes reassigning the patient's
    original start-of-therapy bathing therapist before generic candidates.

Scenario:
    - Patient is on a 7-day therapy course.
    - First day bathing therapist was T_init.
    - Current bathing therapist T_curr takes emergency leave on target date.
    - T_init is available/free today.
    - Generic bathing therapist T_generic is also available in the pool.

Execution Steps:
    1. Sync EmergencyLeave for T_curr.
    2. Run resheduleMorningandNight.py (process_reassignments).
    3. Inspect reassigned bathing therapist.

Expected Results:
    1. Algorithm identifies T_init from start-of-therapy history.
    2. Reassigns T_init as bathing therapist (prioritizing over generic candidate pool).
    3. TherapistBooking.is_bathing remains exactly True for T_init.
"""
import pytest
from datetime import date, time
from django.test import TestCase

from Sheduling.models import PatientSnapshot, TherapyAllocation, Booking, BookingAssignment
from masters.models import (
    SlotMaster,
    TherapistGrade,
    TherapistMaster,
    TherapyMaster,
    EmergencyLeave,
)
from Patient.models import TreatmentRoom, RoomName, TherapistBooking
from resheduleMorningandNight import (
    find_bathing_therapist_from_start_of_therapy,
    process_reassignments,
)


START_DATE = date(2099, 12, 1)   # Day 1 of therapy
TARGET_DATE = date(2099, 12, 4)  # Day 4 of therapy (current session)
END_DATE = date(2099, 12, 7)     # Day 7 of therapy


def _ensure_slot(number, slot_time):
    obj, _ = SlotMaster.objects.get_or_create(
        slot_number=number,
        defaults={"slot_time": slot_time, "is_active": True},
    )
    return obj


def _ensure_grade(name, order):
    obj, _ = TherapistGrade.objects.get_or_create(
        name=name,
        defaults={"display_order": order, "is_active": True},
    )
    return obj


def _ensure_therapy(code, name, category="Medium", bathing="Yes", grade_counts=None):
    if grade_counts is None:
        grade_counts = {"senior": 1}
    obj, _ = TherapyMaster.objects.get_or_create(
        therapy_code=code,
        defaults={
            "therapy_name": name,
            "therapy_category": category,
            "therapy_duration": "45",
            "bathing_required": bathing,
            "treatment_room_required": "Yes",
            "no_of_super_senior_therapist": grade_counts.get("super_senior", 0),
            "no_of_senior_therapist": grade_counts.get("senior", 1),
            "no_of_junior_therapist": grade_counts.get("junior", 0),
            "no_of_trainee_therapist": grade_counts.get("trainee", 0),
            "total_no_of_therapist": sum(grade_counts.values()),
            "patient_type": "IP",
            "is_active": True,
        },
    )
    return obj


def _ensure_therapist(code, name, gender, grade, employee_code, is_bathing=True):
    obj, _ = TherapistMaster.objects.get_or_create(
        therapist_code=code,
        defaults={
            "therapist_name": name,
            "therapist_gender": gender,
            "therapist_grade": grade,
            "employee_code": employee_code,
            "is_bathing_therapist": is_bathing,
            "is_helping_therapist": False,
            "is_active": True,
        },
    )
    return obj


def _ensure_room(room_no):
    room_name, _ = RoomName.objects.get_or_create(
        name=f"Room {room_no}", defaults={"is_active": True}
    )
    obj, _ = TreatmentRoom.objects.get_or_create(
        room_no=room_no,
        defaults={
            "room_name": room_name,
            "floor": "G",
            "is_active": True,
        },
    )
    return obj


@pytest.mark.django_db(transaction=True)
class TestREQBathingSpecialistLeaveRecovery(TestCase):
    """
    Test suite for Checklist #11: Bathing Specialist Leave Recovery to Start-of-Therapy Bathing Therapist.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        cls.slot = _ensure_slot(2, time(8, 30))
        cls.grade_senior = _ensure_grade("Senior Therapist", 2)
        cls.therapy = _ensure_therapy(
            "T_BATH_REC_01",
            "Abhyangam Bathing Recovery Therapy",
            category="Medium",
            bathing="Yes",
            grade_counts={"senior": 1},
        )

        # T_init: Original first-day bathing therapist
        cls.t_init = _ensure_therapist(
            "THR_BATH_INIT",
            "Therapist Init Bathing",
            "Male",
            cls.grade_senior,
            "EMP_BATH_INIT",
            is_bathing=True,
        )

        # T_curr: Current day bathing therapist who takes emergency leave
        cls.t_curr = _ensure_therapist(
            "THR_BATH_CURR",
            "Therapist Curr Bathing",
            "Male",
            cls.grade_senior,
            "EMP_BATH_CURR",
            is_bathing=True,
        )

        # T_generic: Another generic bathing therapist in pool with no prior patient continuity
        cls.t_generic = _ensure_therapist(
            "THR_BATH_GENERIC",
            "Therapist Generic Bathing",
            "Male",
            cls.grade_senior,
            "EMP_BATH_GENERIC",
            is_bathing=True,
        )

        cls.room = _ensure_room("BATH_REC_R1")

    def test_bathing_specialist_leave_recovery_reassign_to_start_of_therapy_bathing_therapist(self):
        """
        Verify that when current bathing therapist takes emergency leave, the algorithm
        prioritizes reassigning the start-of-therapy bathing therapist (T_init) over generic
        candidates, keeping is_bathing=True for T_init.
        """
        reg_no = "660066"
        patient = PatientSnapshot.objects.create(
            pat_reg_no=reg_no,
            pat_name="Bathing Recovery Patient",
            pat_sex="Male",
            pat_age="40",
        )

        # 7-day therapy allocation
        allocation = TherapyAllocation.objects.create(
            patient=patient,
            therapy_code=self.therapy.therapy_code,
            therapy_name=self.therapy.therapy_name,
            from_date=START_DATE,
            to_date=END_DATE,
            days=7,
            timeslot=self.slot,
            room=self.room,
            required_therapist_roles=[{"role": "senior", "count": 1}],
            status="scheduled",
        )

        # 1. Start-of-therapy history: T_init treated patient as bathing therapist on Day 1
        TherapistBooking.objects.create(
            therapist=self.t_init,
            date=START_DATE,
            time_slot=self.slot,
            therapy_name=self.therapy.therapy_name,
            patient_id=patient.id,
            status="BOOKED",
            visit=allocation,
            therapy=self.therapy,
            is_bathing=True,
        )

        # 2. Current booking on TARGET_DATE assigned to T_curr with is_bathing=True
        target_tb = TherapistBooking.objects.create(
            therapist=self.t_curr,
            date=TARGET_DATE,
            time_slot=self.slot,
            therapy_name=self.therapy.therapy_name,
            patient_id=patient.id,
            status="BOOKED",
            visit=allocation,
            therapy=self.therapy,
            is_bathing=True,
        )

        # Accompanying Booking entry for target date
        today_booking = Booking.objects.create(
            allocation=allocation,
            date=TARGET_DATE,
            timeslot=self.slot,
            room=self.room,
            status="scheduled",
        )

        # --- Execution Step 1: Sync EmergencyLeave for T_curr ---
        EmergencyLeave.objects.create(
            therapist=self.t_curr,
            employee_code=self.t_curr.employee_code,
            from_date=TARGET_DATE,
            to_date=TARGET_DATE,
            is_half_day=False,
            status="new",
        )

        # --- Expected Result 1: Direct function inspection ---
        # find_bathing_therapist_from_start_of_therapy() identifies T_init from start-of-therapy history
        identified_therapist = find_bathing_therapist_from_start_of_therapy(
            booking=target_tb,
            allocation=allocation,
            target_date=TARGET_DATE,
            em_therapist_ids={self.t_curr.id},
            em_emp_codes={self.t_curr.employee_code},
        )
        assert identified_therapist is not None, "find_bathing_therapist_from_start_of_therapy returned None!"
        assert identified_therapist.therapist_code == self.t_init.therapist_code, (
            f"Expected T_init ({self.t_init.therapist_code}) from start-of-therapy history, "
            f"but got {identified_therapist.therapist_code}!"
        )

        # --- Execution Step 2: Run resheduleMorningandNight.py reassignment engine ---
        summary = process_reassignments(
            target_date=TARGET_DATE,
            dry_run=False,
            max_daily_normal=5,
            max_daily_overtime_extra=2,
        )
        assert len(summary["reassigned"]) == 1, (
            f"Expected 1 reassignment, but got summary: {summary}"
        )
        reassigned_pk, old_code, new_code = summary["reassigned"][0]
        assert reassigned_pk == target_tb.pk
        assert old_code == self.t_curr.therapist_code
        assert new_code == self.t_init.therapist_code

        # --- Execution Step 3 & Expected Results 2 & 3: Inspect reassigned bathing therapist ---
        target_tb.refresh_from_db()

        # Expected Result 2: Reassigns T_init as bathing therapist (prioritized over generic candidates)
        assert target_tb.therapist.therapist_code == self.t_init.therapist_code, (
            f"Expected reassigned therapist to be T_init ({self.t_init.therapist_code}), "
            f"but got {target_tb.therapist.therapist_code}!"
        )
        assert target_tb.therapist.therapist_code != self.t_generic.therapist_code, (
            "Generic therapist was wrongly preferred over start-of-therapy bathing therapist!"
        )

        # Expected Result 3: TherapistBooking.is_bathing remains exactly True for T_init
        assert target_tb.is_bathing is True, (
            f"Expected is_bathing to remain True for reassigned therapist T_init, but got {target_tb.is_bathing}!"
        )
        assert target_tb.status == "BOOKED"
