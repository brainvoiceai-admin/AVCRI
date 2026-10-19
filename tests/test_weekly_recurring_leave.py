"""
Weekly Recurring Leave Enforcement Test Suite

Validates that:
- A therapist with an active recurring weekly leave on target_date.weekday() (TherapistLeaveMaster)
  is strictly excluded from allocation on that weekday.
- Leave on a different weekday does NOT block allocation.
- Absence of weekly leave permits allocation.
- Rescheduling module checks active status (is_active=True) for weekly leave.
"""
import pytest
from datetime import date, time
from django.test import TestCase

from masters.models import SlotMaster, TherapistGrade, TherapistMaster, TherapistLeaveMaster
from Patient.models import TherapistBooking
from final_allocation import allocate_therapists
from resheduleMorningandNight import therapist_has_weekly_leave_on

TARGET_DATE = date(2099, 9, 22)  # Far future Tuesday (weekday = 1)


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


@pytest.mark.django_db(transaction=True)
class TestWeeklyRecurringLeaveEnforcement(TestCase):
    """
    Validates that a therapist with a weekly leave on target_date.weekday()
    is strictly excluded from allocation on that weekday.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.slot = _ensure_slot(81, time(10, 0))
        cls.grade = _ensure_grade("Senior Therapist", 2)

        cls.th_leave = _ensure_therapist(
            "TH_WLEAVE", "Weekly Leave Therapist", "Male", cls.grade, "EMP_WLEAVE"
        )
        cls.th_available = _ensure_therapist(
            "TH_WAVAIL", "Weekly Available Therapist", "Male", cls.grade, "EMP_WAVAIL"
        )

    def tearDown(self):
        TherapistLeaveMaster.objects.filter(therapist=self.th_leave).delete()
        TherapistBooking.objects.filter(date=TARGET_DATE).delete()

    def test_weekly_recurring_leave_blocks_therapist_on_that_weekday(self):
        """TARGET_DATE is a Tuesday (weekday = 1). Setting leave_day=1 blocks th_leave."""
        weekday_num = TARGET_DATE.weekday()  # Tuesday = 1

        TherapistLeaveMaster.objects.create(
            therapist=self.th_leave,
            leave_day=weekday_num,
            is_active=True,
        )

        assert therapist_has_weekly_leave_on(self.th_leave, TARGET_DATE) is True

        reqs = {"senior": 1}
        allocated = allocate_therapists(
            date=TARGET_DATE,
            time_slot=self.slot,
            therapy_requirements=reqs,
            patient_gender="Male",
            patient_age="30",
        )
        assert len(allocated) == 1
        assert allocated[0].therapist_code == self.th_available.therapist_code
        assert allocated[0].therapist_code != self.th_leave.therapist_code

    def test_weekly_leave_on_different_weekday_does_not_block(self):
        """Setting recurring leave on a different weekday (e.g. Wednesday = 2) does NOT block on Tuesday."""
        TherapistLeaveMaster.objects.create(
            therapist=self.th_leave,
            leave_day=2,  # Wednesday
            is_active=True,
        )

        assert therapist_has_weekly_leave_on(self.th_leave, TARGET_DATE) is False

        reqs = {"senior": 1}
        allocated = allocate_therapists(
            date=TARGET_DATE,
            time_slot=self.slot,
            therapy_requirements=reqs,
            patient_gender="Male",
            patient_age="30",
            avoid_therapists=[self.th_available.therapist_code],
        )
        assert len(allocated) == 1
        assert allocated[0].therapist_code == self.th_leave.therapist_code

    def test_absence_of_weekly_leave_allows_allocation(self):
        """When no weekly leave record exists for that weekday, the therapist is readily allocated."""
        assert therapist_has_weekly_leave_on(self.th_leave, TARGET_DATE) is False

        reqs = {"senior": 1}
        allocated = allocate_therapists(
            date=TARGET_DATE,
            time_slot=self.slot,
            therapy_requirements=reqs,
            patient_gender="Male",
            patient_age="30",
            avoid_therapists=[self.th_available.therapist_code],
        )
        assert len(allocated) == 1
        assert allocated[0].therapist_code == self.th_leave.therapist_code

    def test_reschedule_checks_active_status_for_weekly_leave(self):
        """therapist_has_weekly_leave_on respects is_active=False on TherapistLeaveMaster."""
        weekday_num = TARGET_DATE.weekday()
        TherapistLeaveMaster.objects.create(
            therapist=self.th_leave,
            leave_day=weekday_num,
            is_active=False,
        )
        assert therapist_has_weekly_leave_on(self.th_leave, TARGET_DATE) is False
