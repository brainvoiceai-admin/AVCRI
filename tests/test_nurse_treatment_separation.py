"""
Nurse Treatment Separation Test Suite

Validates NurseTreatmentMaster integration:
- is_nurse_treatment accurately identifies nurse treatments by treatment_code and therapy_name.
- Non-nurse therapies return None.
- Inactive nurse treatments are ignored.
"""
import pytest
from django.test import TestCase

from masters.models import NurseTreatmentMaster
from Sheduling.nurse_allocation import is_nurse_treatment


@pytest.mark.django_db(transaction=True)
class TestNurseTreatmentSeparation(TestCase):
    """
    Validates NurseTreatmentMaster integration:
    - is_nurse_treatment accurately identifies nurse treatments by code and name.
    - Non-nurse therapies return None.
    - Inactive nurse treatments are ignored.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.nt_active, _ = NurseTreatmentMaster.objects.get_or_create(
            treatment_code="NT_001",
            defaults={"name": "Nurse Enema Procedure", "number_of_nurse_required": 1, "is_active": True},
        )
        cls.nt_inactive, _ = NurseTreatmentMaster.objects.get_or_create(
            treatment_code="NT_INACT",
            defaults={"name": "Inactive Nurse Procedure", "number_of_nurse_required": 1, "is_active": False},
        )

    def test_is_nurse_treatment_identifies_nurse_treatments_by_code_and_name(self):
        """is_nurse_treatment finds active nurse treatment by code or name."""
        res_by_code = is_nurse_treatment("NT_001")
        assert res_by_code is not None
        assert res_by_code.treatment_code == "NT_001"

        res_by_name = is_nurse_treatment("UNKNOWN_CODE", "Nurse Enema Procedure")
        assert res_by_name is not None
        assert res_by_name.treatment_code == "NT_001"

    def test_is_nurse_treatment_returns_none_for_standard_therapies(self):
        """Standard therapies return None and are not classified as nurse treatments."""
        res = is_nurse_treatment("THEB001", "Standard Abhyangam")
        assert res is None

    def test_nurse_treatment_inactive_is_ignored(self):
        """Inactive nurse treatments return None."""
        res = is_nurse_treatment("NT_INACT", "Inactive Nurse Procedure")
        assert res is None
