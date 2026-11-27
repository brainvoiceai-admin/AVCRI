"""
CP-0 Test Suite: Duplicate Same-Slot Treatments for the Same Patient.

Verifies:
When two treatments are assigned on the exact same (date, slot) for the same patient
(even when both have previous-day continuity therapists):
- Exactly ONE treatment allocates (status='scheduled').
- The SECOND treatment fails with failure_reason='patient_already_has_booking'.
- No stale TherapistBooking lock remains for the failed allocation.
"""
import pytest
from datetime import date, time, timedelta
from unittest.mock import patch
from django.test import TestCase

from masters.models import SlotMaster, TherapistGrade, TherapistMaster, TherapyMaster
from Patient.models import TreatmentRoom, RoomName, TherapistBooking
from Sheduling.models import PatientSnapshot, TherapyAllocation, Booking
from final_allocation import bulk_allocate_for_date

PREV_DATE = date(2099, 11, 24)
TEST_DATE = PREV_DATE + timedelta(days=1)


@pytest.mark.django_db(transaction=True)
class SameSlotDuplicatePatientTests(TestCase):
    def setUp(self):
        self.slot_1000, _ = SlotMaster.objects.get_or_create(
            slot_number=2, defaults={"slot_time": time(10, 0), "is_active": True}
        )
        self.grade, _ = TherapistGrade.objects.get_or_create(
            name="Senior Therapist", defaults={"display_order": 1, "is_active": True}
        )
        self.th1, _ = TherapistMaster.objects.get_or_create(
            therapist_code="TH_CP0_DUP1",
            defaults={
                "therapist_name": "Dup Therapist 1",
                "therapist_gender": "Female",
                "therapist_grade": self.grade,
                "employee_code": "EMP_CP0_DUP1",
                "is_bathing_therapist": True,
                "is_active": True,
            },
        )
        self.th2, _ = TherapistMaster.objects.get_or_create(
            therapist_code="TH_CP0_DUP2",
            defaults={
                "therapist_name": "Dup Therapist 2",
                "therapist_gender": "Female",
                "therapist_grade": self.grade,
                "employee_code": "EMP_CP0_DUP2",
                "is_bathing_therapist": True,
                "is_active": True,
            },
        )
        rn1, _ = RoomName.objects.get_or_create(name="Room TR-1", defaults={"is_active": True})
        self.room1, _ = TreatmentRoom.objects.get_or_create(
            room_no="TR-1", defaults={"room_name": rn1, "floor": "G", "is_active": True}
        )
        rn2, _ = RoomName.objects.get_or_create(name="Room TR-2", defaults={"is_active": True})
        self.room2, _ = TreatmentRoom.objects.get_or_create(
            room_no="TR-2", defaults={"room_name": rn2, "floor": "G", "is_active": True}
        )
        self.therapy, _ = TherapyMaster.objects.get_or_create(
            therapy_code="THEB_CP0_DUP",
            defaults={
                "therapy_name": "CP0 Dup Slot Therapy",
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
            pat_reg_no="880005",
            pat_name="Same Slot Patient",
            pat_sex="Female",
            pat_age="34",
            pat_room_no="DS-1",
        )

    def test_one_schedules_and_duplicate_fails_with_patient_already_has_booking(self):
        alloc_a = TherapyAllocation.objects.create(
            patient=self.patient, therapy_code=self.therapy.therapy_code,
            therapy_name=self.therapy.therapy_name, timeslot=self.slot_1000,
            from_date=PREV_DATE, to_date=TEST_DATE, days=2, status="draft",
        )
        alloc_b = TherapyAllocation.objects.create(
            patient=self.patient, therapy_code=self.therapy.therapy_code,
            therapy_name=self.therapy.therapy_name, timeslot=self.slot_1000,
            from_date=PREV_DATE, to_date=TEST_DATE, days=2, status="draft",
        )

        # Previous-day continuity rows for BOTH allocations
        TherapistBooking.objects.create(
            therapist=self.th1, date=PREV_DATE, time_slot=self.slot_1000,
            therapy_name=self.therapy.therapy_name, patient_id=self.patient.id,
            visit=alloc_a, status="BOOKED",
        )
        TherapistBooking.objects.create(
            therapist=self.th2, date=PREV_DATE, time_slot=self.slot_1000,
            therapy_name=self.therapy.therapy_name, patient_id=self.patient.id,
            visit=alloc_b, status="BOOKED",
        )

        bk_a = Booking.objects.create(
            allocation=alloc_a, date=TEST_DATE, timeslot=self.slot_1000,
            status="draft", snapshot_therapy_name=self.therapy.therapy_name,
        )
        bk_b = Booking.objects.create(
            allocation=alloc_b, date=TEST_DATE, timeslot=self.slot_1000,
            status="draft", snapshot_therapy_name=self.therapy.therapy_name,
        )

        with patch("final_allocation.is_patient_active", return_value=True):
            bulk_allocate_for_date(TEST_DATE.isoformat())

        bk_a.refresh_from_db()
        bk_b.refresh_from_db()

        self.assertEqual(sorted([bk_a.status, bk_b.status]), ["failed", "scheduled"])
        failed_bk = bk_a if bk_a.status == "failed" else bk_b
        self.assertEqual(failed_bk.failure_reason, "patient_already_has_booking")
        # Failed allocation must have 0 active TherapistBooking locks
        self.assertFalse(
            TherapistBooking.objects.filter(
                visit=failed_bk.allocation, date=TEST_DATE, time_slot=self.slot_1000, status="BOOKED"
            ).exists()
        )
