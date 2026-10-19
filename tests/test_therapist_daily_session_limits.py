"""
Therapist Daily Session Capacity Limits Test Suite

Validates therapist daily session limits:
- Normal limit: 5 sessions per therapist.
- 6th overtime session only permitted when all eligible candidates have reached 5 sessions.
- Hard cap at 6 sessions strictly prevents a 7th session under any circumstances.
- Difficulty category and overall session count load balancing.
"""
import pytest
from datetime import date, time
from django.test import TestCase

from masters.models import SlotMaster, TherapistGrade, TherapistMaster
from Patient.models import TherapistBooking
from final_allocation import allocate_therapists

TARGET_DATE = date(2099, 9, 22)


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
class TestTherapistDailySessionLimits(TestCase):
    """
    Validates therapist session limits:
    - Normal cap: 5 sessions.
    - Overtime cap: 6 sessions (when all available candidates have reached 5).
    - Hard ceiling: Therapist with 6 sessions CANNOT be assigned to a 7th session.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.slots = [_ensure_slot(70 + i, time(6 + i * 2, 0)) for i in range(7)]
        cls.grade = _ensure_grade("Senior Therapist", 2)

        cls.th_primary = _ensure_therapist(
            "TH_LIMIT_P", "Primary Limit Therapist", "Male", cls.grade, "EMP_LIMIT_P"
        )
        cls.th_secondary = _ensure_therapist(
            "TH_LIMIT_S", "Secondary Limit Therapist", "Male", cls.grade, "EMP_LIMIT_S"
        )

    def tearDown(self):
        TherapistBooking.objects.filter(date=TARGET_DATE).delete()

    def test_therapist_with_under_5_sessions_allocated_normally(self):
        """Therapist with < 5 sessions is readily allocated under normal mode."""
        reqs = {"senior": 1}
        # Pre-book 3 sessions for th_primary on TARGET_DATE
        for s in self.slots[:3]:
            TherapistBooking.objects.create(
                therapist=self.th_primary, date=TARGET_DATE, time_slot=s, status="BOOKED"
            )

        allocated = allocate_therapists(
            date=TARGET_DATE,
            time_slot=self.slots[3],
            therapy_requirements=reqs,
            patient_gender="Male",
            patient_age="30",
            avoid_therapists=[self.th_secondary.therapist_code],
        )
        assert len(allocated) == 1
        assert allocated[0].therapist_code == self.th_primary.therapist_code

    def test_therapist_at_5_sessions_not_allocated_if_under_limit_therapist_available(self):
        """When therapist A has 5 sessions and therapist B has 0, therapist B is preferred."""
        reqs = {"senior": 1}
        # Pre-book 5 sessions for th_primary
        for s in self.slots[:5]:
            TherapistBooking.objects.create(
                therapist=self.th_primary, date=TARGET_DATE, time_slot=s, status="BOOKED"
            )

        # Both primary (5 sessions) and secondary (0 sessions) are free at slot 6
        allocated = allocate_therapists(
            date=TARGET_DATE,
            time_slot=self.slots[5],
            therapy_requirements=reqs,
            patient_gender="Male",
            patient_age="30",
        )
        assert len(allocated) == 1
        # Secondary therapist (under 5 sessions) must be chosen
        assert allocated[0].therapist_code == self.th_secondary.therapist_code

    def test_therapist_at_5_sessions_allocated_when_overtime_allowed(self):
        """When all candidates have reached 5 sessions, overtime mode allows a 6th session."""
        reqs = {"senior": 1}
        # Pre-book 5 sessions for th_primary
        for s in self.slots[:5]:
            TherapistBooking.objects.create(
                therapist=self.th_primary, date=TARGET_DATE, time_slot=s, status="BOOKED"
            )

        # Only th_primary is available (avoid th_secondary), primary already has 5
        allocated = allocate_therapists(
            date=TARGET_DATE,
            time_slot=self.slots[5],
            therapy_requirements=reqs,
            patient_gender="Male",
            patient_age="30",
            avoid_therapists=[self.th_secondary.therapist_code],
        )
        assert len(allocated) == 1
        assert allocated[0].therapist_code == self.th_primary.therapist_code

    def test_hard_cap_at_6_sessions_prevents_7th_session(self):
        """A therapist who already has 6 sessions for the day CANNOT be assigned a 7th session."""
        reqs = {"senior": 1}
        # Pre-book 6 sessions for th_primary
        for s in self.slots[:6]:
            TherapistBooking.objects.create(
                therapist=self.th_primary, date=TARGET_DATE, time_slot=s, status="BOOKED"
            )

        # Attempt to allocate th_primary at 7th slot
        allocated = allocate_therapists(
            date=TARGET_DATE,
            time_slot=self.slots[6],
            therapy_requirements=reqs,
            patient_gender="Male",
            patient_age="30",
            avoid_therapists=[self.th_secondary.therapist_code],
        )
        assert len(allocated) == 0, (
            f"Hard cap of 6 sessions violated! Therapist with 6 sessions was allocated a 7th: {allocated}"
        )
