import json
from datetime import date, time, timedelta
from django.test import TestCase, Client
from django.contrib.auth import get_user_model
from django.utils import timezone

from masters.models import (
    SlotMaster,
    TherapistMaster,
    TherapistGrade,
    TherapistLeaveMaster,
    EmergencyLeave,
    TherapyMaster
)
from Patient.models import TreatmentRoom, RoomName, TherapistBooking, Therapist
from Sheduling.models import (
    PatientSnapshot,
    TherapyAllocation,
    Booking,
    BookingAssignment,
    SchedulingAuditLog
)

User = get_user_model()


class TestPatientEmergencyFeverReschedule(TestCase):
    def setUp(self):
        from authentication.models import Module
        Module.objects.get_or_create(name="therapy_scheduling", defaults={"display_name": "Therapy Scheduling", "is_active": True})
        self.client = Client()
        self.user = User.objects.create_user(username="test_scheduler", password="password123", role="super_admin")
        self.client.force_login(self.user)

        self.patient = PatientSnapshot.objects.create(
            pat_reg_no="IP-FEVER-001",
            pat_name="Fever Patient A",
            pat_sex="Male",
            pat_age="45",
            pat_room_no="DS-1"
        )

        # Therapist Grades
        self.grade_senior, _ = TherapistGrade.objects.get_or_create(name="Senior Therapist")
        self.grade_junior, _ = TherapistGrade.objects.get_or_create(name="Junior Therapist")

        # Treatment Rooms
        self.room_name1, _ = RoomName.objects.get_or_create(name="Treatment Room 1")
        self.room1, _ = TreatmentRoom.objects.get_or_create(
            room_no="TR-1",
            defaults={"room_name": self.room_name1, "is_active": True}
        )
        if not self.room1.is_active:
            self.room1.is_active = True
            self.room1.save()

        self.room_name2, _ = RoomName.objects.get_or_create(name="Treatment Room 2")
        self.room2, _ = TreatmentRoom.objects.get_or_create(
            room_no="TR-2",
            defaults={"room_name": self.room_name2, "is_active": True}
        )
        if not self.room2.is_active:
            self.room2.is_active = True
            self.room2.save()

        # Slots: Morning and Afternoon
        # Slot 1: 08:30 (Morning)
        self.morning_slot, _ = SlotMaster.objects.get_or_create(
            slot_number=2,
            defaults={"slot_time": time(8, 30), "is_active": True}
        )
        if self.morning_slot.slot_time != time(8, 30):
            self.morning_slot.slot_time = time(8, 30)
            self.morning_slot.save()

        # Slot 5: 14:30 (Afternoon 1)
        self.afternoon_slot1, _ = SlotMaster.objects.get_or_create(
            slot_number=5,
            defaults={"slot_time": time(14, 30), "is_active": True}
        )
        if self.afternoon_slot1.slot_time != time(14, 30):
            self.afternoon_slot1.slot_time = time(14, 30)
            self.afternoon_slot1.save()

        # Slot 6: 16:00 (Afternoon 2)
        self.afternoon_slot2, _ = SlotMaster.objects.get_or_create(
            slot_number=6,
            defaults={"slot_time": time(16, 0), "is_active": True}
        )
        if self.afternoon_slot2.slot_time != time(16, 0):
            self.afternoon_slot2.slot_time = time(16, 0)
            self.afternoon_slot2.save()

        # Therapy Master
        self.therapy, _ = TherapyMaster.objects.get_or_create(
            therapy_code="TH-FEVER-TEST",
            defaults={
                "therapy_name": "Fever Recovery Treatment",
                "total_no_of_therapist": 2,
                "no_of_junior_therapist": 2,
                "treatment_room_required": "Yes",
                "bathing_required": "No"
            }
        )

        # Therapists
        self.t1 = self._create_therapist("T-FEV-1", "Therapist One", self.grade_junior)
        self.t2 = self._create_therapist("T-FEV-2", "Therapist Two", self.grade_junior)
        self.t3 = self._create_therapist("T-FEV-3", "Therapist Three", self.grade_junior)

    def _create_therapist(self, code, name, grade):
        tm, _ = TherapistMaster.objects.get_or_create(
            therapist_code=code,
            defaults={
                "therapist_name": name,
                "therapist_grade": grade,
                "therapist_gender": "Male",
                "is_active": True,
                "is_helping_therapist": False,
                "is_bathing_therapist": True
            }
        )
        Therapist.objects.get_or_create(
            therapist_code=code,
            defaults={"therapist_name": name, "therapist_grade": grade.name}
        )
        return tm

    def test_workflow_filter_morning_treatments(self):
        """
        Step 1: Verify patient_emergency_filter_treatments_api correctly lists scheduled morning treatments
        and flags morning vs afternoon session.
        """
        target_date = date.today() + timedelta(days=1)
        alloc = TherapyAllocation.objects.create(
            patient=self.patient,
            therapy_code="TH-FEVER-TEST",
            therapy_name="Fever Recovery Treatment",
            timeslot=self.morning_slot,
            room=self.room1,
            from_date=target_date,
            to_date=target_date,
            days=1,
            status="scheduled"
        )
        b_morning = Booking.objects.create(
            allocation=alloc,
            date=target_date,
            timeslot=self.morning_slot,
            room=self.room1,
            status="scheduled"
        )
        # Assign t1 and t2
        pt1 = Therapist.objects.get(therapist_code=self.t1.therapist_code)
        pt2 = Therapist.objects.get(therapist_code=self.t2.therapist_code)
        BookingAssignment.objects.create(
            booking=b_morning,
            therapist=pt1,
            booking_date=target_date,
            booking_timeslot=self.morning_slot,
            status="assigned"
        )
        BookingAssignment.objects.create(
            booking=b_morning,
            therapist=pt2,
            booking_date=target_date,
            booking_timeslot=self.morning_slot,
            status="assigned"
        )

        resp = self.client.get(f"/sheduling/scheduling/api/patient-emergency-filter-treatments/?date={target_date.isoformat()}&only_morning=true")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data.get("success"))
        treatments = data.get("treatments", [])
        self.assertEqual(len(treatments), 1)
        t_data = treatments[0]
        self.assertEqual(t_data["booking_id"], b_morning.id)
        self.assertTrue(t_data["is_morning"])
        self.assertEqual(t_data["session_name"], "Morning")
        self.assertEqual(len(t_data["therapists"]), 2)

    def test_workflow_afternoon_session_rejected_for_fever_reschedule(self):
        """
        Step 2: If a treatment is already in the afternoon, it cannot be rescheduled under morning fever reschedule.
        """
        target_date = date.today() + timedelta(days=2)
        alloc = TherapyAllocation.objects.create(
            patient=self.patient,
            therapy_code="TH-FEVER-TEST",
            therapy_name="Fever Recovery Treatment",
            timeslot=self.afternoon_slot1,
            room=self.room1,
            from_date=target_date,
            to_date=target_date,
            days=1,
            status="scheduled"
        )
        b_afternoon = Booking.objects.create(
            allocation=alloc,
            date=target_date,
            timeslot=self.afternoon_slot1,
            room=self.room1,
            status="scheduled"
        )

        resp = self.client.get(f"/sheduling/scheduling/api/patient-emergency-afternoon-slots/?booking_id={b_afternoon.id}")
        self.assertEqual(resp.status_code, 400)
        data = resp.json()
        self.assertFalse(data.get("success"))
        self.assertIn("already scheduled in an afternoon session", data.get("error", ""))

    def test_workflow_maximum_therapist_match_indicator(self):
        """
        Steps 3, 4, 5:
        Evaluate afternoon slots.
        In afternoon_slot1 (14:30), both T1 and T2 are free -> Match: 2/2 original therapists (Maximum match).
        In afternoon_slot2 (16:00), T2 is booked on another patient -> Match: 1/2 original therapists.
        Verify afternoon_slot1 is marked is_max_match=True!
        """
        target_date = date.today() + timedelta(days=3)
        alloc = TherapyAllocation.objects.create(
            patient=self.patient,
            therapy_code="TH-FEVER-TEST",
            therapy_name="Fever Recovery Treatment",
            timeslot=self.morning_slot,
            room=self.room1,
            from_date=target_date,
            to_date=target_date,
            days=1,
            status="scheduled"
        )
        b_morning = Booking.objects.create(
            allocation=alloc,
            date=target_date,
            timeslot=self.morning_slot,
            room=self.room1,
            status="scheduled"
        )
        pt1 = Therapist.objects.get(therapist_code=self.t1.therapist_code)
        pt2 = Therapist.objects.get(therapist_code=self.t2.therapist_code)
        BookingAssignment.objects.create(booking=b_morning, therapist=pt1, booking_date=target_date, booking_timeslot=self.morning_slot, status="assigned")
        BookingAssignment.objects.create(booking=b_morning, therapist=pt2, booking_date=target_date, booking_timeslot=self.morning_slot, status="assigned")
        TherapistBooking.objects.create(therapist=self.t1, date=target_date, time_slot=self.morning_slot, visit=alloc, status="BOOKED")
        TherapistBooking.objects.create(therapist=self.t2, date=target_date, time_slot=self.morning_slot, visit=alloc, status="BOOKED")

        # Book T2 at afternoon_slot2 (16:00) on a different allocation
        dummy_patient = PatientSnapshot.objects.create(pat_reg_no="IP-DUMMY-99", pat_name="Dummy Patient", pat_sex="Male")
        dummy_alloc = TherapyAllocation.objects.create(patient=dummy_patient, therapy_name="Other Therapy", status="scheduled", from_date=target_date, to_date=target_date, days=1)
        TherapistBooking.objects.create(
            therapist=self.t2,
            date=target_date,
            time_slot=self.afternoon_slot2,
            visit=dummy_alloc,
            status="BOOKED"
        )

        resp = self.client.get(f"/sheduling/scheduling/api/patient-emergency-afternoon-slots/?booking_id={b_morning.id}")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data.get("success"))

        afternoon_slots = data.get("afternoon_slots", [])
        slot1_info = next((s for s in afternoon_slots if s["slot_id"] == self.afternoon_slot1.id), None)
        slot2_info = next((s for s in afternoon_slots if s["slot_id"] == self.afternoon_slot2.id), None)

        self.assertIsNotNone(slot1_info)
        self.assertIsNotNone(slot2_info)

        # Slot 1 (14:30): both T1 and T2 available -> match_count = 2
        self.assertEqual(slot1_info["match_count"], 2)
        self.assertTrue(slot1_info["is_max_match"], "Slot 1 should be marked as maximum match")

        # Slot 2 (16:00): only T1 available -> match_count = 1
        self.assertEqual(slot2_info["match_count"], 1)
        self.assertFalse(slot2_info["is_max_match"], "Slot 2 should not be maximum match when Slot 1 has 2")

    def test_workflow_final_allocation_and_audit_log(self):
        """
        Step 6: Confirm patient emergency reschedule.
        Verify:
        - Timeslot updated to afternoon slot.
        - Previous morning assignments & therapist bookings deleted.
        - New assignments & therapist bookings created for afternoon slot.
        - Retained original therapists kept.
        - Audit log recorded with change_type='patient_emergency_reschedule'.
        """
        target_date = date.today() + timedelta(days=4)
        alloc = TherapyAllocation.objects.create(
            patient=self.patient,
            therapy_code="TH-FEVER-TEST",
            therapy_name="Fever Recovery Treatment",
            timeslot=self.morning_slot,
            room=self.room1,
            from_date=target_date,
            to_date=target_date,
            days=1,
            status="scheduled"
        )
        b_morning = Booking.objects.create(
            allocation=alloc,
            date=target_date,
            timeslot=self.morning_slot,
            room=self.room1,
            status="scheduled"
        )
        pt1 = Therapist.objects.get(therapist_code=self.t1.therapist_code)
        pt2 = Therapist.objects.get(therapist_code=self.t2.therapist_code)
        BookingAssignment.objects.create(booking=b_morning, therapist=pt1, booking_date=target_date, booking_timeslot=self.morning_slot, status="assigned")
        BookingAssignment.objects.create(booking=b_morning, therapist=pt2, booking_date=target_date, booking_timeslot=self.morning_slot, status="assigned")
        TherapistBooking.objects.create(therapist=self.t1, date=target_date, time_slot=self.morning_slot, visit=alloc, status="BOOKED")
        TherapistBooking.objects.create(therapist=self.t2, date=target_date, time_slot=self.morning_slot, visit=alloc, status="BOOKED")

        confirm_payload = {
            "booking_id": b_morning.id,
            "target_slot_id": self.afternoon_slot1.id,
            "target_room_id": self.room1.pk,
            "reason": "Patient had high fever at 08:00 AM; rescheduled to 02:30 PM"
        }

        resp = self.client.post(
            "/sheduling/scheduling/api/patient-emergency-confirm-reschedule/",
            data=json.dumps(confirm_payload),
            content_type="application/json"
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data.get("success"))

        b_morning.refresh_from_db()
        self.assertEqual(b_morning.timeslot, self.afternoon_slot1)
        self.assertEqual(b_morning.status, "scheduled")

        # Verify old morning TherapistBookings were removed
        old_tb = TherapistBooking.objects.filter(visit=alloc, date=target_date, time_slot=self.morning_slot)
        self.assertEqual(old_tb.count(), 0)

        # Verify new afternoon TherapistBookings exist
        new_tb = TherapistBooking.objects.filter(visit=alloc, date=target_date, time_slot=self.afternoon_slot1)
        self.assertEqual(new_tb.count(), 2)

        # Verify new assignments exist at afternoon slot
        new_asgns = BookingAssignment.objects.filter(booking=b_morning, booking_timeslot=self.afternoon_slot1)
        self.assertEqual(new_asgns.count(), 2)
        assigned_codes = {a.therapist.therapist_code for a in new_asgns}
        self.assertEqual(assigned_codes, {self.t1.therapist_code, self.t2.therapist_code})

        # Verify SchedulingAuditLog
        audit = SchedulingAuditLog.objects.filter(booking=b_morning, change_type="patient_emergency_reschedule").first()
        self.assertIsNotNone(audit)
        self.assertEqual(audit.patient_reg_no, self.patient.pat_reg_no)
        self.assertIn("8:30 AM", audit.time_slot_label)
        self.assertIn("2:30 PM", audit.time_slot_label)
        self.assertEqual(audit.reason, "Patient had high fever at 08:00 AM; rescheduled to 02:30 PM")
        self.assertEqual(audit.changed_by, self.user)
