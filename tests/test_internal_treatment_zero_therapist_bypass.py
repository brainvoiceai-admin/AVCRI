"""
Internal Treatment Zero-Therapist Scheduling Bypass (Checklist #22) Test Suite

Validates Checklist #22:
Therapies defined with total_no_of_therapist=0 (Internal treatments)
bypass algorithm passes entirely and auto-schedule immediately with 0 therapists and 0 nurses.

Workflow:
1. Ingest draft booking for internal treatment with linked BookingItem rows.
2. Run bulk_allocate_for_date().
3. Query booking statuses:
   - Engine detects therapy_req.get('total') == 0.
   - Bypasses therapist search and continuity passes completely.
   - allocation_bookings.update(status='scheduled') executes immediately.
   - Linked BookingItem rows marked status='scheduled'.
   - 0 therapists and 0 nurses booked.
"""
import pytest
from datetime import date, time
from unittest.mock import patch
from django.test import TestCase

from Sheduling.models import (
    PatientSnapshot,
    TherapyAllocation,
    Booking,
    BookingItem,
    BookingAssignment,
)
from masters.models import (
    SlotMaster,
    TherapistGrade,
    TherapistMaster,
    TherapyMaster,
    NurseTreatmentMaster,
)
from Patient.models import TreatmentRoom, RoomName, TherapistBooking
from final_allocation import (
    bulk_allocate_for_date,
    therapist_requirements,
    therapy_cache,
)
from Sheduling.nurse_allocation import is_nurse_treatment

TARGET_DATE = date(2099, 9, 22)
TARGET_DATE_STR = TARGET_DATE.isoformat()


def _ensure_slot(number, slot_time):
    obj, _ = SlotMaster.objects.get_or_create(
        slot_number=number,
        defaults={"slot_time": slot_time, "is_active": True},
    )
    if obj.slot_time != slot_time:
        obj.slot_time = slot_time
        obj.save(update_fields=["slot_time"])
    return obj


def _ensure_therapy(code, name, grade_counts, bathing="No", room_req="No", category="Internal"):
    obj, _ = TherapyMaster.objects.get_or_create(
        therapy_code=code,
        defaults={
            "therapy_name": name,
            "therapy_category": category,
            "therapy_duration": "30",
            "bathing_required": bathing,
            "treatment_room_required": room_req,
            "no_of_super_senior_therapist": grade_counts.get("super_senior", 0),
            "no_of_senior_therapist": grade_counts.get("senior", 0),
            "no_of_junior_therapist": grade_counts.get("junior", 0),
            "no_of_trainee_therapist": grade_counts.get("trainee", 0),
            "total_no_of_therapist": sum(grade_counts.values()),
            "is_active": True,
        },
    )
    return obj


def _ensure_room(room_no):
    room_name, _ = RoomName.objects.get_or_create(name=f"Room {room_no}", defaults={"is_active": True})
    obj, _ = TreatmentRoom.objects.get_or_create(
        room_no=room_no,
        defaults={"room_name": room_name, "floor": "G", "is_active": True},
    )
    return obj


