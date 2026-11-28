"""
BUG-4B Regression Test Suite: Therapy Foreign-Key Consistency.

Covers:
1. Rescheduling (`allocate_therapy_for_visit`) creates `TherapistBooking` with `TherapyMaster` FK populated.
2. Rescheduling (`allocate_therapy_for_visit`) creates `RoomBooking` with `TherapyAllocation` FK populated.
3. `create_room_booking_safe(..., visit=booking)` without explicit `therapy_allocation` derives `booking.allocation`.
4. Scheduling alternative-room fallback populates `RoomBooking.therapy`.
5. Explicitly supplied `therapy_allocation` takes precedence over `visit.allocation`.
6. Existing `RoomBooking` rows with `therapy=None` are backfilled safely (both `get_or_create` and
   `IntegrityError` recovery paths), without overwriting an existing `RoomBooking` belonging to another allocation.
7. Invalid or missing `visit.allocation` does not assign an invalid FK or raise.
"""

from datetime import date, time
from unittest.mock import PropertyMock, patch

import pytest
from django.db import IntegrityError
from django.test import TestCase

from Patient.models import RoomBooking, RoomName, TherapistBooking, TreatmentRoom
from Sheduling.models import Booking, PatientSnapshot, TherapyAllocation
from allocation_engine.core.primitives.booking_persistence import create_room_booking_safe
from allocation_engine.scheduling.visit_allocator import (
    create_room_booking_safe as scheduling_create_room_booking_safe,
    expand_therapies_for_visit as scheduling_expand_therapies_for_visit,
)
from masters.models import SlotMaster, TherapistGrade, TherapistMaster, TherapyMaster
from reshedule import allocate_therapy_for_visit


TARGET_DATE = date(2099, 11, 12)


