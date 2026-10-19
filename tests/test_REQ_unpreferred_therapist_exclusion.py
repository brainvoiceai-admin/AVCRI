"""
Regression Test: Doctor-Approved Unpreferred Therapist Exclusion Overrides Continuity

Specification:
    Active TherapistPreferenceRequest with unpreferred_therapists strictly excludes
    specified therapists from candidate pools, EVEN IF they were the patient's
    therapist yesterday.

Scenario:
    - Therapist T1 treated Patient yesterday (prior-day continuity established).
    - Doctor files approved TherapistPreferenceRequest marking T1 as 'unpreferred'.
    - Eligible alternative therapist T2 is available.

Execution:
    1. Run Pass 1 continuity allocation and Pass 2 allocation.
    2. Inspect candidate list and final assigned therapist.

Expected Results:
    1. T1 is removed from last_therapists and exclusion_set.
    2. T1 is NOT assigned despite prior-day continuity.
    3. Eligible alternative therapist T2 is assigned.
"""
import pytest
from datetime import date, time, timedelta
from unittest.mock import patch
from django.test import TestCase
from django.utils import timezone

from Sheduling.models import PatientSnapshot, TherapyAllocation, Booking, TherapistPreferenceRequest
from masters.models import SlotMaster, TherapistGrade, TherapistMaster, TherapyMaster
from Patient.models import TreatmentRoom, RoomName, TherapistBooking
from final_allocation import bulk_allocate_for_date, allocate_therapists


TARGET_DATE = date(2099, 7, 20)
TARGET_DATE_STR = TARGET_DATE.isoformat()
YESTERDAY = TARGET_DATE - timedelta(days=1)


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
            "no_of_senior_therapist": grade_counts.get("senior", 0),
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
class TestREQUnpreferredTherapistExclusion(TestCase):
    """
    Test suite for Doctor-Approved Unpreferred Therapist Exclusion Overriding Continuity.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        cls.slot = _ensure_slot(3, time(10, 0))
        cls.grade_senior = _ensure_grade("Senior Therapist", 2)
        cls.therapy = _ensure_therapy(
            "T_UNPREF_001", "Unpreferred Exclusion Therapy", category="Medium", bathing="No", grade_counts={"senior": 1}
        )

        cls.therapist_t1 = _ensure_therapist(
            "THR_UNPREF_T1", "Therapist T1 Unpreferred", "Male", cls.grade_senior, "EMP_UNPREF_T1"
        )
        cls.therapist_t2 = _ensure_therapist(
            "THR_UNPREF_T2", "Therapist T2 Alternative", "Male", cls.grade_senior, "EMP_UNPREF_T2"
        )
        cls.room = _ensure_room("UNPREF_R1")

    @patch("final_allocation.is_patient_active", return_value=True)
    @patch("Sheduling.preference_views.is_patient_active", return_value=True)
    def test_doctor_approved_unpreferred_therapist_exclusion_overrides_continuity(
        self, mock_pref_active, mock_alloc_active
    ):
        """
        Verify that an active doctor-approved TherapistPreferenceRequest with
        unpreferred_therapists strictly excludes T1 from candidate pools and final
        assignment, even though T1 was the patient's therapist yesterday, assigning
        eligible alternative T2 instead.
        """
        # 1. Arrange: Create patient and allocation
        reg_no = "990099"
        patient = PatientSnapshot.objects.create(
            pat_reg_no=reg_no,
            pat_name="Patient With Unpreferred Request",
            pat_sex="Male",
            pat_age="35",
        )
        allocation = TherapyAllocation.objects.create(
            patient=patient,
            therapy_code=self.therapy.therapy_code,
            therapy_name=self.therapy.therapy_name,
            from_date=YESTERDAY,
            to_date=TARGET_DATE + timedelta(days=5),
            days=7,
            timeslot=self.slot,
            room=self.room,
            required_therapist_roles=[{"role": "senior", "count": 1}],
            status="draft",
        )

        # 2. Prior-day continuity: T1 treated patient yesterday
        TherapistBooking.objects.create(
            therapist=self.therapist_t1,
            date=YESTERDAY,
            time_slot=self.slot,
            therapy_name=self.therapy.therapy_name,
            patient_id=patient.id,
            status="BOOKED",
            visit=allocation,
            therapy=self.therapy,
            is_bathing=False,
        )

        # 3. Doctor files approved TherapistPreferenceRequest marking T1 as unpreferred
        pref_request = TherapistPreferenceRequest.objects.create(
            patient_id=reg_no,
            patient_name=patient.pat_name,
            status="APPROVED",
            is_active=True,
            action_date=timezone.now(),
            unpreferred_therapist_codes=[self.therapist_t1.therapist_code],
            unpreferred_therapist_names=[self.therapist_t1.therapist_name],
        )
        pref_request.unpreferred_therapists.add(self.therapist_t1)

        # 4. Target date draft booking for allocation engine
        today_booking = Booking.objects.create(
            allocation=allocation,
            date=TARGET_DATE,
            timeslot=self.slot,
            room=self.room,
            status="draft",
        )

        # 5. Direct inspection of candidate pool in allocate_therapists (Pass 2):
        # T1 was in last_therapists, but unpreferred preference must exclude T1 and return T2
        candidate_therapists = allocate_therapists(
            TARGET_DATE,
            self.slot,
            {"total": 1, "senior": 1},
            last_therapists=[self.therapist_t1.therapist_code],
            needs_bathing=False,
            patient_gender="Male",
            patient_id=reg_no,
            patient_age="35",
        )
        assert self.therapist_t1 not in candidate_therapists, (
            f"Unpreferred therapist T1 was not excluded from candidate pool! Candidates: {candidate_therapists}"
        )
        assert self.therapist_t2 in candidate_therapists, (
            f"Alternative eligible therapist T2 was not found in candidate pool! Candidates: {candidate_therapists}"
        )

        # 6. Act: Run bulk allocation pipeline (Pass 1 continuity + Pass 2 allocation)
        result = bulk_allocate_for_date(TARGET_DATE_STR)
        assert result["success"] is True, f"bulk_allocate_for_date failed: {result}"

        # 7. Assert: Booking committed successfully
        today_booking.refresh_from_db()
        assert today_booking.status == "scheduled", (
            f"Expected booking status 'scheduled', but got '{today_booking.status}'. "
            f"Failure reason: {today_booking.failure_reason}"
        )

        # 8. Assert: Final assigned therapist is T2, strictly excluding T1 despite continuity
        assigned_bookings = TherapistBooking.objects.filter(
            date=TARGET_DATE,
            patient_id=patient.id,
            status="BOOKED",
        )
        assert assigned_bookings.count() == 1, (
            f"Expected exactly 1 TherapistBooking for patient on target date, found {assigned_bookings.count()}"
        )

        assigned_therapist = assigned_bookings.first().therapist
        assert assigned_therapist.therapist_code == self.therapist_t2.therapist_code, (
            f"Expected alternative therapist {self.therapist_t2.therapist_code} to be assigned, "
            f"but got {assigned_therapist.therapist_code}!"
        )
        assert assigned_therapist.therapist_code != self.therapist_t1.therapist_code, (
            f"Unpreferred therapist {self.therapist_t1.therapist_code} was incorrectly assigned "
            f"due to prior-day continuity!"
        )
