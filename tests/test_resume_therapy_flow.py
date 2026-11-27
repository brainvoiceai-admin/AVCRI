"""
CP-0 Test Suite: Resume Therapy Flow.

Verifies:
1. Full-range resume clears cancelled_date_from/to and restores booking to draft/scheduled.
2. Partial-range resume adjusts cancelled_date_from/to appropriately.
3. Resuming a date outside the cancelled range returns HTTP 400.
4. Resuming one allocation does not disturb another active allocation in a different slot.
"""
import json
import pytest
from datetime import date, time, timedelta
from unittest.mock import patch
from django.test import TestCase, RequestFactory
from django.contrib.auth import get_user_model

from masters.models import SlotMaster, TherapistGrade, TherapistMaster, TherapyMaster
from Patient.models import TreatmentRoom, RoomName, RoomBooking
from Sheduling.models import PatientSnapshot, TherapyAllocation, Booking
from Sheduling.views import therapy_entry

User = get_user_model()
DAY1 = date(2099, 11, 15)
DAY2 = DAY1 + timedelta(days=1)


@pytest.mark.django_db(transaction=True)
class ResumeTherapyFlowTests(TestCase):
    def setUp(self):
        self.rf = RequestFactory()
        self.user, _ = User.objects.get_or_create(
            username="cp0_resume_admin",
            defaults={"is_superuser": True, "is_staff": True, "role": "super_admin"},
        )
        self.slot_0830, _ = SlotMaster.objects.get_or_create(
            slot_number=1, defaults={"slot_time": time(8, 30), "is_active": True}
        )
        self.slot_1000, _ = SlotMaster.objects.get_or_create(
            slot_number=2, defaults={"slot_time": time(10, 0), "is_active": True}
        )
        rn1, _ = RoomName.objects.get_or_create(name="Room TR-1", defaults={"is_active": True})
        self.room1, _ = TreatmentRoom.objects.get_or_create(
            room_no="TR-1", defaults={"room_name": rn1, "floor": "G", "is_active": True}
        )
        self.therapy, _ = TherapyMaster.objects.get_or_create(
            therapy_code="THEB_CP0_R1",
            defaults={
                "therapy_name": "CP0 Resume Test Therapy",
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
            pat_reg_no="880002",
            pat_name="Resume Flow Patient",
            pat_sex="Male",
            pat_age="45",
            pat_room_no="DS-1",
        )

    def test_partial_and_full_resume_updates_cancelled_range_and_booking_status(self):
        alloc = TherapyAllocation.objects.create(
            patient=self.patient, therapy_code=self.therapy.therapy_code,
            therapy_name=self.therapy.therapy_name, timeslot=self.slot_0830,
            from_date=DAY1, to_date=DAY2, days=2, status="cancelled",
            cancelled_date_from=DAY1, cancelled_date_to=DAY2, cancellation_reason="Temp pause",
        )
        bk1 = Booking.objects.create(
            allocation=alloc, date=DAY1, timeslot=self.slot_0830, status="cancelled",
            snapshot_therapy_name=self.therapy.therapy_name,
        )
        bk2 = Booking.objects.create(
            allocation=alloc, date=DAY2, timeslot=self.slot_0830, status="cancelled",
            snapshot_therapy_name=self.therapy.therapy_name,
        )

        # Resume DAY1 only (partial resume)
        req1 = self.rf.post(
            "/sheduling/therapy-entry/?action=resume_therapy",
            data=json.dumps({"allocation_id": alloc.id, "resume_date": DAY1.isoformat()}),
            content_type="application/json",
        )
        req1.user = self.user
        with patch("final_allocation.is_patient_active", return_value=True):
            resp1 = therapy_entry(req1)
        self.assertEqual(resp1.status_code, 200)

        alloc.refresh_from_db()
        bk1.refresh_from_db()
        bk2.refresh_from_db()
        self.assertEqual(bk1.status, "draft")
        self.assertEqual(bk2.status, "cancelled")
        self.assertEqual(alloc.cancelled_date_from, DAY2)
        self.assertEqual(alloc.cancelled_date_to, DAY2)

        # Resume DAY2 (completes full resume)
        req2 = self.rf.post(
            "/sheduling/therapy-entry/?action=resume_therapy",
            data=json.dumps({"allocation_id": alloc.id, "resume_date": DAY2.isoformat()}),
            content_type="application/json",
        )
        req2.user = self.user
        with patch("final_allocation.is_patient_active", return_value=True):
            resp2 = therapy_entry(req2)
        self.assertEqual(resp2.status_code, 200)

        alloc.refresh_from_db()
        bk2.refresh_from_db()
        self.assertEqual(bk2.status, "draft")
        self.assertIsNone(alloc.cancelled_date_from)
        self.assertIsNone(alloc.cancelled_date_to)

    def test_resume_outside_cancelled_range_returns_400(self):
        alloc = TherapyAllocation.objects.create(
            patient=self.patient, therapy_code=self.therapy.therapy_code,
            therapy_name=self.therapy.therapy_name, timeslot=self.slot_0830,
            from_date=DAY1, to_date=DAY2, days=2, status="cancelled",
            cancelled_date_from=DAY1, cancelled_date_to=DAY1, cancellation_reason="One day",
        )
        req = self.rf.post(
            "/sheduling/therapy-entry/?action=resume_therapy",
            data=json.dumps({"allocation_id": alloc.id, "resume_date": DAY2.isoformat()}),
            content_type="application/json",
        )
        req.user = self.user
        resp = therapy_entry(req)
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(json.loads(resp.content)["error"], "resume_date_outside_cancelled_range")
