import json
from datetime import date, time, timedelta
from django.test import TestCase, Client
from django.contrib.auth import get_user_model

from masters.models import (
    SlotMaster,
    TherapistMaster,
    TherapistGrade,
    TherapyMaster,
)
from Patient.models import TreatmentRoom, RoomName, TherapistBooking, Therapist, RoomBooking
from Sheduling.models import (
    PatientSnapshot,
    TherapyAllocation,
    Booking,
    BookingAssignment,
    BookingRescheduleHistory,
    SchedulingAuditLog
)
from reshedule import attempt_allocate_slot, allocate_therapists

User = get_user_model()


class TestRescheduleBugFixes(TestCase):
    def setUp(self):
        from authentication.models import Module
        Module.objects.get_or_create(name="therapy_scheduling", defaults={"display_name": "Therapy Scheduling", "is_active": True})
        self.client = Client()
        self.user = User.objects.create_user(username="resched_tester", password="password123", role="super_admin")
        self.client.force_login(self.user)

        self.patient = PatientSnapshot.objects.create(
            pat_reg_no="IP-RESCHED-001",
            pat_name="Reschedule Test Patient",
            pat_sex="Male",
            pat_age="40",
            pat_room_no="DS-2"
        )

        self.grade_senior, _ = TherapistGrade.objects.get_or_create(name="Senior Therapist")
        self.grade_junior, _ = TherapistGrade.objects.get_or_create(name="Junior Therapist")

        self.room_name1, _ = RoomName.objects.get_or_create(name="Treatment Room 1")
        self.room1, _ = TreatmentRoom.objects.get_or_create(
            room_no="TR-1",
            defaults={"room_name": self.room_name1, "is_active": True}
        )

        self.slot1, _ = SlotMaster.objects.get_or_create(
            slot_number=2,
            defaults={"slot_time": time(8, 30), "is_active": True}
        )
        self.slot2, _ = SlotMaster.objects.get_or_create(
            slot_number=3,
            defaults={"slot_time": time(10, 0), "is_active": True}
        )

        self.therapy, _ = TherapyMaster.objects.get_or_create(
            therapy_code="TH-RESCHED-01",
            defaults={
                "therapy_name": "General Therapy Test",
                "total_no_of_therapist": 1,
                "no_of_senior_therapist": 0,
                "no_of_junior_therapist": 1,
                "no_of_trainee_therapist": 0,
                "no_of_super_senior_therapist": 0,
            }
        )

        self.tm1 = TherapistMaster.objects.create(
            therapist_code="TH_R1",
            therapist_name="Therapist One",
            therapist_gender="Male",
            therapist_grade=self.grade_junior,
            is_active=True
        )

    def test_simulation_mode_does_not_mutate_booking_status(self):
        """
        Verify that calling attempt_allocate_slot with create_bookings=False
        does NOT mutate booking.status to 'scheduled' or alter timeslot/room in DB.
        """
        target_date = date.today() + timedelta(days=2)
        alloc = TherapyAllocation.objects.create(
            patient=self.patient,
            therapy_code=self.therapy.therapy_code,
            therapy_name=self.therapy.therapy_name,
            from_date=target_date,
            to_date=target_date,
            days=1,
            status="failed"
        )
        booking = Booking.objects.create(
            allocation=alloc,
            date=target_date,
            status="failed",
            failure_reason="therapist_unavailable"
        )

        therapy_reqs = {
            "total": 1,
            "senior": 0,
            "junior": 1,
            "trainee": 0,
            "super_senior": 0
        }

        task, success, err = attempt_allocate_slot(
            allocation=alloc,
            booking=booking,
            date=target_date,
            canonical_slot=self.slot1,
            therapy_req=therapy_reqs,
            needs_room_flag=True,
            needs_bath_flag=False,
            used_slots=[],
            create_bookings=False,  # Simulation mode!
            patient_id=self.patient.id,
            last_allocation=None,
            AllocationAttempt=None
        )

        self.assertTrue(success, f"Simulation should succeed, got error: {err}")
        booking.refresh_from_db()
        self.assertEqual(booking.status, "failed", "Booking status should NOT be mutated to scheduled when create_bookings=False!")
        self.assertEqual(booking.failure_reason, "therapist_unavailable")
        self.assertIsNone(booking.timeslot)

    def test_reschedule_api_records_scheduling_audit_log(self):
        """
        Verify that reschedule_therapy_api records a SchedulingAuditLog row with change_type='reschedule'
        without encountering NameError: SchedulingAuditLog.
        """
        target_date = date.today() + timedelta(days=3)
        alloc = TherapyAllocation.objects.create(
            patient=self.patient,
            therapy_code=self.therapy.therapy_code,
            therapy_name=self.therapy.therapy_name,
            from_date=target_date,
            to_date=target_date,
            days=1,
            status="failed"
        )
        booking = Booking.objects.create(
            allocation=alloc,
            date=target_date,
            status="failed",
            failure_reason="therapist_unavailable"
        )

        payload = {
            "allocation_id": alloc.id,
            "date": target_date.strftime("%Y-%m-%d"),
            "target_slot_id": self.slot1.id
        }

        resp = self.client.post(
            "/sheduling/scheduling/api/reschedule-therapy/",
            data=json.dumps(payload),
            content_type="application/json"
        )
        self.assertEqual(resp.status_code, 200, f"API error: {resp.content}")

        audit_log = SchedulingAuditLog.objects.filter(booking=booking, change_type="reschedule").first()
        self.assertIsNotNone(audit_log, "SchedulingAuditLog record must be created on single reschedule!")
        self.assertEqual(audit_log.patient_name, self.patient.pat_name)

    def test_allocate_therapists_can_assign_therapist_symbol_exists(self):
        """
        Verify allocate_therapists executes without NameError: can_assign_therapist
        when bathing therapist is requested.
        """
        target_date = date.today() + timedelta(days=5)
        therapy_reqs = {
            "total": 1,
            "senior": 0,
            "junior": 1,
            "trainee": 0,
            "super_senior": 0
        }
        result = allocate_therapists(
            date=target_date,
            time_slot=self.slot1,
            therapy_requirements=therapy_reqs,
            needs_bathing=True,
            patient_gender="Male",
            patient_id=self.patient.id
        )
        self.assertIsNotNone(result)
