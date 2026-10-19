"""
Scheduling Algorithm Regression Tests:
  - Checklist #3: Outpatient (OP) Slot Confinement (11:30 & 17:30)
  - Checklist #5: IP Over OP Allocation Priority under Resource Contention
  - Checklist #6: Hard & Special Category Time-Slot Restriction
  - Checklist #7: Inpatient (IP) Easy / Medium Overflow into OP Slots

Specification References:
    1. Checklist #3:
       Outpatients (pat_type='OP') are strictly restricted to off-peak slots
       (11:30 and 17:30 / 5:30 PM) to preserve morning/afternoon prime slots for
       admitted inpatients. Primary IP slots (06:30, 08:30, 10:00, etc.) are excluded.

    2. Checklist #5:
       Inpatient (IP) therapies receive strict priority over Outpatients (OP) across
       all seasons whenever slots, rooms, or therapists are constrained.
       1 IP and 1 OP patient requiring identical therapy (1 Male Senior) at target date.
       Only 1 eligible Male Senior therapist is available.
       Expected Results:
         - IP patient therapy is prioritized, processed, and scheduled first.
         - OP booking is held or marked failed due to resource exhaustion.
         - DB confirms IP booking status='scheduled'.

    3. Checklist #6:
       Strenuous treatments categorized as 'Hard' or 'Special' are strictly barred
       from 11:30 and 17:30 slots regardless of patient type due to clinical
       rest/digestion protocols. If morning/afternoon slots are unavailable, booking
       fails rather than assigning 11:30 or 17:30.

    4. Checklist #7:
       When standard IP slots (06:30-16:00) are fully booked, IP patients with
       low-strain Easy or Medium therapies are permitted to overflow into OP slots
       (11:30 and 17:30). Under identical saturation, Hard therapies fail without overflowing.
"""
import pytest
from datetime import date, time
from unittest.mock import patch
from django.test import TestCase

from Sheduling.models import PatientSnapshot, TherapyAllocation, Booking, BookingAssignment
from masters.models import SlotMaster, TherapistGrade, TherapistMaster, TherapyMaster
from Patient.models import TreatmentRoom, RoomName, TherapistBooking, RoomBooking
from reshedule import (
    get_allowed_slot_values,
    expand_therapies_for_visit,
)
from final_allocation import bulk_allocate_for_date


DATE_CHECKLIST_3 = date(2099, 3, 20)
DATE_CHECKLIST_5 = date(2099, 3, 25)
DATE_CHECKLIST_6 = date(2099, 3, 21)
DATE_CHECKLIST_7 = date(2099, 3, 22)

PRIMARY_IP_SLOT_STRS = ["06:30", "08:30", "10:00", "14:30", "16:00"]
OP_OFFPEAK_SLOT_STRS = ["11:30", "17:30"]  # 11:30 AM and 5:30 PM


def _ensure_slot(number, slot_time):
    obj, _ = SlotMaster.objects.get_or_create(
        slot_number=number,
        defaults={"slot_time": slot_time, "is_active": True},
    )
    return obj


def _ensure_grade(name, order):
    obj, _ = TherapistGrade.objects.get_or_create(
        name=name,
        defaults={"display_order": order, "is_active": True},
    )
    return obj


def _ensure_therapy(code, name, category="Medium", patient_type="IP", grade_counts=None):
    if grade_counts is None:
        grade_counts = {"senior": 1}
    obj, _ = TherapyMaster.objects.get_or_create(
        therapy_code=code,
        defaults={
            "therapy_name": name,
            "therapy_category": category,
            "therapy_duration": "30",
            "bathing_required": "No",
            "treatment_room_required": "Yes",
            "no_of_super_senior_therapist": grade_counts.get("super_senior", 0),
            "no_of_senior_therapist": grade_counts.get("senior", 1),
            "no_of_junior_therapist": grade_counts.get("junior", 0),
            "no_of_trainee_therapist": grade_counts.get("trainee", 0),
            "total_no_of_therapist": sum(grade_counts.values()),
            "patient_type": patient_type,
            "is_active": True,
        },
    )
    return obj


