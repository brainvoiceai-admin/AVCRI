"""
Emergency Leave Allocation Test Suite

Verifies that the allocation algorithms strictly follow the EmergencyLeave rules:
1. Full-day emergency leave:
   - When a therapist is on full-day leave (`is_half_day=False` or `half_day_session='Both'`),
     they MUST be completely avoided in allocation for all slots (morning and afternoon).
2. Half-day emergency leave:
   - Forenoon leave (`is_half_day=True`, `half_day_session='Forenoon'`):
     - The therapist is BLOCKED ONLY for morning slots (06:30, 08:30, 10:00, 11:30, i.e., < 13:00 / slots 1-4).
     - The therapist is ELIGIBLE and available for afternoon slots (14:30, 16:00, 17:30, i.e., >= 13:00 / slots 5-7).
   - Afternoon leave (`is_half_day=True`, `half_day_session='Afternoon'`):
     - The therapist is ELIGIBLE and available for morning slots (06:30-11:30).
     - The therapist is BLOCKED for afternoon slots (14:30-17:30).

Algorithms and layers tested:
- Model methods and module helpers: `EmergencyLeave.is_forenoon_slot`, `EmergencyLeave.is_slot_on_leave`,
  `is_therapist_on_emergency_leave`
- Direct allocation engine: `final_allocation.allocate_therapists`
- Bulk allocation pipeline: `final_allocation.bulk_allocate_for_date`
- Reschedule allocation engine: `reshedule.allocate_therapists`,
  `reshedule.allocate_therapists_with_grade_substitution`
- Emergency morning/night reschedule: `resheduleMorningandNight.get_emergency_leave_sets_for_date`,
  `resheduleMorningandNight.available_candidates_by_level_and_bathing`
"""
import pytest
from datetime import date, time, timedelta
from unittest.mock import patch
from django.test import TestCase

from Sheduling.models import PatientSnapshot, TherapyAllocation, Booking, TherapistContinuityPlan
from masters.models import (
    SlotMaster,
    TherapistGrade,
    TherapistMaster,
    TherapyMaster,
    EmergencyLeave,
    is_therapist_on_emergency_leave,
)
from Patient.models import TreatmentRoom, RoomName, TherapistBooking, RoomBooking

from final_allocation import allocate_therapists, bulk_allocate_for_date
from reshedule import (
    allocate_therapists as reshedule_allocate_therapists,
    allocate_therapists_with_grade_substitution as reshedule_allocate_with_sub,
)
from resheduleMorningandNight import (
    get_emergency_leave_sets_for_date,
    available_candidates_by_level_and_bathing,
)


TARGET_DATE = date(2099, 7, 15)
TARGET_DATE_STR = TARGET_DATE.isoformat()


# ---------------------------------------------------------------------------
# Helpers for master data creation
# ---------------------------------------------------------------------------
def _get_or_create_slot(number, slot_time):
    obj, _ = SlotMaster.objects.get_or_create(
        slot_number=number,
        defaults={"slot_time": slot_time, "is_active": True},
    )
    if obj.slot_time != slot_time:
        obj.slot_time = slot_time
        obj.save(update_fields=["slot_time"])
    return obj


def _get_or_create_grade(name, order):
    obj, _ = TherapistGrade.objects.get_or_create(
        name=name,
        defaults={"display_order": order, "is_active": True},
    )
    return obj


def _get_or_create_therapy(code, name, grade_counts):
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


def _get_or_create_therapist(code, name, gender, grade, emp_code):
    obj, _ = TherapistMaster.objects.get_or_create(
        therapist_code=code,
        defaults={
            "therapist_name": name,
            "therapist_gender": gender,
            "therapist_grade": grade,
            "employee_code": emp_code,
            "is_bathing_therapist": True,
            "is_helping_therapist": False,
            "is_active": True,
        },
    )
    return obj


def _get_or_create_room(room_no):
    room_name, _ = RoomName.objects.get_or_create(name=f"Room {room_no}", defaults={"is_active": True})
    obj, _ = TreatmentRoom.objects.get_or_create(
        room_no=room_no,
        defaults={"room_name": room_name, "floor": "G", "is_active": True},
    )
    return obj


