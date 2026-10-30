"""
Test Suite: Vasthi Therapy Dynamic Slot & Cottage Room Allocation

Requirements Verified:
1. Vasthi Identification:
   - Dynamic toggle is_vasthi=True on TherapyMaster marks therapy as Vasthi.
   - Therapy group 'Vasthi' is recognized as Vasthi.
   - THEB037 (Mathra Vasthi) is exempt.
2. Dynamic Slot Configuration:
   - Dynamic toggle is_vasthi_slot=True on SlotMaster marks slot as Vasthi slot (defaults to 08:30).
   - get_vasthi_slots() returns active Vasthi slots.
3. Dedicated Vasthi Room Allocation (allocate_vasthi_treatment_room):
   - Vasthi treatment for a patient in a Cottage Room (e.g. CT-1) preferably allocates TRC-1.
   - If more than one patient is admitted in the same Cottage Room, only one patient is assigned
     to the Cottage Room (TRC-1); the remaining patients are assigned to other suitable treatment rooms (TR-1 to TR-16).
   - Non-cottage patients (e.g. DS-1, NR-7) follow normal staying room rules.
   - Existing normal treatment room allocation for non-Vasthi therapies remains completely unaffected.
4. Admin / Management Views:
   - therapy_master_toggle_vasthi toggles is_vasthi.
   - slot_master_toggle_vasthi toggles is_vasthi_slot.
"""

import pytest
from datetime import date, time
from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth import get_user_model

from masters.models import TherapyMaster, SlotMaster, TherapyGroup
from Patient.models import TreatmentRoom, RoomName, RoomBooking
from Sheduling.models import PatientSnapshot
from reshedule import (
    is_vasthi_treatment,
    get_vasthi_slots,
    allocate_vasthi_treatment_room,
    allocate_treatment_room as reshedule_allocate_treatment_room,
)
from final_allocation import allocate_treatment_room as final_allocate_treatment_room


