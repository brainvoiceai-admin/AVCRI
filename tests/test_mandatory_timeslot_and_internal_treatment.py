import json
import pytest
from datetime import date, time
from django.test import TestCase, Client

from masters.models import SlotMaster, TherapyMaster
from Sheduling.models import PatientSnapshot, TherapyAllocation, Booking


@pytest.mark.django_db
class MandatoryTimeslotAndInternalTreatmentTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.target_date = date(2027, 3, 15)
        self.target_date_str = self.target_date.strftime("%Y-%m-%d")

        # Create slot
        self.slot, _ = SlotMaster.objects.get_or_create(
            slot_number=1,
            defaults={"slot_time": time(8, 0), "is_active": True}
        )

        # Regular external therapy
        self.regular_therapy, _ = TherapyMaster.objects.get_or_create(
            therapy_code="TH_EXT_REG",
            defaults={
                "therapy_name": "External Abhyangam",
                "therapy_category": "Medium",
                "total_no_of_therapist": 2,
                "is_active": True,
            }
        )

        # Internal therapy with zero therapists
        self.zero_therapy, _ = TherapyMaster.objects.get_or_create(
            therapy_code="TH_ZERO_TPT",
            defaults={
                "therapy_name": "Zero Therapist Medicine",
                "therapy_category": "Easy",
                "total_no_of_therapist": 0,
                "is_active": True,
            }
        )

        # Patient
        self.patient, _ = PatientSnapshot.objects.get_or_create(
            pat_reg_no="TEST_SLOT_001",
            defaults={
                "pat_name": "Slot Test Patient",
                "pat_age": "40",
                "pat_sex": "Male",
                "is_vip": True,
            }
        )

    def test_regular_therapy_without_timeslot_fails(self):
        """Regular external therapy cannot be allocated without a timeslot."""
        payload = {
            "patient_reg_no": self.patient.pat_reg_no,
            "patient_name": self.patient.pat_name,
            "therapy_code": self.regular_therapy.therapy_code,
            "therapy_name": self.regular_therapy.therapy_name,
            "ext_int": "External",
            "slot": "",  # Empty slot
            "from_date": self.target_date_str,
            "to_date": self.target_date_str,
            "items_groups": []
        }
        resp = self.client.post(
            "/sheduling/therapy-entry/?action=allocate",
            data=json.dumps(payload),
            content_type="application/json"
        )
        self.assertEqual(resp.status_code, 400)
        data = resp.json()
        self.assertEqual(data.get("error"), "timeslot_required")

    def test_regular_therapy_with_timeslot_succeeds(self):
        """Regular external therapy with timeslot succeeds."""
        payload = {
            "patient_reg_no": self.patient.pat_reg_no,
            "patient_name": self.patient.pat_name,
            "therapy_code": self.regular_therapy.therapy_code,
            "therapy_name": self.regular_therapy.therapy_name,
            "ext_int": "External",
            "slot": "08:00",
            "from_date": self.target_date_str,
            "to_date": self.target_date_str,
            "items_groups": []
        }
        resp = self.client.post(
            "/sheduling/therapy-entry/?action=allocate",
            data=json.dumps(payload),
            content_type="application/json"
        )
        self.assertIn(resp.status_code, [200, 201])
        data = resp.json()
        self.assertEqual(data.get("status"), "ok")
        alloc_id = data.get("allocation_id")
        alloc = TherapyAllocation.objects.get(id=alloc_id)
        self.assertEqual(alloc.timeslot, self.slot)

    def test_internal_therapy_without_timeslot_succeeds(self):
        """Internal therapy (ext_int='Internal') does NOT require a timeslot."""
        payload = {
            "patient_reg_no": self.patient.pat_reg_no,
            "patient_name": self.patient.pat_name,
            "therapy_code": self.regular_therapy.therapy_code,
            "therapy_name": self.regular_therapy.therapy_name,
            "ext_int": "Internal",
            "slot": "",  # Empty slot allowed for internal
            "from_date": self.target_date_str,
            "to_date": self.target_date_str,
            "items_groups": []
        }
        resp = self.client.post(
            "/sheduling/therapy-entry/?action=allocate",
            data=json.dumps(payload),
            content_type="application/json"
        )
        self.assertIn(resp.status_code, [200, 201])
        data = resp.json()
        self.assertEqual(data.get("status"), "ok")
        alloc_id = data.get("allocation_id")
        alloc = TherapyAllocation.objects.get(id=alloc_id)
        self.assertIsNone(alloc.timeslot)

    def test_zero_therapist_therapy_without_timeslot_succeeds(self):
        """Zero-therapist internal treatment does not require timeslot even if ext_int is not specified."""
        payload = {
            "patient_reg_no": self.patient.pat_reg_no,
            "patient_name": self.patient.pat_name,
            "therapy_code": self.zero_therapy.therapy_code,
            "therapy_name": self.zero_therapy.therapy_name,
            "ext_int": "",
            "slot": "",
            "from_date": self.target_date_str,
            "to_date": self.target_date_str,
            "items_groups": []
        }
        resp = self.client.post(
            "/sheduling/therapy-entry/?action=allocate",
            data=json.dumps(payload),
            content_type="application/json"
        )
        self.assertIn(resp.status_code, [200, 201])
        data = resp.json()
        self.assertEqual(data.get("status"), "ok")

    def test_update_regular_therapy_clearing_timeslot_fails(self):
        """Updating a regular therapy and clearing the timeslot is rejected."""
        alloc = TherapyAllocation.objects.create(
            patient=self.patient,
            therapy_code=self.regular_therapy.therapy_code,
            therapy_name=self.regular_therapy.therapy_name,
            ext_int="External",
            timeslot=self.slot,
            from_date=self.target_date,
            to_date=self.target_date,
            days=1
        )
        payload = {
            "allocation_id": alloc.id,
            "therapy_name": alloc.therapy_name,
            "ext_int": "External",
            "slot": "",  # Try to clear timeslot
        }
        resp = self.client.post(
            "/sheduling/therapy-entry/?action=update_therapy",
            data=json.dumps(payload),
            content_type="application/json"
        )
        self.assertEqual(resp.status_code, 400)
        data = resp.json()
        self.assertEqual(data.get("error"), "timeslot_required")

    def test_virechanam_by_code_without_timeslot_succeeds(self):
        """Virechanam (THEB128) by code without timeslot succeeds even if ext_int is empty."""
        payload = {
            "patient_reg_no": self.patient.pat_reg_no,
            "patient_name": self.patient.pat_name,
            "therapy_code": "THEB128",
            "therapy_name": "Virechanam",
            "ext_int": "",
            "slot": "",
            "from_date": self.target_date_str,
            "to_date": self.target_date_str,
            "items_groups": []
        }
        resp = self.client.post(
            "/sheduling/therapy-entry/?action=allocate",
            data=json.dumps(payload),
            content_type="application/json"
        )
        self.assertIn(resp.status_code, [200, 201])
        data = resp.json()
        self.assertEqual(data.get("status"), "ok")

    def test_nurse_treatment_without_timeslot_succeeds(self):
        """Nurse treatment (NT001) without timeslot succeeds."""
        payload = {
            "patient_reg_no": self.patient.pat_reg_no,
            "patient_name": self.patient.pat_name,
            "therapy_code": "NT001",
            "therapy_name": "Tarpanam",
            "ext_int": "",
            "slot": "",
            "from_date": self.target_date_str,
            "to_date": self.target_date_str,
            "items_groups": []
        }
        resp = self.client.post(
            "/sheduling/therapy-entry/?action=allocate",
            data=json.dumps(payload),
            content_type="application/json"
        )
        self.assertIn(resp.status_code, [200, 201])
        data = resp.json()
        self.assertEqual(data.get("status"), "ok")
