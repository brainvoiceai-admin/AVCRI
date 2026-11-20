"""
Test suite for Dhara & Pizhichil Room Continuity, Temporary Cancellation,
and 3-Tier Patient Allocation Priority (Wheelchair -> Dhara Pizhichil -> Normal).

Validates:
1. TherapyMaster option:
   - 'is_dhara_pizhichil' boolean flag in TherapyMaster.
   - Toggle view therapy_master_toggle_dhara_pizhichil flips the state.
   - Only therapies with is_dhara_pizhichil=True strictly enforce room continuity.
2. Room Continuity across days:
   - Once assigned at treatment start, the same room is preserved on subsequent days.
3. Temporary Treatment Cancellation & Resumption:
   - When cancelled for a day, the room/slot is vacant and allocatable to another patient.
   - When resumed on subsequent days, the original Dhara Pizhichil room is retained.
   - The original Dhara Pizhichil patient is prioritized ahead of normal treatment patients.
4. Patient Allocation Priority:
   - Priority 1: Wheelchair patients
   - Priority 2: Dhara Pizhichil patients
   - Priority 3: Normal treatment patients
"""
import pytest
from datetime import date, time, timedelta
from unittest.mock import patch
from django.test import TestCase, Client
from django.contrib.auth import get_user_model
from django.urls import reverse

from masters.models import SlotMaster, TherapistGrade, TherapistMaster, TherapyMaster
from Patient.models import TreatmentRoom, RoomName, RoomBooking, TherapistBooking
from Sheduling.models import PatientSnapshot, TherapyAllocation, Booking
from final_allocation import (
    bulk_allocate_for_date,
    allocate_treatment_room,
    is_dhara_pizhichil_treatment,
    get_dhara_pizhichil_assigned_room,
    get_patient_category_priority,
)

User = get_user_model()
BASE_DATE = date(2099, 10, 1)


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


def _ensure_therapist(code, name, gender, grade, emp_code):
    obj, _ = TherapistMaster.objects.get_or_create(
        therapist_code=code,
        defaults={
            "therapist_name": name,
            "therapist_gender": gender,
            "therapist_grade": grade,
            "employee_code": emp_code,
            "is_bathing_therapist": True,
            "is_active": True,
        },
    )
    return obj


def _ensure_room(room_no, is_wheelchair=False):
    rn, _ = RoomName.objects.get_or_create(name=f"Room {room_no}", defaults={"is_active": True})
    obj, _ = TreatmentRoom.objects.get_or_create(
        room_no=room_no,
        defaults={
            "room_name": rn,
            "floor": "G",
            "is_wheelchair_accessible": is_wheelchair,
            "is_active": True,
        },
    )
    if obj.is_wheelchair_accessible != is_wheelchair:
        obj.is_wheelchair_accessible = is_wheelchair
        obj.save(update_fields=["is_wheelchair_accessible"])
    return obj


