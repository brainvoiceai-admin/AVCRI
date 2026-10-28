"""
Regression and Feature Test: Hard Treatment Scheduling Rule (Requirement 4)

Specifications:
1. Two hard treatments should not be scheduled in the same session (morning or evening) for the same patient on any given day.
   - Morning session: slots with slot_time < 13:00 (06:30, 08:30, 10:00, 11:30; slots 1-4).
   - Evening session: slots with slot_time >= 13:00 (14:30, 16:00, 17:30; slots 5-7).
2. Exception: Medium and Easy treatments can be assigned in the same session (e.g., Lepam).
3. For a patient with 4 treatments:
   - No two hard treatments should be scheduled in morning or evening session.
   - Other combinations (e.g., 1 Hard + 1 Medium in morning, 1 Hard + 1 Easy in evening) CAN be assigned.
4. Rescheduling and options APIs:
   - Preferred morning slot for second hard treatment falls back to evening slot.
   - Options API excludes slots from the conflicting session.
   - API endpoints (therapy_entry, allocate_therapy) return 400 with 'two_hard_treatments_same_session' if attempted.
"""
import json
import pytest
from datetime import date, time, timedelta
from django.test import TestCase, RequestFactory

from authentication.models import CustomUser
from masters.models import (
    SlotMaster, TherapistGrade, TherapistMaster, TherapyMaster
)
from Patient.models import TreatmentRoom, RoomName, TherapistBooking, RoomBooking
from Sheduling.models import PatientSnapshot, TherapyAllocation, Booking, BookingAssignment
import reshedule
from reshedule import (
    is_hard_treatment,
    get_slot_session,
    patient_has_hard_treatment_in_session,
    get_allowed_slot_values,
)
import final_allocation
from Sheduling.views import therapy_entry, allocate_therapy, reschedule_options_api


