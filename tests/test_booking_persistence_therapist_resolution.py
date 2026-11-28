"""
BUG-4A Regression Test Suite: Therapist Object Resolution in `create_therapist_booking_safe`.

Covers:
1. TherapistMaster instance input.
2. Integer therapist PK input.
3. String therapist code input.
4. Numeric string PK input.
5. Patient.models.Therapist instance input.
6. Helping therapist supplied via its string code (verifies `is_helping_therapist_assignment=True`).
7. Nonexistent therapist identifiers (code, int PK, None) returning `(None, False)` safely.
8. Omission enforcement & IntegrityError recovery using resolved `booking_therapist`.
"""

from datetime import date, time

import pytest
from django.test import TestCase

from Patient.models import Therapist as PatientTherapist, TherapistBooking
from Sheduling.models import PatientSnapshot, TherapyAllocation
from allocation_engine.core.primitives.booking_persistence import create_therapist_booking_safe
from masters.models import (
    SlotMaster,
    TherapistGrade,
    TherapistMaster,
    TherapistTreatmentOmission,
    TherapyMaster,
)


TARGET_DATE = date(2099, 11, 5)


@pytest.mark.django_db(transaction=True)
class TherapistResolutionBookingPersistenceTests(TestCase):
    def setUp(self):
        self.slots = []
        for idx, st in enumerate(
            [time(6, 30), time(8, 30), time(10, 0), time(11, 30), time(14, 30), time(16, 0)],
            start=41,
        ):
            s, _ = SlotMaster.objects.get_or_create(
                slot_number=idx, defaults={"slot_time": st, "is_active": True}
            )
            if s.slot_time != st:
                s.slot_time = st
                s.save(update_fields=["slot_time"])
            self.slots.append(s)

        self.grade, _ = TherapistGrade.objects.get_or_create(
            name="Senior Therapist", defaults={"display_order": 2, "is_active": True}
        )
        self.therapy, _ = TherapyMaster.objects.get_or_create(
            therapy_code="THEB_BUG4A",
            defaults={
                "therapy_name": "BUG4A Resolution Therapy",
                "therapy_category": "Easy",
                "therapy_duration": "45",
                "bathing_required": "No",
                "treatment_room_required": "Yes",
                "total_no_of_therapist": 1,
                "no_of_senior_therapist": 1,
                "is_active": True,
            },
        )
        self.patient = PatientSnapshot.objects.create(
            pat_reg_no="884001",
            pat_name="BUG4A Patient",
            pat_sex="Male",
            pat_age="40",
            pat_room_no="DS-1",
        )
        self.alloc = TherapyAllocation.objects.create(
            patient=self.patient,
            therapy_code=self.therapy.therapy_code,
            therapy_name=self.therapy.therapy_name,
            timeslot=self.slots[0],
            from_date=TARGET_DATE,
            to_date=TARGET_DATE,
            days=1,
            status="draft",
        )
        self.tm_regular, _ = TherapistMaster.objects.get_or_create(
            therapist_code="TH_B4A_REG",
            defaults={
                "therapist_name": "BUG4A Regular Therapist",
                "therapist_gender": "Male",
                "therapist_grade": self.grade,
                "employee_code": "EMP_B4A_REG",
                "is_helping_therapist": False,
                "is_active": True,
            },
        )
        self.tm_helping, _ = TherapistMaster.objects.get_or_create(
            therapist_code="TH_B4A_HELP",
            defaults={
                "therapist_name": "BUG4A Helping Therapist",
                "therapist_gender": "Male",
                "therapist_grade": self.grade,
                "employee_code": "EMP_B4A_HELP",
                "is_helping_therapist": True,
                "is_active": True,
            },
        )

    def test_therapist_master_instance_input(self):
        tb, created = create_therapist_booking_safe(
            self.tm_regular,
            TARGET_DATE,
            self.slots[0],
            self.therapy.therapy_name,
            self.patient.id,
            self.alloc,
        )
        self.assertTrue(created)
        self.assertIsNotNone(tb)
        self.assertEqual(tb.therapist_id, self.tm_regular.pk)
        self.assertFalse(tb.is_helping_therapist_assignment)

    def test_integer_therapist_pk_input(self):
        tb, created = create_therapist_booking_safe(
            self.tm_regular.pk,
            TARGET_DATE,
            self.slots[1],
            self.therapy.therapy_name,
            self.patient.id,
            self.alloc,
        )
        self.assertTrue(created)
        self.assertIsNotNone(tb)
        self.assertEqual(tb.therapist_id, self.tm_regular.pk)

    def test_string_therapist_code_input(self):
        tb, created = create_therapist_booking_safe(
            self.tm_regular.therapist_code,
            TARGET_DATE,
            self.slots[2],
            self.therapy.therapy_name,
            self.patient.id,
            self.alloc,
        )
        self.assertTrue(created)
        self.assertIsNotNone(tb)
        self.assertEqual(tb.therapist_id, self.tm_regular.pk)

    def test_numeric_string_pk_input(self):
        tb, created = create_therapist_booking_safe(
            str(self.tm_regular.pk),
            TARGET_DATE,
            self.slots[3],
            self.therapy.therapy_name,
            self.patient.id,
            self.alloc,
        )
        self.assertTrue(created)
        self.assertIsNotNone(tb)
        self.assertEqual(tb.therapist_id, self.tm_regular.pk)

    def test_patient_therapist_instance_input(self):
        pt_obj, _ = PatientTherapist.objects.get_or_create(
            therapist_code=self.tm_regular.therapist_code,
            defaults={
                "therapist_name": self.tm_regular.therapist_name,
                "therapist_grade": "Senior Therapist",
            },
        )
        tb, created = create_therapist_booking_safe(
            pt_obj,
            TARGET_DATE,
            self.slots[4],
            self.therapy.therapy_name,
            self.patient.id,
            self.alloc,
        )
        self.assertTrue(created)
        self.assertIsNotNone(tb)
        self.assertEqual(tb.therapist_id, self.tm_regular.pk)

    def test_helping_therapist_via_string_code_sets_helping_flag(self):
        tb, created = create_therapist_booking_safe(
            self.tm_helping.therapist_code,
            TARGET_DATE,
            self.slots[0],
            self.therapy.therapy_name,
            self.patient.id,
            self.alloc,
        )
        self.assertTrue(created)
        self.assertIsNotNone(tb)
        self.assertEqual(tb.therapist_id, self.tm_helping.pk)
        self.assertTrue(tb.is_helping_therapist_assignment)

    def test_nonexistent_therapist_identifier_returns_none_false(self):
        for bad_input in ("NO_SUCH_THERAPIST_999", 999999999, "999999999", None, ""):
            tb, created = create_therapist_booking_safe(
                bad_input,
                TARGET_DATE,
                self.slots[5],
                self.therapy.therapy_name,
                self.patient.id,
                self.alloc,
            )
            self.assertIsNone(tb, f"Expected None for invalid therapist input {bad_input!r}")
            self.assertFalse(created)

    def test_omitted_therapist_supplied_by_pk_is_blocked(self):
        TherapistTreatmentOmission.objects.get_or_create(
            therapist=self.tm_regular,
            treatment=self.therapy,
            defaults={"status": "approved", "is_active": True, "reason": "BUG4A omission check"},
        )
        tb, created = create_therapist_booking_safe(
            self.tm_regular.pk,
            TARGET_DATE,
            self.slots[5],
            self.therapy.therapy_name,
            self.patient.id,
            self.alloc,
        )
        self.assertIsNone(tb)
        self.assertFalse(created)
        self.assertFalse(
            TherapistBooking.objects.filter(
                therapist=self.tm_regular, date=TARGET_DATE, time_slot=self.slots[5], status="BOOKED"
            ).exists()
        )
