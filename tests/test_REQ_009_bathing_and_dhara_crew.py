"""
Regression Tests for Bathing & Dhara/Pizhichil Crew Allocation Rules:
  - Checklist #9: Bathing Therapist Assignment & Single-Flag Propagation
  - Checklist #15, #16, #17, #18: Dhara & Pizhichil Crew Composition & Senior Pot-Handler Daily Limit

Specification References:
    1. Checklist #9 (Bathing Therapist Assignment & Single-Flag Propagation):
       If bathing_required='Yes', at least one therapist with is_bathing_therapist=True
       must be assigned, and exactly one assigned therapist gets is_bathing=True per visit.
       Therapy has bathing_required='Yes'. Pool contains 1 Senior non-bathing and 1 Junior bathing therapist.
       Expected Results:
         - At least one therapist with is_bathing_therapist=True is allocated.
         - In TherapistBooking, is_bathing flag is set to True for exactly one therapist and False for co-therapists.

    2. Checklist #15, #16, #17, #18 (Dhara & Pizhichil Crew & Senior Pot-Handler Daily Limit):
       Dhara/Pizhichil requires a 4 Senior + 2 Junior crew. Exactly one Senior handles
       the pot (highlighted as is_senior=True, strictly non-bathing) and is limited to at most
       2 senior-tagged sessions per day.
       Therapy matches special Dhara/Pizhichil list (e.g., 'dhara & pizhichil (6)').
       Senior T1 already has 2 senior-tagged sessions today; Senior T2 has 0.
       Expected Results:
         - Crew assigned strictly adheres to required breakdown (4 Senior, 2 Junior).
         - Exactly one Senior is tagged as senior pot-handler (is_senior=True), and strictly has is_bathing=False.
         - T1 is bypassed for the senior tag because the daily limit of 2 is reached (current < 2); T2 is assigned the tag.
         - Non-senior therapist is assigned is_bathing=True.
"""
import pytest
from datetime import date, time
from unittest.mock import patch
from django.test import TestCase

from Sheduling.models import PatientSnapshot, TherapyAllocation, Booking, BookingAssignment
from masters.models import SlotMaster, TherapistGrade, TherapistMaster, TherapyMaster
from Patient.models import TreatmentRoom, RoomName, TherapistBooking, RoomBooking
from reshedule import (
    expand_therapies_for_visit,
    is_treatment_requiring_senior_tag,
    get_senior_tag_count_for_therapist,
)


DATE_CHECKLIST_9 = date(2099, 4, 10)
DATE_CHECKLIST_DHARA = date(2099, 4, 11)


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


def _ensure_therapy(code, name, category="Medium", bathing="Yes", grade_counts=None):
    if grade_counts is None:
        grade_counts = {"senior": 1}
    obj, _ = TherapyMaster.objects.get_or_create(
        therapy_code=code,
        defaults={
            "therapy_name": name,
            "therapy_category": category,
            "therapy_duration": "45",
            "bathing_required": bathing,
            "treatment_room_required": "Yes",
            "no_of_super_senior_therapist": grade_counts.get("super_senior", 0),
            "no_of_senior_therapist": grade_counts.get("senior", 0),
            "no_of_junior_therapist": grade_counts.get("junior", 0),
            "no_of_trainee_therapist": grade_counts.get("trainee", 0),
            "total_no_of_therapist": sum(grade_counts.values()),
            "patient_type": "IP",
            "is_active": True,
        },
    )
    return obj