@pytest.mark.django_db
class TestVasthiTherapyAllocation(TestCase):
    def setUp(self):
        # 1. Setup Slots
        self.slot_0830, _ = SlotMaster.objects.get_or_create(
            slot_number=2,
            defaults={"slot_time": time(8, 30), "slot_name": "08:30 AM", "is_active": True, "is_vasthi_slot": True}
        )
        self.slot_0830.is_vasthi_slot = True
        self.slot_0830.is_active = True
        self.slot_0830.save()

        self.slot_1000, _ = SlotMaster.objects.get_or_create(
            slot_number=3,
            defaults={"slot_time": time(10, 0), "slot_name": "10:00 AM", "is_active": True, "is_vasthi_slot": False}
        )
        self.slot_1000.is_vasthi_slot = False
        self.slot_1000.is_active = True
        self.slot_1000.save()

        # 2. Setup Treatment Rooms
        # Cottage Treatment Rooms
        rnc1, _ = RoomName.objects.get_or_create(name="Cottage TRC-1", defaults={"is_active": True})
        self.trc1, _ = TreatmentRoom.objects.get_or_create(
            room_no="TRC-1",
            defaults={"room_name": rnc1, "floor": "G", "is_active": True}
        )
        self.trc1.is_active = True
        self.trc1.save()

        rnc2, _ = RoomName.objects.get_or_create(name="Cottage TRC-2", defaults={"is_active": True})
        self.trc2, _ = TreatmentRoom.objects.get_or_create(
            room_no="TRC-2",
            defaults={"room_name": rnc2, "floor": "G", "is_active": True}
        )
        self.trc2.is_active = True
        self.trc2.save()

        # Standard Treatment Rooms (TR-1, TR-2, TR-3)
        rn1, _ = RoomName.objects.get_or_create(name="Room TR-1", defaults={"is_active": True})
        self.tr1, _ = TreatmentRoom.objects.get_or_create(
            room_no="TR-1",
            defaults={"room_name": rn1, "floor": "G", "is_active": True}
        )
        self.tr1.is_active = True
        self.tr1.save()

        rn2, _ = RoomName.objects.get_or_create(name="Room TR-2", defaults={"is_active": True})
        self.tr2, _ = TreatmentRoom.objects.get_or_create(
            room_no="TR-2",
            defaults={"room_name": rn2, "floor": "G", "is_active": True}
        )
        self.tr2.is_active = True
        self.tr2.save()

        rn3, _ = RoomName.objects.get_or_create(name="Room TR-3", defaults={"is_active": True})
        self.tr3, _ = TreatmentRoom.objects.get_or_create(
            room_no="TR-3",
            defaults={"room_name": rn3, "floor": "G", "is_active": True}
        )
        self.tr3.is_active = True
        self.tr3.save()

        # 3. Setup Therapies
        self.grp_vasthi, _ = TherapyGroup.objects.get_or_create(name="Vasthi", defaults={"is_active": True})

        self.th_kashaya, _ = TherapyMaster.objects.get_or_create(
            therapy_code="THEB020",
            defaults={"therapy_name": "Kashayavasthi", "therapy_group": self.grp_vasthi, "is_vasthi": True, "is_active": True}
        )
        self.th_kashaya.is_vasthi = True
        self.th_kashaya.save()

        self.th_mathra, _ = TherapyMaster.objects.get_or_create(
            therapy_code="THEB037",
            defaults={"therapy_name": "Mathra Vasthi", "therapy_group": self.grp_vasthi, "is_vasthi": False, "is_active": True}
        )
        self.th_mathra.is_vasthi = False
        self.th_mathra.save()

        self.th_abhyanga, _ = TherapyMaster.objects.get_or_create(
            therapy_code="THEB001",
            defaults={"therapy_name": "Abhyanga", "is_vasthi": False, "is_active": True}
        )
        self.th_abhyanga.is_vasthi = False
        self.th_abhyanga.save()

        # 4. User and Client
        User = get_user_model()
        self.admin_user, _ = User.objects.get_or_create(
            username="vasthi_admin",
            defaults={"is_staff": True, "is_superuser": True, "role": "super_admin"}
        )
        self.admin_user.role = "super_admin"
        self.admin_user.set_password("pass123")
        self.admin_user.save()
        self.client = Client()
        self.client.login(username="vasthi_admin", password="pass123")

        self.target_date = date(2026, 11, 10)

    def test_vasthi_identification(self):
        """Test is_vasthi_treatment detection and exception for Mathra Vasthi."""
        self.assertTrue(is_vasthi_treatment(self.th_kashaya.therapy_name, self.th_kashaya.therapy_code))
        self.assertTrue(is_vasthi_treatment("Kashayavasthi"))
        # Mathra Vasthi (THEB037) is exempt
        self.assertFalse(is_vasthi_treatment(self.th_mathra.therapy_name, self.th_mathra.therapy_code))
        # Normal therapy is not Vasthi
        self.assertFalse(is_vasthi_treatment(self.th_abhyanga.therapy_name, self.th_abhyanga.therapy_code))

    def test_dynamic_vasthi_toggle_on_therapy(self):
        """Toggling is_vasthi on any therapy makes it a Vasthi treatment."""
        self.th_abhyanga.is_vasthi = True
        self.th_abhyanga.save()
        self.assertTrue(is_vasthi_treatment(self.th_abhyanga.therapy_name, self.th_abhyanga.therapy_code))

        self.th_abhyanga.is_vasthi = False
        self.th_abhyanga.save()
        self.assertFalse(is_vasthi_treatment(self.th_abhyanga.therapy_name, self.th_abhyanga.therapy_code))

    def test_get_vasthi_slots(self):
        """Test that get_vasthi_slots returns configured active Vasthi slots."""
        slots = get_vasthi_slots()
        self.assertIn("08:30", slots)

    def test_cottage_patient_preferred_vasthi_room(self):
        """
        Rule: For patients admitted to a Cottage Room, the system should preferably
        allocate the Vasthi treatment to the Cottage Room (e.g., CT-1 -> TRC-1).
        """
        p1, _ = PatientSnapshot.objects.get_or_create(
            pat_reg_no="P_COT_1",
            defaults={"pat_name": "Cottage Patient 1", "pat_room_no": "CT-1"}
        )

        room = allocate_vasthi_treatment_room(
            self.target_date,
            self.slot_0830,
            therapy_name=self.th_kashaya.therapy_name,
            patient_staying_room="CT-1",
            patient=p1
        )
        self.assertIsNotNone(room)
        self.assertEqual(room.room_no, "TRC-1")

        # Test through main allocate_treatment_room functions
        res_room = reshedule_allocate_treatment_room(
            self.target_date,
            self.slot_0830,
            therapy_name=self.th_kashaya.therapy_name,
            patient_staying_room="CT-1",
            patient=p1
        )
        self.assertIsNotNone(res_room)
        self.assertEqual(res_room.room_no, "TRC-1")

        final_room = final_allocate_treatment_room(
            self.target_date,
            self.slot_0830,
            therapy_name=self.th_kashaya.therapy_name,
            patient_staying_room="CT-1",
            patient=p1
        )
        self.assertIsNotNone(final_room)
        self.assertEqual(final_room.room_no, "TRC-1")

    def test_multiple_patients_in_same_cottage_room(self):
        """
        Rule: If more than one patient is admitted in the Cottage Room, only one patient
        should be assigned to the Cottage Room for the treatment; the remaining patients
        should be assigned to other suitable treatment rooms.
        """
        p1, _ = PatientSnapshot.objects.get_or_create(
            pat_reg_no="P_COT_1",
            defaults={"pat_name": "Cottage Patient 1", "pat_room_no": "CT-1"}
        )
        p2, _ = PatientSnapshot.objects.get_or_create(
            pat_reg_no="P_COT_2",
            defaults={"pat_name": "Cottage Patient 2", "pat_room_no": "CT-1"}
        )

        # Allocate P1 -> Gets TRC-1
        room_p1 = allocate_vasthi_treatment_room(
            self.target_date,
            self.slot_0830,
            therapy_name=self.th_kashaya.therapy_name,
            patient_staying_room="CT-1",
            patient=p1
        )
        self.assertEqual(room_p1.room_no, "TRC-1")

        # Simulate TRC-1 being booked for P1
        RoomBooking.objects.create(
            room=room_p1,
            date=self.target_date,
            time_slot=self.slot_0830,
            status="BOOKED"
        )

        # Allocate P2 from same cottage CT-1:
        # Since TRC-1 is booked, P2 must be assigned to an alternative suitable room (e.g. TR-1)
        room_p2 = allocate_vasthi_treatment_room(
            self.target_date,
            self.slot_0830,
            therapy_name=self.th_kashaya.therapy_name,
            patient_staying_room="CT-1",
            patient=p2
        )
        self.assertIsNotNone(room_p2)
        self.assertNotEqual(room_p2.room_no, "TRC-1")
        self.assertTrue(room_p2.room_no.startswith("TR-"))

        # Verify through final_allocation.allocate_treatment_room as well
        room_p2_final = final_allocate_treatment_room(
            self.target_date,
            self.slot_0830,
            therapy_name=self.th_kashaya.therapy_name,
            patient_staying_room="CT-1",
            patient=p2
        )
        self.assertIsNotNone(room_p2_final)
        self.assertNotEqual(room_p2_final.room_no, "TRC-1")

    def test_non_cottage_patients_follow_normal_rules(self):
        """Non-cottage patients (e.g., DS-1) follow standard room mapping (TR-1/TR-2)."""
        p_ds, _ = PatientSnapshot.objects.get_or_create(
            pat_reg_no="P_DS_1",
            defaults={"pat_name": "DS Patient", "pat_room_no": "DS-1"}
        )
        room = allocate_vasthi_treatment_room(
            self.target_date,
            self.slot_0830,
            therapy_name=self.th_kashaya.therapy_name,
            patient_staying_room="DS-1",
            patient=p_ds
        )
        self.assertIsNotNone(room)
        self.assertIn(room.room_no, ["TR-1", "TR-2", "TR-3", "TR-4"])

    def test_non_vasthi_therapy_in_cottage_unaffected(self):
        """Normal non-vasthi therapy allocation in CT-1 still uses standard room logic."""
        p_cot, _ = PatientSnapshot.objects.get_or_create(
            pat_reg_no="P_COT_NORM",
            defaults={"pat_name": "Cottage Normal", "pat_room_no": "CT-1"}
        )
        room = reshedule_allocate_treatment_room(
            self.target_date,
            self.slot_1000,
            therapy_name=self.th_abhyanga.therapy_name,
            patient_staying_room="CT-1",
            patient=p_cot
        )
        self.assertEqual(room.room_no, "TRC-1")

    def test_toggle_vasthi_therapy_view(self):
        """Test therapy_master_toggle_vasthi endpoint toggles is_vasthi field."""
        url = reverse("therapy_master_toggle_vasthi", kwargs={"pk": self.th_abhyanga.pk})
        self.assertFalse(self.th_abhyanga.is_vasthi)

        # Toggle to True
        response = self.client.post(url, HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["is_vasthi"])
        self.th_abhyanga.refresh_from_db()
        self.assertTrue(self.th_abhyanga.is_vasthi)

        # Toggle back to False
        response = self.client.post(url, HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["is_vasthi"])
        self.th_abhyanga.refresh_from_db()
        self.assertFalse(self.th_abhyanga.is_vasthi)

    def test_toggle_vasthi_slot_view(self):
        """Test slot_master_toggle_vasthi endpoint toggles is_vasthi_slot field."""
        url = reverse("slot_master_toggle_vasthi", kwargs={"pk": self.slot_1000.pk})
        self.assertFalse(self.slot_1000.is_vasthi_slot)

        # Toggle to True
        response = self.client.post(url, HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["is_vasthi_slot"])
        self.slot_1000.refresh_from_db()
        self.assertTrue(self.slot_1000.is_vasthi_slot)

        # Toggle back to False
        response = self.client.post(url, HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["is_vasthi_slot"])
        self.slot_1000.refresh_from_db()
        self.assertFalse(self.slot_1000.is_vasthi_slot)

    def test_time_slots_api_includes_vasthi_slot(self):
        """Test time_slots API returns is_vasthi_slot attribute."""
        url = reverse("patient:time_slots")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("slots", data)
        slot_0830_item = next((s for s in data["slots"] if s["start_time"] == "08:30"), None)
        self.assertIsNotNone(slot_0830_item)
        self.assertTrue(slot_0830_item["is_vasthi_slot"])

    def test_get_vasthi_slot_names_and_dynamic_display(self):
        """Test get_vasthi_slot_names returns formatted dynamic names when multiple slots are turned on."""
        from reshedule import get_vasthi_slot_names

        # Initially only slot_0830 (08:30 AM) is on
        names = get_vasthi_slot_names()
        self.assertEqual(len(names), 1)
        self.assertIn("8:30 AM", names[0])

        # Turn on slot_1000 ("Slot 3", 10:00 AM)
        self.slot_1000.is_vasthi_slot = True
        self.slot_1000.slot_name = "Slot 3"
        self.slot_1000.save()

        names_multi = get_vasthi_slot_names()
        self.assertEqual(len(names_multi), 2)
        self.assertTrue(any("10:00 AM" in n for n in names_multi))

        # Check Therapy Master Form GET request displays the dynamic slot names
        url_create = reverse("therapy_master_add")
        res_create = self.client.get(url_create)
        self.assertEqual(res_create.status_code, 200)
        html_create = res_create.content.decode("utf-8")
        # Ensure static condition text is NOT present
        self.assertNotIn("For patients admitted in a Cottage Room, preferably allocates to their Cottage Room", html_create)
        # Ensure dynamic Vasthi slots are present
        self.assertIn("Vasthi Slots:", html_create)
        self.assertIn("10:00 AM", html_create)
        self.assertIn("8:30 AM", html_create)

        # Check Therapy Master Manage page GET request
        url_manage = reverse("therapy_master_manage")
        res_manage = self.client.get(url_manage)
        self.assertEqual(res_manage.status_code, 200)
        html_manage = res_manage.content.decode("utf-8")
        self.assertNotIn("8:30 AM slot; Cottage preferred room rule", html_manage)

    def test_therapy_entry_search_therapies_returns_is_vasthi(self):
        """Test search_therapies action returns is_vasthi flag accurately."""
        url = reverse("patient_therapy") + "?action=search_therapies&q=vasthi"
        res = self.client.get(url)
        self.assertEqual(res.status_code, 200)
        data = res.json()
        kashaya = next((t for t in data if t.get("therapy_code") == "THEB020"), None)
        self.assertIsNotNone(kashaya)
        self.assertTrue(kashaya.get("is_vasthi"))

        mathra = next((t for t in data if t.get("therapy_code") == "THEB037"), None)
        if mathra:
            self.assertFalse(mathra.get("is_vasthi"))

        url_all = reverse("patient_therapy") + "?action=search_therapies&q=abhyanga"
        res_all = self.client.get(url_all)
        self.assertEqual(res_all.status_code, 200)
        abhyanga = next((t for t in res_all.json() if t.get("therapy_code") == "THEB001"), None)
        self.assertIsNotNone(abhyanga)
        self.assertFalse(abhyanga.get("is_vasthi"))

    def test_therapy_entry_slots_vasthi_only_filter(self):
        """Test action=slots with filter_type=vasthi_only returns only Vasthi slots."""
        url_vasthi = reverse("patient_therapy") + "?action=slots&filter_type=vasthi_only"
        res_vasthi = self.client.get(url_vasthi)
        self.assertEqual(res_vasthi.status_code, 200)
        vasthi_slots = res_vasthi.json().get("slots", [])
        self.assertTrue(len(vasthi_slots) >= 1)
        # All returned slots must be vasthi slots
        for s in vasthi_slots:
            self.assertTrue(s.get("is_vasthi_slot"))
            self.assertFalse(s.get("is_vamanam_slot"))
        self.assertTrue(any(s.get("start_time") == "08:30" for s in vasthi_slots))

        # Check regular_only excludes vamanam but includes vasthi & normal slots
        url_reg = reverse("patient_therapy") + "?action=slots&filter_type=regular_only"
        res_reg = self.client.get(url_reg)
        self.assertEqual(res_reg.status_code, 200)
        reg_slots = res_reg.json().get("slots", [])
        for s in reg_slots:
            self.assertFalse(s.get("is_vamanam_slot"))
        self.assertTrue(any(s.get("start_time") == "08:30" for s in reg_slots))
        self.assertTrue(any(s.get("start_time") == "10:00" for s in reg_slots))