# ===========================================================================
# 1. Unit Tests: EmergencyLeave Model & Helper Functions
# ===========================================================================
class TestEmergencyLeaveModelBehavior(TestCase):
    """
    Unit tests for is_forenoon_slot, is_slot_on_leave, and is_therapist_on_emergency_leave.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # Morning slots (slots 1-4, < 13:00)
        cls.slot_m1 = _get_or_create_slot(1, time(6, 30))
        cls.slot_m2 = _get_or_create_slot(2, time(8, 30))
        cls.slot_m3 = _get_or_create_slot(3, time(10, 0))
        cls.slot_m4 = _get_or_create_slot(4, time(11, 30))

        # Afternoon slots (slots 5-7, >= 13:00)
        cls.slot_a5 = _get_or_create_slot(5, time(14, 30))
        cls.slot_a6 = _get_or_create_slot(6, time(16, 0))
        cls.slot_a7 = _get_or_create_slot(7, time(17, 30))

        cls.grade = _get_or_create_grade("Senior Therapist", 2)
        cls.therapist = _get_or_create_therapist(
            "TH_EL_UNIT", "Unit Test Therapist", "Male", cls.grade, "EMP_EL_UNIT"
        )

    def tearDown(self):
        EmergencyLeave.objects.filter(employee_code=self.therapist.employee_code).delete()

    def test_is_forenoon_slot_identification(self):
        """Validates that slots 06:30-11:30 are forenoon (< 13:00) and 14:30-17:30 are afternoon."""
        # Morning slots
        for s in [self.slot_m1, self.slot_m2, self.slot_m3, self.slot_m4]:
            assert EmergencyLeave.is_forenoon_slot(s) is True, f"Slot {s.slot_number} ({s.slot_time}) should be forenoon"

        # Afternoon slots
        for s in [self.slot_a5, self.slot_a6, self.slot_a7]:
            assert EmergencyLeave.is_forenoon_slot(s) is False, f"Slot {s.slot_number} ({s.slot_time}) should not be forenoon"

        # Direct time objects
        assert EmergencyLeave.is_forenoon_slot(time(6, 30)) is True
        assert EmergencyLeave.is_forenoon_slot(time(11, 30)) is True
        assert EmergencyLeave.is_forenoon_slot(time(14, 30)) is False
        assert EmergencyLeave.is_forenoon_slot(time(17, 30)) is False

        # Slot numbers / strings
        assert EmergencyLeave.is_forenoon_slot(1) is True
        assert EmergencyLeave.is_forenoon_slot(4) is True
        assert EmergencyLeave.is_forenoon_slot(5) is False
        assert EmergencyLeave.is_forenoon_slot("08:30") is True
        assert EmergencyLeave.is_forenoon_slot("16:00") is False

    def test_full_day_leave_blocks_all_slots(self):
        """A full-day emergency leave blocks every slot throughout the day."""
        el = EmergencyLeave.objects.create(
            therapist=self.therapist,
            employee_code=self.therapist.employee_code,
            from_date=TARGET_DATE,
            to_date=TARGET_DATE,
            is_half_day=False,
        )

        # Blocked for morning slots
        assert el.is_slot_on_leave(TARGET_DATE, self.slot_m1) is True
        assert el.is_slot_on_leave(TARGET_DATE, self.slot_m4) is True

        # Blocked for afternoon slots
        assert el.is_slot_on_leave(TARGET_DATE, self.slot_a5) is True
        assert el.is_slot_on_leave(TARGET_DATE, self.slot_a7) is True

        # Blocked when slot=None (any leave check)
        assert el.is_slot_on_leave(TARGET_DATE, None) is True

        # Module helper is_therapist_on_emergency_leave
        assert is_therapist_on_emergency_leave(self.therapist, TARGET_DATE, self.slot_m1) is True
        assert is_therapist_on_emergency_leave(self.therapist, TARGET_DATE, self.slot_a5) is True

    def test_forenoon_half_day_leave_blocks_morning_and_permits_afternoon(self):
        """
        A therapist on Forenoon leave is:
        - ON LEAVE (blocked) for morning slots (06:30-11:30)
        - AVAILABLE (eligible) for afternoon slots (14:30-17:30)
        """
        el = EmergencyLeave.objects.create(
            therapist=self.therapist,
            employee_code=self.therapist.employee_code,
            from_date=TARGET_DATE,
            to_date=TARGET_DATE,
            is_half_day=True,
            half_day_date=TARGET_DATE,
            half_day_session="Forenoon",
        )

        # Morning slots: BLOCKED
        for s in [self.slot_m1, self.slot_m2, self.slot_m3, self.slot_m4]:
            assert el.is_slot_on_leave(TARGET_DATE, s) is True, f"Slot {s.slot_number} should be on leave for Forenoon"
            assert is_therapist_on_emergency_leave(self.therapist, TARGET_DATE, s) is True

        # Afternoon slots: ELIGIBLE / AVAILABLE
        for s in [self.slot_a5, self.slot_a6, self.slot_a7]:
            assert el.is_slot_on_leave(TARGET_DATE, s) is False, f"Slot {s.slot_number} should be available for Forenoon leave"
            assert is_therapist_on_emergency_leave(self.therapist, TARGET_DATE, s) is False

    def test_afternoon_half_day_leave_permits_morning_and_blocks_afternoon(self):
        """
        A therapist on Afternoon leave is:
        - AVAILABLE (eligible) for morning slots (06:30-11:30)
        - ON LEAVE (blocked) for afternoon slots (14:30-17:30)
        """
        el = EmergencyLeave.objects.create(
            therapist=self.therapist,
            employee_code=self.therapist.employee_code,
            from_date=TARGET_DATE,
            to_date=TARGET_DATE,
            is_half_day=True,
            half_day_date=TARGET_DATE,
            half_day_session="Afternoon",
        )

        # Morning slots: AVAILABLE
        for s in [self.slot_m1, self.slot_m2, self.slot_m3, self.slot_m4]:
            assert el.is_slot_on_leave(TARGET_DATE, s) is False, f"Slot {s.slot_number} should be available for Afternoon leave"
            assert is_therapist_on_emergency_leave(self.therapist, TARGET_DATE, s) is False

        # Afternoon slots: BLOCKED
        for s in [self.slot_a5, self.slot_a6, self.slot_a7]:
            assert el.is_slot_on_leave(TARGET_DATE, s) is True, f"Slot {s.slot_number} should be on leave for Afternoon leave"
            assert is_therapist_on_emergency_leave(self.therapist, TARGET_DATE, s) is True


# ===========================================================================
# 2. Test Class: Direct Allocation Engine (final_allocation.allocate_therapists)
# ===========================================================================
@pytest.mark.django_db(transaction=True)
class TestDirectAllocationEmergencyLeave(TestCase):
    """
    Validates that final_allocation.allocate_therapists respects full-day and
    half-day emergency leaves.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # Morning slots: 06:30, 08:30, 10:00, 11:30
        cls.slot_morning_1 = _get_or_create_slot(11, time(6, 30))
        cls.slot_morning_2 = _get_or_create_slot(12, time(8, 30))
        cls.slot_morning_3 = _get_or_create_slot(13, time(10, 0))
        cls.slot_morning_4 = _get_or_create_slot(14, time(11, 30))

        # Afternoon slots: 14:30, 16:00, 17:30
        cls.slot_afternoon_5 = _get_or_create_slot(15, time(14, 30))
        cls.slot_afternoon_6 = _get_or_create_slot(16, time(16, 0))
        cls.slot_afternoon_7 = _get_or_create_slot(17, time(17, 30))

        cls.grade_senior = _get_or_create_grade("Senior Therapist", 2)
        cls.therapy = _get_or_create_therapy("T_EL_ALLOC", "Emergency Leave Allocation Therapy", {"senior": 1})

        # Therapist on Forenoon leave
        cls.th_fn = _get_or_create_therapist(
            "TH_EL_FN", "Forenoon Leave Therapist", "Male", cls.grade_senior, "EMP_EL_FN"
        )
        # Therapist on Full-day leave
        cls.th_full = _get_or_create_therapist(
            "TH_EL_FULL", "Full Day Leave Therapist", "Male", cls.grade_senior, "EMP_EL_FULL"
        )
        # Therapist on Afternoon leave
        cls.th_an = _get_or_create_therapist(
            "TH_EL_AN", "Afternoon Leave Therapist", "Male", cls.grade_senior, "EMP_EL_AN"
        )

    def setUp(self):
        super().setUp()
        # Create leaves for TARGET_DATE
        EmergencyLeave.objects.create(
            therapist=self.th_fn,
            employee_code=self.th_fn.employee_code,
            from_date=TARGET_DATE,
            to_date=TARGET_DATE,
            is_half_day=True,
            half_day_date=TARGET_DATE,
            half_day_session="Forenoon",
        )
        EmergencyLeave.objects.create(
            therapist=self.th_full,
            employee_code=self.th_full.employee_code,
            from_date=TARGET_DATE,
            to_date=TARGET_DATE,
            is_half_day=False,
        )
        EmergencyLeave.objects.create(
            therapist=self.th_an,
            employee_code=self.th_an.employee_code,
            from_date=TARGET_DATE,
            to_date=TARGET_DATE,
            is_half_day=True,
            half_day_date=TARGET_DATE,
            half_day_session="Afternoon",
        )

    def tearDown(self):
        EmergencyLeave.objects.filter(from_date=TARGET_DATE).delete()
        TherapistBooking.objects.filter(date=TARGET_DATE).delete()

    def test_full_day_leave_therapist_avoided_in_all_slots(self):
        """A therapist on full-day leave must NEVER be allocated for any slot."""
        reqs = {"senior": 1}
        # In a pool where only th_full is considered (by excluding the other two)
        for slot in [self.slot_morning_1, self.slot_morning_3, self.slot_afternoon_5, self.slot_afternoon_7]:
            allocated = allocate_therapists(
                date=TARGET_DATE,
                time_slot=slot,
                therapy_requirements=reqs,
                patient_gender="Male",
                patient_age="30",
                avoid_therapists=[self.th_fn.therapist_code, self.th_an.therapist_code],
            )
            # Full-day leave therapist must NOT be allocated
            allocated_codes = [t.therapist_code for t in allocated]
            assert self.th_full.therapist_code not in allocated_codes, (
                f"Full-day leave therapist {self.th_full.therapist_code} was allocated at slot {slot.slot_number}!"
            )
            assert len(allocated) == 0

    def test_forenoon_leave_therapist_blocked_for_all_morning_slots(self):
        """
        Therapist on Forenoon leave MUST be blocked for all morning slots:
        06:30, 08:30, 10:00, 11:30.
        """
        reqs = {"senior": 1}
        morning_slots = [self.slot_morning_1, self.slot_morning_2, self.slot_morning_3, self.slot_morning_4]

        for slot in morning_slots:
            allocated = allocate_therapists(
                date=TARGET_DATE,
                time_slot=slot,
                therapy_requirements=reqs,
                patient_gender="Male",
                patient_age="30",
                avoid_therapists=[self.th_full.therapist_code, self.th_an.therapist_code],
            )
            allocated_codes = [t.therapist_code for t in allocated]
            assert self.th_fn.therapist_code not in allocated_codes, (
                f"Forenoon leave therapist {self.th_fn.therapist_code} was incorrectly allocated for morning slot {slot.slot_number} ({slot.slot_time})!"
            )
            assert len(allocated) == 0

    def test_forenoon_leave_therapist_eligible_for_all_afternoon_slots(self):
        """
        Therapist on Forenoon leave IS ELIGIBLE and MUST be allocated for afternoon slots:
        14:30, 16:00, 17:30.
        """
        reqs = {"senior": 1}
        afternoon_slots = [self.slot_afternoon_5, self.slot_afternoon_6, self.slot_afternoon_7]

        for slot in afternoon_slots:
            # Avoid full-day and afternoon-leave therapists, so th_fn is the only available candidate
            allocated = allocate_therapists(
                date=TARGET_DATE,
                time_slot=slot,
                therapy_requirements=reqs,
                patient_gender="Male",
                patient_age="30",
                avoid_therapists=[self.th_full.therapist_code, self.th_an.therapist_code],
            )
            assert len(allocated) == 1, (
                f"Forenoon leave therapist should be eligible for afternoon slot {slot.slot_number} ({slot.slot_time}), but got 0 allocated"
            )
            assert allocated[0].therapist_code == self.th_fn.therapist_code, (
                f"Expected {self.th_fn.therapist_code}, got {allocated[0].therapist_code}"
            )

    def test_afternoon_leave_therapist_eligible_for_morning_and_blocked_for_afternoon(self):
        """
        Therapist on Afternoon leave:
        - Eligible for morning slots (06:30-11:30)
        - Blocked for afternoon slots (14:30-17:30)
        """
        reqs = {"senior": 1}

        # Morning slot: th_an SHOULD be allocated
        alloc_morning = allocate_therapists(
            date=TARGET_DATE,
            time_slot=self.slot_morning_1,
            therapy_requirements=reqs,
            patient_gender="Male",
            patient_age="30",
            avoid_therapists=[self.th_full.therapist_code, self.th_fn.therapist_code],
        )
        assert len(alloc_morning) == 1
        assert alloc_morning[0].therapist_code == self.th_an.therapist_code

        # Afternoon slot: th_an MUST NOT be allocated
        alloc_afternoon = allocate_therapists(
            date=TARGET_DATE,
            time_slot=self.slot_afternoon_5,
            therapy_requirements=reqs,
            patient_gender="Male",
            patient_age="30",
            avoid_therapists=[self.th_full.therapist_code, self.th_fn.therapist_code],
        )
        assert len(alloc_afternoon) == 0, (
            f"Afternoon leave therapist was incorrectly allocated for afternoon slot: {alloc_afternoon}"
        )

    def test_continuity_therapist_on_forenoon_leave_rejected_for_morning_accepted_for_afternoon(self):
        """
        If a continuity therapist (in last_therapists) is on Forenoon leave:
        - They are rejected if the booking is at a morning slot.
        - They are accepted and allocated if the booking is at an afternoon slot.
        """
        reqs = {"senior": 1}

        # Attempt morning allocation with th_fn as last_therapist
        alloc_morning = allocate_therapists(
            date=TARGET_DATE,
            time_slot=self.slot_morning_1,
            therapy_requirements=reqs,
            last_therapists=[self.th_fn.therapist_code],
            patient_gender="Male",
            patient_age="30",
            avoid_therapists=[self.th_full.therapist_code, self.th_an.therapist_code],
        )
        # Must NOT allocate th_fn despite continuity
        assert len(alloc_morning) == 0

        # Attempt afternoon allocation with th_fn as last_therapist
        alloc_afternoon = allocate_therapists(
            date=TARGET_DATE,
            time_slot=self.slot_afternoon_5,
            therapy_requirements=reqs,
            last_therapists=[self.th_fn.therapist_code],
            patient_gender="Male",
            patient_age="30",
            avoid_therapists=[self.th_full.therapist_code, self.th_an.therapist_code],
        )
        # MUST allocate th_fn
        assert len(alloc_afternoon) == 1
        assert alloc_afternoon[0].therapist_code == self.th_fn.therapist_code


