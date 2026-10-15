"""
REQ-001: Active Patient Allocation Test

Verifies that the allocation algorithm (`bulk_allocate_for_date`) processes
ONLY active patients and excludes inactive patients.

Allocation entry point tested:
    final_allocation.bulk_allocate_for_date(target_date_str)

Patient active/inactive status is determined by:
    final_allocation.is_patient_active(pat_reg_no)
    which queries Registration.objects.using('therapy_db').filter(pat_reg_no=...).pat_status
    Active = pat_status == 'Y'   (or not found / OP → treated as active)
    Inactive = pat_status is any non-'Y' value (e.g., 'N', 'D', 'Discharged')

The bulk allocation performs an INACTIVE PATIENT CHECK at lines 4093-4121 of
final_allocation.py:
    - Groups draft bookings by patient
    - Calls is_patient_active() for each patient
    - If inactive: marks ALL their draft Booking rows as status='failed',
      failure_reason='Patient Inactive', and removes them from further processing
    - Active patients proceed through the continuity + allocation pipeline.
"""
import pytest
from datetime import date, time, timedelta
from unittest.mock import patch, MagicMock
from django.test import TestCase

from Sheduling.models import PatientSnapshot, TherapyAllocation, Booking
from masters.models import SlotMaster, TherapistGrade, TherapistMaster, TherapyMaster
from Patient.models import TreatmentRoom, RoomName


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------
TARGET_DATE = date(2099, 1, 15)  # Far-future date so no collision with real data
TARGET_DATE_STR = TARGET_DATE.isoformat()


def _ensure_slot(number, slot_time):
    """Get-or-create a SlotMaster row."""
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


def _ensure_therapy(code, name, grade_counts):
    """
    Get-or-create a TherapyMaster with the given therapist-grade requirements.
    grade_counts: dict with keys super_senior, senior, junior, trainee.
    """
    obj, _ = TherapyMaster.objects.get_or_create(
        therapy_code=code,
        defaults={
            "therapy_name": name,
            "therapy_category": "General",
            "therapy_duration": "30",
            "bathing_required": "No",
            "treatment_room_required": "Yes",
            "no_of_super_senior_therapist": grade_counts.get("super_senior", 0),
            "no_of_senior_therapist": grade_counts.get("senior", 1),
            "no_of_junior_therapist": grade_counts.get("junior", 0),
            "no_of_trainee_therapist": grade_counts.get("trainee", 0),
            "total_no_of_therapist": sum(grade_counts.values()),
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
            "is_bathing_therapist": True,
            "is_helping_therapist": False,
            "is_active": True,
        },
    )
    return obj


def _ensure_room(room_no):
    room_name, _ = RoomName.objects.get_or_create(name="Test Room", defaults={"is_active": True})
    obj, _ = TreatmentRoom.objects.get_or_create(
        room_no=room_no,
        defaults={
            "room_name": room_name,
            "floor": "G",
            "is_active": True,
        },
    )
    return obj


