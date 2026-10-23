"""
Regression Test: Therapist Treatment Omission (Special Request & HR/Admin Approvals)

Specifications:
1. Therapists may omit particular treatments on special request.
2. In Therapist Master edit, user selects treatments to omit with a reason, submitted for approval (pending).
3. HR and Admin (GM) can approve or reject treatment omissions.
4. Once approved, the therapist must NOT be scheduled with those treatments in the scheduling list.
5. The therapist remains fully eligible for all other treatments they have not omitted.
6. If the request is pending or rejected, the therapist is NOT omitted from scheduling.
"""
import pytest
from datetime import date, time
from django.test import TestCase, RequestFactory
from django.utils import timezone

from masters.models import (
    SlotMaster, TherapistGrade, TherapistMaster, TherapyMaster,
    TherapistTreatmentOmission,
    is_therapist_omitted_for_treatment,
    get_omitted_therapist_ids_for_treatment,
    get_omitted_therapist_codes_for_treatment,
    can_approve_treatment_omission,
    TherapistOmissionRequestGroup, group_omissions_by_request
)
from authentication.models import CustomUser
from final_allocation import allocate_therapists, create_therapist_booking_safe
import reshedule
from Sheduling.availability_views import get_available_therapists_api
from masters.views import (
    approve_therapist_treatment_omission_api,
    reject_therapist_treatment_omission_api,
    approve_therapist_treatment_omission_batch_api,
    reject_therapist_treatment_omission_batch_api,
    delete_therapist_treatment_omission_batch_api,
    therapist_treatment_omission_approvals_view
)


