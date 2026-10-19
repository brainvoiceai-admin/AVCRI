"""
Checklist #27: Emergency Leave Automated Invalidation & Substitute Reassignment Test Suite

Requirement:
    Registering emergency leave for a therapist invalidates their upcoming bookings
    and automatically triggers algorithmic reassignment to eligible substitute candidates.

Scenario (Checklist #27):
    Therapist T1 booked on 5 sessions tomorrow.
    Superadmin registers EmergencyLeave for T1.
    Candidate T2 is free and eligible.

Actions:
    1. Execute resheduleMorningandNight.py (process_reassignments).
    2. Query TherapistBooking and BookingAssignment.

Expected Outcomes:
    1. T1's 5 bookings are detected and invalidated.
    2. T1 is unassigned and reallocated to eligible candidate T2.
    3. Grade, gender, and slot constraints preserved.
"""
import pytest
from datetime import date, time, timedelta
from django.test import TestCase

from Sheduling.models import PatientSnapshot, TherapyAllocation, Booking, BookingAssignment
from masters.models import SlotMaster, TherapistGrade, TherapistMaster, TherapyMaster, EmergencyLeave
from Patient.models import TreatmentRoom, RoomName, TherapistBooking, RoomBooking, Therapist as PatientTherapist

from resheduleMorningandNight import process_reassignments


TOMORROW = date(2099, 8, 20)
TOMORROW_STR = TOMORROW.isoformat()


# ---------------------------------------------------------------------------
# Helper functions for master and transactional data creation
# ---------------------------------------------------------------------------
def _ensure_slot(number, slot_time):
    obj, _ = SlotMaster.objects.get_or_create(
        slot_number=number,
        defaults={"slot_time": slot_time, "is_active": True},
    )
    if obj.slot_time != slot_time:
        obj.slot_time = slot_time
        obj.save(update_fields=["slot_time"])
    return obj


def _ensure_grade(name, order):
    obj, _ = TherapistGrade.objects.get_or_create(
        name=name,
        defaults={"display_order": order, "is_active": True},
    )
    return obj


def _ensure_therapy(code, name, grade_counts):
    obj, _ = TherapyMaster.objects.get_or_create(
        therapy_code=code,
        defaults={
            "therapy_name": name,
            "therapy_category": "General",
            "therapy_duration": "30",
            "bathing_required": "No",
            "treatment_room_required": "Yes",
            "no_of_super_senior_therapist": grade_counts.get("super_senior", 0),
            "no_of_senior_therapist": grade_counts.get("senior", 1),
            "no_of_junior_therapist": grade_counts.get("junior", 0),
            "no_of_trainee_therapist": grade_counts.get("trainee", 0),
            "total_no_of_therapist": sum(grade_counts.values()),
            "is_active": True,
        },
    )
    return obj


def _ensure_therapist(code, name, gender, grade, emp_code):
    obj, _ = TherapistMaster.objects.get_or_create(
        therapist_code=code,
        defaults={
            "therapist_name": name,
            "therapist_gender": gender,
            "therapist_grade": grade,
            "employee_code": emp_code,
            "is_bathing_therapist": True,
            "is_helping_therapist": False,
            "is_active": True,
        },
    )
    if obj.therapist_gender != gender:
        obj.therapist_gender = gender
        obj.save(update_fields=["therapist_gender"])
    return obj