@pytest.mark.django_db(transaction=True)
class BookingTherapyFKConsistencyTests(TestCase):
    def setUp(self):
        self.slot_0830, _ = SlotMaster.objects.get_or_create(
            slot_number=51, defaults={"slot_time": time(8, 30), "is_active": True}
        )
        if self.slot_0830.slot_time != time(8, 30):
            self.slot_0830.slot_time = time(8, 30)
            self.slot_0830.save(update_fields=["slot_time"])

        self.slot_1000, _ = SlotMaster.objects.get_or_create(
            slot_number=52, defaults={"slot_time": time(10, 0), "is_active": True}
        )
        if self.slot_1000.slot_time != time(10, 0):
            self.slot_1000.slot_time = time(10, 0)
            self.slot_1000.save(update_fields=["slot_time"])

        self.grade, _ = TherapistGrade.objects.get_or_create(
            name="Senior Therapist", defaults={"display_order": 2, "is_active": True}
        )
        self.therapist, _ = TherapistMaster.objects.get_or_create(
            therapist_code="TH_B4B_01",
            defaults={
                "therapist_name": "BUG4B Therapist",
                "therapist_gender": "Male",
                "therapist_grade": self.grade,
                "employee_code": "EMP_B4B_01",
                "is_bathing_therapist": True,
                "is_helping_therapist": False,
                "is_active": True,
            },
        )
        rn1, _ = RoomName.objects.get_or_create(name="Room TR-1", defaults={"is_active": True})
        rn2, _ = RoomName.objects.get_or_create(name="Room TR-2", defaults={"is_active": True})
        self.room1, _ = TreatmentRoom.objects.get_or_create(
            room_no="TR-1", defaults={"room_name": rn1, "floor": "G", "is_active": True}
        )
        self.room2, _ = TreatmentRoom.objects.get_or_create(
            room_no="TR-2", defaults={"room_name": rn2, "floor": "G", "is_active": True}
        )
        self.therapy, _ = TherapyMaster.objects.get_or_create(
            therapy_code="THEB_BUG4B",
            defaults={
                "therapy_name": "BUG4B FK Consistency Therapy",
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
            pat_reg_no="884101",
            pat_name="BUG4B Patient",
            pat_sex="Male",
            pat_age="41",
            pat_room_no="DS-1",
        )
        self.other_patient = PatientSnapshot.objects.create(
            pat_reg_no="884102",
            pat_name="BUG4B Other Patient",
            pat_sex="Male",
            pat_age="39",
            pat_room_no="DS-2",
        )

    def _make_alloc_and_booking(self, patient=None, slot=None, status="failed"):
        patient = patient or self.patient
        slot = slot or self.slot_0830
        alloc = TherapyAllocation.objects.create(
            patient=patient,
            therapy_code=self.therapy.therapy_code,
            therapy_name=self.therapy.therapy_name,
            timeslot=slot,
            from_date=TARGET_DATE,
            to_date=TARGET_DATE,
            days=1,
            status=status,
        )
        booking = Booking.objects.create(
            allocation=alloc,
            date=TARGET_DATE,
            timeslot=slot,
            status=status,
            snapshot_therapy_name=self.therapy.therapy_name,
        )
        return alloc, booking

    def test_rescheduling_populates_therapist_booking_and_room_booking_therapy_fks(self):
        """1 & 2: Rescheduling populates TherapistBooking.therapy (TherapyMaster) and RoomBooking.therapy (TherapyAllocation)."""
        alloc, _booking = self._make_alloc_and_booking(status="failed")

        with patch("reshedule.is_patient_active", return_value=True):
            tasks = allocate_therapy_for_visit(alloc.id, TARGET_DATE, create_bookings=True)

        self.assertTrue(isinstance(tasks, list) and len(tasks) >= 1)
        self.assertEqual(tasks[0]["status"], "BOOKED")

        tb = TherapistBooking.objects.filter(visit=alloc, date=TARGET_DATE, status="BOOKED").first()
        self.assertIsNotNone(tb)
        self.assertEqual(tb.therapy_id, self.therapy.pk)

        rb = RoomBooking.objects.filter(visit__allocation=alloc, date=TARGET_DATE, status="BOOKED").first()
        self.assertIsNotNone(rb)
        self.assertEqual(rb.therapy_id, alloc.pk)

    def test_create_room_booking_safe_derives_allocation_from_visit(self):
        """3: Calling create_room_booking_safe(..., visit=booking) without therapy_allocation derives booking.allocation."""
        alloc, booking = self._make_alloc_and_booking(status="draft")

        rb, created = create_room_booking_safe(
            self.room1,
            TARGET_DATE,
            self.slot_0830,
            self.therapy.therapy_name,
            self.patient.id,
            booking,
        )

        self.assertTrue(created)
        self.assertIsNotNone(rb)
        rb.refresh_from_db()
        self.assertEqual(rb.visit_id, booking.pk)
        self.assertEqual(rb.therapy_id, alloc.pk)

    def test_alternative_room_fallback_populates_room_booking_therapy_fk(self):
        """4: Scheduling alternative-room fallback in visit_allocator populates RoomBooking.therapy."""
        alloc, booking = self._make_alloc_and_booking(status="draft")
        other_alloc, other_booking = self._make_alloc_and_booking(patient=self.other_patient, status="scheduled")

        call_state = {"count": 0}

        def fake_create_room_booking(room, dt, ts, th_name, pid, visit):
            call_state["count"] += 1
            if call_state["count"] == 1:
                # Simulate race where TR-1 was booked just before create_room_booking_safe ran
                existing_rb = RoomBooking.objects.create(
                    room=room,
                    date=dt,
                    time_slot=ts,
                    therapy_name=th_name,
                    patient_id=self.other_patient.id,
                    visit=other_booking,
                    therapy=other_alloc,
                    status="BOOKED",
                )
                return existing_rb, False
            return scheduling_create_room_booking_safe(room, dt, ts, th_name, pid, visit)

        with patch("final_allocation.is_patient_active", return_value=True), patch(
            "allocation_engine.scheduling.visit_allocator.create_room_booking_safe",
            side_effect=fake_create_room_booking,
        ):
            tasks = scheduling_expand_therapies_for_visit(alloc.id, TARGET_DATE, create_bookings=True)

        self.assertEqual(call_state["count"], 2)
        self.assertEqual(tasks[0]["status"], "BOOKED")
        self.assertEqual(tasks[0]["room_no"], "TR-2")

        fallback_rb = RoomBooking.objects.filter(
            room=self.room2, date=TARGET_DATE, time_slot=self.slot_0830, status="BOOKED"
        ).first()
        self.assertIsNotNone(fallback_rb)
        self.assertEqual(fallback_rb.visit_id, booking.pk)
        self.assertEqual(fallback_rb.therapy_id, alloc.pk)

    def test_explicit_therapy_allocation_takes_precedence_over_visit_allocation(self):
        """5: Explicitly supplied therapy_allocation overrides visit.allocation derivation."""
        _alloc1, booking1 = self._make_alloc_and_booking(status="draft")
        explicit_alloc, _booking2 = self._make_alloc_and_booking(slot=self.slot_1000, status="draft")

        rb, created = create_room_booking_safe(
            self.room1,
            TARGET_DATE,
            self.slot_0830,
            self.therapy.therapy_name,
            self.patient.id,
            booking1,
            therapy_allocation=explicit_alloc,
        )

        self.assertTrue(created)
        rb.refresh_from_db()
        self.assertEqual(rb.therapy_id, explicit_alloc.pk)

    def test_existing_room_booking_missing_therapy_fk_backfilled_without_overwriting_other(self):
        """6a: Existing RoomBooking with therapy=None is backfilled safely; existing owned RoomBooking is preserved."""
        alloc1, booking1 = self._make_alloc_and_booking(status="draft")
        other_alloc, other_booking = self._make_alloc_and_booking(patient=self.other_patient, status="scheduled")

        # Existing row with missing therapy FK
        rb_missing = RoomBooking.objects.create(
            room=self.room1,
            date=TARGET_DATE,
            time_slot=self.slot_0830,
            therapy_name=self.therapy.therapy_name,
            patient_id=self.patient.id,
            visit=booking1,
            therapy=None,
            status="BOOKED",
        )
        rb_out, created = create_room_booking_safe(
            self.room1, TARGET_DATE, self.slot_0830, self.therapy.therapy_name, self.patient.id, booking1
        )
        self.assertFalse(created)
        self.assertEqual(rb_out.pk, rb_missing.pk)
        rb_missing.refresh_from_db()
        self.assertEqual(rb_missing.therapy_id, alloc1.pk)

        # Existing row already owned by another booking/allocation must NOT be overwritten
        rb_other = RoomBooking.objects.create(
            room=self.room2,
            date=TARGET_DATE,
            time_slot=self.slot_0830,
            therapy_name=self.therapy.therapy_name,
            patient_id=self.other_patient.id,
            visit=other_booking,
            therapy=other_alloc,
            status="BOOKED",
        )
        rb_conflict, created2 = create_room_booking_safe(
            self.room2, TARGET_DATE, self.slot_0830, self.therapy.therapy_name, self.patient.id, booking1
        )
        self.assertFalse(created2)
        self.assertEqual(rb_conflict.pk, rb_other.pk)
        rb_other.refresh_from_db()
        self.assertEqual(rb_other.visit_id, other_booking.pk)
        self.assertEqual(rb_other.therapy_id, other_alloc.pk)

    def test_integrity_error_recovery_backfills_missing_room_booking_therapy_fk(self):
        """6b: IntegrityError recovery path populates missing RoomBooking.therapy FK."""
        alloc, booking = self._make_alloc_and_booking(status="draft")
        existing = RoomBooking.objects.create(
            room=self.room1,
            date=TARGET_DATE,
            time_slot=self.slot_1000,
            therapy_name=self.therapy.therapy_name,
            patient_id=self.patient.id,
            visit=None,
            therapy=None,
            status="BOOKED",
        )

        with patch.object(RoomBooking.objects, "get_or_create", side_effect=IntegrityError("simulated duplicate")):
            rb_recovered, created = create_room_booking_safe(
                self.room1, TARGET_DATE, self.slot_1000, self.therapy.therapy_name, self.patient.id, booking
            )

        self.assertFalse(created)
        self.assertEqual(rb_recovered.pk, existing.pk)
        existing.refresh_from_db()
        self.assertEqual(existing.visit_id, booking.pk)
        self.assertEqual(existing.therapy_id, alloc.pk)

    def test_invalid_or_missing_visit_allocation_does_not_assign_invalid_fk(self):
        """7: visit=None or invalid visit.allocation does not fail or assign an invalid FK."""
        rb1, created1 = create_room_booking_safe(
            self.room1, TARGET_DATE, self.slot_0830, self.therapy.therapy_name, self.patient.id, None
        )
        self.assertTrue(created1)
        rb1.refresh_from_db()
        self.assertIsNone(rb1.therapy_id)

        # Dummy object with non-TherapyAllocation .allocation attribute; pass visit=None vs mock attr via invalid therapy_allocation
        rb2, created2 = create_room_booking_safe(
            self.room2,
            TARGET_DATE,
            self.slot_0830,
            self.therapy.therapy_name,
            self.patient.id,
            None,
            therapy_allocation="not_an_allocation",
        )
        self.assertTrue(created2)
        rb2.refresh_from_db()
        self.assertIsNone(rb2.therapy_id)

        # Real persisted Booking whose .allocation evaluates to None or non-TherapyAllocation
        _alloc_real, booking_real = self._make_alloc_and_booking(slot=self.slot_1000, status="draft")
        with patch.object(Booking, "allocation", new_callable=PropertyMock, return_value=None):
            rb3, created3 = create_room_booking_safe(
                self.room1, TARGET_DATE, self.slot_1000, self.therapy.therapy_name, self.patient.id, booking_real
            )
        self.assertTrue(created3)
        rb3.refresh_from_db()
        self.assertEqual(rb3.visit_id, booking_real.pk)
        self.assertIsNone(rb3.therapy_id)

        with patch.object(Booking, "allocation", new_callable=PropertyMock, return_value="invalid_allocation_str"):
            rb4, created4 = create_room_booking_safe(
                self.room2,
                TARGET_DATE,
                self.slot_1000,
                self.therapy.therapy_name,
                self.patient.id,
                booking_real,
            )
        self.assertTrue(created4)
        rb4.refresh_from_db()
        self.assertEqual(rb4.visit_id, booking_real.pk)
        self.assertIsNone(rb4.therapy_id)
