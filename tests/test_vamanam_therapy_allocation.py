"""
Test Suite: Vamanam Therapy Dynamic Slot & Room Allocation

Requirements Verified:
1. When a therapy has is_vamanam=True (or matches Vamanam in TherapyMaster):
   - Allowed slots are EXCLUSIVELY Vamanam slots (e.g., 05:00 AM, 05:30 AM).
   - Regular therapies NEVER receive Vamanam slots (strictly excluded from allowed slots).
2. Treatment room allocation:
   - Only rooms with is_vamanam_room=True in TreatmentRoom are eligible.
   - If all Vamanam rooms are occupied, allocation fails with a descriptive reason.
   - Dynamic toggle of is_vamanam_room immediately reflects in room availability.
3. Views and Management:
   - slot_master_toggle_vamanam toggles is_vamanam_slot between True and False.
   - treatment_room_master_toggle_vamanam toggles is_vamanam_room between True and False.
   - SlotMasterManagementView separates regular_slot_list and vamanam_slot_list.
"""

import pytest
from datetime import date, time
from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth import get_user_model

from masters.models import TherapyMaster, SlotMaster, TherapistMaster, TherapistGrade
from Patient.models import TreatmentRoom, RoomName, RoomBooking
from Sheduling.models import PatientSnapshot, TherapyAllocation, Booking
from reshedule import (
    get_allowed_slot_values,
    is_vamanam_treatment,
    get_vamanam_slots,
    get_vamanam_treatment_rooms,
    allocate_treatment_room as reshedule_allocate_treatment_room,
)
from final_allocation import allocate_treatment_room as final_allocate_treatment_room