def _ensure_therapist(code, name, gender, grade, employee_code, is_bathing=True):
    obj, _ = TherapistMaster.objects.get_or_create(
        therapist_code=code,
        defaults={
            "therapist_name": name,
            "therapist_gender": gender,
            "therapist_grade": grade,
            "employee_code": employee_code,
            "is_bathing_therapist": is_bathing,
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
class TestBathingAndDharaCrewScheduling(TestCase):
    """
    Regression suite for:
      - Checklist #9: Bathing Therapist Assignment & Single-Flag Propagation
      - Checklist #15, #16, #17, #18: Dhara & Pizhichil Crew Composition & Senior Pot-Handler Daily Limit
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        # Standard time slots
        cls.slot_0630 = _ensure_slot(1, time(6, 30))
        cls.slot_0830 = _ensure_slot(2, time(8, 30))
        cls.slot_1000 = _ensure_slot(3, time(10, 0))
        cls.slot_1130 = _ensure_slot(4, time(11, 30))
        cls.slot_1430 = _ensure_slot(5, time(14, 30))
        cls.slot_1600 = _ensure_slot(6, time(16, 0))
        cls.slot_1730 = _ensure_slot(7, time(17, 30))

        # Grades
        cls.grade_senior = _ensure_grade("Senior Therapist", 2)
        cls.grade_junior = _ensure_grade("Junior Therapist", 3)

        # Room TR-1 (used by patient in staying room DS-1)
        cls.room = _ensure_room("TR-1")

        # Checklist #9 Therapy: 1 Senior + 1 Junior, bathing_required='Yes'
        cls.therapy_bath_9 = _ensure_therapy(
            code="T_BATH_009",
            name="Abhyangam with Bath REQ009",
            category="Medium",
            bathing="Yes",
            grade_counts={"senior": 1, "junior": 1},
        )

        # Checklist #15-18 Therapy: Dhara & Pizhichil (6) (4 Senior + 2 Junior, bathing_required='Yes')
        cls.therapy_dhara = _ensure_therapy(
            code="T_DHARA_006",
            name="dhara & pizhichil (6)",
            category="Special",
            bathing="Yes",
            grade_counts={"senior": 4, "junior": 2},
        )

    # -----------------------------------------------------------------------
    # Checklist #9: Bathing Therapist Assignment & Single-Flag Propagation
    # -----------------------------------------------------------------------
    @patch("final_allocation.is_patient_active", return_value=True)
    @patch("reshedule.is_patient_active", return_value=True)
    def test_bathing_therapist_assignment_and_single_flag_propagation(self, mock_is_act_resh, mock_is_act_final):
        """
        Checklist #9:
        If bathing_required='Yes', at least one therapist with is_bathing_therapist=True
        must be assigned, and exactly one assigned therapist gets is_bathing=True per visit.
        Pool contains:
          - 1 Senior non-bathing (is_bathing_therapist=False)
          - 1 Junior bathing (is_bathing_therapist=True)
        """
        target_date = DATE_CHECKLIST_9
        target_date_str = target_date.isoformat()

        # Pool: 1 Senior non-bathing, 1 Junior bathing
        thr_senior_nonbath = _ensure_therapist(
            "THR_009_S_NONBATH", "Senior Non-Bathing 009", "Male",
            self.grade_senior, "EMP_009_S_NB", is_bathing=False,
        )
        thr_junior_bath = _ensure_therapist(
            "THR_009_J_BATH", "Junior Bathing 009", "Male",
            self.grade_junior, "EMP_009_J_B", is_bathing=True,
        )

        patient = PatientSnapshot.objects.create(
            pat_reg_no="990091", pat_name="Bathing Test Patient", pat_sex="Male", pat_age="30", pat_room_no="DS-1"
        )
        alloc = TherapyAllocation.objects.create(
            patient=patient,
            therapy_code=self.therapy_bath_9.therapy_code,
            therapy_name=self.therapy_bath_9.therapy_name,
            from_date=target_date,
            to_date=target_date,
            days=1,
            timeslot=self.slot_0830,
            room=self.room,
            required_therapist_roles=[{"role": "senior", "count": 1}, {"role": "junior", "count": 1}],
            status="draft",
        )
        booking = Booking.objects.create(
            allocation=alloc,
            date=target_date,
            timeslot=self.slot_0830,
            room=self.room,
            status="draft",
        )

        try:
            # 1. Trigger scheduling engine
            tasks = expand_therapies_for_visit(alloc.id, target_date_str, create_bookings=True)
            booking.refresh_from_db()
            assert booking.status == "scheduled", f"Booking failed to schedule: {booking.failure_reason}"

            # 2. Inspect assigned therapists and flags in TherapistBooking
            tb_qs = TherapistBooking.objects.filter(visit=alloc, date=target_date, status="BOOKED")
            assert tb_qs.count() == 2, f"Expected 2 therapists booked, got {tb_qs.count()}"

            # Expected 1: At least one therapist with is_bathing_therapist=True is allocated
            assigned_master_therapists = [tb.therapist for tb in tb_qs]
            assert any(t.is_bathing_therapist for t in assigned_master_therapists), (
                "No therapist with is_bathing_therapist=True was allocated for bathing therapy!"
            )
            assert thr_junior_bath in assigned_master_therapists, "Junior bathing therapist was not allocated"
            assert thr_senior_nonbath in assigned_master_therapists, "Senior non-bathing therapist was not allocated"

            # Expected 2: is_bathing flag is set to True for EXACTLY one therapist and False for co-therapists
            bathing_bookings = tb_qs.filter(is_bathing=True)
            non_bathing_bookings = tb_qs.filter(is_bathing=False)

            assert bathing_bookings.count() == 1, (
                f"Exactly one therapist must have is_bathing=True, got {bathing_bookings.count()}"
            )
            assert non_bathing_bookings.count() == 1, (
                f"Co-therapist must have is_bathing=False, got {non_bathing_bookings.count()}"
            )

            # Junior bathing therapist must be the one with is_bathing=True
            assert bathing_bookings.first().therapist == thr_junior_bath
            # Senior non-bathing therapist must have is_bathing=False
            assert non_bathing_bookings.first().therapist == thr_senior_nonbath

        finally:
            TherapistBooking.objects.filter(visit=alloc).delete()
            RoomBooking.objects.filter(therapy=alloc).delete()
            booking.delete()
            alloc.delete()
            patient.delete()
            thr_senior_nonbath.delete()
            thr_junior_bath.delete()

    # -----------------------------------------------------------------------
    # Checklist #15, #16, #17, #18: Dhara/Pizhichil Crew & Senior Pot-Handler
    # -----------------------------------------------------------------------
    @patch("final_allocation.is_patient_active", return_value=True)
    @patch("reshedule.is_patient_active", return_value=True)
    def test_dhara_crew_composition_and_senior_pot_handler_limit(self, mock_is_act_resh, mock_is_act_final):
        """
        Checklist #15, #16, #17, #18:
        Dhara/Pizhichil requires a 4 Senior + 2 Junior crew.
        Exactly one Senior handles the pot (tagged as senior pot-handler, strictly non-bathing)
        and is limited to at most 2 senior-tagged sessions per day.
        Senior T1 already has 2 senior-tagged sessions today; Senior T2 has 0.
        Expected Results:
          1. Crew assigned strictly adheres to required breakdown (4 Senior, 2 Junior).
          2. Exactly one Senior is tagged as senior pot-handler (is_senior=True), and strictly has is_bathing=False.
          3. T1 is bypassed for the senior tag because the daily limit of 2 is reached (current < 2); T2 is assigned the tag.
          4. Non-senior therapist is assigned is_bathing=True.
        """
        target_date = DATE_CHECKLIST_DHARA
        target_date_str = target_date.isoformat()

        # Sanity check: Ensure therapy name matches the special senior tag list
        assert is_treatment_requiring_senior_tag("dhara & pizhichil (6)") is True

        # Pool setup: 4 Seniors + 2 Juniors
        # Senior T1: Will have 2 prior senior sessions today
        thr_s1 = _ensure_therapist(
            "THR_DHARA_S1", "Senior T1 (Saturated)", "Male",
            self.grade_senior, "EMP_DHARA_S1", is_bathing=True,
        )
        # Senior T2: Will receive the senior pot-handler tag
        thr_s2 = _ensure_therapist(
            "THR_DHARA_S2", "Senior T2 (Available)", "Male",
            self.grade_senior, "EMP_DHARA_S2", is_bathing=False,
        )
        thr_s3 = _ensure_therapist(
            "THR_DHARA_S3", "Senior T3", "Male",
            self.grade_senior, "EMP_DHARA_S3", is_bathing=False,
        )
        thr_s4 = _ensure_therapist(
            "THR_DHARA_S4", "Senior T4", "Male",
            self.grade_senior, "EMP_DHARA_S4", is_bathing=False,
        )
        # 2 Juniors (at least one is bathing therapist)
        thr_j1 = _ensure_therapist(
            "THR_DHARA_J1", "Junior J1 (Bathing)", "Male",
            self.grade_junior, "EMP_DHARA_J1", is_bathing=True,
        )
        thr_j2 = _ensure_therapist(
            "THR_DHARA_J2", "Junior J2", "Male",
            self.grade_junior, "EMP_DHARA_J2", is_bathing=False,
        )

        # Setup prior sessions: Give Senior T1 exactly 2 senior-tagged sessions earlier today (at 06:30 and 08:30)
        dummy_pat = PatientSnapshot.objects.create(
            pat_reg_no="990098", pat_name="Prior Dhara Patient", pat_sex="Male", pat_age="45"
        )
        prior_tb1 = TherapistBooking.objects.create(
            therapist=thr_s1,
            date=target_date,
            time_slot=self.slot_0630,
            status="BOOKED",
            is_bathing=False,  # Non-bathing in Dhara = senior pot-handler session
            therapy_name="dhara & pizhichil (6)",
            patient_id=dummy_pat.id,
        )
        prior_tb2 = TherapistBooking.objects.create(
            therapist=thr_s1,
            date=target_date,
            time_slot=self.slot_0830,
            status="BOOKED",
            is_bathing=False,
            therapy_name="dhara & pizhichil (6)",
            patient_id=dummy_pat.id,
        )

        # Verify Senior T1 has reached daily limit of 2, while T2 has 0
        assert get_senior_tag_count_for_therapist(thr_s1, target_date) == 2, "Senior T1 should have 2 prior sessions"
        assert get_senior_tag_count_for_therapist(thr_s2, target_date) == 0, "Senior T2 should have 0 prior sessions"

        # Create Patient and draft allocation for Dhara booking at 10:00 (when T1, T2, etc. are free)
        patient = PatientSnapshot.objects.create(
            pat_reg_no="990092", pat_name="Dhara Patient", pat_sex="Male", pat_age="40", pat_room_no="DS-1"
        )
        alloc = TherapyAllocation.objects.create(
            patient=patient,
            therapy_code=self.therapy_dhara.therapy_code,
            therapy_name=self.therapy_dhara.therapy_name,
            from_date=target_date,
            to_date=target_date,
            days=1,
            timeslot=self.slot_1000,
            room=self.room,
            required_therapist_roles=[{"role": "senior", "count": 4}, {"role": "junior", "count": 2}],
            status="draft",
        )
        booking = Booking.objects.create(
            allocation=alloc,
            date=target_date,
            timeslot=self.slot_1000,
            room=self.room,
            status="draft",
        )

        try:
            # 1. Trigger allocation for Dhara booking
            tasks = expand_therapies_for_visit(alloc.id, target_date_str, create_bookings=True)
            booking.refresh_from_db()
            assert booking.status == "scheduled", f"Dhara booking failed to schedule: {booking.failure_reason}"
            assert isinstance(tasks, list) and len(tasks) > 0

            # 2. Inspect crew composition
            tb_qs = TherapistBooking.objects.filter(visit=alloc, date=target_date, status="BOOKED")
            assert tb_qs.count() == 6, f"Expected 6 therapists in crew, got {tb_qs.count()}"

            seniors_booked = [tb for tb in tb_qs if tb.therapist.therapist_grade.name == "Senior Therapist"]
            juniors_booked = [tb for tb in tb_qs if tb.therapist.therapist_grade.name == "Junior Therapist"]

            # Expected 1: Crew strictly adheres to breakdown (4 Senior, 2 Junior)
            assert len(seniors_booked) == 4, f"Expected 4 Seniors, got {len(seniors_booked)}"
            assert len(juniors_booked) == 2, f"Expected 2 Juniors, got {len(juniors_booked)}"

            # Expected 2 & 3: Senior tag limit & Pot-handler assignment
            # In task audit: exactly one Senior is tagged with is_senior=True
            assigned_task_therapists = tasks[0].get("therapists", [])
            senior_tagged_list = [t for t in assigned_task_therapists if t.get("is_senior") is True]

            assert len(senior_tagged_list) == 1, (
                f"Exactly one senior must be tagged as senior pot-handler, got {len(senior_tagged_list)}"
            )
            tagged_senior_code = senior_tagged_list[0]["therapist_code"]

            # T1 was bypassed because count == 2 (limit reached); T2 was assigned
            assert tagged_senior_code != thr_s1.therapist_code, (
                "Senior T1 must be bypassed for the senior tag as they already reached daily limit of 2!"
            )
            assert tagged_senior_code == thr_s2.therapist_code, (
                f"Senior T2 should have received senior pot-handler tag, got {tagged_senior_code}"
            )

            # Senior pot-handler strictly has is_bathing=False
            assert senior_tagged_list[0]["is_bathing"] is False, (
                "Senior pot-handler must strictly have is_bathing=False!"
            )
            tb_t2 = tb_qs.get(therapist=thr_s2)
            assert tb_t2.is_bathing is False, "Senior T2 must have is_bathing=False in TherapistBooking!"

            # Expected 4: Non-senior therapist is assigned is_bathing=True
            bathing_tbs = tb_qs.filter(is_bathing=True)
            assert bathing_tbs.count() == 1, f"Exactly one therapist must be bathing, got {bathing_tbs.count()}"
            bathing_assigned_tb = bathing_tbs.first()

            assert bathing_assigned_tb.therapist.therapist_code != thr_s2.therapist_code, (
                "The senior pot-handler cannot be assigned as the bathing therapist!"
            )
            assert bathing_assigned_tb.therapist.therapist_grade.name == "Junior Therapist", (
                "A non-senior (junior) therapist should be assigned is_bathing=True"
            )

        finally:
            prior_tb1.delete()
            prior_tb2.delete()
            dummy_pat.delete()
            TherapistBooking.objects.filter(visit=alloc).delete()
            RoomBooking.objects.filter(therapy=alloc).delete()
            booking.delete()
            alloc.delete()
            patient.delete()
            thr_s1.delete()
            thr_s2.delete()
            thr_s3.delete()
            thr_s4.delete()
            thr_j1.delete()
            thr_j2.delete()

    def tearDown(self):
        test_dates = [DATE_CHECKLIST_9, DATE_CHECKLIST_DHARA]
        TherapistBooking.objects.filter(date__in=test_dates).delete()
        RoomBooking.objects.filter(date__in=test_dates).delete()
        BookingAssignment.objects.filter(booking__date__in=test_dates).delete()
        Booking.objects.filter(date__in=test_dates).delete()
        TherapyAllocation.objects.filter(from_date__in=test_dates).delete()
        PatientSnapshot.objects.filter(
            pat_reg_no__in=["990091", "990092", "990098"]
        ).delete()