@pytest.mark.django_db
class TestHardTreatmentScheduling(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        from authentication.models import Module
        Module.objects.get_or_create(name="therapy_scheduling", defaults={"display_name": "Therapy Scheduling", "is_active": True})
        self.admin_user = CustomUser.objects.create_user(username="admin_hard_test", role="super_admin")
        self.target_date = date(2099, 11, 10)

        # Create Standard 7 Slots:
        # Morning: 06:30 (1), 08:30 (2), 10:00 (3), 11:30 (4)
        # Evening: 14:30 (5), 16:00 (6), 17:30 (7)
        self.slot_0630 = SlotMaster.objects.create(slot_number=1, slot_time=time(6, 30), is_active=True)
        self.slot_0830 = SlotMaster.objects.create(slot_number=2, slot_time=time(8, 30), is_active=True)
        self.slot_1000 = SlotMaster.objects.create(slot_number=3, slot_time=time(10, 0), is_active=True)
        self.slot_1130 = SlotMaster.objects.create(slot_number=4, slot_time=time(11, 30), is_active=True)
        self.slot_1430 = SlotMaster.objects.create(slot_number=5, slot_time=time(14, 30), is_active=True)
        self.slot_1600 = SlotMaster.objects.create(slot_number=6, slot_time=time(16, 0), is_active=True)
        self.slot_1730 = SlotMaster.objects.create(slot_number=7, slot_time=time(17, 30), is_active=True)

        # Therapist Grades
        self.grade_senior = TherapistGrade.objects.create(name="Senior Therapist", display_order=1, is_active=True)
        self.grade_junior = TherapistGrade.objects.create(name="Junior Therapist", display_order=2, is_active=True)

        # Therapists
        self.th1 = TherapistMaster.objects.create(
            therapist_code="TH001",
            employee_code="EMP001",
            therapist_name="Therapist One",
            therapist_grade=self.grade_senior,
            therapist_gender="male",
            is_active=True,
            is_bathing_therapist=True,
        )
        self.th2 = TherapistMaster.objects.create(
            therapist_code="TH002",
            employee_code="EMP002",
            therapist_name="Therapist Two",
            therapist_grade=self.grade_junior,
            therapist_gender="male",
            is_active=True,
            is_bathing_therapist=False,
        )
        self.th3 = TherapistMaster.objects.create(
            therapist_code="TH003",
            employee_code="EMP003",
            therapist_name="Therapist Three",
            therapist_grade=self.grade_junior,
            therapist_gender="male",
            is_active=True,
            is_bathing_therapist=False,
        )
        self.th4 = TherapistMaster.objects.create(
            therapist_code="TH004",
            employee_code="EMP004",
            therapist_name="Therapist Four",
            therapist_grade=self.grade_senior,
            therapist_gender="male",
            is_active=True,
            is_bathing_therapist=True,
        )

        # Treatment Rooms
        rn1, _ = RoomName.objects.get_or_create(name="Room TR-1", defaults={"is_active": True})
        self.room1, _ = TreatmentRoom.objects.get_or_create(room_no="TR-1", defaults={"room_name": rn1, "is_active": True})
        rn2, _ = RoomName.objects.get_or_create(name="Room TR-2", defaults={"is_active": True})
        self.room2, _ = TreatmentRoom.objects.get_or_create(room_no="TR-2", defaults={"room_name": rn2, "is_active": True})

        # Therapy Masters
        self.therapy_hard_1 = TherapyMaster.objects.create(
            therapy_code="TH_HARD_1",
            therapy_name="Abhyangam Hard",
            therapy_category="Hard",
            therapy_duration="45",
            bathing_required="No",
            treatment_room_required="Yes",
            total_no_of_therapist=1,
            no_of_senior_therapist=1,
            patient_type="IP",
            is_active=True,
        )
        self.therapy_hard_2 = TherapyMaster.objects.create(
            therapy_code="TH_HARD_2",
            therapy_name="Pizhichil Hard",
            therapy_category="Hard",
            therapy_duration="45",
            bathing_required="No",
            treatment_room_required="Yes",
            total_no_of_therapist=1,
            no_of_senior_therapist=1,
            patient_type="IP",
            is_active=True,
        )
        self.therapy_medium = TherapyMaster.objects.create(
            therapy_code="TH_MED_1",
            therapy_name="Shirodhara Medium",
            therapy_category="Medium",
            therapy_duration="45",
            bathing_required="No",
            treatment_room_required="Yes",
            total_no_of_therapist=1,
            no_of_senior_therapist=0,
            patient_type="IP",
            is_active=True,
        )
        self.therapy_easy = TherapyMaster.objects.create(
            therapy_code="TH_EASY_1",
            therapy_name="Lepam Easy",
            therapy_category="Easy",
            therapy_duration="45",
            bathing_required="No",
            treatment_room_required="Yes",
            total_no_of_therapist=1,
            no_of_senior_therapist=0,
            patient_type="IP",
            is_active=True,
        )

        # Patient Snapshot
        self.patient = PatientSnapshot.objects.create(
            pat_reg_no="10001",
            pat_name="John Doe",
            pat_age="45",
            pat_sex="male",
            pat_room_no="DS-1"
        )

    def test_helpers_identification_and_session_mapping(self):
        """Verify is_hard_treatment and get_slot_session return expected values."""
        # is_hard_treatment
        assert is_hard_treatment(therapy_obj=self.therapy_hard_1) is True
        assert is_hard_treatment(therapy_code="TH_HARD_2") is True
        assert is_hard_treatment(therapy_name="Abhyangam Hard") is True
        assert is_hard_treatment(category="Hard") is True
        assert is_hard_treatment(category="hard") is True

        # Medium and Easy are NOT hard treatments
        assert is_hard_treatment(therapy_obj=self.therapy_medium) is False
        assert is_hard_treatment(therapy_code="TH_MED_1") is False
        assert is_hard_treatment(therapy_obj=self.therapy_easy) is False
        assert is_hard_treatment(therapy_code="TH_EASY_1") is False
        assert is_hard_treatment(category="Medium") is False
        assert is_hard_treatment(category="Easy") is False

        # get_slot_session
        assert get_slot_session(self.slot_0630) == "morning"
        assert get_slot_session(self.slot_0830) == "morning"
        assert get_slot_session(self.slot_1000) == "morning"
        assert get_slot_session(self.slot_1130) == "morning"
        assert get_slot_session("08:30") == "morning"
        assert get_slot_session(time(11, 30)) == "morning"
        assert get_slot_session(1) == "morning"

        assert get_slot_session(self.slot_1430) == "evening"
        assert get_slot_session(self.slot_1600) == "evening"
        assert get_slot_session(self.slot_1730) == "evening"
        assert get_slot_session("14:30") == "evening"
        assert get_slot_session(time(16, 0)) == "evening"
        assert get_slot_session(5) == "evening"

    def test_patient_has_hard_treatment_in_session(self):
        """Verify detection of existing hard treatment in morning or evening session."""
        # Initially, patient has no treatments
        assert not patient_has_hard_treatment_in_session(self.patient.id, self.target_date, "morning")
        assert not patient_has_hard_treatment_in_session(self.patient.id, self.target_date, "evening")

        # Create a hard treatment booking in morning (08:30)
        alloc_hard = TherapyAllocation.objects.create(
            patient=self.patient,
            therapy_code=self.therapy_hard_1.therapy_code,
            therapy_name=self.therapy_hard_1.therapy_name,
            from_date=self.target_date,
            to_date=self.target_date,
            days=1,
            timeslot=self.slot_0830,
            status="scheduled",
        )
        b_hard = Booking.objects.create(
            allocation=alloc_hard,
            date=self.target_date,
            timeslot=self.slot_0830,
            status="scheduled",
            snapshot_therapy_name=self.therapy_hard_1.therapy_name,
        )

        # Now morning session must report True, while evening must report False
        assert patient_has_hard_treatment_in_session(self.patient.id, self.target_date, "morning") is True
        assert patient_has_hard_treatment_in_session(self.patient.id, self.target_date, "evening") is False

        # Exclude this booking -> should report False
        assert patient_has_hard_treatment_in_session(
            self.patient.id, self.target_date, "morning", exclude_booking_id=b_hard.id
        ) is False

    def test_get_allowed_slot_values_filters_conflicting_session(self):
        """When patient has a hard treatment in morning, get_allowed_slot_values for another hard excludes morning."""
        # Create an active morning hard treatment
        alloc_morning_hard = TherapyAllocation.objects.create(
            patient=self.patient,
            therapy_code=self.therapy_hard_1.therapy_code,
            therapy_name=self.therapy_hard_1.therapy_name,
            from_date=self.target_date,
            to_date=self.target_date,
            days=1,
            timeslot=self.slot_0830,
            status="scheduled",
        )
        Booking.objects.create(
            allocation=alloc_morning_hard,
            date=self.target_date,
            timeslot=self.slot_0830,
            status="scheduled",
            snapshot_therapy_name=self.therapy_hard_1.therapy_name,
        )

        # For another Hard treatment, allowed slots must exclude morning (06:30, 08:30, 10:00)
        # IP Hard slots without restriction: ["06:30", "08:30", "10:00", "14:30", "16:00"]
        allowed_for_hard = get_allowed_slot_values(
            patient_type="IP",
            therapy_category="Hard",
            therapy_name=self.therapy_hard_2.therapy_name,
            therapy_code=self.therapy_hard_2.therapy_code,
            patient_id=self.patient.id,
            target_date=self.target_date,
        )
        # Only evening slots remaining
        assert allowed_for_hard == ["14:30", "16:00"]
        assert "06:30" not in allowed_for_hard
        assert "08:30" not in allowed_for_hard
        assert "10:00" not in allowed_for_hard

        # EXCEPTION VERIFIED: For an Easy/Medium treatment (e.g. Lepam), morning slots are NOT excluded!
        allowed_for_easy = get_allowed_slot_values(
            patient_type="IP",
            therapy_category="Easy",
            therapy_name=self.therapy_easy.therapy_name,
            therapy_code=self.therapy_easy.therapy_code,
            patient_id=self.patient.id,
            target_date=self.target_date,
        )
        # Morning slots must still be present for Easy/Medium (e.g. 08:30, 10:00)
        assert "08:30" in allowed_for_easy
        assert "10:00" in allowed_for_easy

    def test_four_treatments_same_patient_scheduling(self):
        """
        User Requirement:
        For a patient with 4 treatments, no two hard treatments should be scheduled
        at mrng or evening session, but other combinations can be assigned.
        E.g.: 2 Hard (1 morning, 1 evening), 1 Medium (morning), 1 Easy (evening).
        """
        # 1. First Hard Treatment in Morning (08:30)
        alloc_h1 = TherapyAllocation.objects.create(
            patient=self.patient,
            therapy_code=self.therapy_hard_1.therapy_code,
            therapy_name=self.therapy_hard_1.therapy_name,
            from_date=self.target_date,
            to_date=self.target_date,
            days=1,
            timeslot=self.slot_0830,
            room=self.room1,
            status="scheduled",
        )
        b_h1 = Booking.objects.create(
            allocation=alloc_h1,
            date=self.target_date,
            timeslot=self.slot_0830,
            room=self.room1,
            status="scheduled",
            snapshot_therapy_name=self.therapy_hard_1.therapy_name,
        )

        # 2. Medium Treatment in Morning (10:00) -> Allowed in the SAME morning session as Hard 1!
        alloc_m = TherapyAllocation.objects.create(
            patient=self.patient,
            therapy_code=self.therapy_medium.therapy_code,
            therapy_name=self.therapy_medium.therapy_name,
            from_date=self.target_date,
            to_date=self.target_date,
            days=1,
            timeslot=self.slot_1000,
            room=self.room2,
            status="scheduled",
        )
        b_m = Booking.objects.create(
            allocation=alloc_m,
            date=self.target_date,
            timeslot=self.slot_1000,
            room=self.room2,
            status="scheduled",
            snapshot_therapy_name=self.therapy_medium.therapy_name,
        )

        # 3. Second Hard Treatment -> Preferred slot is morning (06:30), but should be rejected and fall back to evening!
        alloc_h2 = TherapyAllocation.objects.create(
            patient=self.patient,
            therapy_code=self.therapy_hard_2.therapy_code,
            therapy_name=self.therapy_hard_2.therapy_name,
            from_date=self.target_date,
            to_date=self.target_date,
            days=1,
            timeslot=self.slot_0630,  # Morning slot requested
            room=self.room1,
            status="draft",
        )
        b_h2 = Booking.objects.create(
            allocation=alloc_h2,
            date=self.target_date,
            timeslot=self.slot_0630,
            room=self.room1,
            status="draft",
            snapshot_therapy_name=self.therapy_hard_2.therapy_name,
        )

        # Run reschedule expansion for alloc_h2
        tasks_h2 = reshedule.expand_therapies_for_visit(
            alloc_h2.id,
            self.target_date,
            create_bookings=True,
            force_slot_only=False,
        )
        # Reschedule should NOT place Hard 2 in morning; it must be placed in evening (14:30 or 16:00)!
        b_h2.refresh_from_db()
        assert b_h2.status in ("BOOKED", "scheduled")
        assert get_slot_session(b_h2.timeslot) == "evening", (
            f"Hard treatment 2 was scheduled in {b_h2.timeslot}, but must be in evening session!"
        )

        # 4. Easy Treatment (Lepam) in Evening (16:00) -> Allowed in the SAME evening session as Hard 2!
        alloc_e = TherapyAllocation.objects.create(
            patient=self.patient,
            therapy_code=self.therapy_easy.therapy_code,
            therapy_name=self.therapy_easy.therapy_name,
            from_date=self.target_date,
            to_date=self.target_date,
            days=1,
            timeslot=self.slot_1600,
            room=self.room2,
            status="draft",
        )
        b_e = Booking.objects.create(
            allocation=alloc_e,
            date=self.target_date,
            timeslot=self.slot_1600,
            room=self.room2,
            status="draft",
            snapshot_therapy_name=self.therapy_easy.therapy_name,
        )
        tasks_e = reshedule.expand_therapies_for_visit(
            alloc_e.id,
            self.target_date,
            create_bookings=True,
            force_slot_only=True,
        )
        b_e.refresh_from_db()
        assert b_e.status in ("BOOKED", "scheduled")
        assert get_slot_session(b_e.timeslot) == "evening"

        # Verification of complete 4-treatment plan:
        # Morning session: 1 Hard (08:30) + 1 Medium (10:00)
        # Evening session: 1 Hard (14:30) + 1 Easy (16:00)
        # Exactly 0 sessions with multiple hard treatments.
        all_bookings = Booking.objects.filter(
            allocation__patient=self.patient,
            date=self.target_date,
            status__in=["BOOKED", "scheduled"]
        )
        morning_hard_count = sum(
            1 for b in all_bookings
            if get_slot_session(b.timeslot) == "morning" and is_hard_treatment(therapy_name=b.snapshot_therapy_name)
        )
        evening_hard_count = sum(
            1 for b in all_bookings
            if get_slot_session(b.timeslot) == "evening" and is_hard_treatment(therapy_name=b.snapshot_therapy_name)
        )
        assert morning_hard_count == 1
        assert evening_hard_count == 1

    def test_force_two_hard_treatments_same_session_fails(self):
        """If user forces a second hard treatment into the same session, it must fail."""
        # Hard 1 booked at 08:30
        alloc_h1 = TherapyAllocation.objects.create(
            patient=self.patient,
            therapy_code=self.therapy_hard_1.therapy_code,
            therapy_name=self.therapy_hard_1.therapy_name,
            from_date=self.target_date,
            to_date=self.target_date,
            days=1,
            timeslot=self.slot_0830,
            status="scheduled",
        )
        Booking.objects.create(
            allocation=alloc_h1,
            date=self.target_date,
            timeslot=self.slot_0830,
            status="scheduled",
            snapshot_therapy_name=self.therapy_hard_1.therapy_name,
        )

        # Hard 2 forced to 10:00 (also morning)
        alloc_h2 = TherapyAllocation.objects.create(
            patient=self.patient,
            therapy_code=self.therapy_hard_2.therapy_code,
            therapy_name=self.therapy_hard_2.therapy_name,
            from_date=self.target_date,
            to_date=self.target_date,
            days=1,
            timeslot=self.slot_1000,
            status="draft",
        )
        b_h2 = Booking.objects.create(
            allocation=alloc_h2,
            date=self.target_date,
            timeslot=self.slot_1000,
            status="draft",
            snapshot_therapy_name=self.therapy_hard_2.therapy_name,
        )

        # Reschedule with force_slot_only=True
        tasks = reshedule.expand_therapies_for_visit(
            alloc_h2.id,
            self.target_date,
            create_bookings=True,
            force_slot_only=True,
        )
        b_h2.refresh_from_db()
        assert b_h2.status == "failed"
        assert b_h2.failure_reason == "hard_treatment_same_session_conflict"

    def test_final_allocation_pass2_fails_second_hard_in_same_session(self):
        """In final_allocation.py PASS 2, a booking violating the hard treatment rule is marked failed."""
        # Morning hard booking already scheduled
        alloc_h1 = TherapyAllocation.objects.create(
            patient=self.patient,
            therapy_code=self.therapy_hard_1.therapy_code,
            therapy_name=self.therapy_hard_1.therapy_name,
            from_date=self.target_date,
            to_date=self.target_date,
            days=1,
            timeslot=self.slot_0830,
            status="scheduled",
        )
        Booking.objects.create(
            allocation=alloc_h1,
            date=self.target_date,
            timeslot=self.slot_0830,
            status="scheduled",
            snapshot_therapy_name=self.therapy_hard_1.therapy_name,
        )

        # Second morning hard booking to be scheduled by final allocation
        alloc_h2 = TherapyAllocation.objects.create(
            patient=self.patient,
            therapy_code=self.therapy_hard_2.therapy_code,
            therapy_name=self.therapy_hard_2.therapy_name,
            from_date=self.target_date,
            to_date=self.target_date,
            days=1,
            timeslot=self.slot_1000,
            status="draft",
        )
        b_h2 = Booking.objects.create(
            allocation=alloc_h2,
            date=self.target_date,
            timeslot=self.slot_1000,
            status="draft",
            snapshot_therapy_name=self.therapy_hard_2.therapy_name,
        )

        tasks = final_allocation.expand_therapies_for_visit(
            alloc_h2.id,
            self.target_date,
            create_bookings=True,
        )
        b_h2.refresh_from_db()
        assert b_h2.status == "failed"
        assert b_h2.failure_reason == "hard_treatment_same_session_conflict"

    def test_api_therapy_entry_blocks_two_hard_treatments_same_session(self):
        """therapy_entry action='allocate' returns 400 when two hard treatments are scheduled in the same session."""
        # 1. Allocate first Hard treatment in morning (08:30)
        payload1 = {
            "action": "allocate",
            "patient_reg_no": self.patient.pat_reg_no,
            "patient_name": self.patient.pat_name,
            "patient_age": self.patient.pat_age,
            "patient_sex": self.patient.pat_sex,
            "therapy_code": self.therapy_hard_1.therapy_code,
            "therapy_name": self.therapy_hard_1.therapy_name,
            "from_date": self.target_date.strftime("%Y-%m-%d"),
            "to_date": self.target_date.strftime("%Y-%m-%d"),
            "timeslot": "08:30",
        }
        req1 = self.factory.post(
            "/scheduling/therapy-entry/",
            data=json.dumps(payload1),
            content_type="application/json",
        )
        res1 = therapy_entry(req1)
        assert res1.status_code in (200, 201), res1.content

        # Mark its booking as scheduled / BOOKED
        Booking.objects.filter(
            allocation__patient=self.patient,
            date=self.target_date,
        ).update(status="scheduled")

        # 2. Attempt to allocate second Hard treatment in morning (10:00)
        payload2 = {
            "action": "allocate",
            "patient_reg_no": self.patient.pat_reg_no,
            "patient_name": self.patient.pat_name,
            "patient_age": self.patient.pat_age,
            "patient_sex": self.patient.pat_sex,
            "therapy_code": self.therapy_hard_2.therapy_code,
            "therapy_name": self.therapy_hard_2.therapy_name,
            "from_date": self.target_date.strftime("%Y-%m-%d"),
            "to_date": self.target_date.strftime("%Y-%m-%d"),
            "timeslot": "10:00",
        }
        req2 = self.factory.post(
            "/scheduling/therapy-entry/",
            data=json.dumps(payload2),
            content_type="application/json",
        )
        res2 = therapy_entry(req2)
        assert res2.status_code == 400
        data2 = json.loads(res2.content.decode("utf-8"))
        assert data2.get("error") == "two_hard_treatments_same_session"

        # 3. EXCEPTION VERIFIED: Allocate Medium or Easy treatment (Lepam) in morning (10:00) -> Allowed!
        payload_easy = {
            "action": "allocate",
            "patient_reg_no": self.patient.pat_reg_no,
            "patient_name": self.patient.pat_name,
            "patient_age": self.patient.pat_age,
            "patient_sex": self.patient.pat_sex,
            "therapy_code": self.therapy_easy.therapy_code,
            "therapy_name": self.therapy_easy.therapy_name,
            "from_date": self.target_date.strftime("%Y-%m-%d"),
            "to_date": self.target_date.strftime("%Y-%m-%d"),
            "timeslot": "10:00",
        }
        req_easy = self.factory.post(
            "/scheduling/therapy-entry/",
            data=json.dumps(payload_easy),
            content_type="application/json",
        )
        res_easy = therapy_entry(req_easy)
        assert res_easy.status_code in (200, 201), res_easy.content

    def test_api_allocate_therapy_blocks_two_hard_treatments_same_session(self):
        """allocate_therapy view returns 400 when two hard treatments are scheduled in the same session."""
        # Create active morning hard booking
        alloc_h1 = TherapyAllocation.objects.create(
            patient=self.patient,
            therapy_code=self.therapy_hard_1.therapy_code,
            therapy_name=self.therapy_hard_1.therapy_name,
            from_date=self.target_date,
            to_date=self.target_date,
            days=1,
            timeslot=self.slot_0830,
            status="scheduled",
        )
        Booking.objects.create(
            allocation=alloc_h1,
            date=self.target_date,
            timeslot=self.slot_0830,
            status="scheduled",
            snapshot_therapy_name=self.therapy_hard_1.therapy_name,
        )

        # Attempt to allocate second Hard treatment via allocate_therapy API at 10:00
        payload = {
            "patient_reg_no": self.patient.pat_reg_no,
            "patient_name": self.patient.pat_name,
            "therapy_code": self.therapy_hard_2.therapy_code,
            "therapy_name": self.therapy_hard_2.therapy_name,
            "from_date": self.target_date.strftime("%Y-%m-%d"),
            "to_date": self.target_date.strftime("%Y-%m-%d"),
            "timeslot": "10:00",
            "items_groups": [],
        }
        req = self.factory.post(
            "/scheduling/allocate-therapy/",
            data=json.dumps(payload),
            content_type="application/json",
        )
        res = allocate_therapy(req)
        assert res.status_code == 400
        data = json.loads(res.content.decode("utf-8"))
        assert data.get("error") == "two_hard_treatments_same_session"

    def test_api_update_therapy_blocks_two_hard_treatments_same_session(self):
        """therapy_entry action='update_therapy' blocks changing timeslot of a hard treatment into a session with another hard treatment."""
        # 1. Existing morning hard treatment
        alloc_h1 = TherapyAllocation.objects.create(
            patient=self.patient,
            therapy_code=self.therapy_hard_1.therapy_code,
            therapy_name=self.therapy_hard_1.therapy_name,
            from_date=self.target_date,
            to_date=self.target_date,
            days=1,
            timeslot=self.slot_0830,
            status="scheduled",
        )
        Booking.objects.create(
            allocation=alloc_h1,
            date=self.target_date,
            timeslot=self.slot_0830,
            status="scheduled",
            snapshot_therapy_name=self.therapy_hard_1.therapy_name,
        )

        # 2. Existing evening hard treatment (14:30)
        alloc_h2 = TherapyAllocation.objects.create(
            patient=self.patient,
            therapy_code=self.therapy_hard_2.therapy_code,
            therapy_name=self.therapy_hard_2.therapy_name,
            from_date=self.target_date,
            to_date=self.target_date,
            days=1,
            timeslot=self.slot_1430,
            status="scheduled",
        )
        Booking.objects.create(
            allocation=alloc_h2,
            date=self.target_date,
            timeslot=self.slot_1430,
            status="scheduled",
            snapshot_therapy_name=self.therapy_hard_2.therapy_name,
        )

        # 3. Attempt to update alloc_h2 timeslot from 14:30 (evening) to 10:00 (morning) -> Should return 400!
        update_payload = {
            "action": "update_therapy",
            "allocation_id": alloc_h2.id,
            "timeslot": "10:00",
        }
        req_update = self.factory.post(
            "/scheduling/therapy-entry/",
            data=json.dumps(update_payload),
            content_type="application/json",
        )
        res_update = therapy_entry(req_update)
        assert res_update.status_code == 400
        data_update = json.loads(res_update.content.decode("utf-8"))
        assert data_update.get("error") == "two_hard_treatments_same_session"

    def test_reschedule_options_api_excludes_conflicting_session(self):
        """reschedule_options_api excludes slots in morning session when patient already has a morning hard treatment."""
        # Morning hard booking
        alloc_h1 = TherapyAllocation.objects.create(
            patient=self.patient,
            therapy_code=self.therapy_hard_1.therapy_code,
            therapy_name=self.therapy_hard_1.therapy_name,
            from_date=self.target_date,
            to_date=self.target_date,
            days=1,
            timeslot=self.slot_0830,
            status="scheduled",
        )
        Booking.objects.create(
            allocation=alloc_h1,
            date=self.target_date,
            timeslot=self.slot_0830,
            status="scheduled",
            snapshot_therapy_name=self.therapy_hard_1.therapy_name,
        )

        # Second hard treatment (failed booking)
        alloc_h2 = TherapyAllocation.objects.create(
            patient=self.patient,
            therapy_code=self.therapy_hard_2.therapy_code,
            therapy_name=self.therapy_hard_2.therapy_name,
            from_date=self.target_date,
            to_date=self.target_date,
            days=1,
            timeslot=self.slot_1000,
            status="draft",
        )
        b_h2 = Booking.objects.create(
            allocation=alloc_h2,
            date=self.target_date,
            timeslot=self.slot_1000,
            status="failed",
            failure_reason="hard_treatment_same_session_conflict",
            snapshot_therapy_name=self.therapy_hard_2.therapy_name,
        )

        # Call reschedule_options_api (POST with allocation_id and date)
        req = self.factory.post(
            "/scheduling/reschedule-options/",
            data=json.dumps({
                "allocation_id": alloc_h2.id,
                "date": self.target_date.strftime("%Y-%m-%d"),
            }),
            content_type="application/json",
        )
        req.user = self.admin_user
        res = reschedule_options_api(req)
        assert res.status_code == 200, res.content
        data = json.loads(res.content.decode("utf-8"))
        # All available slots in available_slots list must be in evening session
        available_slots = data.get("available_slots", [])
        assert len(available_slots) > 0, "Expected at least one available evening slot"
        for slot_info in available_slots:
            slot_val = slot_info.get("slot_time") or slot_info.get("slot_id")
            assert get_slot_session(slot_val) == "evening", (
                f"Expected only evening slots in reschedule options, but got {slot_val}"
            )