def _ensure_therapist(code, name, gender, grade, employee_code):
    obj, _ = TherapistMaster.objects.get_or_create(
        therapist_code=code,
        defaults={
            "therapist_name": name,
            "therapist_gender": gender,
            "therapist_grade": grade,
            "employee_code": employee_code,
            "is_bathing_therapist": True,
            "is_helping_therapist": False,
            "is_active": True,
        },
    )
    return obj


def _ensure_room(room_no):
    room_name, _ = RoomName.objects.get_or_create(
        name=f"Room {room_no}", defaults={"is_active": True}
    )
    obj, _ = TreatmentRoom.objects.get_or_create(
        room_no=room_no,
        defaults={
            "room_name": room_name,
            "floor": "G",
            "is_active": True,
        },
    )
    return obj


@pytest.mark.django_db(transaction=True)
class TestSchedulingAlgorithmSlotRules(TestCase):
    """
    Regression suite for Scheduling Algorithm Time-Slot Confinement & Overflow Rules.
    Covers Checklist #3, Checklist #6, and Checklist #7.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        # Standard 7 time slots
        cls.slot_0630 = _ensure_slot(1, time(6, 30))
        cls.slot_0830 = _ensure_slot(2, time(8, 30))
        cls.slot_1000 = _ensure_slot(3, time(10, 0))
        cls.slot_1130 = _ensure_slot(4, time(11, 30))
        cls.slot_1430 = _ensure_slot(5, time(14, 30))
        cls.slot_1600 = _ensure_slot(6, time(16, 0))
        cls.slot_1730 = _ensure_slot(7, time(17, 30))

        # Shared masters
        cls.grade_senior = _ensure_grade("Senior Therapist", 2)
        cls.therapist_m = _ensure_therapist(
            "THR_REQ003_M", "Male Senior REQ003", "Male",
            cls.grade_senior, "EMP_REQ003_M",
        )
        cls.room = _ensure_room("TR-1")

        # Therapy categories
        cls.therapy_easy = _ensure_therapy(
            "T_REQ_EASY", "Easy Therapy REQ", category="Easy", patient_type="IP"
        )
        cls.therapy_medium = _ensure_therapy(
            "T_REQ_MED", "Medium Therapy REQ", category="Medium", patient_type="OP"
        )
        cls.therapy_hard = _ensure_therapy(
            "T_REQ_HARD", "Hard Therapy REQ", category="Hard", patient_type="IP"
        )
        cls.therapy_special = _ensure_therapy(
            "T_REQ_SPEC", "Special Therapy REQ", category="Special", patient_type="IP"
        )

    # -----------------------------------------------------------------------
    # Checklist #3: Outpatient (OP) Slot Confinement (11:30 & 17:30)
    # -----------------------------------------------------------------------
    @patch("final_allocation.is_patient_active", return_value=True)
    @patch("reshedule.is_patient_active", return_value=True)
    def test_op_patient_confinement_to_1130_and_530(self, mock_is_act_resh, mock_is_act_final):
        """
        Checklist #3: Verify OP patient allocation is strictly restricted to 11:30 or 17:30 (5:30 PM)
        and all other slots (06:30, 08:30, 10:00, 14:30, 16:00) are excluded.
        """
        target_date = DATE_CHECKLIST_3
        target_date_str = target_date.isoformat()

        # 1. Candidate pool definition strictly excludes primary IP slots
        op_candidates = get_allowed_slot_values(
            patient_type="OP",
            therapy_category="Medium",
            therapy_name=self.therapy_medium.therapy_name,
            therapy_code=self.therapy_medium.therapy_code,
        )
        assert op_candidates == OP_OFFPEAK_SLOT_STRS, (
            f"OP candidate pool should strictly be {OP_OFFPEAK_SLOT_STRS}, got: {op_candidates}"
        )
        for ip_slot in PRIMARY_IP_SLOT_STRS:
            assert ip_slot not in op_candidates, (
                f"Primary IP slot {ip_slot} must be excluded from OP candidate pool!"
            )

        # 2. Ingest OP draft (5 digits -> is_op() == True)
        patient = PatientSnapshot.objects.create(
            pat_reg_no="50101", pat_name="OP Patient Step 1", pat_sex="Male", pat_age="30"
        )
        assert patient.is_op() is True

        alloc = TherapyAllocation.objects.create(
            patient=patient,
            therapy_code=self.therapy_medium.therapy_code,
            therapy_name=self.therapy_medium.therapy_name,
            from_date=target_date,
            to_date=target_date,
            days=1,
            timeslot=None,
            room=None,
            required_therapist_roles=[{"role": "senior", "count": 1}],
            status="draft",
        )
        booking = Booking.objects.create(
            allocation=alloc,
            date=target_date,
            timeslot=None,
            room=None,
            status="draft",
        )

        # 3. Run scheduling engine
        tasks = expand_therapies_for_visit(alloc.id, target_date_str, create_bookings=True)
        assert isinstance(tasks, list) and len(tasks) > 0, "Scheduling engine failed to process booking"

        # 4. Check Booking.timeslot
        booking.refresh_from_db()
        assert booking.status == "scheduled", f"Booking not scheduled: {booking.failure_reason}"
        assert booking.timeslot is not None, "Booking.timeslot was not assigned"

        assigned_time = booking.timeslot.slot_time.strftime("%H:%M")
        assert assigned_time in OP_OFFPEAK_SLOT_STRS, (
            f"OP allocation must be restricted to 11:30 or 17:30 (5:30 PM). Got: {assigned_time}"
        )
        assert assigned_time not in PRIMARY_IP_SLOT_STRS, (
            f"ERROR: OP patient was allocated to primary IP slot {assigned_time}!"
        )

    # -----------------------------------------------------------------------
    # Checklist #6: Hard & Special Category Time-Slot Restriction
    # -----------------------------------------------------------------------
    @patch("final_allocation.is_patient_active", return_value=True)
    @patch("reshedule.is_patient_active", return_value=True)
    def test_hard_special_category_time_slot_restriction(self, mock_is_act_resh, mock_is_act_final):
        """
        Checklist #6: Hard & Special Category Time-Slot Restriction.
        Strenuous treatments categorized as 'Hard' or 'Special' are strictly barred
        from 11:30 and 17:30 slots regardless of patient type due to clinical rest/digestion protocols.
        If morning/afternoon slots are unavailable, booking fails rather than assigning 11:30 or 17:30.
        """
        target_date = DATE_CHECKLIST_6
        target_date_str = target_date.isoformat()

        # 1. Inspect allowed slots evaluation across patient types for Hard and Special
        for ptype in ["IP", "OP"]:
            hard_slots = get_allowed_slot_values(patient_type=ptype, therapy_category="Hard")
            special_slots = get_allowed_slot_values(patient_type=ptype, therapy_category="Special")
            assert "11:30" not in hard_slots, f"Hard treatments must be barred from 11:30 for {ptype}"
            assert "17:30" not in hard_slots, f"Hard treatments must be barred from 17:30 for {ptype}"
            assert "11:30" not in special_slots, f"Special treatments must be barred from 11:30 for {ptype}"
            assert "17:30" not in special_slots, f"Special treatments must be barred from 17:30 for {ptype}"

        # 2. Saturate morning/afternoon prime slots (06:30, 08:30, 10:00, 14:30, 16:00)
        dummy_pat = PatientSnapshot.objects.create(
            pat_reg_no="990061", pat_name="Dummy Blocker 6", pat_sex="Male", pat_age="40"
        )
        sat_tbs = []
        for s in [self.slot_0630, self.slot_0830, self.slot_1000, self.slot_1430, self.slot_1600]:
            tb = TherapistBooking.objects.create(
                therapist=self.therapist_m,
                date=target_date,
                time_slot=s,
                status="BOOKED",
                patient_id=dummy_pat.id,
            )
            sat_tbs.append(tb)

        # 3. Ingest Hard therapy draft (11:30 and 17:30 are vacant/free)
        patient_hard = PatientSnapshot.objects.create(
            pat_reg_no="990062", pat_name="Hard Patient", pat_sex="Male", pat_age="35", pat_room_no="DS-1"
        )
        alloc_hard = TherapyAllocation.objects.create(
            patient=patient_hard,
            therapy_code=self.therapy_hard.therapy_code,
            therapy_name=self.therapy_hard.therapy_name,
            from_date=target_date,
            to_date=target_date,
            days=1,
            timeslot=None,
            room=None,
            required_therapist_roles=[{"role": "senior", "count": 1}],
            status="draft",
        )
        booking_hard = Booking.objects.create(
            allocation=alloc_hard,
            date=target_date,
            timeslot=None,
            room=None,
            status="draft",
        )

        try:
            # 4. Attempt scheduling: morning/afternoon slots unavailable, 11:30 and 17:30 free
            tasks = expand_therapies_for_visit(alloc_hard.id, target_date_str, create_bookings=True)
            booking_hard.refresh_from_db()

            # Hard booking must fail rather than assigning 11:30 or 17:30
            if booking_hard.timeslot is not None:
                assigned_time = booking_hard.timeslot.slot_time.strftime("%H:%M")
                assert assigned_time not in OP_OFFPEAK_SLOT_STRS, (
                    f"CRITICAL: Hard treatment was forbidden at 11:30 and 17:30 but got: {assigned_time}"
                )
            assert booking_hard.status in ["failed", "draft"], (
                f"Expected Hard therapy booking to fail under prime slot unavailability, got: {booking_hard.status}"
            )
        finally:
            for tb in sat_tbs:
                tb.delete()
            dummy_pat.delete()
            booking_hard.delete()
            alloc_hard.delete()
            patient_hard.delete()

    # -----------------------------------------------------------------------
    # Checklist #7: Inpatient (IP) Easy / Medium Overflow into OP Slots
    # -----------------------------------------------------------------------
    @patch("final_allocation.is_patient_active", return_value=True)
    @patch("reshedule.is_patient_active", return_value=True)
    def test_inpatient_easy_medium_overflow_into_op_slots(self, mock_is_act_resh, mock_is_act_final):
        """
        Checklist #7: Inpatient (IP) Easy / Medium Overflow into OP Slots.
        When standard IP slots (06:30-16:00) are fully booked, IP patients with
        low-strain Easy or Medium therapies are permitted to overflow into OP slots (11:30 and 17:30).
        Under identical saturation, Hard therapies fail without overflowing.
        """
        target_date = DATE_CHECKLIST_7
        target_date_str = target_date.isoformat()

        # 1. Trigger get_allowed_slot_values('IP', 'Easy') and verify dynamic append
        easy_candidates = get_allowed_slot_values(patient_type="IP", therapy_category="Easy")
        medium_candidates = get_allowed_slot_values(patient_type="IP", therapy_category="Medium")
        hard_candidates = get_allowed_slot_values(patient_type="IP", therapy_category="Hard")

        assert "11:30" in easy_candidates and "17:30" in easy_candidates
        assert "11:30" in medium_candidates and "17:30" in medium_candidates
        assert "11:30" not in hard_candidates and "17:30" not in hard_candidates

        # 2. Saturate primary IP slots (06:30, 08:30, 10:00, 14:30, 16:00)
        dummy_pat = PatientSnapshot.objects.create(
            pat_reg_no="990071", pat_name="Dummy Blocker 7", pat_sex="Male", pat_age="40"
        )
        sat_tbs = []
        for s in [self.slot_0630, self.slot_0830, self.slot_1000, self.slot_1430, self.slot_1600]:
            tb = TherapistBooking.objects.create(
                therapist=self.therapist_m,
                date=target_date,
                time_slot=s,
                status="BOOKED",
                patient_id=dummy_pat.id,
            )
            sat_tbs.append(tb)

        # 3. Run allocation engine for IP Easy therapy under primary saturation
        pat_ip = PatientSnapshot.objects.create(
            pat_reg_no="990072", pat_name="IP Easy Patient", pat_sex="Male", pat_age="30", pat_room_no="DS-1"
        )
        assert pat_ip.is_op() is False, "Patient must be IP (6 digits)"

        alloc_easy = TherapyAllocation.objects.create(
            patient=pat_ip,
            therapy_code=self.therapy_easy.therapy_code,
            therapy_name=self.therapy_easy.therapy_name,
            from_date=target_date,
            to_date=target_date,
            days=1,
            timeslot=None,
            room=None,
            required_therapist_roles=[{"role": "senior", "count": 1}],
            status="draft",
        )
        booking_easy = Booking.objects.create(
            allocation=alloc_easy,
            date=target_date,
            timeslot=None,
            room=None,
            status="draft",
        )

        try:
            tasks_easy = expand_therapies_for_visit(alloc_easy.id, target_date_str, create_bookings=True)
            booking_easy.refresh_from_db()

            # Easy booking commits successfully at 11:30 or 17:30
            assert booking_easy.status == "scheduled", f"Easy booking failed to overflow: {booking_easy.failure_reason}"
            assert booking_easy.timeslot is not None
            assigned_slot = booking_easy.timeslot.slot_time.strftime("%H:%M")
            assert assigned_slot in OP_OFFPEAK_SLOT_STRS, (
                f"IP Easy therapy should overflow to 11:30 or 17:30 when primary slots are full. Got: {assigned_slot}"
            )
        finally:
            booking_easy.delete()
            alloc_easy.delete()
            TherapistBooking.objects.filter(date=target_date).exclude(id__in=[t.id for t in sat_tbs]).delete()
            RoomBooking.objects.filter(date=target_date).delete()

        # 4. Under identical saturation, Hard therapies fail without overflowing
        alloc_hard = TherapyAllocation.objects.create(
            patient=pat_ip,
            therapy_code=self.therapy_hard.therapy_code,
            therapy_name=self.therapy_hard.therapy_name,
            from_date=target_date,
            to_date=target_date,
            days=1,
            timeslot=None,
            room=None,
            required_therapist_roles=[{"role": "senior", "count": 1}],
            status="draft",
        )
        booking_hard = Booking.objects.create(
            allocation=alloc_hard,
            date=target_date,
            timeslot=None,
            room=None,
            status="draft",
        )

        try:
            tasks_hard = expand_therapies_for_visit(alloc_hard.id, target_date_str, create_bookings=True)
            booking_hard.refresh_from_db()

            # Hard booking must fail without overflowing to 11:30 or 17:30
            if booking_hard.timeslot is not None:
                assigned_hard = booking_hard.timeslot.slot_time.strftime("%H:%M")
                assert assigned_hard not in OP_OFFPEAK_SLOT_STRS, (
                    f"Hard therapy must not overflow into OP slots! Got: {assigned_hard}"
                )
            assert booking_hard.status in ["failed", "draft"], (
                f"Expected Hard therapy to fail under primary slot saturation, got: {booking_hard.status}"
            )
        finally:
            for tb in sat_tbs:
                tb.delete()
            dummy_pat.delete()
            booking_hard.delete()
            alloc_hard.delete()
            pat_ip.delete()

    # -----------------------------------------------------------------------
    # Checklist #5: IP Over OP Allocation Priority under Resource Contention
    # -----------------------------------------------------------------------
    @patch("final_allocation.is_patient_active", return_value=True)
    @patch("reshedule.is_patient_active", return_value=True)
    def test_ip_over_op_allocation_priority_under_resource_contention(self, mock_is_act_resh, mock_is_act_final):
        """
        Checklist #5:
        Inpatient (IP) therapies receive strict priority over Outpatients (OP) across
        all seasons whenever slots, rooms, or therapists are constrained.
        Scenario:
          1 IP and 1 OP patient requiring identical therapy (1 Male Senior) at target date.
          Only 1 eligible Male Senior therapist is available.
        Expected Results:
          1. IP patient therapy is prioritized, processed, and scheduled first.
          2. OP booking is held or marked failed due to resource exhaustion.
          3. DB confirms IP booking status='scheduled'.
        """
        target_date = DATE_CHECKLIST_5
        target_date_str = target_date.isoformat()
        room_b = _ensure_room("TR-2")

        # 1. Ingest draft bookings for both OP and IP patients.
        # OP is ingested first to demonstrate that allocation priority is NOT
        # dependent on ingestion/PK order, but strictly honors IP over OP priority.
        pat_op = PatientSnapshot.objects.create(
            pat_reg_no="50005", pat_name="OP Contention Patient", pat_sex="Male", pat_age="35"
        )
        assert pat_op.is_op() is True, "pat_op must be OP (5 digits)"

        alloc_op = TherapyAllocation.objects.create(
            patient=pat_op,
            therapy_code=self.therapy_medium.therapy_code,
            therapy_name=self.therapy_medium.therapy_name,
            from_date=target_date,
            to_date=target_date,
            days=1,
            timeslot=self.slot_1130,
            room=room_b,
            required_therapist_roles=[{"role": "senior", "count": 1}],
            status="draft",
        )
        booking_op = Booking.objects.create(
            allocation=alloc_op,
            date=target_date,
            timeslot=self.slot_1130,
            room=room_b,
            status="draft",
        )

        pat_ip = PatientSnapshot.objects.create(
            pat_reg_no="990055", pat_name="IP Contention Patient", pat_sex="Male", pat_age="45", pat_room_no="DS-2"
        )
        assert pat_ip.is_op() is False, "pat_ip must be IP (6 digits)"

        alloc_ip = TherapyAllocation.objects.create(
            patient=pat_ip,
            therapy_code=self.therapy_medium.therapy_code,
            therapy_name=self.therapy_medium.therapy_name,
            from_date=target_date,
            to_date=target_date,
            days=1,
            timeslot=self.slot_1130,
            room=self.room,
            required_therapist_roles=[{"role": "senior", "count": 1}],
            status="draft",
        )
        booking_ip = Booking.objects.create(
            allocation=alloc_ip,
            date=target_date,
            timeslot=self.slot_1130,
            room=self.room,
            status="draft",
        )

        try:
            # 2. Trigger bulk_allocate_for_date()
            res = bulk_allocate_for_date(target_date_str)
            assert res["success"] is True, f"bulk_allocate_for_date failed: {res}"

            # 3. Inspect allocation order: IP patient therapy is prioritized, processed, and scheduled first
            results = res.get("results", [])
            assert len(results) >= 2, f"Expected at least 2 processed results, got: {results}"

            alloc_order = [r["allocation_id"] for r in results]
            assert alloc_ip.id in alloc_order and alloc_op.id in alloc_order
            assert alloc_order.index(alloc_ip.id) < alloc_order.index(alloc_op.id), (
                f"IP allocation {alloc_ip.id} must be processed before OP allocation {alloc_op.id}!"
            )

            # DB confirms IP booking status='scheduled'
            booking_ip.refresh_from_db()
            assert booking_ip.status == "scheduled", (
                f"IP booking should be 'scheduled', got '{booking_ip.status}' (reason: {booking_ip.failure_reason})"
            )

            # OP booking is held or marked failed due to resource exhaustion
            booking_op.refresh_from_db()
            assert booking_op.status in ["failed", "draft"], (
                f"OP booking should be failed/held due to therapist exhaustion, got '{booking_op.status}'"
            )
            if booking_op.status == "failed":
                assert any(
                    err in booking_op.failure_reason.lower()
                    for err in ["insufficient_therapists", "unavailable", "booked", "exhaustion"]
                ), f"Unexpected failure reason for OP booking: {booking_op.failure_reason}"

        finally:
            TherapistBooking.objects.filter(date=target_date).delete()
            RoomBooking.objects.filter(date=target_date).delete()
            booking_ip.delete()
            booking_op.delete()
            alloc_ip.delete()
            alloc_op.delete()
            pat_ip.delete()
            pat_op.delete()

    def tearDown(self):
        test_dates = [DATE_CHECKLIST_3, DATE_CHECKLIST_5, DATE_CHECKLIST_6, DATE_CHECKLIST_7]
        TherapistBooking.objects.filter(date__in=test_dates).delete()
        RoomBooking.objects.filter(date__in=test_dates).delete()
        BookingAssignment.objects.filter(booking__date__in=test_dates).delete()
        Booking.objects.filter(date__in=test_dates).delete()
        TherapyAllocation.objects.filter(from_date__in=test_dates).delete()
        PatientSnapshot.objects.filter(
            pat_reg_no__in=["50001", "50101", "990061", "990062", "990071", "990072", "50005", "990055"]
        ).delete()