@pytest.mark.django_db
class TestTherapistTreatmentOmission(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.target_date = date(2099, 10, 15)

        # Slot
        self.slot = SlotMaster.objects.create(
            slot_number=1,
            slot_time=time(8, 30),
            is_active=True
        )

        # Grade
        self.senior_grade = TherapistGrade.objects.create(
            name="Senior Therapist",
            display_order=2,
            is_active=True
        )

        # Therapists
        self.therapist_1 = TherapistMaster.objects.create(
            therapist_code="TH_OMIT_01",
            therapist_name="Therapist One",
            therapist_gender="Male",
            therapist_grade=self.senior_grade,
            employee_code="EMP_OMIT_01",
            is_active=True
        )
        self.therapist_2 = TherapistMaster.objects.create(
            therapist_code="TH_NORM_02",
            therapist_name="Therapist Two",
            therapist_gender="Male",
            therapist_grade=self.senior_grade,
            employee_code="EMP_NORM_02",
            is_active=True
        )

        # Therapies
        self.therapy_a = TherapyMaster.objects.create(
            therapy_code="TH_A",
            therapy_name="Abhyanga",
            therapy_category="Medium",
            therapy_duration="45",
            bathing_required="No",
            treatment_room_required="Yes",
            no_of_senior_therapist=1,
            total_no_of_therapist=1,
            patient_type="IP",
            is_active=True
        )
        self.therapy_b = TherapyMaster.objects.create(
            therapy_code="TH_B",
            therapy_name="Shirodhara",
            therapy_category="Medium",
            therapy_duration="45",
            bathing_required="No",
            treatment_room_required="Yes",
            no_of_senior_therapist=1,
            total_no_of_therapist=1,
            patient_type="IP",
            is_active=True
        )

        # Users for permissions
        self.admin_user = CustomUser.objects.create_user(
            username="admin_gm",
            email="admin@hospital.com",
            password="password123",
            role="admin"
        )
        self.hr_user = CustomUser.objects.create_user(
            username="hr_officer",
            email="hr@hospital.com",
            password="password123",
            role="hr"
        )
        self.therapist_user = CustomUser.objects.create_user(
            username="regular_th",
            email="th@hospital.com",
            password="password123",
            role="therapist"
        )

    def test_permission_helper(self):
        """HR and Admin can approve treatment omissions, regular users cannot"""
        self.assertTrue(can_approve_treatment_omission(self.admin_user))
        self.assertTrue(can_approve_treatment_omission(self.hr_user))
        self.assertFalse(can_approve_treatment_omission(self.therapist_user))

    def test_omission_model_and_helper_functions(self):
        """Verify is_therapist_omitted_for_treatment behaves accurately across statuses"""
        # Create pending omission for therapy A
        omission = TherapistTreatmentOmission.objects.create(
            therapist=self.therapist_1,
            treatment=self.therapy_a,
            reason="Allergy to specific herbal oils used in Abhyanga",
            status="pending",
            requested_by=self.therapist_user
        )

        # While pending, should NOT be considered omitted for scheduling
        self.assertFalse(is_therapist_omitted_for_treatment(self.therapist_1, self.therapy_a))
        self.assertFalse(is_therapist_omitted_for_treatment(self.therapist_1, "Abhyanga"))
        self.assertFalse(is_therapist_omitted_for_treatment(self.therapist_1, "TH_A"))
        self.assertEqual(len(get_omitted_therapist_ids_for_treatment(self.therapy_a)), 0)

        # Approve omission
        omission.status = "approved"
        omission.approved_by = self.admin_user
        omission.approved_at = timezone.now()
        omission.save()

        # Now therapist_1 IS omitted for therapy A
        self.assertTrue(is_therapist_omitted_for_treatment(self.therapist_1, self.therapy_a))
        self.assertTrue(is_therapist_omitted_for_treatment(self.therapist_1, "Abhyanga"))
        self.assertTrue(is_therapist_omitted_for_treatment(self.therapist_1, "TH_A"))
        self.assertIn(self.therapist_1.pk, get_omitted_therapist_ids_for_treatment(self.therapy_a))
        self.assertIn(self.therapist_1.therapist_code, get_omitted_therapist_codes_for_treatment("Abhyanga"))

        # But therapist_1 is NOT omitted for therapy B
        self.assertFalse(is_therapist_omitted_for_treatment(self.therapist_1, self.therapy_b))
        self.assertFalse(is_therapist_omitted_for_treatment(self.therapist_1, "Shirodhara"))
        self.assertFalse(is_therapist_omitted_for_treatment(self.therapist_1, "TH_B"))

        # And therapist_2 is NOT omitted for therapy A or B
        self.assertFalse(is_therapist_omitted_for_treatment(self.therapist_2, self.therapy_a))
        self.assertFalse(is_therapist_omitted_for_treatment(self.therapist_2, self.therapy_b))

        # If rejected, should NOT be considered omitted
        omission.status = "rejected"
        omission.save()
        self.assertFalse(is_therapist_omitted_for_treatment(self.therapist_1, self.therapy_a))

    def test_final_allocation_excludes_therapist_for_omitted_treatment(self):
        """Therapist with approved omission is excluded when allocating that treatment, but included for others"""
        # Approve omission for therapist_1 on Therapy A
        TherapistTreatmentOmission.objects.create(
            therapist=self.therapist_1,
            treatment=self.therapy_a,
            reason="Medical condition",
            status="approved",
            approved_by=self.admin_user
        )

        req_a = {
            "senior": 1,
            "therapy_name": "Abhyanga",
            "therapy_code": "TH_A"
        }

        # Allocation for Therapy A: therapist_1 must be omitted, therapist_2 should be picked
        allocated_for_a = allocate_therapists(
            date=self.target_date,
            time_slot=self.slot,
            therapy_requirements=req_a,
            patient_gender="Male"
        )
        self.assertIn(self.therapist_2, allocated_for_a)
        self.assertNotIn(self.therapist_1, allocated_for_a)

        # Allocation for Therapy B: therapist_1 is NOT omitted, both are eligible
        req_b = {
            "senior": 1,
            "therapy_name": "Shirodhara",
            "therapy_code": "TH_B"
        }
        # Explicitly pass therapist_1 in last_therapists for continuity test
        allocated_for_b = allocate_therapists(
            date=self.target_date,
            time_slot=self.slot,
            therapy_requirements=req_b,
            last_therapists=[self.therapist_1.therapist_code],
            patient_gender="Male"
        )
        self.assertIn(self.therapist_1, allocated_for_b)

    def test_reschedule_excludes_therapist_for_omitted_treatment(self):
        """reshedule.py allocate_therapists respects treatment omissions"""
        TherapistTreatmentOmission.objects.create(
            therapist=self.therapist_1,
            treatment=self.therapy_a,
            reason="Shoulder injury",
            status="approved",
            approved_by=self.hr_user
        )

        req_a = {
            "senior": 1,
            "therapy_name": "Abhyanga",
            "therapy_code": "TH_A"
        }

        allocated = reshedule.allocate_therapists(
            date=self.target_date,
            time_slot=self.slot,
            therapy_requirements=req_a,
            patient_gender="Male"
        )
        self.assertIn(self.therapist_2, allocated)
        self.assertNotIn(self.therapist_1, allocated)

    def test_create_therapist_booking_safe_barrier(self):
        """create_therapist_booking_safe strictly prevents booking omitted therapist"""
        TherapistTreatmentOmission.objects.create(
            therapist=self.therapist_1,
            treatment=self.therapy_a,
            reason="Special Request Approved",
            status="approved",
            approved_by=self.admin_user
        )

        # Attempt to book therapist_1 for Abhyanga -> should fail (return None, False)
        tb, created = create_therapist_booking_safe(
            therapist=self.therapist_1,
            date=self.target_date,
            time_slot=self.slot,
            therapy_name="Abhyanga",
            patient_id=101,
            visit=None
        )
        self.assertIsNone(tb)
        self.assertFalse(created)

        # Attempt to book therapist_1 for Shirodhara -> should succeed
        tb2, created2 = create_therapist_booking_safe(
            therapist=self.therapist_1,
            date=self.target_date,
            time_slot=self.slot,
            therapy_name="Shirodhara",
            patient_id=101,
            visit=None
        )
        self.assertIsNotNone(tb2)
        self.assertTrue(created2)

    def test_availability_api_excludes_omitted_therapist_when_treatment_specified(self):
        """get_available_therapists_api excludes therapist only when treatment is specified and approved"""
        TherapistTreatmentOmission.objects.create(
            therapist=self.therapist_1,
            treatment=self.therapy_a,
            reason="Exclusion request",
            status="approved",
            approved_by=self.admin_user
        )

        # Query for Abhyanga
        request_a = self.factory.get('/sheduling/api/available-therapists/', {
            'date': self.target_date.isoformat(),
            'treatment': 'Abhyanga'
        })
        request_a.user = self.admin_user
        response_a = get_available_therapists_api(request_a)
        data_a = response_a.content.decode('utf-8')
        self.assertNotIn(self.therapist_1.therapist_code, data_a)
        self.assertIn(self.therapist_2.therapist_code, data_a)

        # Query for Shirodhara -> therapist_1 IS available
        request_b = self.factory.get('/sheduling/api/available-therapists/', {
            'date': self.target_date.isoformat(),
            'treatment': 'Shirodhara'
        })
        request_b.user = self.admin_user
        response_b = get_available_therapists_api(request_b)
        data_b = response_b.content.decode('utf-8')
        self.assertIn(self.therapist_1.therapist_code, data_b)
        self.assertIn(self.therapist_2.therapist_code, data_b)

    def test_approval_api_endpoints(self):
        """Admin/HR can approve/reject omission requests via API"""
        omission = TherapistTreatmentOmission.objects.create(
            therapist=self.therapist_1,
            treatment=self.therapy_a,
            reason="Request for exemption",
            status="pending",
            requested_by=self.therapist_user
        )

        # Non-HR/Admin attempt -> 403 Forbidden
        req_unauth = self.factory.post(
            f'/masters/api/therapist-treatment-omissions/{omission.pk}/approve/',
            content_type='application/json'
        )
        req_unauth.user = self.therapist_user
        resp_unauth = approve_therapist_treatment_omission_api(req_unauth, omission.pk)
        self.assertEqual(resp_unauth.status_code, 403)

        # Admin approval -> 200 OK
        req_admin = self.factory.post(
            f'/masters/api/therapist-treatment-omissions/{omission.pk}/approve/',
            data='{"remarks": "Approved by GM"}',
            content_type='application/json'
        )
        req_admin.user = self.admin_user
        resp_admin = approve_therapist_treatment_omission_api(req_admin, omission.pk)
        self.assertEqual(resp_admin.status_code, 200)

        omission.refresh_from_db()
        self.assertEqual(omission.status, 'approved')
        self.assertEqual(omission.approved_by, self.admin_user)
        self.assertEqual(omission.approval_remarks, 'Approved by GM')

        # Admin rejection
        req_reject = self.factory.post(
            f'/masters/api/therapist-treatment-omissions/{omission.pk}/reject/',
            data='{"remarks": "No longer needed"}',
            content_type='application/json'
        )
        req_reject.user = self.admin_user
        resp_reject = reject_therapist_treatment_omission_api(req_reject, omission.pk)
        self.assertEqual(resp_reject.status_code, 200)

        omission.refresh_from_db()
        self.assertEqual(omission.status, 'rejected')

    def test_therapist_update_view_submits_multiple_omissions(self):
        """Therapist update form renders quick action buttons and submits multiple omissions"""
        from django.urls import reverse
        self.client.force_login(self.admin_user)
        url = reverse('therapist_master_update', args=[self.therapist_1.pk])

        # GET form
        resp_get = self.client.get(url)
        self.assertEqual(resp_get.status_code, 200)
        content = resp_get.content.decode('utf-8')
        self.assertIn("Select All Hard", content)
        self.assertIn("Select All Medium", content)
        self.assertIn("Select All Easy", content)
        self.assertIn("Clear All", content)
        self.assertIn("treatment-checkbox", content)

        # POST multiple omit_treatment_ids
        post_data = {
            'therapist_name': self.therapist_1.therapist_name,
            'therapist_grade': self.senior_grade.pk,
            'employee_code': self.therapist_1.employee_code,
            'therapist_gender': 'Male',
            'is_active': 'on',
            'omit_treatment_ids': [self.therapy_a.pk, self.therapy_b.pk],
            'omit_reason': 'Request to omit hard and medium treatments due to arm strain'
        }
        resp_post = self.client.post(url, post_data)
        # Should redirect to manage page on success
        self.assertEqual(resp_post.status_code, 302)

        # Verify pending omissions created
        omissions = TherapistTreatmentOmission.objects.filter(
            therapist=self.therapist_1,
            status='pending'
        )
        self.assertEqual(omissions.count(), 2)
        treatment_ids = set(omissions.values_list('treatment_id', flat=True))
        self.assertIn(self.therapy_a.pk, treatment_ids)
        self.assertIn(self.therapy_b.pk, treatment_ids)
        self.assertEqual(
            omissions.first().reason,
            'Request to omit hard and medium treatments due to arm strain'
        )

    def test_batch_request_creation_and_batch_approval(self):
        """All treatments submitted in a single request share a batch_id and can be approved in one action"""
        from django.urls import reverse
        self.client.force_login(self.admin_user)
        url = reverse('therapist_master_update', args=[self.therapist_1.pk])

        post_data = {
            'therapist_name': self.therapist_1.therapist_name,
            'therapist_grade': self.senior_grade.pk,
            'employee_code': self.therapist_1.employee_code,
            'therapist_gender': 'Male',
            'is_active': 'on',
            'omit_treatment_ids': [self.therapy_a.pk, self.therapy_b.pk],
            'omit_reason': 'Combined batch omission request'
        }
        resp = self.client.post(url, post_data)
        self.assertEqual(resp.status_code, 302)

        omissions = TherapistTreatmentOmission.objects.filter(
            therapist=self.therapist_1,
            status='pending'
        )
        self.assertEqual(omissions.count(), 2)
        batch_id = omissions.first().batch_id
        self.assertTrue(bool(batch_id))
        self.assertTrue(batch_id.startswith('TOR-'))
        # Both omissions must share the exact same batch_id
        self.assertEqual(omissions[0].batch_id, omissions[1].batch_id)

        # Test grouping helper
        grouped = group_omissions_by_request(omissions)
        self.assertEqual(len(grouped), 1)
        req = grouped[0]
        self.assertEqual(req.total_count, 2)
        self.assertEqual(req.medium_count, 2)
        self.assertEqual(req.batch_id, batch_id)

        # Before approval, therapist is not omitted
        self.assertFalse(is_therapist_omitted_for_treatment(self.therapist_1, self.therapy_a))
        self.assertFalse(is_therapist_omitted_for_treatment(self.therapist_1, self.therapy_b))

        # Admin approves the whole batch in one single API call
        req_admin = self.factory.post(
            f'/masters/therapists/treatment-omissions/batch/{batch_id}/approve/',
            data='{"remarks": "Batch approved by Admin"}',
            content_type='application/json'
        )
        req_admin.user = self.admin_user
        resp_admin = approve_therapist_treatment_omission_batch_api(req_admin, batch_id)
        self.assertEqual(resp_admin.status_code, 200)

        # Verify all omissions in the batch are now approved
        omissions_after = TherapistTreatmentOmission.objects.filter(batch_id=batch_id)
        self.assertEqual(omissions_after.count(), 2)
        for om in omissions_after:
            self.assertEqual(om.status, 'approved')
            self.assertEqual(om.approved_by, self.admin_user)
            self.assertEqual(om.approval_remarks, 'Batch approved by Admin')

        # Now therapist_1 IS omitted for BOTH treatments
        self.assertTrue(is_therapist_omitted_for_treatment(self.therapist_1, self.therapy_a))
        self.assertTrue(is_therapist_omitted_for_treatment(self.therapist_1, self.therapy_b))

    def test_batch_request_rejection(self):
        """Admin/HR can reject an entire batch of treatments in one single action"""
        batch_id = "TOR-TEST-REJECT-001"
        TherapistTreatmentOmission.objects.create(
            therapist=self.therapist_1,
            treatment=self.therapy_a,
            reason="Exemption test",
            status="pending",
            batch_id=batch_id,
            requested_by=self.therapist_user
        )
        TherapistTreatmentOmission.objects.create(
            therapist=self.therapist_1,
            treatment=self.therapy_b,
            reason="Exemption test",
            status="pending",
            batch_id=batch_id,
            requested_by=self.therapist_user
        )

        req_reject = self.factory.post(
            f'/masters/therapists/treatment-omissions/batch/{batch_id}/reject/',
            data='{"remarks": "Not approved"}',
            content_type='application/json'
        )
        req_reject.user = self.hr_user
        resp_reject = reject_therapist_treatment_omission_batch_api(req_reject, batch_id)
        self.assertEqual(resp_reject.status_code, 200)

        omissions = TherapistTreatmentOmission.objects.filter(batch_id=batch_id)
        self.assertEqual(omissions.count(), 2)
        for om in omissions:
            self.assertEqual(om.status, 'rejected')
            self.assertEqual(om.approved_by, self.hr_user)

        self.assertFalse(is_therapist_omitted_for_treatment(self.therapist_1, self.therapy_a))
        self.assertFalse(is_therapist_omitted_for_treatment(self.therapist_1, self.therapy_b))

    def test_batch_request_delete_cancellation(self):
        """Cancelling a batch request deletes all associated omission records"""
        batch_id = "TOR-TEST-DELETE-001"
        TherapistTreatmentOmission.objects.create(
            therapist=self.therapist_1,
            treatment=self.therapy_a,
            reason="Delete test",
            status="pending",
            batch_id=batch_id
        )
        TherapistTreatmentOmission.objects.create(
            therapist=self.therapist_1,
            treatment=self.therapy_b,
            reason="Delete test",
            status="pending",
            batch_id=batch_id
        )

        req_del = self.factory.post(
            f'/masters/therapists/treatment-omissions/batch/{batch_id}/delete/',
            content_type='application/json'
        )
        req_del.user = self.admin_user
        resp_del = delete_therapist_treatment_omission_batch_api(req_del, batch_id)
        self.assertEqual(resp_del.status_code, 200)

        self.assertEqual(TherapistTreatmentOmission.objects.filter(batch_id=batch_id).count(), 0)

    def test_approvals_view_shows_single_request_for_multiple_treatments(self):
        """Dashboard groups all treatments into a single request row and displays total treatments"""
        batch_id = "TOR-TEST-DASHBOARD-001"
        TherapistTreatmentOmission.objects.create(
            therapist=self.therapist_1,
            treatment=self.therapy_a,
            reason="Special arm injury",
            status="pending",
            batch_id=batch_id,
            requested_by=self.admin_user
        )
        TherapistTreatmentOmission.objects.create(
            therapist=self.therapist_1,
            treatment=self.therapy_b,
            reason="Special arm injury",
            status="pending",
            batch_id=batch_id,
            requested_by=self.admin_user
        )

        self.client.force_login(self.admin_user)
        from django.urls import reverse
        resp = self.client.get(reverse('therapist_treatment_omission_approvals'))
        self.assertEqual(resp.status_code, 200)
        content = resp.content.decode('utf-8')

        # Context has 1 request and 2 treatments
        self.assertEqual(resp.context['pending_requests_count'], 1)
        self.assertEqual(resp.context['pending_treatments_count'], 2)
        self.assertEqual(len(resp.context['pending_requests']), 1)

        # Template displays the therapist and 2 Treatments badge
        self.assertIn("Therapist One", content)
        self.assertIn("2 Treatments", content)
        self.assertIn("Approve Request", content)
        self.assertIn("Reject Request", content)
        self.assertIn(batch_id, content)

