"""
CP-0 Test Suite: Cancel Therapy & Re-allocate Same Slot.

Verifies:
1. Cancelling a treatment clears Booking.room=None and sets status='cancelled'.
2. Cancelling releases BookingAssignment and cancels TherapistBooking / RoomBooking
   even when pre-existing CANCELLED rows exist for the same (therapist/room, date, slot)
   (UniqueConstraint edge case).
3. Allocating a new treatment for the same patient on the same slot succeeds cleanly.
4. Cancelling one treatment does NOT cancel another treatment of the same patient in a different slot.
"""
import json
import pytest
from datetime import date, time
from unittest.mock import patch
from django.test import TestCase, RequestFactory
from django.contrib.auth import get_user_model

from masters.models import SlotMaster, TherapistGrade, TherapistMaster, TherapyMaster
from Patient.models import TreatmentRoom, RoomName, RoomBooking, TherapistBooking, Therapist as PatientTherapist
from Sheduling.models import PatientSnapshot, TherapyAllocation, Booking, BookingAssignment
from Sheduling.views import therapy_entry
from final_allocation import bulk_allocate_for_date

User = get_user_model()
TEST_DATE = date(2099, 11, 10)


@pytest.mark.django_db(transaction=True)
class CancelAndReallocateSlotTests(TestCase):
    def setUp(self):
        self.rf = RequestFactory()
        self.user, _ = User.objects.get_or_create(
            username="cp0_cancel_admin",
            defaults={"is_superuser": True, "is_staff": True, "role": "super_admin"},
        )
        self.slot_0830, _ = SlotMaster.objects.get_or_create(
            slot_number=1, defaults={"slot_time": time(8, 30), "is_active": True}
        )
        self.slot_1000, _ = SlotMaster.objects.get_or_create(
            slot_number=2, defaults={"slot_time": time(10, 0), "is_active": True}
        )
        self.grade, _ = TherapistGrade.objects.get_or_create(
            name="Senior Therapist", defaults={"display_order": 1, "is_active": True}
        )
        self.th, _ = TherapistMaster.objects.get_or_create(
            therapist_code="TH_CP0_C1",
            defaults={
                "therapist_name": "Cancel Test Therapist",
                "therapist_gender": "Male",
                "therapist_grade": self.grade,
                "employee_code": "EMP_CP0_C1",
                "is_bathing_therapist": True,
                "is_active": True,
            },
        )
        self.pt_th, _ = PatientTherapist.objects.get_or_create(
            therapist_code=self.th.therapist_code,
            defaults={
                "therapist_name": self.th.therapist_name,
                "therapist_grade": "Senior Therapist",
                "is_bathing_therapist": True,
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
            therapy_code="THEB_CP0_C1",
            defaults={
                "therapy_name": "CP0 Standard Oil Therapy",
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
            pat_reg_no="880001",
            pat_name="Cancel Realloc Patient",
            pat_sex="Male",
            pat_age="40",
            pat_room_no="DS-1",
        )

    def test_cancel_with_preexisting_cancelled_rows_and_reallocate_same_slot(self):
        # Seed pre-existing CANCELLED rows for same therapist & room on TEST_DATE + slot_0830
        TherapistBooking.objects.create(
            therapist=self.th, date=TEST_DATE, time_slot=self.slot_0830,
            therapy_name=self.therapy.therapy_name, patient_id=self.patient.id, status="CANCELLED",
        )
        RoomBooking.objects.create(
            room=self.room1, date=TEST_DATE, time_slot=self.slot_0830,
            therapy_name=self.therapy.therapy_name, patient_id=self.patient.id, status="CANCELLED",
        )

        alloc1 = TherapyAllocation.objects.create(
            patient=self.patient, therapy_code=self.therapy.therapy_code,
            therapy_name=self.therapy.therapy_name, timeslot=self.slot_0830,
            room=self.room1, from_date=TEST_DATE, to_date=TEST_DATE, days=1, status="allocated",
        )
        bk1 = Booking.objects.create(
            allocation=alloc1, date=TEST_DATE, timeslot=self.slot_0830,
            room=self.room1, status="scheduled", snapshot_therapy_name=self.therapy.therapy_name,
        )
        BookingAssignment.objects.create(booking=bk1, therapist=self.pt_th, status="assigned")
        TherapistBooking.objects.create(
            therapist=self.th, date=TEST_DATE, time_slot=self.slot_0830,
            therapy_name=self.therapy.therapy_name, patient_id=self.patient.id,
            visit=alloc1, status="BOOKED",
        )
        # RoomBooking with therapy=None (legacy pattern) linked only via visit=bk1
        RoomBooking.objects.create(
            room=self.room1, date=TEST_DATE, time_slot=self.slot_0830,
            therapy_name=self.therapy.therapy_name, patient_id=self.patient.id,
            visit=bk1, therapy=None, status="BOOKED",
        )

        # Cancel alloc1 via therapy_entry POST
        req = self.rf.post(
            "/sheduling/therapy-entry/?action=cancel_therapy",
            data=json.dumps({
                "allocation_id": alloc1.id,
                "cancel_from": TEST_DATE.isoformat(),
                "cancel_to": TEST_DATE.isoformat(),
                "reason": "Patient requested change",
            }),
            content_type="application/json",
        )
        req.user = self.user
        resp = therapy_entry(req)
        self.assertEqual(resp.status_code, 200)

        bk1.refresh_from_db()
        self.assertEqual(bk1.status, "cancelled")
        self.assertIsNone(bk1.room)
        self.assertFalse(
            TherapistBooking.objects.filter(
                therapist=self.th, date=TEST_DATE, time_slot=self.slot_0830, status="BOOKED"
            ).exists()
        )
        self.assertFalse(
            RoomBooking.objects.filter(
                room=self.room1, date=TEST_DATE, time_slot=self.slot_0830, status="BOOKED"
            ).exists()
        )
        self.assertEqual(BookingAssignment.objects.get(booking=bk1).status, "released")

        # Now allocate a second treatment on the EXACT SAME slot for the SAME patient
        alloc2 = TherapyAllocation.objects.create(
            patient=self.patient, therapy_code=self.therapy.therapy_code,
            therapy_name=self.therapy.therapy_name, timeslot=self.slot_0830,
            from_date=TEST_DATE, to_date=TEST_DATE, days=1, status="draft",
        )
        bk2 = Booking.objects.create(
            allocation=alloc2, date=TEST_DATE, timeslot=self.slot_0830,
            status="draft", snapshot_therapy_name=self.therapy.therapy_name,
        )

        with patch("final_allocation.is_patient_active", return_value=True):
            bulk_allocate_for_date(TEST_DATE.isoformat())

        bk2.refresh_from_db()
        self.assertEqual(bk2.status, "scheduled", f"Expected scheduled, got {bk2.status} ({bk2.failure_reason})")
        self.assertIsNotNone(bk2.room)

    def test_cancel_one_slot_does_not_cancel_other_slot_for_same_patient(self):
        alloc1 = TherapyAllocation.objects.create(
            patient=self.patient, therapy_code=self.therapy.therapy_code,
            therapy_name=self.therapy.therapy_name, timeslot=self.slot_0830,
            room=self.room1, from_date=TEST_DATE, to_date=TEST_DATE, days=1, status="allocated",
        )
        bk1 = Booking.objects.create(
            allocation=alloc1, date=TEST_DATE, timeslot=self.slot_0830,
            room=self.room1, status="scheduled", snapshot_therapy_name=self.therapy.therapy_name,
        )
        RoomBooking.objects.create(
            room=self.room1, date=TEST_DATE, time_slot=self.slot_0830,
            therapy_name=self.therapy.therapy_name, patient_id=self.patient.id,
            visit=bk1, therapy=None, status="BOOKED",
        )

        alloc2 = TherapyAllocation.objects.create(
            patient=self.patient, therapy_code=self.therapy.therapy_code,
            therapy_name=self.therapy.therapy_name, timeslot=self.slot_1000,
            room=self.room2, from_date=TEST_DATE, to_date=TEST_DATE, days=1, status="allocated",
        )
        bk2 = Booking.objects.create(
            allocation=alloc2, date=TEST_DATE, timeslot=self.slot_1000,
            room=self.room2, status="scheduled", snapshot_therapy_name=self.therapy.therapy_name,
        )
        rb2 = RoomBooking.objects.create(
            room=self.room2, date=TEST_DATE, time_slot=self.slot_1000,
            therapy_name=self.therapy.therapy_name, patient_id=self.patient.id,
            visit=bk2, therapy=None, status="BOOKED",
        )

        req = self.rf.post(
            "/sheduling/therapy-entry/?action=cancel_therapy",
            data=json.dumps({
                "allocation_id": alloc1.id,
                "cancel_from": TEST_DATE.isoformat(),
                "cancel_to": TEST_DATE.isoformat(),
                "reason": "Cancel morning slot only",
            }),
            content_type="application/json",
        )
        req.user = self.user
        resp = therapy_entry(req)
        self.assertEqual(resp.status_code, 200)

        rb2.refresh_from_db()
        bk2.refresh_from_db()
        self.assertEqual(rb2.status, "BOOKED")
        self.assertEqual(bk2.status, "scheduled")
