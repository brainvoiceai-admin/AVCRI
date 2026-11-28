"""
BUG-6 Regression Test Suite: Missing TherapyMaster Defaults Consistency.

Verifies that scheduling and rescheduling consistently require 1 therapist by
default (default_total_if_missing=1) when a TherapyMaster row is missing,
while preserving mapped zero-therapist treatments (total_no_of_therapist=0)
and wheelchair bathing_therapists_count overrides.
"""

from datetime import date, time
from types import SimpleNamespace
from unittest.mock import patch

from django.test import TestCase

import final_allocation
import reshedule
import resheduleMorningandNight
from Patient.models import TherapistBooking
from Sheduling.models import Booking, PatientSnapshot, TherapyAllocation
from allocation_engine.core.primitives.therapy_catalog import (
    therapist_requirements as core_therapist_requirements,
)
from allocation_engine.rescheduling import (
    leave_reassignment,
    options_preview,
    slot_attempter,
    visit_rescheduler,
)
from allocation_engine.scheduling import bulk_allocator, visit_allocator
from masters.models import SlotMaster, TherapistGrade, TherapistMaster, TherapyMaster

TEST_DATE = date(2099, 11, 25)


class MissingTherapyMasterDefaultsTests(TestCase):
    def setUp(self):
        self.slot_0830, _ = SlotMaster.objects.get_or_create(
            slot_number=101,
            defaults={"slot_time": time(8, 30), "is_active": True},
        )
        if self.slot_0830.slot_time != time(8, 30) or not self.slot_0830.is_active:
            self.slot_0830.slot_time = time(8, 30)
            self.slot_0830.is_active = True
            self.slot_0830.save(update_fields=["slot_time", "is_active"])

        self.grade_junior, _ = TherapistGrade.objects.get_or_create(
            name="Junior Therapist",
            defaults={"display_order": 3, "is_active": True},
        )
        self.therapist = TherapistMaster.objects.create(
            therapist_code="TH_BUG6_M1",
            therapist_name="BUG6 Male Therapist",
            therapist_gender="Male",
            therapist_grade=self.grade_junior,
            employee_code="EMP_BUG6_M1",
            is_bathing_therapist=True,
            is_helping_therapist=False,
            is_active=True,
        )
        self.patient = PatientSnapshot.objects.create(
            pat_reg_no="886001",
            pat_name="BUG6 Test Patient",
            pat_sex="Male",
            pat_age="40",
            pat_room_no="DS-1",
        )
        self.unmapped_name = "BUG6 Unmapped Misspelled Therapy"
        self.mapped_zero_therapy = TherapyMaster.objects.create(
            therapy_code="THEB_BUG6_ZERO",
            therapy_name="BUG6 Mapped Internal Zero Therapy",
            therapy_category="Internal",
            therapy_duration="30",
            bathing_required="No",
            treatment_room_required="No",
            no_of_super_senior_therapist=0,
            no_of_senior_therapist=0,
            no_of_junior_therapist=0,
            no_of_trainee_therapist=0,
            total_no_of_therapist=0,
            is_active=True,
        )

    def _create_unmapped_booking(self, *, bathing_count=0):
        alloc = TherapyAllocation.objects.create(
            patient=self.patient,
            therapy_code="THEB_BUG6_MISSING",
            therapy_name=self.unmapped_name,
            timeslot=self.slot_0830,
            from_date=TEST_DATE,
            to_date=TEST_DATE,
            days=1,
            bathing_therapists_count=bathing_count,
            status="failed",
        )
        booking = Booking.objects.create(
            allocation=alloc,
            date=TEST_DATE,
            timeslot=self.slot_0830,
            room=None,
            status="failed",
            failure_reason="insufficient_therapists_available",
            snapshot_therapy_name=self.unmapped_name,
        )
        return alloc, booking

    def test_wrapper_parity_across_scheduling_and_rescheduling(self):
        """All scheduling and rescheduling therapist_requirements wrappers return total=1 for missing TherapyMaster."""
        alloc_stub = SimpleNamespace(
            therapy_name=self.unmapped_name,
            therapy_code="THEB_BUG6_MISSING",
            bathing_therapists_count=0,
        )
        wrappers = [
            ("core", core_therapist_requirements),
            ("final_allocation", final_allocation.therapist_requirements),
            ("bulk_allocator", bulk_allocator.therapist_requirements),
            ("visit_allocator", visit_allocator.therapist_requirements),
            ("reshedule", reshedule.therapist_requirements),
            ("visit_rescheduler", visit_rescheduler.therapist_requirements),
            ("slot_attempter", slot_attempter.therapist_requirements),
            ("leave_reassignment", leave_reassignment.therapist_requirements),
            ("resheduleMorningandNight", resheduleMorningandNight.therapist_requirements),
        ]

        for label, fn in wrappers:
            with self.subTest(wrapper=label):
                req = fn(alloc_stub)
                self.assertEqual(req["total"], 1)
                self.assertEqual(req["normal_total"], 1)
                self.assertEqual(req["super_senior"], 0)
                self.assertEqual(req["senior"], 0)
                self.assertEqual(req["junior"], 0)
                self.assertEqual(req["trainee"], 0)
                self.assertIsNone(req["therapy_category"])

    def test_direct_allocate_therapists_with_unmapped_therapy(self):
        """Direct reshedule.allocate_therapists() allocates 1 therapist for an unmapped therapy."""
        alloc_stub = SimpleNamespace(
            therapy_name=self.unmapped_name,
            therapy_code="THEB_BUG6_MISSING",
            bathing_therapists_count=0,
        )
        req = reshedule.therapist_requirements(alloc_stub)
        self.assertEqual(req["total"], 1)

        allocated = reshedule.allocate_therapists(
            TEST_DATE,
            self.slot_0830,
            req,
            patient_gender="Male",
            patient_id=self.patient.pat_reg_no,
            patient_age=40,
            create_bookings=False,
        )
        self.assertEqual(len(allocated), 1)
        self.assertEqual(allocated[0].therapist_code, self.therapist.therapist_code)

    def test_visit_rescheduler_allocates_one_therapist_when_available(self):
        """End-to-end visit_rescheduler succeeds with 1 therapist when a therapist is available."""
        alloc, booking = self._create_unmapped_booking()

        with patch.object(reshedule, "is_patient_active", return_value=True):
            tasks = visit_rescheduler.expand_therapies_for_visit(
                alloc.id,
                TEST_DATE.isoformat(),
                create_bookings=True,
                force_slot_only=True,
            )

        self.assertIsInstance(tasks, list)
        self.assertEqual(len(tasks), 1)
        self.assertEqual(tasks[0]["status"], "BOOKED")
        self.assertEqual(len(tasks[0]["therapists"]), 1)
        self.assertEqual(tasks[0]["therapists"][0]["therapist_code"], self.therapist.therapist_code)

        booking.refresh_from_db()
        self.assertEqual(booking.status, "scheduled")
        self.assertEqual(
            TherapistBooking.objects.filter(visit=alloc, date=TEST_DATE, status="BOOKED").count(),
            1,
        )

    def test_visit_rescheduler_fails_when_no_therapist_available(self):
        """End-to-end visit_rescheduler fails cleanly when no eligible therapist is available (never succeeds with 0)."""
        alloc, booking = self._create_unmapped_booking()
        TherapistMaster.objects.filter(is_active=True, therapist_gender__istartswith="m").update(
            is_active=False
        )

        with patch.object(reshedule, "is_patient_active", return_value=True):
            tasks = visit_rescheduler.expand_therapies_for_visit(
                alloc.id,
                TEST_DATE.isoformat(),
                create_bookings=True,
                force_slot_only=True,
            )

        self.assertIsInstance(tasks, list)
        self.assertEqual(len(tasks), 1)
        self.assertEqual(tasks[0]["status"], "FAILED")
        self.assertIn("insufficient_therapists_available", str(tasks[0]["reason"]))
        self.assertEqual(tasks[0]["therapists"], [])

        booking.refresh_from_db()
        self.assertEqual(booking.status, "failed")
        self.assertEqual(
            TherapistBooking.objects.filter(visit=alloc, date=TEST_DATE, status="BOOKED").count(),
            0,
        )

    def test_options_preview_slot_and_compute_with_unmapped_therapy(self):
        """Both preview_slot_reschedule and compute_reschedule_options_preview handle unmapped therapies with total=1."""
        alloc, booking = self._create_unmapped_booking()

        # 1. preview_slot_reschedule with available therapist (strictly read-only)
        task, ok, reason = options_preview.preview_slot_reschedule(
            alloc,
            booking,
            TEST_DATE,
            self.slot_0830,
        )
        self.assertTrue(ok, f"Expected preview_slot_reschedule to succeed, got reason={reason}")
        self.assertEqual(task["status"], "BOOKED")
        self.assertEqual(len(task["therapists"]), 1)
        self.assertEqual(TherapistBooking.objects.filter(date=TEST_DATE).count(), 0)

        # 2. compute_reschedule_options_preview with available therapist (strictly read-only)
        preview = options_preview.compute_reschedule_options_preview(alloc, booking, TEST_DATE)
        slot_ids = [item["slot_id"] for item in preview["available_slots"]]
        self.assertIn(self.slot_0830.id, slot_ids)
        matched = next(item for item in preview["available_slots"] if item["slot_id"] == self.slot_0830.id)
        self.assertEqual(len(matched["task"]["therapists"]), 1)
        self.assertEqual(TherapistBooking.objects.filter(date=TEST_DATE).count(), 0)

        # 3. Both preview helpers report unavailable when no therapist is available
        TherapistMaster.objects.filter(is_active=True, therapist_gender__istartswith="m").update(
            is_active=False
        )
        task_unavail, ok_unavail, reason_unavail = options_preview.preview_slot_reschedule(
            alloc,
            booking,
            TEST_DATE,
            self.slot_0830,
        )
        self.assertFalse(ok_unavail)
        self.assertEqual(task_unavail["status"], "FAILED")
        self.assertIn("insufficient_therapists_available", str(reason_unavail))

        preview_unavail = options_preview.compute_reschedule_options_preview(alloc, booking, TEST_DATE)
        self.assertEqual(preview_unavail["available_slots"], [])

    def test_mapped_zero_therapist_treatment_still_returns_zero(self):
        """Legitimate mapped TherapyMaster rows with total_no_of_therapist=0 keep total=0 across all wrappers."""
        zero_stub = SimpleNamespace(
            therapy_name=self.mapped_zero_therapy.therapy_name,
            therapy_code=self.mapped_zero_therapy.therapy_code,
            bathing_therapists_count=0,
        )
        for label, fn in [
            ("core", core_therapist_requirements),
            ("final_allocation", final_allocation.therapist_requirements),
            ("bulk_allocator", bulk_allocator.therapist_requirements),
            ("visit_allocator", visit_allocator.therapist_requirements),
            ("reshedule", reshedule.therapist_requirements),
            ("visit_rescheduler", visit_rescheduler.therapist_requirements),
            ("slot_attempter", slot_attempter.therapist_requirements),
            ("leave_reassignment", leave_reassignment.therapist_requirements),
            ("resheduleMorningandNight", resheduleMorningandNight.therapist_requirements),
        ]:
            with self.subTest(wrapper=label):
                req = fn(zero_stub)
                self.assertEqual(req["total"], 0)
                self.assertEqual(req["normal_total"], 0)

    def test_missing_therapy_with_bathing_therapists_count_override(self):
        """Missing TherapyMaster with bathing_therapists_count=2 returns total=2 and normal_total=1."""
        wc_stub = SimpleNamespace(
            therapy_name=self.unmapped_name,
            therapy_code="THEB_BUG6_MISSING",
            bathing_therapists_count=2,
        )
        for label, fn in [
            ("core", core_therapist_requirements),
            ("final_allocation", final_allocation.therapist_requirements),
            ("reshedule", reshedule.therapist_requirements),
            ("visit_rescheduler", visit_rescheduler.therapist_requirements),
            ("slot_attempter", slot_attempter.therapist_requirements),
            ("leave_reassignment", leave_reassignment.therapist_requirements),
            ("resheduleMorningandNight", resheduleMorningandNight.therapist_requirements),
        ]:
            with self.subTest(wrapper=label):
                req = fn(wc_stub)
                self.assertEqual(req["total"], 2)
                self.assertEqual(req["normal_total"], 1)
                self.assertEqual(req["bathing_therapists_count"], 2)

    def test_missing_therapy_not_classified_as_zero_therapist_booking(self):
        """Unmapped therapies satisfy total > 0 (not hidden as zero-therapist prescriptions), unlike mapped total=0."""
        alloc, _ = self._create_unmapped_booking()
        mapped_zero_alloc = SimpleNamespace(
            therapy_name=self.mapped_zero_therapy.therapy_name,
            therapy_code=self.mapped_zero_therapy.therapy_code,
            bathing_therapists_count=0,
        )

        # Matches dashboard failed-schedule and scheduled-list predicates in Sheduling/views.py
        self.assertGreater(reshedule.therapist_requirements(alloc).get("total", 1), 0)
        self.assertNotEqual(reshedule.therapist_requirements(alloc).get("total", 1), 0)

        # Mapped zero-therapist treatment remains classified as total == 0
        self.assertEqual(reshedule.therapist_requirements(mapped_zero_alloc).get("total", 1), 0)
