"""
Grade Substitution Hierarchy & Helping Therapist Fallback Test Suite

Validates:
- Grade substitution hierarchy: Junior requirement falls back to Senior / Super Senior when no Junior is free.
- Primary therapists (is_helping_therapist=False) are always preferred over helping therapists.
- Helping therapists are NOT allocated when allow_helping_fallback=False.
- Helping therapists ARE allocated when allow_helping_fallback=True and primary therapists are exhausted.
- HelpingTherapistAllocationLog audit trail record is generated upon fallback.
"""
import pytest
from datetime import date, time
from django.test import TestCase

from masters.models import SlotMaster, TherapistGrade, TherapistMaster
from Patient.models import TherapistBooking
from Sheduling.models import HelpingTherapistAllocationLog
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
    updated = False
    if obj.is_bathing_therapist != is_bathing:
        obj.is_bathing_therapist = is_bathing
        updated = True
    if obj.is_helping_therapist != is_helping:
        obj.is_helping_therapist = is_helping
        updated = True
    if updated:
        obj.save(update_fields=["is_bathing_therapist", "is_helping_therapist"])
    return obj


@pytest.mark.django_db(transaction=True)
class TestGradeSubstitutionHierarchyAndHelpingTherapist(TestCase):
    """
    Validates:
    - Grade substitution hierarchy: Junior requirement falls back to Senior / Super Senior when no Junior is free.
    - Primary therapists (is_helping_therapist=False) are always preferred over helping therapists.
    - Helping therapists are NOT allocated when allow_helping_fallback=False.
    - Helping therapists ARE allocated when allow_helping_fallback=True and primary therapists are exhausted.
    - HelpingTherapistAllocationLog audit trail record is generated upon fallback.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.slot = _ensure_slot(101, time(10, 0))
        cls.grade_junior = _ensure_grade("Junior Therapist", 3)
        cls.grade_senior = _ensure_grade("Senior Therapist", 2)
        cls.grade_super_senior = _ensure_grade("Super Senior Therapist", 1)

        cls.th_senior_primary = _ensure_therapist(
            "TH_SUB_SNR", "Senior Primary", "Male", cls.grade_senior, "EMP_SUB_SNR", is_helping=False
        )
        cls.th_helping = _ensure_therapist(
            "TH_HELP_1", "Helping Therapist", "Male", cls.grade_senior, "EMP_HELP_1", is_helping=True
        )

    def tearDown(self):
        TherapistBooking.objects.filter(date=TARGET_DATE).delete()
        HelpingTherapistAllocationLog.objects.filter(date=TARGET_DATE).delete()

    def test_grade_substitution_junior_falls_back_to_senior(self):
        """When a Junior therapist is needed but none exist/available, Senior therapist is substituted."""
        reqs = {"junior": 1}
        # Only Senior primary therapist exists
        allocated = allocate_therapists(
            date=TARGET_DATE,
            time_slot=self.slot,
            therapy_requirements=reqs,
            patient_gender="Male",
            patient_age="30",
        )
        assert len(allocated) == 1
        assert allocated[0].therapist_code == self.th_senior_primary.therapist_code
        assert allocated[0].therapist_grade.name == "Senior Therapist"

    def test_primary_therapist_preferred_over_helping_therapist(self):
        """When both a primary therapist and a helping therapist are free, the primary therapist is selected."""
        reqs = {"senior": 1}
        # Both th_senior_primary and th_helping are free
        allocated = allocate_therapists(
            date=TARGET_DATE,
            time_slot=self.slot,
            therapy_requirements=reqs,
            patient_gender="Male",
            patient_age="30",
            allow_helping_fallback=True,
        )
        assert len(allocated) == 1
        assert allocated[0].therapist_code == self.th_senior_primary.therapist_code
        assert allocated[0].is_helping_therapist is False

    def test_helping_therapist_not_allocated_when_fallback_disabled(self):
        """When primary pool is exhausted and allow_helping_fallback=False, helping therapist is NOT used."""
        reqs = {"senior": 1}
        # Avoid primary therapist so only helping therapist remains
        allocated = allocate_therapists(
            date=TARGET_DATE,
            time_slot=self.slot,
            therapy_requirements=reqs,
            patient_gender="Male",
            patient_age="30",
            avoid_therapists=[self.th_senior_primary.therapist_code],
            allow_helping_fallback=False,
        )
        assert len(allocated) == 0, f"Helping therapist should not be allocated when fallback is disabled: {allocated}"

    def test_helping_therapist_fallback_when_primary_shortage_and_audit_logged(self):
        """When primary pool is exhausted and allow_helping_fallback=True, helping therapist is allocated with audit log."""
        reqs = {"senior": 1}
        # Pre-book primary therapist so they are unavailable
        TherapistBooking.objects.create(
            therapist=self.th_senior_primary, date=TARGET_DATE, time_slot=self.slot, status="BOOKED"
        )

        allocated = allocate_therapists(
            date=TARGET_DATE,
            time_slot=self.slot,
            therapy_requirements=reqs,
            patient_gender="Male",
            patient_age="30",
            patient_id=999,
            allow_helping_fallback=True,
        )
        assert len(allocated) == 1
        assert allocated[0].therapist_code == self.th_helping.therapist_code
        assert allocated[0].is_helping_therapist is True

        # Check HelpingTherapistAllocationLog was created
        log_entry = HelpingTherapistAllocationLog.objects.filter(
            helping_therapist=self.th_helping,
            date=TARGET_DATE,
        ).first()
        assert log_entry is not None, "HelpingTherapistAllocationLog audit trail was not created!"
        assert log_entry.is_supporting_backup is True