# ===========================================================================
# 3. Test Class: Bulk Allocation Pipeline (final_allocation.bulk_allocate_for_date)
# ===========================================================================
@pytest.mark.django_db(transaction=True)
class TestBulkAllocationEmergencyLeavePipeline(TestCase):
    """
    Validates that final_allocation.bulk_allocate_for_date enforces full-day
    and half-day emergency leave rules in the end-to-end pipeline.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # Morning slot (08:30, slot 2) and Afternoon slot (14:30, slot 5)
        cls.slot_morning = _get_or_create_slot(22, time(8, 30))
        cls.slot_afternoon = _get_or_create_slot(25, time(14, 30))

        cls.grade_senior = _get_or_create_grade("Senior Therapist", 2)
        cls.therapy = _get_or_create_therapy("T_EL_BULK", "Bulk Emergency Leave Therapy", {"senior": 1})

        # Only 2 therapists available for this group to test exact allocation behavior:
        # 1. th_fn: on Forenoon leave (blocked in morning, eligible in afternoon)
        # 2. th_full: on Full-day leave (blocked all day)
        cls.th_fn = _get_or_create_therapist(
            "TH_BLK_EL_FN", "Bulk Forenoon Leave Th", "Male", cls.grade_senior, "EMP_BLK_EL_FN"
        )
        cls.th_full = _get_or_create_therapist(
            "TH_BLK_EL_FULL", "Bulk Full Day Leave Th", "Male", cls.grade_senior, "EMP_BLK_EL_FULL"
        )

        cls.room_m = _get_or_create_room("BLK_EL_RM")
        cls.room_a = _get_or_create_room("BLK_EL_RA")

    def _create_booking(self, reg_no, name, slot, room):
        patient = PatientSnapshot.objects.create(
            pat_reg_no=reg_no,
            pat_name=name,
            pat_sex="Male",
            pat_age="35",
        )
        allocation = TherapyAllocation.objects.create(
            patient=patient,
            therapy_code=self.therapy.therapy_code,
            therapy_name=self.therapy.therapy_name,
            from_date=TARGET_DATE,
            to_date=TARGET_DATE + timedelta(days=6),
            days=7,
            timeslot=slot,
            room=room,
            required_therapist_roles=[{"role": "senior", "count": 1}],
            status="draft",
        )
        booking = Booking.objects.create(
            allocation=allocation,
            date=TARGET_DATE,
            timeslot=slot,
            room=room,
            status="draft",
        )
        return patient, allocation, booking

    @patch("final_allocation.is_patient_active")
    def test_bulk_pipeline_respects_half_day_and_full_day_leave(self, mock_is_active):
        """
        In bulk allocation:
        - Morning booking: Neither th_fn (Forenoon leave) nor th_full (Full leave) can be allocated.
          Booking must fail.
        - Afternoon booking: th_fn (Forenoon leave) IS ELIGIBLE and allocated!
          th_full (Full leave) is still avoided.
        """
        mock_is_active.return_value = True

        # Register Forenoon leave for th_fn and Full-day leave for th_full
        EmergencyLeave.objects.create(
            therapist=self.th_fn,
            employee_code=self.th_fn.employee_code,
            from_date=TARGET_DATE,
            to_date=TARGET_DATE,
            is_half_day=True,
            half_day_date=TARGET_DATE,
            half_day_session="Forenoon",
        )
        EmergencyLeave.objects.create(
            therapist=self.th_full,
            employee_code=self.th_full.employee_code,
            from_date=TARGET_DATE,
            to_date=TARGET_DATE,
            is_half_day=False,
        )

        # Patient 1: Morning booking (08:30)
        pat_m, alloc_m, bk_m = self._create_booking("600001", "Morning Patient", self.slot_morning, self.room_m)
        # Patient 2: Afternoon booking (14:30)
        pat_a, alloc_a, bk_a = self._create_booking("600002", "Afternoon Patient", self.slot_afternoon, self.room_a)

        # Run bulk allocation
        bulk_allocate_for_date(TARGET_DATE_STR)

        bk_m.refresh_from_db()
        bk_a.refresh_from_db()

        # 1. Morning booking should FAIL because th_fn is on Forenoon leave & th_full is on full-day leave
        assert bk_m.status == "failed", (
            f"Morning booking should fail due to unavailability, got: {bk_m.status}"
        )
        tb_morning = TherapistBooking.objects.filter(patient_id=pat_m.id, date=TARGET_DATE, status="BOOKED")
        assert tb_morning.count() == 0, "No therapist should be booked for morning patient"

        # 2. Afternoon booking should SUCCEED because th_fn IS ELIGIBLE in the afternoon
        assert bk_a.status == "scheduled", (
            f"Afternoon booking should be scheduled with th_fn, got: {bk_a.status}"
        )
        tb_afternoon = TherapistBooking.objects.filter(patient_id=pat_a.id, date=TARGET_DATE, status="BOOKED")
        assert tb_afternoon.count() == 1
        assert tb_afternoon.first().therapist.therapist_code == self.th_fn.therapist_code, (
            f"Expected afternoon booking to allocate th_fn ({self.th_fn.therapist_code}), "
            f"got: {tb_afternoon.first().therapist.therapist_code}"
        )

        # 3. Full-day leave therapist was NEVER allocated to any booking
        tb_full = TherapistBooking.objects.filter(therapist=self.th_full, date=TARGET_DATE, status="BOOKED")
        assert tb_full.count() == 0, "Full-day leave therapist should have 0 bookings!"

    def tearDown(self):
        EmergencyLeave.objects.filter(from_date=TARGET_DATE).delete()
        TherapistBooking.objects.filter(date=TARGET_DATE).delete()
        RoomBooking.objects.filter(date=TARGET_DATE).delete()
        TherapistContinuityPlan.objects.filter(date=TARGET_DATE).delete()
        Booking.objects.filter(date=TARGET_DATE).delete()
        TherapyAllocation.objects.filter(therapy_code=self.therapy.therapy_code).delete()
        PatientSnapshot.objects.filter(pat_reg_no__startswith="6000").delete()


# ===========================================================================
# 4. Test Class: Reschedule Allocation Engine (reshedule.py)
# ===========================================================================
@pytest.mark.django_db(transaction=True)
class TestRescheduleEmergencyLeave(TestCase):
    """
    Validates that reshedule.allocate_therapists and grade substitution
    respect full-day and half-day emergency leaves.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.slot_morning = _get_or_create_slot(31, time(10, 0))
        cls.slot_afternoon = _get_or_create_slot(35, time(16, 0))

        cls.grade_senior = _get_or_create_grade("Senior Therapist", 2)
        cls.grade_super_sr = _get_or_create_grade("Super Senior Therapist", 1)

        cls.th_fn = _get_or_create_therapist(
            "TH_RSH_EL_FN", "Rsh Forenoon Leave Th", "Male", cls.grade_senior, "EMP_RSH_EL_FN"
        )
        cls.th_full = _get_or_create_therapist(
            "TH_RSH_EL_FULL", "Rsh Full Day Leave Th", "Male", cls.grade_senior, "EMP_RSH_EL_FULL"
        )
        cls.th_sub_fn = _get_or_create_therapist(
            "TH_RSH_SUB_FN", "Rsh Sub Forenoon Leave Th", "Male", cls.grade_super_sr, "EMP_RSH_SUB_FN"
        )

    def setUp(self):
        super().setUp()
        EmergencyLeave.objects.create(
            therapist=self.th_fn,
            employee_code=self.th_fn.employee_code,
            from_date=TARGET_DATE,
            to_date=TARGET_DATE,
            is_half_day=True,
            half_day_date=TARGET_DATE,
            half_day_session="Forenoon",
        )
        EmergencyLeave.objects.create(
            therapist=self.th_full,
            employee_code=self.th_full.employee_code,
            from_date=TARGET_DATE,
            to_date=TARGET_DATE,
            is_half_day=False,
        )
        EmergencyLeave.objects.create(
            therapist=self.th_sub_fn,
            employee_code=self.th_sub_fn.employee_code,
            from_date=TARGET_DATE,
            to_date=TARGET_DATE,
            is_half_day=True,
            half_day_date=TARGET_DATE,
            half_day_session="Forenoon",
        )

    def tearDown(self):
        EmergencyLeave.objects.filter(from_date=TARGET_DATE).delete()
        TherapistBooking.objects.filter(date=TARGET_DATE).delete()

    def test_reschedule_allocate_therapists_emergency_leave(self):
        """reshedule.allocate_therapists blocks forenoon leave in morning and permits in afternoon."""
        reqs = {"senior": 1}

        # Morning slot: th_fn and th_full must be avoided
        alloc_morning = reshedule_allocate_therapists(
            date=TARGET_DATE,
            time_slot=self.slot_morning,
            therapy_requirements=reqs,
            patient_gender="Male",
            patient_age="30",
        )
        assert len(alloc_morning) == 0

        # Afternoon slot: th_fn IS ELIGIBLE and allocated
        alloc_afternoon = reshedule_allocate_therapists(
            date=TARGET_DATE,
            time_slot=self.slot_afternoon,
            therapy_requirements=reqs,
            patient_gender="Male",
            patient_age="30",
        )
        assert len(alloc_afternoon) == 1
        assert alloc_afternoon[0].therapist_code == self.th_fn.therapist_code

    def test_reschedule_grade_substitution_respects_emergency_leave(self):
        """
        In grade substitution:
        - A substitute therapist on Forenoon leave cannot substitute during morning slots.
        - A substitute therapist on Forenoon leave CAN substitute during afternoon slots.
        - A substitute on full-day leave cannot substitute in either.
        """
        reqs = {"senior": 1}

        # Block th_fn for afternoon test to force substitution with th_sub_fn (Super Senior)
        # In morning: Both th_fn (Senior) and th_sub_fn (Super Senior) are on Forenoon leave
        alloc_sub_morning = reshedule_allocate_with_sub(
            date=TARGET_DATE,
            time_slot=self.slot_morning,
            therapy_requirements=reqs,
            patient_gender="Male",
            patient_age="30",
        )
        assert len(alloc_sub_morning) == 0, "No substitute on Forenoon leave should be allocated in morning"

        # In afternoon: Both th_fn and th_sub_fn are available. th_fn fulfills senior directly.
        alloc_sub_afternoon = reshedule_allocate_with_sub(
            date=TARGET_DATE,
            time_slot=self.slot_afternoon,
            therapy_requirements=reqs,
            patient_gender="Male",
            patient_age="30",
        )
        assert len(alloc_sub_afternoon) == 1
        assert alloc_sub_afternoon[0].therapist_code == self.th_fn.therapist_code