# ---------------------------------------------------------------------------
# Test class
# ---------------------------------------------------------------------------
@pytest.mark.django_db(transaction=True)
class TestREQ001ActivePatientAllocation(TestCase):
    """
    REQ-001: Verify that allocation processes active patients only
    and excludes inactive patients.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        # --- Master data ---
        cls.slot = _ensure_slot(1, time(6, 30))
        cls.grade_senior = _ensure_grade("Senior Therapist", 2)
        cls.therapy = _ensure_therapy(
            "T_REQ001", "Test Abhyangam REQ001", {"senior": 1}
        )
        cls.therapist_m = _ensure_therapist(
            "THR_REQ001_M", "Male Senior REQ001", "Male",
            cls.grade_senior, "EMP_REQ001_M",
        )
        cls.therapist_f = _ensure_therapist(
            "THR_REQ001_F", "Female Senior REQ001", "Female",
            cls.grade_senior, "EMP_REQ001_F",
        )
        cls.room_a = _ensure_room("REQ001_R1")
        cls.room_b = _ensure_room("REQ001_R2")
        cls.room_c = _ensure_room("REQ001_R3")

    def _create_patient_and_bookings(self, reg_no, name, room, sex="Male", age="30"):
        """
        Create a PatientSnapshot, TherapyAllocation, and a draft Booking
        for TARGET_DATE. Returns (patient, allocation, booking).
        """
        patient = PatientSnapshot.objects.create(
            pat_reg_no=reg_no,
            pat_name=name,
            pat_sex=sex,
            pat_age=age,
        )
        allocation = TherapyAllocation.objects.create(
            patient=patient,
            therapy_code=self.therapy.therapy_code,
            therapy_name=self.therapy.therapy_name,
            from_date=TARGET_DATE,
            to_date=TARGET_DATE + timedelta(days=6),
            days=7,
            timeslot=self.slot,
            room=room,
            required_therapist_roles=[{"role": "senior", "count": 1}],
            status="draft",
        )
        booking = Booking.objects.create(
            allocation=allocation,
            date=TARGET_DATE,
            timeslot=self.slot,
            room=room,
            status="draft",
        )
        return patient, allocation, booking

    @patch("final_allocation.is_patient_active")
    def test_active_patients_allocated_inactive_excluded(self, mock_is_active):
        """
        Scenario:
          - Patient A (reg 900001): ACTIVE   → bookings should be processed
          - Patient B (reg 900002): ACTIVE   → bookings should be processed
          - Patient C (reg 900003): INACTIVE → bookings must be marked 'failed'
            with failure_reason = 'Patient Inactive' and receive NO allocation

        We mock `is_patient_active` because the real implementation queries an
        external SQL Server (therapy_db / Registration table) which is
        unreachable in the test environment.  The mock returns True for
        active reg_nos and False for the inactive one, simulating the exact
        same boolean decision the production code makes.

        The allocation logic itself (draft booking grouping, inactive filtering,
        continuity planning, therapist assignment) runs un-mocked.
        """
        # --- Arrange ---
        pat_a, alloc_a, booking_a = self._create_patient_and_bookings(
            "900001", "Active Patient A", self.room_a, sex="Male"
        )
        pat_b, alloc_b, booking_b = self._create_patient_and_bookings(
            "900002", "Active Patient B", self.room_b, sex="Female"
        )
        pat_c, alloc_c, booking_c = self._create_patient_and_bookings(
            "900003", "Inactive Patient C", self.room_c, sex="Male"
        )

        # Mock: A and B are active, C is inactive
        def _side_effect(pat_reg_no):
            reg_str = str(pat_reg_no).strip()
            if reg_str == "900003":
                return False  # Inactive
            return True  # Active

        mock_is_active.side_effect = _side_effect

        # --- Act ---
        from final_allocation import bulk_allocate_for_date
        result = bulk_allocate_for_date(TARGET_DATE_STR)

        # --- Assert: overall result ---
        assert result["success"] is True, f"bulk_allocate_for_date failed: {result}"

        # --- Assert 1 & 2: Active patients were NOT excluded ---
        # Reload bookings from DB
        booking_a.refresh_from_db()
        booking_b.refresh_from_db()
        booking_c.refresh_from_db()

        # Active patients' bookings should NOT be 'draft' any more;
        # they should have been processed (either 'scheduled' or 'failed' with
        # a reason OTHER than 'Patient Inactive').
        assert booking_a.status != "draft", (
            f"Active Patient A's booking was not processed (still draft). "
            f"Status: {booking_a.status}"
        )
        assert booking_b.status != "draft", (
            f"Active Patient B's booking was not processed (still draft). "
            f"Status: {booking_b.status}"
        )

        # Active patients' bookings must NOT have 'Patient Inactive' as reason
        assert booking_a.failure_reason != "Patient Inactive", (
            "Active Patient A was incorrectly marked as inactive!"
        )
        assert booking_b.failure_reason != "Patient Inactive", (
            "Active Patient B was incorrectly marked as inactive!"
        )

        # --- Assert 3: Inactive patient's booking is marked 'failed' ---
        assert booking_c.status == "failed", (
            f"Inactive Patient C's booking should be 'failed' but is '{booking_c.status}'"
        )
        assert booking_c.failure_reason == "Patient Inactive", (
            f"Inactive Patient C's failure_reason should be 'Patient Inactive' "
            f"but is '{booking_c.failure_reason}'"
        )

        # --- Assert 4: Inactive patient received NO therapist bookings ---
        from Patient.models import TherapistBooking
        inactive_therapist_bookings = TherapistBooking.objects.filter(
            patient_id=pat_c.id,
            date=TARGET_DATE,
            status="BOOKED",
        )
        assert inactive_therapist_bookings.count() == 0, (
            f"Inactive Patient C should have 0 TherapistBookings but has "
            f"{inactive_therapist_bookings.count()}"
        )

        # --- Assert 5: is_patient_active was actually called ---
        # The bulk path calls it once per unique patient
        assert mock_is_active.call_count >= 3, (
            f"is_patient_active should have been called for each patient "
            f"but was called {mock_is_active.call_count} times"
        )

        # Verify it was called with each patient's reg number
        called_reg_nos = {str(c.args[0]).strip() for c in mock_is_active.call_args_list}
        assert "900001" in called_reg_nos, "is_patient_active not called for Patient A"
        assert "900002" in called_reg_nos, "is_patient_active not called for Patient B"
        assert "900003" in called_reg_nos, "is_patient_active not called for Patient C"

    def tearDown(self):
        """Clean up test data to avoid interference with other tests."""
        from Patient.models import TherapistBooking, RoomBooking
        from Sheduling.models import TherapistContinuityPlan

        # Clean up bookings and allocations created in this test
        TherapistBooking.objects.filter(date=TARGET_DATE).delete()
        RoomBooking.objects.filter(date=TARGET_DATE).delete()
        TherapistContinuityPlan.objects.filter(date=TARGET_DATE).delete()
        Booking.objects.filter(date=TARGET_DATE).delete()
        TherapyAllocation.objects.filter(
            therapy_code="T_REQ001",
            from_date=TARGET_DATE,
        ).delete()
        PatientSnapshot.objects.filter(
            pat_reg_no__in=["900001", "900002", "900003"]
        ).delete()
