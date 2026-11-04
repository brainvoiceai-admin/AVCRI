import datetime
import pytest
from django.test import TestCase, Client
from django.contrib.auth import get_user_model
from django.urls import reverse

from Patient.models import TreatmentRoom, RoomBooking, RoomName
from Sheduling.models import TherapyAllocation, Booking, PatientSnapshot, SlotMaster
from reshedule import (
    allocate_treatment_room as reshedule_allocate_treatment_room,
    get_wheelchair_accessible_rooms
)
from final_allocation import (
    allocate_treatment_room as final_allocate_treatment_room
)

User = get_user_model()


class WheelchairRoomAllocationTests(TestCase):
    def setUp(self):
        self.today = datetime.date.today()
        self.slot_time = datetime.time(8, 0)
        self.slot = SlotMaster.objects.create(
            slot_number=1,
            slot_name="08:00 AM",
            slot_time=self.slot_time,
            is_active=True
        )

        # Create two treatment rooms: one standard, one wheelchair accessible
        rn1, _ = RoomName.objects.get_or_create(name="Room TR-1", defaults={"is_active": True})
        self.standard_room = TreatmentRoom.objects.create(
            room_no="TR-1",
            room_name=rn1,
            floor="G",
            is_active=True,
            is_wheelchair_accessible=False
        )
        rn2, _ = RoomName.objects.get_or_create(name="Room TR-2", defaults={"is_active": True})
        self.accessible_room = TreatmentRoom.objects.create(
            room_no="TR-2",
            room_name=rn2,
            floor="G",
            is_active=True,
            is_wheelchair_accessible=True
        )

        # Create patient snapshots
        self.regular_patient = PatientSnapshot.objects.create(
            pat_reg_no="REG-1001",
            pat_name="Regular Patient",
            pat_room_no="DS-1",
            is_wheelchair=False
        )
        self.wheelchair_patient = PatientSnapshot.objects.create(
            pat_reg_no="REG-1002",
            pat_name="Wheelchair Patient",
            pat_room_no="DS-1",
            is_wheelchair=True
        )

    def test_wheelchair_room_master_toggle(self):
        """Test toggling wheelchair accessibility via Room Master view."""
        user = User.objects.create_superuser(username="admin", password="password123")
        user.role = 'super_admin'
        user.save()
        client = Client()
        client.force_login(user)

        self.assertFalse(self.standard_room.is_wheelchair_accessible)
        url = reverse("treatment_room_master_toggle_wheelchair", kwargs={"pk": self.standard_room.pk})
        
        response = client.post(url, HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data.get("is_wheelchair_accessible"))

        self.standard_room.refresh_from_db()
        self.assertTrue(self.standard_room.is_wheelchair_accessible)

        # Toggle back
        response = client.post(url, HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        self.assertEqual(response.status_code, 200)
        self.standard_room.refresh_from_db()
        self.assertFalse(self.standard_room.is_wheelchair_accessible)

    def test_get_wheelchair_accessible_rooms(self):
        """Test helper retrieves only active wheelchair accessible rooms."""
        rooms = get_wheelchair_accessible_rooms()
        self.assertIn("TR-2", rooms)
        self.assertNotIn("TR-1", rooms)

        # Inactive accessible room shouldn't be included
        rn3, _ = RoomName.objects.get_or_create(name="Room TR-3", defaults={"is_active": True})
        inactive_room = TreatmentRoom.objects.create(
            room_no="TR-3",
            room_name=rn3,
            floor="G",
            is_active=False,
            is_wheelchair_accessible=True
        )
        rooms_after = get_wheelchair_accessible_rooms()
        self.assertNotIn("TR-3", rooms_after)

    def test_reshedule_allocate_treatment_room_respects_wheelchair(self):
        """Wheelchair patients must not be allocated non-wheelchair rooms."""
        # When is_wheelchair=True, standard_room must NOT be allocated
        room = reshedule_allocate_treatment_room(
            date=self.today,
            time_slot=self.slot,
            therapy_name="Abhyangam",
            patient=self.wheelchair_patient,
            is_wheelchair=True
        )
        self.assertIsNotNone(room)
        self.assertEqual(room.room_no, "TR-2")
        self.assertTrue(room.is_wheelchair_accessible)

        # When accessible room is booked, wheelchair patient must NOT get standard_room
        RoomBooking.objects.create(
            room=self.accessible_room,
            date=self.today,
            time_slot=self.slot,
            status='BOOKED'
        )
        room_unavailable = reshedule_allocate_treatment_room(
            date=self.today,
            time_slot=self.slot,
            therapy_name="Abhyangam",
            patient=self.wheelchair_patient,
            is_wheelchair=True
        )
        self.assertIsNone(room_unavailable)

    def test_final_allocate_treatment_room_respects_wheelchair(self):
        """final_allocation must also strictly allocate only accessible rooms to wheelchair patients."""
        room = final_allocate_treatment_room(
            date=self.today,
            time_slot=self.slot,
            therapy_name="Abhyangam",
            patient=self.wheelchair_patient,
            is_wheelchair=True
        )
        self.assertIsNotNone(room)
        self.assertEqual(room.room_no, "TR-2")
        self.assertTrue(room.is_wheelchair_accessible)

        # When accessible room is booked, wheelchair patient gets None
        RoomBooking.objects.create(
            room=self.accessible_room,
            date=self.today,
            time_slot=self.slot,
            status='BOOKED'
        )
        room_unavailable = final_allocate_treatment_room(
            date=self.today,
            time_slot=self.slot,
            therapy_name="Abhyangam",
            patient=self.wheelchair_patient,
            is_wheelchair=True
        )
        self.assertIsNone(room_unavailable)

    def test_regular_patient_can_get_any_room(self):
        """Regular non-wheelchair patient can be allocated standard room."""
        room = reshedule_allocate_treatment_room(
            date=self.today,
            time_slot=self.slot,
            therapy_name="Abhyangam",
            patient=self.regular_patient,
            is_wheelchair=False
        )
        self.assertIsNotNone(room)

    def test_therapy_allocation_and_booking_save_wheelchair_flag(self):
        """Test is_wheelchair is stored correctly on TherapyAllocation and Booking."""
        alloc = TherapyAllocation.objects.create(
            patient=self.wheelchair_patient,
            therapy_code="THEB001",
            therapy_name="Abhyangam",
            timeslot=self.slot,
            from_date=self.today,
            to_date=self.today,
            days=1,
            is_wheelchair=True,
            status='draft'
        )
        booking = Booking.objects.create(
            allocation=alloc,
            date=self.today,
            timeslot=self.slot,
            is_wheelchair=True,
            status='draft'
        )

        alloc.refresh_from_db()
        booking.refresh_from_db()
        self.assertTrue(alloc.is_wheelchair)
        self.assertTrue(booking.is_wheelchair)