@pytest.mark.django_db(transaction=True)
class DharaPizhichilRoomContinuityAndPriorityTests(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.slot_0830 = _ensure_slot(1, time(8, 30))
        cls.slot_1000 = _ensure_slot(2, time(10, 0))
        cls.grade = _ensure_grade("Senior Therapist", 1)

        # Therapists
        cls.th1 = _ensure_therapist("TH_DP_1", "Therapist One", "Male", cls.grade, "EMP_DP_1")
        cls.th2 = _ensure_therapist("TH_DP_2", "Therapist Two", "Male", cls.grade, "EMP_DP_2")

        # Rooms
        cls.room_tr1 = _ensure_room("TR-1", is_wheelchair=False)
        cls.room_tr2 = _ensure_room("TR-2", is_wheelchair=True)  # Wheelchair accessible
        cls.room_tr3 = _ensure_room("TR-3", is_wheelchair=False)

        # Therapies
        cls.dhara_pizhichil_therapy, _ = TherapyMaster.objects.get_or_create(
            therapy_code="THEB_DP_TEST",
            defaults={
                "therapy_name": "Special Dhara & Pizhichil",
                "therapy_category": "Hard",
                "therapy_duration": "60",
                "bathing_required": "Yes",
                "treatment_room_required": "Yes",
                "no_of_senior_therapist": 1,
                "total_no_of_therapist": 1,
                "is_dhara_pizhichil": True,
                "is_active": True,
            },
        )
        if not cls.dhara_pizhichil_therapy.is_dhara_pizhichil:
            cls.dhara_pizhichil_therapy.is_dhara_pizhichil = True
            cls.dhara_pizhichil_therapy.save(update_fields=["is_dhara_pizhichil"])

        cls.normal_therapy, _ = TherapyMaster.objects.get_or_create(
            therapy_code="THEB_NORM_TEST",
            defaults={
                "therapy_name": "General Abhyangam",
                "therapy_category": "Medium",
                "therapy_duration": "45",
                "bathing_required": "No",
                "treatment_room_required": "Yes",
                "no_of_senior_therapist": 1,
                "total_no_of_therapist": 1,
                "is_dhara_pizhichil": False,
                "is_active": True,
            },
        )

    def setUp(self):
        self.client = Client()
        self.admin_user = User.objects.create_user(
            username="admin_test_dp", password="adminpassword123", email="admin@test.com", role="super_admin"
        )
        self.client.force_login(self.admin_user)

    def tearDown(self):
        RoomBooking.objects.filter(date__gte=BASE_DATE).delete()
        TherapistBooking.objects.filter(date__gte=BASE_DATE).delete()
        Booking.objects.filter(date__gte=BASE_DATE).delete()
        TherapyAllocation.objects.filter(patient__pat_reg_no__startswith="PAT-DP-").delete()
        PatientSnapshot.objects.filter(pat_reg_no__startswith="PAT-DP-").delete()

    def test_therapy_master_dhara_pizhichil_toggle_view(self):
        """Verify the toggle endpoint toggles is_dhara_pizhichil on and off."""
        t = self.dhara_pizhichil_therapy
        self.assertTrue(t.is_dhara_pizhichil)

        # Toggle OFF
        url = reverse('therapy_master_toggle_dhara_pizhichil', args=[t.pk])
        resp = self.client.post(url, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(resp.status_code, 200)
        t.refresh_from_db()
        self.assertFalse(t.is_dhara_pizhichil)

        # Toggle back ON
        resp = self.client.post(url, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(resp.status_code, 200)
        t.refresh_from_db()
        self.assertTrue(t.is_dhara_pizhichil)

    def test_is_dhara_pizhichil_treatment_respects_master_flag(self):
        """Verify is_dhara_pizhichil_treatment helper checks TherapyMaster flag."""
        # Therapy marked with flag=True
        self.assertTrue(is_dhara_pizhichil_treatment(
            therapy_name=self.dhara_pizhichil_therapy.therapy_name,
            therapy_code=self.dhara_pizhichil_therapy.therapy_code
        ))
        # Normal therapy with flag=False
        self.assertFalse(is_dhara_pizhichil_treatment(
            therapy_name=self.normal_therapy.therapy_name,
            therapy_code=self.normal_therapy.therapy_code
        ))

    def test_dhara_pizhichil_room_continuity_across_consecutive_days(self):
        """
        Requirement 1:
        Once a room is assigned to a Dhara Pizhichil patient at treatment start,
        the SAME room must be maintained on subsequent days until discharge.
        """
        day1 = BASE_DATE
        day2 = BASE_DATE + timedelta(days=1)

        pat = PatientSnapshot.objects.create(
            pat_reg_no="PAT-DP-001", pat_name="DP Patient 1", pat_room_no="DS-1"
        )
        alloc = TherapyAllocation.objects.create(
            patient=pat,
            therapy_code=self.dhara_pizhichil_therapy.therapy_code,
            therapy_name=self.dhara_pizhichil_therapy.therapy_name,
            from_date=day1,
            to_date=day2,
            days=2,
            timeslot=self.slot_0830,
            status="draft",
        )

        # Day 1: allocate room TR-1
        allocated_day1 = allocate_treatment_room(
            day1, self.slot_0830, None,
            therapy_name=self.dhara_pizhichil_therapy.therapy_name,
            patient_id=pat.id,
            patient_staying_room="DS-1",
            patient=pat
        )
        self.assertIsNotNone(allocated_day1)
        assigned_room = allocated_day1

        # Simulate booking persistence on Day 1
        RoomBooking.objects.create(
            room=assigned_room,
            date=day1,
            time_slot=self.slot_0830,
            therapy_name=self.dhara_pizhichil_therapy.therapy_name,
            patient_id=pat.id,
            status="BOOKED"
        )
        alloc.room = assigned_room
        alloc.save(update_fields=['room'])

        # Day 2: allocate room
        allocated_day2 = allocate_treatment_room(
            day2, self.slot_0830, None,
            therapy_name=self.dhara_pizhichil_therapy.therapy_name,
            patient_id=pat.id,
            patient_staying_room="DS-1",
            patient=pat
        )
        # MUST BE THE EXACT SAME ROOM AS DAY 1
        self.assertEqual(allocated_day2.room_no, assigned_room.room_no)

    def test_temporary_cancellation_and_resumption_room_continuity(self):
        """
        Requirement 2:
        - Day 1: Room TR-1 assigned.
        - Day 2: Treatment cancelled for DP patient. Slot in TR-1 can be given to Patient B.
        - Day 3: Treatment resumes. DP patient must get the original room (TR-1).
        """
        day1 = BASE_DATE + timedelta(days=10)
        day2 = BASE_DATE + timedelta(days=11)
        day3 = BASE_DATE + timedelta(days=12)

        pat_a = PatientSnapshot.objects.create(
            pat_reg_no="PAT-DP-002", pat_name="DP Patient 2", pat_room_no="DS-1"
        )
        alloc_a = TherapyAllocation.objects.create(
            patient=pat_a,
            therapy_code=self.dhara_pizhichil_therapy.therapy_code,
            therapy_name=self.dhara_pizhichil_therapy.therapy_name,
            from_date=day1, to_date=day3, days=3,
            timeslot=self.slot_0830,
            room=self.room_tr1,
            status="scheduled",
        )
        # Day 1 booked in TR-1
        RoomBooking.objects.create(
            room=self.room_tr1, date=day1, time_slot=self.slot_0830,
            therapy_name=self.dhara_pizhichil_therapy.therapy_name,
            patient_id=pat_a.id, status="BOOKED"
        )

        # Day 2: CANCELLED for Patient A
        rb_day2_cancel = RoomBooking.objects.create(
            room=self.room_tr1, date=day2, time_slot=self.slot_0830,
            therapy_name=self.dhara_pizhichil_therapy.therapy_name,
            patient_id=pat_a.id, status="CANCELED"
        )

        # Another patient (Patient B) wants TR-1 on Day 2
        pat_b = PatientSnapshot.objects.create(
            pat_reg_no="PAT-DP-003", pat_name="Normal Patient B", pat_room_no="DS-1"
        )
        room_for_b = allocate_treatment_room(
            day2, self.slot_0830, None,
            therapy_name=self.normal_therapy.therapy_name,
            patient_id=pat_b.id,
            patient_staying_room="DS-1",
            patient=pat_b
        )
        # Patient B can take TR-1 on Day 2 because Patient A is cancelled!
        self.assertEqual(room_for_b.room_no, "TR-1")

        # Book TR-1 for Patient B on Day 2
        RoomBooking.objects.create(
            room=self.room_tr1, date=day2, time_slot=self.slot_0830,
            therapy_name=self.normal_therapy.therapy_name,
            patient_id=pat_b.id, status="BOOKED"
        )

        # Day 3: Patient A resumes treatment!
        # Must retain original room TR-1!
        room_for_a_resumed = allocate_treatment_room(
            day3, self.slot_0830, None,
            therapy_name=self.dhara_pizhichil_therapy.therapy_name,
            patient_id=pat_a.id,
            patient_staying_room="DS-1",
            patient=pat_a
        )
        self.assertEqual(room_for_a_resumed.room_no, "TR-1")

    def test_patient_allocation_priority_tiers(self):
        """
        Requirement 3:
        1. Wheelchair patients (priority 0)
        2. Dhara Pizhichil patients (priority 1)
        3. Normal patients (priority 2)
        """
        pat_wc = PatientSnapshot.objects.create(
            pat_reg_no="PAT-DP-WC", pat_name="Wheelchair Patient", is_wheelchair=True
        )
        pat_dp = PatientSnapshot.objects.create(
            pat_reg_no="PAT-DP-DP", pat_name="Dhara Pizhichil Patient", is_wheelchair=False
        )
        pat_norm = PatientSnapshot.objects.create(
            pat_reg_no="PAT-DP-NORM", pat_name="Normal Patient", is_wheelchair=False
        )

        alloc_wc = TherapyAllocation.objects.create(
            patient=pat_wc, therapy_code=self.normal_therapy.therapy_code,
            therapy_name=self.normal_therapy.therapy_name, is_wheelchair=True,
            from_date=BASE_DATE, to_date=BASE_DATE, days=1
        )
        alloc_dp = TherapyAllocation.objects.create(
            patient=pat_dp, therapy_code=self.dhara_pizhichil_therapy.therapy_code,
            therapy_name=self.dhara_pizhichil_therapy.therapy_name, is_wheelchair=False,
            from_date=BASE_DATE, to_date=BASE_DATE, days=1
        )
        alloc_norm = TherapyAllocation.objects.create(
            patient=pat_norm, therapy_code=self.normal_therapy.therapy_code,
            therapy_name=self.normal_therapy.therapy_name, is_wheelchair=False,
            from_date=BASE_DATE, to_date=BASE_DATE, days=1
        )

        p_wc = get_patient_category_priority(pat_wc, allocation=alloc_wc)
        p_dp = get_patient_category_priority(pat_dp, allocation=alloc_dp)
        p_norm = get_patient_category_priority(pat_norm, allocation=alloc_norm)

        self.assertEqual(p_wc, 0, "Wheelchair patients must have Priority Tier 0 (highest)")
        self.assertEqual(p_dp, 1, "Dhara Pizhichil patients must have Priority Tier 1 (second)")
        self.assertEqual(p_norm, 2, "Normal treatment patients must have Priority Tier 2 (third)")
        self.assertLess(p_wc, p_dp)
        self.assertLess(p_dp, p_norm)

    def test_strict_room_continuity_refuses_room_substitution(self):
        """
        For Dhara Pizhichil, if the assigned room is occupied at a slot,
        allocate_treatment_room MUST return None, NOT an alternative room!
        """
        day = BASE_DATE + timedelta(days=20)
        pat = PatientSnapshot.objects.create(
            pat_reg_no="PAT-DP-004", pat_name="DP Patient 4", pat_room_no="DS-1"
        )
        alloc = TherapyAllocation.objects.create(
            patient=pat,
            therapy_code=self.dhara_pizhichil_therapy.therapy_code,
            therapy_name=self.dhara_pizhichil_therapy.therapy_name,
            from_date=day - timedelta(days=1), to_date=day + timedelta(days=2), days=4,
            timeslot=self.slot_0830,
            room=self.room_tr1,  # Originally assigned TR-1
            status="scheduled",
        )
        # TR-1 is occupied on day at slot_0830 by someone else
        dummy_pat = PatientSnapshot.objects.create(pat_reg_no="PAT-DP-OCC", pat_name="Occupant")
        RoomBooking.objects.create(
            room=self.room_tr1, date=day, time_slot=self.slot_0830,
            therapy_name="Some Other", patient_id=dummy_pat.id, status="BOOKED"
        )

        # Allocate room for DP patient on day at slot_0830:
        # TR-1 is occupied. Even though TR-2 and TR-3 are free,
        # it MUST return None (NO room substitution permitted for Dhara Pizhichil)!
        res = allocate_treatment_room(
            day, self.slot_0830, None,
            therapy_name=self.dhara_pizhichil_therapy.therapy_name,
            patient_id=pat.id,
            patient_staying_room="DS-1",
            patient=pat
        )
        self.assertIsNone(res, "Dhara Pizhichil must never substitute a different room when the assigned room is busy")

        # But if we check slot_1000 where TR-1 is free:
        res_slot2 = allocate_treatment_room(
            day, self.slot_1000, None,
            therapy_name=self.dhara_pizhichil_therapy.therapy_name,
            patient_id=pat.id,
            patient_staying_room="DS-1",
            patient=pat
        )
        self.assertIsNotNone(res_slot2)
        self.assertEqual(res_slot2.room_no, "TR-1", "Dhara Pizhichil should keep TR-1 in an alternative free slot")
