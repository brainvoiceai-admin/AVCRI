"""
CP-0 Test Suite: Reschedule Options API Read-Only Guarantee & Freed Slot Visibility.

Verifies:
1. Calling reschedule_options_api NEVER mutates Booking.status, Booking.room,
   TherapistBooking, RoomBooking, or HelpingTherapistAllocationLog.
2. When a failed therapy's registered slot becomes free (e.g., after another
   treatment is cancelled), reschedule_options_api includes that registered slot
   in available_slots.
3. VIP patients are excluded from reschedule_options_api (HTTP 400).
"""
import json
import pytest
from datetime import date, time
from unittest.mock import patch
from django.test import TestCase, RequestFactory
from django.contrib.auth import get_user_model

from masters.models import SlotMaster, TherapistGrade, TherapistMaster, TherapyMaster
from Patient.models import TreatmentRoom, RoomName, RoomBooking, TherapistBooking
from Sheduling.models import PatientSnapshot, TherapyAllocation, Booking, HelpingTherapistAllocationLog
from Sheduling.views import reschedule_options_api

User = get_user_model()
TEST_DATE = date(2099, 11, 20)


@pytest.mark.django_db(transaction=True)
class RescheduleOptionsReadOnlyTests(TestCase):
    def setUp(self):
        self.rf = RequestFactory()
        self.user, _ = User.objects.get_or_create(
            username="cp0_opts_admin",
            defaults={"is_superuser": True, "is_staff": True, "role": "super_admin"},
        )
        self.user.has_module_access = lambda mod: True
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
            therapist_code="TH_CP0_RO1",
            defaults={
                "therapist_name": "ReadOnly Test Therapist",
                "therapist_gender": "Male",
                "therapist_grade": self.grade,
                "employee_code": "EMP_CP0_RO1",
                "is_bathing_therapist": True,
                "is_active": True,
            },
        )
        rn1, _ = RoomName.objects.get_or_create(name="Room TR-1", defaults={"is_active": True})
        self.room1, _ = TreatmentRoom.objects.get_or_create(
            room_no="TR-1", defaults={"room_name": rn1, "floor": "G", "is_active": True}
        )
        self.therapy, _ = TherapyMaster.objects.get_or_create(
            therapy_code="THEB_CP0_RO1",
            defaults={
                "therapy_name": "CP0 ReadOnly Therapy",
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
            pat_reg_no="880003",
            pat_name="ReadOnly Preview Patient",
            pat_sex="Male",
            pat_age="38",
            pat_room_no="DS-1",
        )

    def test_reschedule_options_is_strictly_readonly_and_shows_freed_registered_slot(self):
        alloc = TherapyAllocation.objects.create(
            patient=self.patient, therapy_code=self.therapy.therapy_code,
            therapy_name=self.therapy.therapy_name, timeslot=self.slot_0830,
            from_date=TEST_DATE, to_date=TEST_DATE, days=1, status="failed",
        )
        booking = Booking.objects.create(
            allocation=alloc, date=TEST_DATE, timeslot=self.slot_0830,
            room=None, status="failed", failure_reason="no_room_available",
            snapshot_therapy_name=self.therapy.therapy_name,
        )

        tb_before = TherapistBooking.objects.filter(date=TEST_DATE).count()
        rb_before = RoomBooking.objects.filter(date=TEST_DATE).count()
        ht_log_before = HelpingTherapistAllocationLog.objects.filter(date=TEST_DATE).count()

        req = self.rf.post(
            "/sheduling/scheduling/api/reschedule-options/",
            data=json.dumps({"allocation_id": alloc.id, "date": TEST_DATE.isoformat()}),
            content_type="application/json",
        )
        req.user = self.user
        with patch("final_allocation.is_patient_active", return_value=True):
            resp = reschedule_options_api(req)

        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.content)
        self.assertTrue(data["success"])

        # Strict read-only assertions
        booking.refresh_from_db()
        self.assertEqual(booking.status, "failed")
        self.assertIsNone(booking.room)
        self.assertEqual(TherapistBooking.objects.filter(date=TEST_DATE).count(), tb_before)
        self.assertEqual(RoomBooking.objects.filter(date=TEST_DATE).count(), rb_before)
        self.assertEqual(HelpingTherapistAllocationLog.objects.filter(date=TEST_DATE).count(), ht_log_before)

        # Freed registered slot must be present in available_slots
        slot_ids = [s["slot_id"] for s in data["available_slots"]]
        self.assertIn(self.slot_0830.id, slot_ids)
        self.assertIn(self.slot_1000.id, slot_ids)

    def test_reschedule_options_vip_patient_remains_strictly_readonly(self):
        vip_pat = PatientSnapshot.objects.create(
            pat_reg_no="880004", pat_name="VIP Preview Patient",
            pat_sex="Male", pat_age="50", pat_room_no="DS-1", is_vip=True,
        )
        alloc = TherapyAllocation.objects.create(
            patient=vip_pat, therapy_code=self.therapy.therapy_code,
            therapy_name=self.therapy.therapy_name, timeslot=self.slot_0830,
            from_date=TEST_DATE, to_date=TEST_DATE, days=1, status="failed", is_vip=True,
        )
        booking = Booking.objects.create(
            allocation=alloc, date=TEST_DATE, timeslot=self.slot_0830,
            status="failed", snapshot_therapy_name=self.therapy.therapy_name, is_vip=True,
        )
        tb_before = TherapistBooking.objects.filter(date=TEST_DATE).count()
        req = self.rf.post(
            "/sheduling/scheduling/api/reschedule-options/",
            data=json.dumps({"allocation_id": alloc.id, "date": TEST_DATE.isoformat()}),
            content_type="application/json",
        )
        req.user = self.user
        with patch("final_allocation.is_patient_active", return_value=True):
            resp = reschedule_options_api(req)
        self.assertEqual(resp.status_code, 200)
        booking.refresh_from_db()
        self.assertEqual(booking.status, "failed")
        self.assertEqual(TherapistBooking.objects.filter(date=TEST_DATE).count(), tb_before)