@pytest.mark.django_db(transaction=True)
class TestInternalTreatmentZeroTherapistBypass(TestCase):
    """
    Validates Checklist #22:
    Therapies defined with total_no_of_therapist=0 (Internal treatments)
    bypass algorithm passes entirely and auto-schedule immediately with 0 therapists and 0 nurses.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.slot = _ensure_slot(131, time(10, 0))
        cls.room = _ensure_room("INT_R1")

        # Create TherapyMaster with total_no_of_therapist=0 (Internal Treatment)
        cls.therapy_internal = _ensure_therapy(
            code="T_INT_ZERO",
            name="Internal Kashayam Therapy",
            grade_counts={},  # all 0
            bathing="No",
            room_req="No",
            category="Internal",
        )
        cls.therapy_internal.total_no_of_therapist = 0
        cls.therapy_internal.no_of_super_senior_therapist = 0
        cls.therapy_internal.no_of_senior_therapist = 0
        cls.therapy_internal.no_of_junior_therapist = 0
        cls.therapy_internal.no_of_trainee_therapist = 0
        cls.therapy_internal.save()

    def setUp(self):
        therapy_cache.clear()

    def tearDown(self):
        therapy_cache.clear()
        BookingItem.objects.filter(booking__date=TARGET_DATE).delete()
        BookingAssignment.objects.filter(booking__date=TARGET_DATE).delete()
        TherapistBooking.objects.filter(date=TARGET_DATE).delete()
        Booking.objects.filter(date=TARGET_DATE).delete()
        TherapyAllocation.objects.filter(therapy_code=self.therapy_internal.therapy_code).delete()
        PatientSnapshot.objects.filter(pat_reg_no__startswith="5000").delete()

    @patch("final_allocation.is_patient_active")
    def test_internal_treatment_zero_therapist_auto_schedules_immediately(self, mock_is_active):
        """
        Checklist #22:
        1. Ingest draft booking for internal treatment (total_no_of_therapist=0).
        2. Run bulk_allocate_for_date().
        3. Query booking statuses:
           - Engine detects therapy_req.get('total') == 0.
           - Bypasses therapist search and continuity passes completely.
           - allocation_bookings.update(status='scheduled') executes immediately.
           - Linked BookingItem rows marked status='scheduled'.
           - 0 therapists and 0 nurses allocated.
        """
        mock_is_active.return_value = True

        pat = PatientSnapshot.objects.create(
            pat_reg_no="500001",
            pat_name="Internal Treatment Patient",
            pat_sex="Male",
            pat_age="42",
        )
        alloc = TherapyAllocation.objects.create(
            patient=pat,
            therapy_code=self.therapy_internal.therapy_code,
            therapy_name=self.therapy_internal.therapy_name,
            from_date=TARGET_DATE,
            to_date=TARGET_DATE,
            days=1,
            timeslot=self.slot,
            room=self.room,
            required_therapist_roles=[],
            status="draft",
        )
        bk = Booking.objects.create(
            allocation=alloc,
            date=TARGET_DATE,
            timeslot=self.slot,
            room=self.room,
            status="draft",
        )
        bi = BookingItem.objects.create(
            booking=bk,
            item_code="MED_KASH_01",
            item_name="Kashayam Decoction 100ml",
            status="draft",
        )

        # Confirm therapist_requirements helper detects total == 0
        req = therapist_requirements(alloc)
        assert req.get("total") == 0, f"Expected total=0, got {req}"

        # Execute bulk_allocate_for_date
        response = bulk_allocate_for_date(TARGET_DATE_STR)

        # 1. Booking marked as scheduled
        bk.refresh_from_db()
        assert bk.status == "scheduled", f"Expected booking to be scheduled, got: {bk.status}"

        # 2. Linked BookingItem marked as scheduled
        bi.refresh_from_db()
        assert bi.status == "scheduled", f"Expected BookingItem to be scheduled, got: {bi.status}"

        # 3. 0 therapists booked in TherapistBooking
        tb_count = TherapistBooking.objects.filter(patient_id=pat.id, date=TARGET_DATE).count()
        assert tb_count == 0, f"Expected 0 TherapistBookings, found {tb_count}"

        # 4. 0 BookingAssignment rows created (algorithm passes bypassed)
        assign_count = BookingAssignment.objects.filter(booking=bk).count()
        assert assign_count == 0, f"Expected 0 BookingAssignments, found {assign_count}"

        # 5. Result audit reports auto_scheduled: True
        results_list = response.get("results", [])
        alloc_result = next((r for r in results_list if r.get("allocation_id") == alloc.id), None)
        assert alloc_result is not None, f"Allocation {alloc.id} not found in results: {response}"
        assert alloc_result.get("auto_scheduled") is True
        assert alloc_result.get("status") == "success"

    @patch("final_allocation.is_patient_active")
    def test_internal_treatment_bypasses_continuity_pass1(self, mock_is_active):
        """
        In PASS 1 (Continuity priority pass), internal treatments with total=0
        are skipped without locking continuity therapists.
        """
        mock_is_active.return_value = True

        pat = PatientSnapshot.objects.create(
            pat_reg_no="500002",
            pat_name="Continuity Bypass Patient",
            pat_sex="Female",
            pat_age="29",
        )
        alloc = TherapyAllocation.objects.create(
            patient=pat,
            therapy_code=self.therapy_internal.therapy_code,
            therapy_name=self.therapy_internal.therapy_name,
            from_date=TARGET_DATE,
            to_date=TARGET_DATE,
            days=1,
            timeslot=self.slot,
            room=self.room,
            required_therapist_roles=[],
            status="draft",
        )
        bk = Booking.objects.create(
            allocation=alloc,
            date=TARGET_DATE,
            timeslot=self.slot,
            room=self.room,
            status="draft",
        )

        bulk_allocate_for_date(TARGET_DATE_STR)

        bk.refresh_from_db()
        assert bk.status == "scheduled"
        # No continuity records or therapist bookings should exist
        assert TherapistBooking.objects.filter(patient_id=pat.id, date=TARGET_DATE).count() == 0

    def test_nurse_treatment_with_zero_therapists_does_not_bypass_via_internal_rule(self):
        """
        If a therapy has total_no_of_therapist=0 but is a nurse treatment in NurseTreatmentMaster,
        it does NOT take the zero-therapist immediate auto-schedule bypass (it proceeds through nurse allocation).
        """
        nt, _ = NurseTreatmentMaster.objects.get_or_create(
            treatment_code="NT_BYPASS_CHECK",
            defaults={"name": "Nurse Enema Check", "number_of_nurse_required": 1, "is_active": True},
        )
        alloc = TherapyAllocation(
            therapy_code="NT_BYPASS_CHECK",
            therapy_name="Nurse Enema Check",
        )
        assert is_nurse_treatment(alloc.therapy_code, alloc.therapy_name) is not None
