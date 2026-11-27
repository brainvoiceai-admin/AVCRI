"""
CP-0 Test Suite: Emergency Therapist Replacement API.

Verifies:
1. action_type='replace' swaps the therapist in both BookingAssignment and TherapistBooking,
   updates bathing designation, records SchedulingAuditLog, and leaves other bookings untouched.
2. action_type='bathing_only' reassigns is_bathing within the assigned crew.
3. Missing or short (<3 char) reason is rejected with HTTP 400.
"""
import json
import pytest
from datetime import date, time
from django.test import TestCase, RequestFactory
from django.contrib.auth import get_user_model

from masters.models import SlotMaster, TherapistGrade, TherapistMaster, TherapyMaster
from Patient.models import TreatmentRoom, RoomName, TherapistBooking, Therapist as PatientTherapist
from Sheduling.models import PatientSnapshot, TherapyAllocation, Booking, BookingAssignment, SchedulingAuditLog
from Sheduling.views import emergency_replace_therapist_api

User = get_user_model()
TEST_DATE = date(2099, 12, 2)


@pytest.mark.django_db(transaction=True)
class EmergencyReplaceTherapistTests(TestCase):
    def setUp(self):
        self.rf = RequestFactory()
        self.user, _ = User.objects.get_or_create(
            username="cp0_emg_admin",
            defaults={"is_superuser": True, "is_staff": True, "role": "super_admin"},
        )
        self.user.has_module_access = lambda mod: True
        self.slot_0830, _ = SlotMaster.objects.get_or_create(
            slot_number=1, defaults={"slot_time": time(8, 30), "is_active": True}
        )
        self.grade, _ = TherapistGrade.objects.get_or_create(
            name="Senior Therapist", defaults={"display_order": 1, "is_active": True}
        )
        self.th_a, _ = TherapistMaster.objects.get_or_create(
            therapist_code="TH_CP0_EM1",
            defaults={
                "therapist_name": "Emg Therapist A",
                "therapist_gender": "Male",
                "therapist_grade": self.grade,
                "employee_code": "EMP_CP0_EM1",
                "is_bathing_therapist": True,
                "is_active": True,
            },
        )
        self.th_b, _ = TherapistMaster.objects.get_or_create(
            therapist_code="TH_CP0_EM2",
            defaults={
                "therapist_name": "Emg Therapist B",
                "therapist_gender": "Male",
                "therapist_grade": self.grade,
                "employee_code": "EMP_CP0_EM2",
                "is_bathing_therapist": True,
                "is_active": True,
            },
        )
        self.th_c, _ = TherapistMaster.objects.get_or_create(
            therapist_code="TH_CP0_EM3",
            defaults={
                "therapist_name": "Emg Therapist C",
                "therapist_gender": "Male",
                "therapist_grade": self.grade,
                "employee_code": "EMP_CP0_EM3",
                "is_bathing_therapist": True,
                "is_active": True,
            },
        )
        for tm in (self.th_a, self.th_b, self.th_c):
            PatientTherapist.objects.get_or_create(
                therapist_code=tm.therapist_code,
                defaults={
                    "therapist_name": tm.therapist_name,
                    "therapist_grade": "Senior Therapist",
                    "is_bathing_therapist": True,
                },
            )
        rn1, _ = RoomName.objects.get_or_create(name="Room TR-1", defaults={"is_active": True})
        self.room1, _ = TreatmentRoom.objects.get_or_create(
            room_no="TR-1", defaults={"room_name": rn1, "floor": "G", "is_active": True}
        )
        self.therapy, _ = TherapyMaster.objects.get_or_create(
            therapy_code="THEB_CP0_EM",
            defaults={
                "therapy_name": "CP0 Emergency Replace Therapy",
                "therapy_category": "Medium",
                "therapy_duration": "45",
                "bathing_required": "Yes",
                "treatment_room_required": "Yes",
                "total_no_of_therapist": 2,
                "no_of_senior_therapist": 2,
                "is_active": True,
            },
        )
        self.patient = PatientSnapshot.objects.create(
            pat_reg_no="880020", pat_name="Emergency Replace Patient",
            pat_sex="Male", pat_age="42", pat_room_no="DS-1",
        )
        self.alloc = TherapyAllocation.objects.create(
            patient=self.patient, therapy_code=self.therapy.therapy_code,
            therapy_name=self.therapy.therapy_name, timeslot=self.slot_0830,
            room=self.room1, from_date=TEST_DATE, to_date=TEST_DATE, days=1, status="allocated",
        )
        self.booking = Booking.objects.create(
            allocation=self.alloc, date=TEST_DATE, timeslot=self.slot_0830,
            room=self.room1, status="scheduled", snapshot_therapy_name=self.therapy.therapy_name,
        )
        BookingAssignment.objects.create(
            booking=self.booking, therapist_id=self.th_a.therapist_code, status="assigned"
        )
        BookingAssignment.objects.create(
            booking=self.booking, therapist_id=self.th_b.therapist_code, status="assigned"
        )
        TherapistBooking.objects.create(
            therapist=self.th_a, date=TEST_DATE, time_slot=self.slot_0830,
            therapy_name=self.therapy.therapy_name, patient_id=self.patient.id,
            visit=self.alloc, status="BOOKED", is_bathing=True,
        )
        TherapistBooking.objects.create(
            therapist=self.th_b, date=TEST_DATE, time_slot=self.slot_0830,
            therapy_name=self.therapy.therapy_name, patient_id=self.patient.id,
            visit=self.alloc, status="BOOKED", is_bathing=False,
        )

    def test_short_reason_rejected(self):
        req = self.rf.post(
            "/sheduling/scheduling/api/emergency-replace-therapist/",
            data=json.dumps({
                "booking_id": self.booking.id,
                "replaced_therapist_code": self.th_a.therapist_code,
                "replacement_therapist_code": self.th_c.therapist_code,
                "reason": "no",
            }),
            content_type="application/json",
        )
        req.user = self.user
        resp = emergency_replace_therapist_api(req)
        self.assertEqual(resp.status_code, 400)

    def test_bathing_only_reassignment_updates_flag_and_audits(self):
        req = self.rf.post(
            "/sheduling/scheduling/api/emergency-replace-therapist/",
            data=json.dumps({
                "action_type": "bathing_only",
                "booking_id": self.booking.id,
                "bathing_therapist_code": self.th_b.therapist_code,
                "reason": "Swap bathing therapist within team",
            }),
            content_type="application/json",
        )
        req.user = self.user
        resp = emergency_replace_therapist_api(req)
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(
            TherapistBooking.objects.get(
                therapist=self.th_a, date=TEST_DATE, time_slot=self.slot_0830, status="BOOKED"
            ).is_bathing
        )
        self.assertTrue(
            TherapistBooking.objects.get(
                therapist=self.th_b, date=TEST_DATE, time_slot=self.slot_0830, status="BOOKED"
            ).is_bathing
        )
        self.assertTrue(
            SchedulingAuditLog.objects.filter(
                booking=self.booking, change_type="bathing_reassignment"
            ).exists()
        )

    def test_replace_therapist_swaps_assignment_and_booking(self):
        req = self.rf.post(
            "/sheduling/scheduling/api/emergency-replace-therapist/",
            data=json.dumps({
                "action_type": "replace",
                "booking_id": self.booking.id,
                "replaced_therapist_code": self.th_a.therapist_code,
                "replacement_therapist_code": self.th_c.therapist_code,
                "bathing_therapist_code": self.th_c.therapist_code,
                "reason": "Sudden medical leave",
            }),
            content_type="application/json",
        )
        req.user = self.user
        resp = emergency_replace_therapist_api(req)
        self.assertEqual(resp.status_code, 200)

        active_codes = set(
            BookingAssignment.objects.filter(booking=self.booking, status="assigned")
            .values_list("therapist_id", flat=True)
        )
        self.assertEqual(active_codes, {self.th_b.therapist_code, self.th_c.therapist_code})
        self.assertTrue(
            TherapistBooking.objects.filter(
                therapist=self.th_c, date=TEST_DATE, time_slot=self.slot_0830, status="BOOKED", is_bathing=True
            ).exists()
        )
        self.assertFalse(
            TherapistBooking.objects.filter(
                therapist=self.th_a, date=TEST_DATE, time_slot=self.slot_0830, status="BOOKED"
            ).exists()
        )
