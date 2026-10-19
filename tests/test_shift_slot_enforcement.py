"""
Shift Slot Enforcements Test Suite

Validates shift slot enforcements via ShiftSlotMapping & TherapistShiftMapping:
- Shift enforcement flag check (_shift_enforcement_enabled).
- _shift_eligibility_sets_for_slot accurately returns mapped_ids and eligible_ids.
- Therapists mapped to a shift are blocked from slots outside that shift.
- Therapists mapped to a shift are allowed for slots within that shift.
"""
import pytest
from datetime import date, time
from django.test import TestCase

from masters.models import (
    SlotMaster,
    TherapistGrade,
    TherapistMaster,
    ShiftMaster,
    ShiftSlotMapping,
    TherapistShiftMapping,
)
from Patient.models import TherapistBooking
from final_allocation import (
    allocate_therapists,
    _shift_enforcement_enabled,
    _shift_eligibility_sets_for_slot,
)

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
class TestShiftSlotEnforcement(TestCase):
    """
    Validates shift slot enforcements:
    - _shift_enforcement_enabled returns True when both ShiftSlotMapping and TherapistShiftMapping exist.
    - Therapists mapped to a shift are blocked from slots outside that shift.
    - Therapists mapped to a shift are allowed for slots inside that shift.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.slot_morning = _ensure_slot(121, time(6, 30))
        cls.slot_evening = _ensure_slot(122, time(16, 0))
        cls.grade = _ensure_grade("Senior Therapist", 2)

        cls.th_shift_morn = _ensure_therapist(
            "TH_SH_M", "Morning Shift Therapist", "Male", cls.grade, "EMP_SH_M"
        )
        cls.th_unmapped = _ensure_therapist(
            "TH_UNMAP", "Unmapped Therapist", "Male", cls.grade, "EMP_UNMAP"
        )

        # Create Shift Master
        cls.shift_morning, _ = ShiftMaster.objects.get_or_create(shift_name="Shift Morning Test")

        # Map Shift Morning to slot_morning
        ShiftSlotMapping.objects.get_or_create(
            shift=cls.shift_morning, slot=cls.slot_morning, defaults={"is_active": True}
        )

        # Map th_shift_morn to Shift Morning
        TherapistShiftMapping.objects.get_or_create(
            therapist=cls.th_shift_morn, shift=cls.shift_morning, defaults={"is_active": True}
        )

    def tearDown(self):
        TherapistBooking.objects.filter(date=TARGET_DATE).delete()

    def test_shift_enforcement_enabled_flag(self):
        """_shift_enforcement_enabled returns True when active mappings exist."""
        assert _shift_enforcement_enabled() is True

    def test_shift_eligibility_sets_for_slot(self):
        """_shift_eligibility_sets_for_slot accurately returns mapped_ids and eligible_ids."""
        mapped, eligible = _shift_eligibility_sets_for_slot(self.slot_morning)
        assert self.th_shift_morn.id in mapped
        assert self.th_shift_morn.id in eligible

        mapped_eve, eligible_eve = _shift_eligibility_sets_for_slot(self.slot_evening)
        assert self.th_shift_morn.id in mapped_eve
        assert self.th_shift_morn.id not in eligible_eve  # Not eligible for evening slot!

    def test_shift_enforcement_blocks_therapist_outside_assigned_shift_slots(self):
        """A therapist mapped to Morning Shift is BLOCKED from allocation at Evening slot."""
        reqs = {"senior": 1}
        # In evening slot, th_shift_morn is blocked because slot_evening is not in Morning Shift
        allocated = allocate_therapists(
            date=TARGET_DATE,
            time_slot=self.slot_evening,
            therapy_requirements=reqs,
            patient_gender="Male",
            patient_age="30",
            avoid_therapists=[self.th_unmapped.therapist_code],
        )
        assert len(allocated) == 0, f"Therapist outside shift slot should NOT be allocated: {allocated}"

    def test_shift_enforcement_allows_therapist_within_assigned_shift_slots(self):
        """A therapist mapped to Morning Shift CAN be allocated for Morning slot."""
        reqs = {"senior": 1}
        allocated = allocate_therapists(
            date=TARGET_DATE,
            time_slot=self.slot_morning,
            therapy_requirements=reqs,
            patient_gender="Male",
            patient_age="30",
            avoid_therapists=[self.th_unmapped.therapist_code],
        )
        assert len(allocated) == 1
        assert allocated[0].therapist_code == self.th_shift_morn.therapist_code
