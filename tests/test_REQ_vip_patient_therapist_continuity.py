"""
Regression Test: VIP Patient Therapist Continuity and Repeated Therapist Assignment

Specification:
    VIP patients should be prioritized for continuity of care by repeatedly assigning
    the same eligible therapist across consecutive treatment sessions, subject to
    therapist availability and scheduling constraints.

Scenario:
    - Patient is marked as VIP.
    - The patient has an existing therapist assignment from the previous treatment session.
    - The previously assigned therapist is available and eligible for the next session.

Execution Steps:
    1. Mark the patient as VIP.
    2. Schedule the first treatment session and record the assigned therapist.
    3. Schedule the patient's next treatment session.
    4. Inspect the therapist assignment and booking records.

Expected Results:
    1. The same eligible therapist is assigned to the VIP patient across consecutive sessions.
    2. Therapist continuity is maintained whenever the therapist is available and eligible.
    3. If the previous therapist is unavailable or ineligible, an eligible alternative is assigned.
    4. Booking and TherapistBooking records reflect the correct assignments.
"""
import pytest
from datetime import date, time
from unittest.mock import patch
from django.test import TestCase

from Sheduling.models import PatientSnapshot, TherapyAllocation, Booking
from masters.models import (
    SlotMaster,
    TherapistGrade,
    TherapistMaster,
    TherapyMaster,
    TherapistLeaveMaster,
)
from Patient.models import TreatmentRoom, RoomName, TherapistBooking, Repeated_Visitors
from authentication.models import PatientProfile
from final_allocation import bulk_allocate_for_date


SESSION_1_DATE = date(2099, 10, 5)  # Monday (weekday=0)
SESSION_2_DATE = date(2099, 10, 6)  # Tuesday (weekday=1)
SESSION_3_DATE = date(2099, 10, 7)  # Wednesday (weekday=2)


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


def _ensure_therapy(code, name, category="Medium", bathing="No", grade_counts=None):
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