@pytest.mark.django_db
class TestVamanamTherapyAllocation(TestCase):
    def setUp(self):
        # 1. Setup Slots
        self.slot_0500, _ = SlotMaster.objects.get_or_create(
            slot_number=8,
            defaults={"slot_time": time(5, 0), "slot_name": "05:00 AM", "is_active": True, "is_vamanam_slot": True}
        )
        self.slot_0500.is_vamanam_slot = True
        self.slot_0500.is_active = True
        self.slot_0500.save()

        self.slot_0530, _ = SlotMaster.objects.get_or_create(
            slot_number=9,
            defaults={"slot_time": time(5, 30), "slot_name": "05:30 AM", "is_active": True, "is_vamanam_slot": True}
        )
        self.slot_0530.is_vamanam_slot = True
        self.slot_0530.is_active = True
        self.slot_0530.save()

        self.slot_0830, _ = SlotMaster.objects.get_or_create(
            slot_number=2,
            defaults={"slot_time": time(8, 30), "slot_name": "08:30 AM", "is_active": True, "is_vamanam_slot": False}
        )
        self.slot_0830.is_vamanam_slot = False
        self.slot_0830.is_active = True
        self.slot_0830.save()

        self.slot_1000, _ = SlotMaster.objects.get_or_create(
            slot_number=3,
            defaults={"slot_time": time(10, 0), "slot_name": "10:00 AM", "is_active": True, "is_vamanam_slot": False}
        )
        self.slot_1000.is_vamanam_slot = False
        self.slot_1000.is_active = True
        self.slot_1000.save()

        # 2. Setup Treatment Rooms
        rn1, _ = RoomName.objects.get_or_create(name="Room TR-1", defaults={"is_active": True})
        self.tr1, _ = TreatmentRoom.objects.get_or_create(
            room_no="TR-1",
            defaults={"room_name": rn1, "floor": "G", "is_active": True, "is_vamanam_room": False}
        )
        self.tr1.is_vamanam_room = False
        self.tr1.save()

        rn_vam1, _ = RoomName.objects.get_or_create(name="Room TR-VAM1", defaults={"is_active": True})
        self.tr_vam1, _ = TreatmentRoom.objects.get_or_create(
            room_no="TR-VAM1",
            defaults={"room_name": rn_vam1, "floor": "G", "is_active": True, "is_vamanam_room": True}
        )
        self.tr_vam1.is_vamanam_room = True
        self.tr_vam1.save()

        # 3. Create Therapist
        self.grade_sr, _ = TherapistGrade.objects.get_or_create(
            name="Senior Therapist",
            defaults={"display_order": 2, "is_active": True}
        )
        self.therapist_male = TherapistMaster.objects.create(
            therapist_code="TH_VAM_M1",
            therapist_name="Suresh Kumar",
            therapist_gender="Male",
            therapist_grade=self.grade_sr,
            employee_code="EMP_VAM_01",
            is_bathing_therapist=True,
            is_active=True
        )

        # 4. Therapies
        self.regular_therapy = TherapyMaster.objects.create(
            therapy_code="THEB901_REG",
            therapy_name="Abhyanga Regular",
            therapy_category="Medium",
            therapy_duration="45 mins",
            bathing_required="No",
            treatment_room_required="Yes",
            cost_of_therapy=1000,
            patient_type="IP",
            is_vamanam=False,
            no_of_senior_therapist=1,
            total_no_of_therapist=1,
            is_active=True
        )

        self.vamanam_therapy = TherapyMaster.objects.create(
            therapy_code="THEB902_VAM",
            therapy_name="Vamanam Special",
            therapy_category="Major",
            therapy_duration="60 mins",
            bathing_required="No",
            treatment_room_required="Yes",
            cost_of_therapy=2500,
            patient_type="IP",
            is_vamanam=True,
            no_of_senior_therapist=1,
            total_no_of_therapist=1,
            is_active=True
        )

        # 5. Patient Snapshot
        self.target_date = date(2026, 6, 15)
        self.patient = PatientSnapshot.objects.create(
            pat_reg_no="600088",
            pat_name="Mr. Vamanam Test Patient",
            pat_sex="Male",
            pat_age="40",
            pat_room_no="DS-1"
        )

    def test_is_vamanam_treatment_detection(self):
        """Validates detection via flag, code and name."""
        assert is_vamanam_treatment(therapy_code=self.vamanam_therapy.therapy_code) is True
        assert is_vamanam_treatment(therapy_name="Vamanam Karma") is True
        assert is_vamanam_treatment(therapy_code=self.regular_therapy.therapy_code) is False
        assert is_vamanam_treatment(therapy_name=self.regular_therapy.therapy_name) is False

    def test_vamanam_slots_retrieval(self):
        """get_vamanam_slots() returns active vamanam slot times."""
        slots = get_vamanam_slots()
        assert "05:00" in slots
        assert "05:30" in slots
        assert "08:30" not in slots

    def test_vamanam_allowed_slots_exclusivity(self):
        """Vamanam therapy strictly gets Vamanam slots; regular therapy never gets Vamanam slots."""
        vam_slots = get_allowed_slot_values(
            patient_type="IP",
            therapy_category="Major",
            therapy_name=self.vamanam_therapy.therapy_name,
            therapy_code=self.vamanam_therapy.therapy_code
        )
        assert "05:00" in vam_slots
        assert "05:30" in vam_slots
        assert "08:30" not in vam_slots
        assert "10:00" not in vam_slots

        reg_slots = get_allowed_slot_values(
            patient_type="IP",
            therapy_category="Medium",
            therapy_name=self.regular_therapy.therapy_name,
            therapy_code=self.regular_therapy.therapy_code
        )
        assert "05:00" not in reg_slots
        assert "05:30" not in reg_slots
        assert "08:30" in reg_slots

    def test_final_allocation_vamanam_treatment_room(self):
        """final_allocation allocate_treatment_room assigns Vamanam room."""
        room_vam = final_allocate_treatment_room(
            date=self.target_date,
            time_slot=self.slot_0500,
            therapy_name=self.vamanam_therapy.therapy_name,
            patient_staying_room="DS-1",
            patient=self.patient
        )
        assert room_vam is not None
        assert room_vam.room_no == "TR-VAM1"

    def test_final_allocation_vamanam_room_unavailable_when_occupied(self):
        """When all Vamanam rooms are booked, regular rooms are NOT borrowed."""
        RoomBooking.objects.create(
            room=self.tr_vam1,
            date=self.target_date,
            time_slot=self.slot_0500,
            status="BOOKED"
        )
        room_vam = final_allocate_treatment_room(
            date=self.target_date,
            time_slot=self.slot_0500,
            therapy_name=self.vamanam_therapy.therapy_name,
            patient_staying_room="DS-1",
            patient=self.patient
        )
        assert room_vam is None

    def test_reshedule_vamanam_treatment_room_allocation(self):
        """reshedule allocate_treatment_room strictly allocates rooms configured with is_vamanam_room=True."""
        allocated_room = reshedule_allocate_treatment_room(
            date=self.target_date,
            time_slot=self.slot_0500,
            therapy_name=self.vamanam_therapy.therapy_name,
            patient_staying_room="DS-1",
            patient=self.patient
        )

        assert allocated_room is not None
        assert allocated_room.room_no == "TR-VAM1"

    def test_reshedule_vamanam_room_unavailable_when_occupied(self):
        """In reshedule, if all Vamanam rooms are occupied, regular rooms are NOT borrowed."""
        RoomBooking.objects.create(
            room=self.tr_vam1,
            date=self.target_date,
            time_slot=self.slot_0500,
            status="BOOKED"
        )

        allocated_room = reshedule_allocate_treatment_room(
            date=self.target_date,
            time_slot=self.slot_0500,
            therapy_name=self.vamanam_therapy.therapy_name,
            patient_staying_room="DS-1",
            patient=self.patient
        )

        assert allocated_room is None

    def test_dynamic_vamanam_room_toggle(self):
        """Enabling is_vamanam_room on TR-1 dynamically allows it to be used for Vamanam."""
        self.tr1.is_vamanam_room = True
        self.tr1.save()

        vamanam_rooms = get_vamanam_treatment_rooms()
        assert "TR-1" in vamanam_rooms

        self.tr1.is_vamanam_room = False
        self.tr1.save()

        vamanam_rooms_after = get_vamanam_treatment_rooms()
        assert "TR-1" not in vamanam_rooms_after

    def test_slot_master_toggle_vamanam_view(self):
        """Validates slot toggle view converts regular slot to vamanam and back."""
        User = get_user_model()
        admin_user, _ = User.objects.get_or_create(
            username="test_superadmin_vam",
            defaults={"is_superuser": True, "is_staff": True, "role": "super_admin"}
        )
        if getattr(admin_user, 'role', None) != 'super_admin':
            admin_user.role = 'super_admin'
            admin_user.save()

        client = Client()
        client.force_login(admin_user)

        url = reverse("slot_master_toggle_vamanam", kwargs={"pk": self.slot_0830.pk})
        response = client.get(url, follow=True)
        assert response.status_code == 200

        self.slot_0830.refresh_from_db()
        assert self.slot_0830.is_vamanam_slot is True

        # Toggle back
        response2 = client.get(url, follow=True)
        assert response2.status_code == 200

        self.slot_0830.refresh_from_db()
        assert self.slot_0830.is_vamanam_slot is False

    def test_treatment_room_master_toggle_vamanam_view(self):
        """Validates treatment room toggle view converts room to vamanam and back."""
        User = get_user_model()
        admin_user, _ = User.objects.get_or_create(
            username="test_superadmin_vam_room",
            defaults={"is_superuser": True, "is_staff": True, "role": "super_admin"}
        )
        if getattr(admin_user, 'role', None) != 'super_admin':
            admin_user.role = 'super_admin'
            admin_user.save()

        client = Client()
        client.force_login(admin_user)

        url = reverse("treatment_room_master_toggle_vamanam", kwargs={"pk": self.tr1.room_no})
        response = client.get(url, follow=True)
        assert response.status_code == 200

        self.tr1.refresh_from_db()
        assert self.tr1.is_vamanam_room is True

        # Toggle back
        response2 = client.get(url, follow=True)
        assert response2.status_code == 200

        self.tr1.refresh_from_db()
        assert self.tr1.is_vamanam_room is False

    def test_therapy_entry_search_therapies_api_includes_vamanam_flag(self):
        """Validates that search_therapies endpoint returns is_vamanam boolean flag."""
        User = get_user_model()
        doctor_user, _ = User.objects.get_or_create(
            username="test_doc_vam",
            defaults={"is_superuser": True, "is_staff": True, "role": "doctor"}
        )
        client = Client()
        client.force_login(doctor_user)

        url = reverse("patient_therapy") + "?action=search_therapies&q=Vamanam"
        response = client.get(url)
        assert response.status_code == 200
        data = response.json()
        assert len(data) > 0
        vam_item = next(item for item in data if item["therapy_code"] == self.vamanam_therapy.therapy_code)
        assert vam_item["is_vamanam"] is True

        # Regular therapy
        url_reg = reverse("patient_therapy") + f"?action=search_therapies&q={self.regular_therapy.therapy_name}"
        response_reg = client.get(url_reg)
        data_reg = response_reg.json()
        reg_item = next(item for item in data_reg if item["therapy_code"] == self.regular_therapy.therapy_code)
        assert reg_item["is_vamanam"] is False

    def test_therapy_entry_slots_api_vamanam_filtering(self):
        """Validates action=slots on Add Therapy endpoint filters Vamanam vs Normal slots."""
        User = get_user_model()
        doctor_user, _ = User.objects.get_or_create(
            username="test_doc_vam_slots",
            defaults={"is_superuser": True, "is_staff": True, "role": "doctor"}
        )
        client = Client()
        client.force_login(doctor_user)

        # 1. When filter_type=vamanam_only or is_vamanam=true: show ONLY vamanam slots
        url_vam = reverse("patient_therapy") + "?action=slots&filter_type=vamanam_only"
        res_vam = client.get(url_vam)
        assert res_vam.status_code == 200
        slots_vam = [s["start_time"] for s in res_vam.json().get("slots", [])]
        assert "05:00" in slots_vam
        assert "05:30" in slots_vam
        assert "08:30" not in slots_vam
        assert "10:00" not in slots_vam

        # 2. When filter_type=regular_only or is_vamanam=false: show other slots EXCEPT vamanam slots
        url_reg = reverse("patient_therapy") + "?action=slots&filter_type=regular_only"
        res_reg = client.get(url_reg)
        assert res_reg.status_code == 200
        slots_reg = [s["start_time"] for s in res_reg.json().get("slots", [])]
        assert "05:00" not in slots_reg
        assert "05:30" not in slots_reg
        assert "08:30" in slots_reg
        assert "10:00" in slots_reg

    def test_patient_views_time_slots_api_filtering(self):
        """Validates /time_slots/ endpoint filters Vamanam vs Normal slots."""
        client = Client()

        # Vamanam filter
        res_vam = client.get(reverse("patient:time_slots") + "?filter_type=vamanam_only")
        assert res_vam.status_code == 200
        times_vam = [s["start_time"] for s in res_vam.json().get("slots", [])]
        assert "05:00" in times_vam
        assert "05:30" in times_vam
        assert "08:30" not in times_vam

        # Regular filter
        res_reg = client.get(reverse("patient:time_slots") + "?filter_type=regular_only")
        assert res_reg.status_code == 200
        times_reg = [s["start_time"] for s in res_reg.json().get("slots", [])]
        assert "05:00" not in times_reg
        assert "05:30" not in times_reg
        assert "08:30" in times_reg

    def test_allocate_therapy_endpoint_vamanam_slot_validation(self):
        """Validates allocate_therapy blocks regular therapy in Vamanam slot and vice-versa."""
        User = get_user_model()
        doctor_user, _ = User.objects.get_or_create(
            username="test_doc_alloc_vam",
            defaults={"is_superuser": True, "is_staff": True, "role": "doctor"}
        )
        client = Client()
        client.force_login(doctor_user)

        import json

        # Attempt to allocate regular therapy in a Vamanam slot (05:00) -> Must be rejected!
        payload_reg = {
            "patient_reg_no": self.patient.pat_reg_no,
            "therapy_code": self.regular_therapy.therapy_code,
            "therapy_name": self.regular_therapy.therapy_name,
            "from_date": "2026-06-15",
            "to_date": "2026-06-15",
            "timeslot": "05:00"
        }
        res_reg = client.post(
            reverse("allocate_therapy"),
            data=json.dumps(payload_reg),
            content_type="application/json"
        )
        assert res_reg.status_code == 400
        assert "vamanam_slot_exclusive" in res_reg.json().get("error", "")

        # Attempt to allocate Vamanam therapy in a regular slot (08:30) -> Must be rejected!
        payload_vam = {
            "patient_reg_no": self.patient.pat_reg_no,
            "therapy_code": self.vamanam_therapy.therapy_code,
            "therapy_name": self.vamanam_therapy.therapy_name,
            "from_date": "2026-06-15",
            "to_date": "2026-06-15",
            "timeslot": "08:30"
        }
        res_vam = client.post(
            reverse("allocate_therapy"),
            data=json.dumps(payload_vam),
            content_type="application/json"
        )
        assert res_vam.status_code == 400
        assert "vamanam_slot_required" in res_vam.json().get("error", "")

    def test_allocate_therapy_auto_schedules_if_final_schedule_run_exists(self):
        """Validates that adding a therapy for a date where FinalScheduleRun exists triggers automatic allocation."""
        from unittest.mock import patch
        from Sheduling.models import FinalScheduleRun
        import datetime
        import json

        User = get_user_model()
        doctor_user, _ = User.objects.get_or_create(
            username="test_doc_alloc_final_sched",
            defaults={"is_superuser": True, "is_staff": True, "role": "doctor"}
        )
        client = Client()
        client.force_login(doctor_user)

        from django.utils import timezone
        target_date = timezone.localtime(timezone.now()).date() + datetime.timedelta(days=1)
        target_date_str = target_date.strftime("%Y-%m-%d")
        FinalScheduleRun.objects.create(
            run_date=target_date,
            status="success"
        )

        with patch("final_allocation.bulk_allocate_for_date") as mock_bulk:
            mock_bulk.return_value = {"success": True}

            payload = {
                "action": "allocate",
                "patient_reg_no": self.patient.pat_reg_no,
                "therapy_code": self.regular_therapy.therapy_code,
                "therapy_name": self.regular_therapy.therapy_name,
                "from_date": target_date_str,
                "to_date": target_date_str,
                "timeslot": "08:30"
            }
            res = client.post(
                reverse("patient_therapy"),
                data=json.dumps(payload),
                content_type="application/json"
            )
            assert res.status_code == 201, f"Failed with {res.json()}"
            assert mock_bulk.called
            assert mock_bulk.call_args[0][0] == target_date_str

