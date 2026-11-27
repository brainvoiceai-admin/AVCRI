"""
CP-0 Test Suite: Reschedule All Failed Priority Ordering & Master-Only Dhara Flag.

Verifies:
1. reschedule_all_failed_api processes failed bookings in strict category priority:
   Wheelchair (0) -> Dhara & Pizhichil (is_dhara_pizhichil=True in TherapyMaster) (1) -> Normal (2).
2. Unmarked therapies whose names happen to contain "Dhara & Pizhichil" do NOT get priority 1.
"""
import json
import pytest
from datetime import date, time
from unittest.mock import patch
from django.test import TestCase, RequestFactory
from django.contrib.auth import get_user_model

from masters.models import SlotMaster, TherapistGrade, TherapistMaster, TherapyMaster
from Patient.models import TreatmentRoom, RoomName
from Sheduling.models import PatientSnapshot, TherapyAllocation, Booking
from Sheduling.views import reschedule_all_failed_api
from final_allocation import is_dhara_pizhichil_treatment, get_patient_category_priority

User = get_user_model()
TEST_DATE = date(2099, 11, 28)


@pytest.mark.django_db(transaction=True)
class RescheduleAllFailedPriorityTests(TestCase):
    def setUp(self):
        self.rf = RequestFactory()
        self.user, _ = User.objects.get_or_create(
            username="cp0_prio_admin",
            defaults={"is_superuser": True, "is_staff": True, "role": "super_admin"},
        )
        self.user.has_module_access = lambda mod: True
        self.slot_0830, _ = SlotMaster.objects.get_or_create(
            slot_number=1, defaults={"slot_time": time(8, 30), "is_active": True}
        )
        self.grade, _ = TherapistGrade.objects.get_or_create(
            name="Senior Therapist", defaults={"display_order": 1, "is_active": True}
        )
        self.th, _ = TherapistMaster.objects.get_or_create(
            therapist_code="TH_CP0_PR1",
            defaults={
                "therapist_name": "Priority Therapist",
                "therapist_gender": "Male",
                "therapist_grade": self.grade,
                "employee_code": "EMP_CP0_PR1",
                "is_bathing_therapist": True,
                "is_active": True,
            },
        )
        rn1, _ = RoomName.objects.get_or_create(name="Room TR-1", defaults={"is_active": True})
        self.room1, _ = TreatmentRoom.objects.get_or_create(
            room_no="TR-1",
            defaults={"room_name": rn1, "floor": "G", "is_wheelchair_accessible": True, "is_active": True},
        )
        self.normal_therapy, _ = TherapyMaster.objects.get_or_create(
            therapy_code="THEB_CP0_NORM",
            defaults={
                "therapy_name": "CP0 Normal Therapy",
                "therapy_category": "Easy",
                "therapy_duration": "45",
                "bathing_required": "No",
                "treatment_room_required": "Yes",
                "total_no_of_therapist": 1,
                "no_of_senior_therapist": 1,
                "is_dhara_pizhichil": False,
                "is_active": True,
            },
        )
        self.dp_therapy, _ = TherapyMaster.objects.get_or_create(
            therapy_code="THEB_CP0_DP",
            defaults={
                "therapy_name": "CP0 Master Flagged DP",
                "therapy_category": "Easy",
                "therapy_duration": "45",
                "bathing_required": "No",
                "treatment_room_required": "Yes",
                "total_no_of_therapist": 1,
                "no_of_senior_therapist": 1,
                "is_dhara_pizhichil": True,
                "is_active": True,
            },
        )
        self.unmarked_dp_name, _ = TherapyMaster.objects.get_or_create(
            therapy_code="THEB_CP0_FAKE_DP",
            defaults={
                "therapy_name": "Unmarked Dhara & Pizhichil Name",
                "therapy_category": "Easy",
                "therapy_duration": "45",
                "bathing_required": "No",
                "treatment_room_required": "Yes",
                "total_no_of_therapist": 1,
                "no_of_senior_therapist": 1,
                "is_dhara_pizhichil": False,
                "is_active": True,
            },
        )

    def test_unmarked_dhara_name_has_normal_priority(self):
        self.assertTrue(is_dhara_pizhichil_treatment(therapy_code=self.dp_therapy.therapy_code))
        self.assertFalse(is_dhara_pizhichil_treatment(therapy_code=self.unmarked_dp_name.therapy_code))
        self.assertFalse(is_dhara_pizhichil_treatment(therapy_name="Random Dhara & Pizhichil Not In Master"))

        pat = PatientSnapshot.objects.create(
            pat_reg_no="880010", pat_name="Fake DP Pat", pat_sex="Male", pat_age="40", pat_room_no="DS-1"
        )
        alloc_fake = TherapyAllocation.objects.create(
            patient=pat, therapy_code=self.unmarked_dp_name.therapy_code,
            therapy_name=self.unmarked_dp_name.therapy_name, timeslot=self.slot_0830,
            from_date=TEST_DATE, to_date=TEST_DATE, days=1, status="failed",
        )
        self.assertEqual(get_patient_category_priority(pat, allocation=alloc_fake), 2)

    def test_reschedule_all_failed_processes_wheelchair_then_dp_then_normal(self):
        # Create in reverse order (Normal -> DP -> Wheelchair) to prove sorting works
        p_norm = PatientSnapshot.objects.create(
            pat_reg_no="880011", pat_name="Normal Pat", pat_sex="Male", pat_age="40", pat_room_no="DS-1"
        )
        p_dp = PatientSnapshot.objects.create(
            pat_reg_no="880012", pat_name="DP Pat", pat_sex="Male", pat_age="40", pat_room_no="DS-1"
        )
        p_wc = PatientSnapshot.objects.create(
            pat_reg_no="880013", pat_name="WC Pat", pat_sex="Male", pat_age="40", pat_room_no="DS-1", is_wheelchair=True
        )

        a_norm = TherapyAllocation.objects.create(
            patient=p_norm, therapy_code=self.normal_therapy.therapy_code,
            therapy_name=self.normal_therapy.therapy_name, timeslot=self.slot_0830,
            from_date=TEST_DATE, to_date=TEST_DATE, days=1, status="failed",
        )
        a_dp = TherapyAllocation.objects.create(
            patient=p_dp, therapy_code=self.dp_therapy.therapy_code,
            therapy_name=self.dp_therapy.therapy_name, timeslot=self.slot_0830,
            from_date=TEST_DATE, to_date=TEST_DATE, days=1, status="failed",
        )
        a_wc = TherapyAllocation.objects.create(
            patient=p_wc, therapy_code=self.normal_therapy.therapy_code,
            therapy_name=self.normal_therapy.therapy_name, timeslot=self.slot_0830,
            from_date=TEST_DATE, to_date=TEST_DATE, days=1, status="failed", is_wheelchair=True,
        )

        for a in (a_norm, a_dp, a_wc):
            Booking.objects.create(
                allocation=a, date=TEST_DATE, timeslot=self.slot_0830,
                status="failed", snapshot_therapy_name=a.therapy_name,
            )

        call_order = []

        def fake_allocate(alloc_id, target_date, **kwargs):
            call_order.append(alloc_id)
            return [{"status": "FAILED", "reason": "mocked"}]

        req = self.rf.post(
            "/sheduling/scheduling/api/reschedule-all-failed/",
            data=json.dumps({"date": TEST_DATE.isoformat()}),
            content_type="application/json",
        )
        req.user = self.user
        with patch("reshedule.allocate_therapy_for_visit", side_effect=fake_allocate), \
             patch("Sheduling.views._refresh_patient_staying_rooms", return_value={"updated": 0}):
            resp = reschedule_all_failed_api(req)

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(call_order, [a_wc.id, a_dp.id, a_norm.id])