def _ensure_therapist(code, name, gender, grade, employee_code):
    obj, _ = TherapistMaster.objects.get_or_create(
        therapist_code=code,
        defaults={
            "therapist_name": name,
            "therapist_gender": gender,
            "therapist_grade": grade,
            "employee_code": employee_code,
            "is_bathing_therapist": False,
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
class TestREQVIPPatientTherapistContinuity(TestCase):
    """
    Test suite for VIP Patient Therapist Continuity and Repeated Therapist Assignment.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        cls.slot = _ensure_slot(2, time(8, 30))
        cls.grade_senior = _ensure_grade("Senior Therapist", 2)
        cls.therapy = _ensure_therapy(
            "T_VIP_CONT_01",
            "VIP Continuity Therapy",
            category="Medium",
            bathing="No",
            grade_counts={"senior": 1},
        )

        cls.therapist_t1 = _ensure_therapist(
            "THR_VIP_T1", "Therapist Alpha Senior", "Male", cls.grade_senior, "EMP_VIP_T1"
        )
        cls.therapist_t2 = _ensure_therapist(
            "THR_VIP_T2", "Therapist Beta Senior", "Male", cls.grade_senior, "EMP_VIP_T2"
        )
        cls.room = _ensure_room("VIP_R101")

    @patch("final_allocation.is_patient_active", return_value=True)
    def test_vip_patient_therapist_continuity_and_repeated_assignment(self, mock_active):
        """
        Verify that:
        1. When a VIP patient has an existing therapist assignment from the previous session,
           the same eligible therapist is repeatedly assigned across consecutive sessions
           (continuity maintained).
        2. If the previous therapist becomes unavailable/ineligible, an eligible alternative
           is assigned.
        3. All Booking and TherapistBooking records reflect the correct assignments.
        """
        reg_no = "770077"

        # --- Step 1: Mark the patient as VIP ---
        patient = PatientSnapshot.objects.create(
            pat_reg_no=reg_no,
            pat_name="VIP Patient Adithya",
            pat_sex="Male",
            pat_age="45",
        )
        Repeated_Visitors.objects.create(
            register_number=int(reg_no),
            patient_name=patient.pat_name,
            total_visits=5,
            is_vip=True,
        )
        from authentication.models import CustomUser
        vip_user = CustomUser.objects.create(
            username=f"vip_user_{reg_no}",
            role="patient",
        )
        PatientProfile.objects.create(
            user=vip_user,
            patient_reg_no=reg_no,
            is_vip=True,
        )

        allocation = TherapyAllocation.objects.create(
            patient=patient,
            therapy_code=self.therapy.therapy_code,
            therapy_name=self.therapy.therapy_name,
            from_date=SESSION_1_DATE,
            to_date=SESSION_3_DATE,
            days=3,
            timeslot=self.slot,
            room=self.room,
            required_therapist_roles=[{"role": "senior", "count": 1}],
            status="draft",
        )

        # --- Step 2: Schedule the first treatment session and record assigned therapist ---
        booking_session1 = Booking.objects.create(
            allocation=allocation,
            date=SESSION_1_DATE,
            timeslot=self.slot,
            room=self.room,
            status="draft",
        )

        alloc_result_s1 = bulk_allocate_for_date(SESSION_1_DATE.isoformat())
        assert alloc_result_s1["success"] is True, f"Session 1 allocation failed: {alloc_result_s1}"

        booking_session1.refresh_from_db()
        assert booking_session1.status == "scheduled", (
            f"Expected session 1 status 'scheduled', got '{booking_session1.status}'. "
            f"Failure reason: {booking_session1.failure_reason}"
        )

        tb_s1 = TherapistBooking.objects.filter(
            date=SESSION_1_DATE,
            patient_id=patient.id,
            status="BOOKED",
        ).first()
        assert tb_s1 is not None, "No TherapistBooking found for Session 1"
        assigned_therapist_s1 = tb_s1.therapist
        assert assigned_therapist_s1.therapist_code in [
            self.therapist_t1.therapist_code,
            self.therapist_t2.therapist_code,
        ], f"Unexpected therapist assigned in session 1: {assigned_therapist_s1}"

        # Identify the alternative therapist
        alt_therapist = (
            self.therapist_t2
            if assigned_therapist_s1.therapist_code == self.therapist_t1.therapist_code
            else self.therapist_t1
        )

        # --- Step 3: Schedule the patient's next treatment session (Session 2) ---
        booking_session2 = Booking.objects.create(
            allocation=allocation,
            date=SESSION_2_DATE,
            timeslot=self.slot,
            room=self.room,
            status="draft",
        )

        alloc_result_s2 = bulk_allocate_for_date(SESSION_2_DATE.isoformat())
        assert alloc_result_s2["success"] is True, f"Session 2 allocation failed: {alloc_result_s2}"

        booking_session2.refresh_from_db()
        assert booking_session2.status == "scheduled", (
            f"Expected session 2 status 'scheduled', got '{booking_session2.status}'. "
            f"Failure reason: {booking_session2.failure_reason}"
        )

        # --- Step 4: Inspect the therapist assignment and booking records ---
        tb_s2 = TherapistBooking.objects.filter(
            date=SESSION_2_DATE,
            patient_id=patient.id,
            status="BOOKED",
        ).first()
        assert tb_s2 is not None, "No TherapistBooking found for Session 2"
        assigned_therapist_s2 = tb_s2.therapist

        # Expected Result 1 & 2:
        # Same eligible therapist is repeatedly assigned across consecutive sessions (continuity maintained)
        assert assigned_therapist_s2.therapist_code == assigned_therapist_s1.therapist_code, (
            f"VIP therapist continuity violated! Expected {assigned_therapist_s1.therapist_code} "
            f"to be assigned again for session 2, but got {assigned_therapist_s2.therapist_code}."
        )

        # Expected Result 3:
        # If the previous therapist is unavailable, an eligible alternative is assigned
        # Place previous therapist on leave for SESSION_3_DATE
        TherapistLeaveMaster.objects.create(
            therapist=assigned_therapist_s1,
            leave_day=SESSION_3_DATE.weekday(),
            is_active=True,
        )

        booking_session3 = Booking.objects.create(
            allocation=allocation,
            date=SESSION_3_DATE,
            timeslot=self.slot,
            room=self.room,
            status="draft",
        )

        alloc_result_s3 = bulk_allocate_for_date(SESSION_3_DATE.isoformat())
        assert alloc_result_s3["success"] is True, f"Session 3 allocation failed: {alloc_result_s3}"

        booking_session3.refresh_from_db()
        assert booking_session3.status == "scheduled", (
            f"Expected session 3 status 'scheduled', got '{booking_session3.status}'. "
            f"Failure reason: {booking_session3.failure_reason}"
        )

        tb_s3 = TherapistBooking.objects.filter(
            date=SESSION_3_DATE,
            patient_id=patient.id,
            status="BOOKED",
        ).first()
        assert tb_s3 is not None, "No TherapistBooking found for Session 3"
        assigned_therapist_s3 = tb_s3.therapist

        assert assigned_therapist_s3.therapist_code != assigned_therapist_s1.therapist_code, (
            f"Unavailable therapist {assigned_therapist_s1.therapist_code} was incorrectly assigned on session 3!"
        )
        assert assigned_therapist_s3.therapist_code == alt_therapist.therapist_code, (
            f"Expected eligible alternative {alt_therapist.therapist_code} to be assigned on session 3, "
            f"but got {assigned_therapist_s3.therapist_code}."
        )

        # Expected Result 4:
        # Booking and TherapistBooking records reflect the correct assignments
        assert booking_session1.status == "scheduled"
        assert booking_session2.status == "scheduled"
        assert booking_session3.status == "scheduled"
        assert tb_s1.status == "BOOKED"
        assert tb_s2.status == "BOOKED"
        assert tb_s3.status == "BOOKED"
