"""
Special Dhara & Pizhichil Senior Tagging Test Suite

Validates special senior tag handling:
- is_treatment_requiring_senior_tag helper identifies the 13 special treatments:
  'dhara & abh(3)', 'dhara& pizhichil (4)', 'dhara & pizhichil (5)', 'dhara & pizhichil (6)',
  'dhara & pizhichil (7)', 'dhara & abyangam ( 3 t)', 'dhara & sudhikalpana dhara (5t)',
  'dhara ( 2 t)', 'thakradhara & abhyangam (4)', 'thakradhara & pizichil(6)',
  'thakradhara ( 2 t)', 'thakradhara&fbkadee kizhi (5 t)', 'thakradhara& thakrapizhichil(7)'.
- Regular treatments return False.
- get_senior_tag_count_for_therapist counts only non-bathing, BOOKED special treatments.
"""
import pytest
from datetime import date, time
from django.test import TestCase

from masters.models import SlotMaster, TherapistGrade, TherapistMaster, TherapyMaster
from Patient.models import TherapistBooking
from final_allocation import (
    is_treatment_requiring_senior_tag,
    get_senior_tag_count_for_therapist,
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


def _ensure_therapy(code, name, grade_counts, bathing="No", room_req="Yes", category="General", group=None):
    obj, _ = TherapyMaster.objects.get_or_create(
        therapy_code=code,
        defaults={
            "therapy_name": name,
            "therapy_category": category,
            "therapy_group": group,
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
class TestSpecialDharaPizhichilSeniorTagging(TestCase):
    """
    Validates special senior tag handling:
    - is_treatment_requiring_senior_tag helper identifies the 13 special treatments.
    - Regular treatments return False.
    - get_senior_tag_count_for_therapist counts only non-bathing, BOOKED special treatments.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.slot = _ensure_slot(111, time(11, 30))
        cls.grade = _ensure_grade("Senior Therapist", 2)
        cls.th_senior = _ensure_therapist(
            "TH_SNR_TAG", "Senior Tag Therapist", "Male", cls.grade, "EMP_SNR_TAG"
        )
        cls.therapy_dhara = _ensure_therapy(
            "T_SP_DHARA", "dhara & abh(3)", {"senior": 1}
        )
        cls.therapy_regular = _ensure_therapy(
            "T_REGULAR", "Abhyangam General", {"senior": 1}
        )

    def tearDown(self):
        TherapistBooking.objects.filter(date=TARGET_DATE).delete()

    def test_is_treatment_requiring_senior_tag_matches_expected_list(self):
        """All 13 special Dhara & Pizhichil treatments are correctly recognized."""
        special_names = [
            'dhara & abh(3)',
            'dhara& pizhichil (4)',
            'dhara & pizhichil (5)',
            'dhara & pizhichil (6)',
            'dhara & pizhichil (7)',
            'dhara & abyangam ( 3 t)',
            'dhara & sudhikalpana dhara (5t)',
            'dhara ( 2 t)',
            'thakradhara & abhyangam (4)',
            'thakradhara & pizichil(6)',
            'thakradhara ( 2 t)',
            'thakradhara&fbkadee kizhi (5 t)',
            'thakradhara& thakrapizhichil(7)',
        ]
        for name in special_names:
            assert is_treatment_requiring_senior_tag(name) is True, f"Failed to match: {name}"
            # Case-insensitivity & whitespace normalization check
            assert is_treatment_requiring_senior_tag(name.upper()) is True
            assert is_treatment_requiring_senior_tag(f"  {name}  ") is True

    def test_is_treatment_requiring_senior_tag_rejects_regular_therapies(self):
        """Standard therapies do not receive senior tag requirement."""
        regular_names = ["Abhyangam", "Nasyam", "Kizhi", "Shirodhara", "Normal Dhara", "", None]
        for name in regular_names:
            assert is_treatment_requiring_senior_tag(name) is False, f"Unexpected match: {name}"

    def test_get_senior_tag_count_for_therapist_counts_only_non_bathing_senior_special_treatments(self):
        """Counts only non-bathing BOOKED bookings of special senior tag treatments for that date."""
        # 1. Non-bathing, BOOKED, special therapy -> COUNTED (+1)
        TherapistBooking.objects.create(
            therapist=self.th_senior,
            therapy=self.therapy_dhara,
            date=TARGET_DATE,
            time_slot=self.slot,
            status="BOOKED",
            is_bathing=False,
        )

        # 2. Bathing, BOOKED, special therapy -> NOT counted (bathing therapist cannot take senior tag)
        slot2 = _ensure_slot(112, time(14, 30))
        TherapistBooking.objects.create(
            therapist=self.th_senior,
            therapy=self.therapy_dhara,
            date=TARGET_DATE,
            time_slot=slot2,
            status="BOOKED",
            is_bathing=True,
        )

        # 3. Non-bathing, BOOKED, regular therapy -> NOT counted
        slot3 = _ensure_slot(113, time(16, 0))
        TherapistBooking.objects.create(
            therapist=self.th_senior,
            therapy=self.therapy_regular,
            date=TARGET_DATE,
            time_slot=slot3,
            status="BOOKED",
            is_bathing=False,
        )

        # 4. Special therapy, but CANCELLED -> NOT counted
        slot4 = _ensure_slot(114, time(17, 30))
        TherapistBooking.objects.create(
            therapist=self.th_senior,
            therapy=self.therapy_dhara,
            date=TARGET_DATE,
            time_slot=slot4,
            status="CANCELLED",
            is_bathing=False,
        )

        count = get_senior_tag_count_for_therapist(self.th_senior, TARGET_DATE)
        assert count == 1, f"Expected senior tag count of 1, got: {count}"