def _ensure_patient_therapist(therapist_master):
    """Ensure corresponding Patient.models.Therapist entry exists for BookingAssignment FK."""
    grade_name = (
        therapist_master.therapist_grade.name
        if hasattr(therapist_master, "therapist_grade") and therapist_master.therapist_grade
        else "Senior Therapist"
    )
    obj, _ = PatientTherapist.objects.get_or_create(
        therapist_code=therapist_master.therapist_code,
        defaults={
            "therapist_name": therapist_master.therapist_name,
            "therapist_grade": grade_name,
            "is_bathing_therapist": therapist_master.is_bathing_therapist,
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
class TestChecklist27EmergencyLeaveReassignment(TestCase):
    """
    Checklist #27: Tests automated invalidation and algorithmic substitute reassignment
    when emergency leave is registered for a booked therapist.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # Create 5 distinct slots for tomorrow:
        # 4 Forenoon/morning slots (06:30, 08:30, 10:00, 11:30) and 1 Afternoon slot (14:30)
        cls.slot1 = _ensure_slot(51, time(6, 30))
        cls.slot2 = _ensure_slot(52, time(8, 30))
        cls.slot3 = _ensure_slot(53, time(10, 0))
        cls.slot4 = _ensure_slot(54, time(11, 30))
        cls.slot5 = _ensure_slot(55, time(14, 30))
        cls.all_slots = [cls.slot1, cls.slot2, cls.slot3, cls.slot4, cls.slot5]

        cls.grade_senior = _ensure_grade("Senior Therapist", 2)
        cls.grade_junior = _ensure_grade("Junior Therapist", 3)

        cls.therapy = _ensure_therapy(
            "T_CHK27", "Checklist 27 Therapy", {"senior": 1}
        )

        # Primary booked therapist T1
        cls.t1 = _ensure_therapist(
            "TH_CHK27_T1", "Therapist T1 Primary", "Male", cls.grade_senior, "EMP_CHK27_T1"
        )
        cls.pt1 = _ensure_patient_therapist(cls.t1)

        # Eligible candidate therapist T2
        cls.t2 = _ensure_therapist(
            "TH_CHK27_T2", "Therapist T2 Substitute", "Male", cls.grade_senior, "EMP_CHK27_T2"
        )
        cls.pt2 = _ensure_patient_therapist(cls.t2)

        # Alternative female candidate T3
        cls.t3_fem = _ensure_therapist(
            "TH_CHK27_T3F", "Therapist T3 Female", "Female", cls.grade_senior, "EMP_CHK27_T3F"
        )
        cls.pt3_fem = _ensure_patient_therapist(cls.t3_fem)

        # Alternative candidate T4 (for load testing)
        cls.t4 = _ensure_therapist(
            "TH_CHK27_T4", "Therapist T4 Substitute", "Male", cls.grade_senior, "EMP_CHK27_T4"
        )
        cls.pt4 = _ensure_patient_therapist(cls.t4)

        cls.rooms = [_ensure_room(f"CHK27_R{i}") for i in range(1, 6)]

    def _create_session(self, patient, slot, room, therapist, pt_therapist, session_num):
        """
        Creates the complete set of models representing a confirmed session:
        1. TherapyAllocation
        2. Sheduling.models.Booking (status='scheduled')
        3. Sheduling.models.BookingAssignment (status='assigned')
        4. Patient.models.TherapistBooking (status='BOOKED')
        5. Patient.models.RoomBooking (status='BOOKED')
        """
        allocation = TherapyAllocation.objects.create(
            patient=patient,
            therapy_code=self.therapy.therapy_code,
            therapy_name=self.therapy.therapy_name,
            from_date=TOMORROW,
            to_date=TOMORROW + timedelta(days=6),
            days=7,
            timeslot=slot,
            room=room,
            required_therapist_roles=[{"role": "senior", "count": 1}],
            status="scheduled",
        )
        sched_booking = Booking.objects.create(
            allocation=allocation,
            date=TOMORROW,
            timeslot=slot,
            room=room,
            status="scheduled",
        )
        booking_assignment = BookingAssignment.objects.create(
            booking=sched_booking,
            therapist=pt_therapist,
            role="Senior Therapist",
            assigned_for="booking",
            status="assigned",
            booking_date=TOMORROW,
            booking_timeslot=slot,
        )
        therapist_booking = TherapistBooking.objects.create(
            therapist=therapist,
            patient_id=patient.id,
            visit=allocation,
            therapy_name=self.therapy.therapy_name,
            date=TOMORROW,
            time_slot=slot,
            status="BOOKED",
            is_bathing=False,
        )
        room_booking = RoomBooking.objects.create(
            room=room,
            patient_id=patient.id,
            therapy_name=self.therapy.therapy_name,
            date=TOMORROW,
            time_slot=slot,
            status="BOOKED",
        )
        return {
            "allocation": allocation,
            "sched_booking": sched_booking,
            "booking_assignment": booking_assignment,
            "therapist_booking": therapist_booking,
            "room_booking": room_booking,
        }

    def setUp(self):
        super().setUp()
        self.t4.is_active = False
        self.t4.save(update_fields=["is_active"])

    def tearDown(self):
        """Clean up all transactional records to ensure idempotent tests."""
        self.t4.is_active = True
        self.t4.save(update_fields=["is_active"])
        EmergencyLeave.objects.filter(from_date=TOMORROW).delete()
        TherapistBooking.objects.filter(date=TOMORROW).delete()
        RoomBooking.objects.filter(date=TOMORROW).delete()
        BookingAssignment.objects.filter(booking_date=TOMORROW).delete()
        Booking.objects.filter(date=TOMORROW).delete()
        TherapyAllocation.objects.filter(therapy_code=self.therapy.therapy_code).delete()
        PatientSnapshot.objects.filter(pat_reg_no__startswith="5000").delete()

    def test_checklist_27_five_sessions_emergency_leave_invalidation_and_reassignment(self):
        """
        Checklist #27:
        1. Therapist T1 booked on 5 sessions tomorrow across 5 time slots.
        2. Candidate T2 is free and eligible.
        3. Superadmin registers EmergencyLeave for T1.
        4. Execute resheduleMorningandNight.py.
        5. Verify:
           - T1's 5 bookings are detected and invalidated.
           - T1 is unassigned and all 5 sessions are reallocated to T2 in both
             TherapistBooking and BookingAssignment.
           - Grade, gender, and slot constraints are preserved.
        """
        # Create 5 distinct patients for the 5 sessions
        created_sessions = []
        for i, slot in enumerate(self.all_slots, start=1):
            pat = PatientSnapshot.objects.create(
                pat_reg_no=f"50000{i}",
                pat_name=f"Patient {i}",
                pat_sex="Male",
                pat_age="30",
            )
            session = self._create_session(
                patient=pat,
                slot=slot,
                room=self.rooms[i - 1],
                therapist=self.t1,
                pt_therapist=self.pt1,
                session_num=i,
            )
            created_sessions.append(session)

        # Verify initial state: T1 has 5 sessions booked tomorrow
        t1_initial_tb = TherapistBooking.objects.filter(
            therapist=self.t1, date=TOMORROW, status="BOOKED"
        ).count()
        t1_initial_ba = BookingAssignment.objects.filter(
            therapist__therapist_code=self.t1.therapist_code,
            booking_date=TOMORROW,
            status="assigned",
        ).count()
        assert t1_initial_tb == 5, f"Expected 5 initial TherapistBooking for T1, got {t1_initial_tb}"
        assert t1_initial_ba == 5, f"Expected 5 initial BookingAssignment for T1, got {t1_initial_ba}"

        # Candidate T2 has 0 sessions currently booked tomorrow
        t2_initial_tb = TherapistBooking.objects.filter(
            therapist=self.t2, date=TOMORROW, status="BOOKED"
        ).count()
        assert t2_initial_tb == 0, f"Expected 0 initial bookings for T2, got {t2_initial_tb}"

        # Superadmin registers EmergencyLeave for T1 for tomorrow
        EmergencyLeave.objects.create(
            therapist=self.t1,
            employee_code=self.t1.employee_code,
            from_date=TOMORROW,
            to_date=TOMORROW,
            is_half_day=False,
            status="new",
        )

        # -------------------------------------------------------------------
        # Step 1: Execute resheduleMorningandNight.py algorithmic reassignment
        # -------------------------------------------------------------------
        summary = process_reassignments(
            target_date=TOMORROW,
            dry_run=False,
            max_daily_normal=5,
            max_daily_overtime_extra=2,
        )

        # Verify execution summary
        assert summary["checked"] == 5, f"Expected 5 checked bookings, got {summary['checked']}"
        assert len(summary["reassigned"]) == 5, (
            f"Expected 5 reassigned bookings, got {len(summary['reassigned'])}. Failed: {summary['failed']}"
        )

        # -------------------------------------------------------------------
        # Step 2: Query TherapistBooking and BookingAssignment
        # -------------------------------------------------------------------
        # 1. T1's 5 bookings are detected and invalidated (0 active bookings remain for T1)
        t1_final_tb = TherapistBooking.objects.filter(
            therapist=self.t1, date=TOMORROW, status="BOOKED"
        ).count()
        t1_final_ba = BookingAssignment.objects.filter(
            therapist__therapist_code=self.t1.therapist_code,
            booking_date=TOMORROW,
            status="assigned",
        ).count()
        assert t1_final_tb == 0, (
            f"T1 bookings were NOT invalidated! T1 still has {t1_final_tb} active TherapistBooking rows."
        )
        assert t1_final_ba == 0, (
            f"T1 assignments were NOT invalidated! T1 still has {t1_final_ba} active BookingAssignment rows."
        )

        # 2. T1 is unassigned and reallocated to eligible candidate T2 in both models
        t2_final_tb_qs = TherapistBooking.objects.filter(
            therapist=self.t2, date=TOMORROW, status="BOOKED"
        ).select_related("time_slot", "therapist")
        t2_final_ba_qs = BookingAssignment.objects.filter(
            therapist__therapist_code=self.t2.therapist_code,
            booking_date=TOMORROW,
            status="assigned",
        ).select_related("booking_timeslot")

        assert t2_final_tb_qs.count() == 5, (
            f"Expected all 5 TherapistBooking rows to be reallocated to T2, got {t2_final_tb_qs.count()}"
        )
        assert t2_final_ba_qs.count() == 5, (
            f"Expected all 5 BookingAssignment rows to be reallocated to T2, got {t2_final_ba_qs.count()}"
        )

        # 3. Grade, gender, and slot constraints preserved:
        # Check Grade constraint: T2 is Senior Therapist
        assert self.t2.therapist_grade.name == "Senior Therapist"

        # Check Gender constraint: T2 is Male (matching male patients)
        assert self.t2.therapist_gender == "Male"

        # Check Slot constraint: Each session remains at its exact original time_slot
        reallocated_tb_slot_ids = {tb.time_slot_id for tb in t2_final_tb_qs}
        original_slot_ids = {s.id for s in self.all_slots}
        assert reallocated_tb_slot_ids == original_slot_ids, (
            f"Slot mismatch in TherapistBooking! Expected {original_slot_ids}, got {reallocated_tb_slot_ids}"
        )

        reallocated_ba_slot_ids = {ba.booking_timeslot_id for ba in t2_final_ba_qs}
        assert reallocated_ba_slot_ids == original_slot_ids, (
            f"Slot mismatch in BookingAssignment! Expected {original_slot_ids}, got {reallocated_ba_slot_ids}"
        )

    def test_dry_run_mode_simulates_without_db_modification(self):
        """Validates that dry_run=True detects affected bookings without mutating database."""
        pat = PatientSnapshot.objects.create(
            pat_reg_no="500099", pat_name="Dry Run Patient", pat_sex="Male", pat_age="35"
        )
        session = self._create_session(
            patient=pat,
            slot=self.slot1,
            room=self.rooms[0],
            therapist=self.t1,
            pt_therapist=self.pt1,
            session_num=1,
        )

        EmergencyLeave.objects.create(
            therapist=self.t1,
            employee_code=self.t1.employee_code,
            from_date=TOMORROW,
            to_date=TOMORROW,
            is_half_day=False,
        )

        summary = process_reassignments(target_date=TOMORROW, dry_run=True)
        assert summary["checked"] == 1
        assert len(summary["reassigned"]) == 1

        # DB must NOT be modified
        session["therapist_booking"].refresh_from_db()
        assert session["therapist_booking"].therapist_id == self.t1.id
        session["booking_assignment"].refresh_from_db()
        assert session["booking_assignment"].therapist.therapist_code == self.t1.therapist_code

    def test_gender_constraint_strictly_preserved_during_reassignment(self):
        """
        When T1 is booked for a Female patient and goes on emergency leave,
        reassignment MUST select female candidate T3_fem, NEVER male candidate T2.
        """
        pat_female = PatientSnapshot.objects.create(
            pat_reg_no="500088", pat_name="Female Patient", pat_sex="Female", pat_age="28"
        )
        session = self._create_session(
            patient=pat_female,
            slot=self.slot1,
            room=self.rooms[0],
            therapist=self.t1,
            pt_therapist=self.pt1,
            session_num=1,
        )

        # Both T2 (Male) and T3_fem (Female) are free
        EmergencyLeave.objects.create(
            therapist=self.t1,
            employee_code=self.t1.employee_code,
            from_date=TOMORROW,
            to_date=TOMORROW,
            is_half_day=False,
        )

        summary = process_reassignments(target_date=TOMORROW, dry_run=False)
        assert len(summary["reassigned"]) == 1

        # Must be reassigned to female candidate T3_fem
        session["therapist_booking"].refresh_from_db()
        assert session["therapist_booking"].therapist_id == self.t3_fem.id
        assert session["therapist_booking"].therapist.therapist_gender == "Female"

        session["booking_assignment"].refresh_from_db()
        assert session["booking_assignment"].therapist.therapist_code == self.t3_fem.therapist_code

    def test_male_child_under_5_exception_strictly_preserved_during_reassignment(self):
        """
        When T1 is booked for a Male child age 3 (< 5) and goes on emergency leave,
        reassignment MUST select female candidate T3_fem (exception rule).
        """
        pat_child = PatientSnapshot.objects.create(
            pat_reg_no="500077", pat_name="Little Boy", pat_sex="Male", pat_age="3"
        )
        session = self._create_session(
            patient=pat_child,
            slot=self.slot2,
            room=self.rooms[1],
            therapist=self.t1,
            pt_therapist=self.pt1,
            session_num=1,
        )

        EmergencyLeave.objects.create(
            therapist=self.t1,
            employee_code=self.t1.employee_code,
            from_date=TOMORROW,
            to_date=TOMORROW,
            is_half_day=False,
        )

        summary = process_reassignments(target_date=TOMORROW, dry_run=False)
        assert len(summary["reassigned"]) == 1

        session["therapist_booking"].refresh_from_db()
        assert session["therapist_booking"].therapist_id == self.t3_fem.id
        assert session["therapist_booking"].therapist.therapist_gender == "Female"

    def test_forenoon_half_day_leave_only_invalidates_morning_sessions(self):
        """
        When T1 registers a Forenoon half-day leave:
        - Morning sessions (slots 1-4) are invalidated and reassigned to T2.
        - Afternoon session (slot 5) remains allocated to T1.
        """
        morning_pat = PatientSnapshot.objects.create(
            pat_reg_no="500061", pat_name="Morning Patient", pat_sex="Male", pat_age="30"
        )
        afternoon_pat = PatientSnapshot.objects.create(
            pat_reg_no="500062", pat_name="Afternoon Patient", pat_sex="Male", pat_age="30"
        )

        morning_session = self._create_session(
            patient=morning_pat,
            slot=self.slot1,  # 06:30 (morning)
            room=self.rooms[0],
            therapist=self.t1,
            pt_therapist=self.pt1,
            session_num=1,
        )
        afternoon_session = self._create_session(
            patient=afternoon_pat,
            slot=self.slot5,  # 14:30 (afternoon)
            room=self.rooms[1],
            therapist=self.t1,
            pt_therapist=self.pt1,
            session_num=2,
        )

        # T1 registers Forenoon leave
        EmergencyLeave.objects.create(
            therapist=self.t1,
            employee_code=self.t1.employee_code,
            from_date=TOMORROW,
            to_date=TOMORROW,
            is_half_day=True,
            half_day_date=TOMORROW,
            half_day_session="Forenoon",
        )

        summary = process_reassignments(target_date=TOMORROW, dry_run=False)
        # Only the 1 morning session is affected
        assert summary["checked"] == 1
        assert len(summary["reassigned"]) == 1

        # Morning session reassigned to T2
        morning_session["therapist_booking"].refresh_from_db()
        assert morning_session["therapist_booking"].therapist_id == self.t2.id
        morning_session["booking_assignment"].refresh_from_db()
        assert morning_session["booking_assignment"].therapist.therapist_code == self.t2.therapist_code

        # Afternoon session remains allocated to T1!
        afternoon_session["therapist_booking"].refresh_from_db()
        assert afternoon_session["therapist_booking"].therapist_id == self.t1.id
        afternoon_session["booking_assignment"].refresh_from_db()
        assert afternoon_session["booking_assignment"].therapist.therapist_code == self.t1.therapist_code

    def test_least_loaded_candidate_prioritized(self):
        """
        When multiple eligible substitute candidates are available,
        the algorithm chooses the least loaded candidate (fewer sessions today).
        """
        self.t4.is_active = True
        self.t4.save(update_fields=["is_active"])

        # Pre-load T2 with 2 bookings on TOMORROW at slot1 and slot2
        for s in [self.slot1, self.slot2]:
            TherapistBooking.objects.create(
                therapist=self.t2, date=TOMORROW, time_slot=s, status="BOOKED"
            )

        # Candidate T4 has 0 sessions on TOMORROW
        # T1 has 1 session at slot3
        pat = PatientSnapshot.objects.create(
            pat_reg_no="500055", pat_name="Load Bal Patient", pat_sex="Male", pat_age="30"
        )
        session = self._create_session(
            patient=pat,
            slot=self.slot3,  # 10:00
            room=self.rooms[2],
            therapist=self.t1,
            pt_therapist=self.pt1,
            session_num=1,
        )

        EmergencyLeave.objects.create(
            therapist=self.t1,
            employee_code=self.t1.employee_code,
            from_date=TOMORROW,
            to_date=TOMORROW,
            is_half_day=False,
        )

        summary = process_reassignments(target_date=TOMORROW, dry_run=False)
        assert len(summary["reassigned"]) == 1

        # Least loaded candidate T4 (0 sessions) should be chosen over T2 (2 sessions)
        session["therapist_booking"].refresh_from_db()
        assert session["therapist_booking"].therapist_id == self.t4.id
        session["booking_assignment"].refresh_from_db()
        assert session["booking_assignment"].therapist.therapist_code == self.t4.therapist_code