# ===========================================================================
# 5. Test Class: Emergency Reschedule Engine (resheduleMorningandNight.py)
# ===========================================================================
@pytest.mark.django_db(transaction=True)
class TestEmergencyRescheduleModule(TestCase):
    """
    Validates get_emergency_leave_sets_for_date and available_candidates_by_level_and_bathing
    in resheduleMorningandNight.py.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.slot_morning = _get_or_create_slot(41, time(6, 30))
        cls.slot_afternoon = _get_or_create_slot(45, time(17, 30))

        cls.grade_senior = _get_or_create_grade("Senior Therapist", 2)

        cls.th_fn = _get_or_create_therapist(
            "TH_EMG_EL_FN", "Emg Forenoon Leave Th", "Male", cls.grade_senior, "EMP_EMG_EL_FN"
        )
        cls.th_full = _get_or_create_therapist(
            "TH_EMG_EL_FULL", "Emg Full Day Leave Th", "Male", cls.grade_senior, "EMP_EMG_EL_FULL"
        )

    def setUp(self):
        super().setUp()
        EmergencyLeave.objects.create(
            therapist=self.th_fn,
            employee_code=self.th_fn.employee_code,
            from_date=TARGET_DATE,
            to_date=TARGET_DATE,
            is_half_day=True,
            half_day_date=TARGET_DATE,
            half_day_session="Forenoon",
        )
        EmergencyLeave.objects.create(
            therapist=self.th_full,
            employee_code=self.th_full.employee_code,
            from_date=TARGET_DATE,
            to_date=TARGET_DATE,
            is_half_day=False,
        )

    def tearDown(self):
        EmergencyLeave.objects.filter(from_date=TARGET_DATE).delete()
        TherapistBooking.objects.filter(date=TARGET_DATE).delete()

    def test_get_emergency_leave_sets_slot_awareness(self):
        """
        get_emergency_leave_sets_for_date must:
        - Include th_fn in excluded leave set for morning slot.
        - EXCLUDE th_fn from excluded leave set for afternoon slot (meaning th_fn is available).
        - Include th_full in excluded leave set for BOTH morning and afternoon slots.
        """
        # Morning slot: both th_fn and th_full are in leave set
        em_ids_morning, em_codes_morning = get_emergency_leave_sets_for_date(TARGET_DATE, slot=self.slot_morning)
        assert self.th_fn.id in em_ids_morning or self.th_fn.employee_code in em_codes_morning
        assert self.th_full.id in em_ids_morning or self.th_full.employee_code in em_codes_morning

        # Afternoon slot: th_fn is NOT in leave set (available!), th_full IS in leave set (blocked)
        em_ids_afternoon, em_codes_afternoon = get_emergency_leave_sets_for_date(TARGET_DATE, slot=self.slot_afternoon)
        assert self.th_fn.id not in em_ids_afternoon and self.th_fn.employee_code not in em_codes_afternoon, (
            "Forenoon leave therapist should NOT be in the leave set for afternoon slot!"
        )
        assert self.th_full.id in em_ids_afternoon or self.th_full.employee_code in em_codes_afternoon, (
            "Full-day leave therapist MUST be in the leave set for afternoon slot!"
        )

    def test_available_candidates_excludes_forenoon_in_morning_includes_in_afternoon(self):
        """
        available_candidates_by_level_and_bathing:
        - In morning: th_fn is excluded from candidate list.
        - In afternoon: th_fn is INCLUDED in candidate list.
        - In both: th_full is excluded from candidate list.
        """
        # Morning slot
        candidates_morning = available_candidates_by_level_and_bathing(
            target_date=TARGET_DATE,
            time_slot=self.slot_morning,
            level=self.grade_senior,
            require_bathing=False,
            desired_gender="male",
        )
        morning_pks = [c.id for c in candidates_morning]
        assert self.th_fn.id not in morning_pks, "Forenoon leave therapist must not be a morning candidate"
        assert self.th_full.id not in morning_pks, "Full-day leave therapist must not be a morning candidate"

        # Afternoon slot
        candidates_afternoon = available_candidates_by_level_and_bathing(
            target_date=TARGET_DATE,
            time_slot=self.slot_afternoon,
            level=self.grade_senior,
            require_bathing=False,
            desired_gender="male",
        )
        afternoon_pks = [c.id for c in candidates_afternoon]
        assert self.th_fn.id in afternoon_pks, "Forenoon leave therapist MUST be an afternoon candidate"
        assert self.th_full.id not in afternoon_pks, "Full-day leave therapist must NOT be an afternoon candidate"
