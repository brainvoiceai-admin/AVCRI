import pytest
import json
from datetime import date, time
from django.test import RequestFactory
from django.contrib.auth import get_user_model

from Sheduling.availability_views import (
    get_available_rooms_api,
    get_occupied_rooms_api,
    get_time_slots_api,
    _resolve_slot_master,
    _get_unified_occupied_rooms,
)
from Patient.models import TreatmentRoom, RoomBooking
from Sheduling.models import Booking, TherapyAllocation, PatientSnapshot
from masters.models import SlotMaster

User = get_user_model()


@pytest.fixture
def auth_user(db):
    user, _ = User.objects.get_or_create(username='test_admin', defaults={'is_staff': True})
    return user


@pytest.fixture
def test_setup(db):
    # Ensure slot
    slot1, _ = SlotMaster.objects.get_or_create(
        slot_number=101,
        defaults={'slot_time': time(6, 30), 'slot_name': 'Slot 101', 'is_active': True}
    )
    slot2, _ = SlotMaster.objects.get_or_create(
        slot_number=102,
        defaults={'slot_time': time(8, 30), 'slot_name': 'Slot 102', 'is_active': True}
    )

    # Ensure rooms
    room1, _ = TreatmentRoom.objects.get_or_create(
        room_no='TEST-TR-1',
        defaults={'floor': '1', 'tr_code': '9001', 'is_active': True}
    )
    room2, _ = TreatmentRoom.objects.get_or_create(
        room_no='TEST-TR-2',
        defaults={'floor': '1', 'tr_code': '9002', 'is_active': True}
    )
    room3, _ = TreatmentRoom.objects.get_or_create(
        room_no='TEST-TR-3',
        defaults={'floor': '2', 'tr_code': '9003', 'is_active': True}
    )

    # Patient
    patient, _ = PatientSnapshot.objects.get_or_create(
        pat_reg_no='PAT999',
        defaults={'pat_name': 'Test Patient', 'pat_age': 40, 'pat_sex': 'M'}
    )

    return {
        'slot1': slot1,
        'slot2': slot2,
        'room1': room1,
        'room2': room2,
        'room3': room3,
        'patient': patient,
        'target_date': date(2099, 1, 1),
    }


@pytest.mark.django_db
class TestRoomAvailabilityDashboard:

    def test_resolve_slot_master(self, test_setup):
        slot1 = test_setup['slot1']

        # By time format %H:%M
        sm, err = _resolve_slot_master('06:30')
        assert err is None
        assert sm.slot_time == time(6, 30)

        # By slot ID
        sm, err = _resolve_slot_master(str(slot1.pk))
        assert err is None
        assert sm.pk == slot1.pk

        # By slot number
        sm, err = _resolve_slot_master('101')
        assert err is None
        assert sm.slot_number == 101

        # All / None
        sm, err = _resolve_slot_master('all')
        assert err is None
        assert sm is None

        # Invalid
        sm, err = _resolve_slot_master('non_existent_slot')
        assert sm is None
        assert "not found" in err

    def test_get_time_slots_api(self, auth_user, test_setup):
        rf = RequestFactory()
        req = rf.get('/sheduling/room-availability/api/time-slots/')
        req.user = auth_user
        resp = get_time_slots_api(req)
        assert resp.status_code == 200
        data = json.loads(resp.content)
        assert data['success'] is True
        assert len(data['time_slots']) >= 2
        # Check slot formatting
        first_slot = next(s for s in data['time_slots'] if s['id'] == test_setup['slot1'].pk)
        assert first_slot['start_time'] == '06:30'
        assert 'Slot 101' in first_slot['display_name']

    def test_availability_and_occupancy_basic(self, auth_user, test_setup):
        rf = RequestFactory()
        target_date_str = test_setup['target_date'].strftime('%Y-%m-%d')

        # Check available rooms with no bookings
        req = rf.get(f'/sheduling/room-availability/api/available-rooms/?date={target_date_str}&time=06:30&floor=1')
        req.user = auth_user
        resp = get_available_rooms_api(req)
        assert resp.status_code == 200
        data = json.loads(resp.content)
        room_nos = [r['room_no'] for r in data['rooms']]
        assert 'TEST-TR-1' in room_nos
        assert 'TEST-TR-2' in room_nos
        assert 'TEST-TR-3' not in room_nos  # Floor 2 excluded

        # Check occupied rooms (should be 0)
        req = rf.get(f'/sheduling/room-availability/api/occupied-rooms/?date={target_date_str}&time=06:30&floor=1')
        req.user = auth_user
        resp = get_occupied_rooms_api(req)
        assert resp.status_code == 200
        data = json.loads(resp.content)
        assert data['total_count'] == 0

    def test_booked_room_reflects_in_occupied_and_excluded_from_available(self, auth_user, test_setup):
        rf = RequestFactory()
        target_date = test_setup['target_date']
        target_date_str = target_date.strftime('%Y-%m-%d')
        room1 = test_setup['room1']
        slot1 = test_setup['slot1']
        patient = test_setup['patient']

        # Create allocation and booking
        alloc = TherapyAllocation.objects.create(
            patient=patient,
            therapy_name='Abhyangam Test',
            from_date=target_date,
            to_date=target_date,
            days=1,
            status='allocated'
        )
        booking = Booking.objects.create(
            allocation=alloc,
            date=target_date,
            timeslot=slot1,
            room=room1,
            status='scheduled',
            snapshot_therapy_name='Abhyangam Test'
        )
        RoomBooking.objects.create(
            room=room1,
            date=target_date,
            time_slot=slot1,
            therapy_name='Abhyangam Test',
            patient_id=patient.id,
            status='BOOKED',
            visit=booking,
            therapy=alloc
        )

        # 1. Available rooms must exclude TEST-TR-1
        req = rf.get(f'/sheduling/room-availability/api/available-rooms/?date={target_date_str}&time=06:30&floor=all')
        req.user = auth_user
        resp = get_available_rooms_api(req)
        data = json.loads(resp.content)
        available_nos = [r['room_no'] for r in data['rooms']]
        assert 'TEST-TR-1' not in available_nos
        assert 'TEST-TR-2' in available_nos

        # 2. Occupied rooms must contain TEST-TR-1 with patient and therapy details
        req = rf.get(f'/sheduling/room-availability/api/occupied-rooms/?date={target_date_str}&time=06:30&floor=all')
        req.user = auth_user
        resp = get_occupied_rooms_api(req)
        data = json.loads(resp.content)
        occ = next(r for r in data['occupied_rooms'] if r['room_no'] == 'TEST-TR-1')
        assert occ['therapy_name'] == 'Abhyangam Test'
        assert occ['patient_name'] == 'Test Patient'
        assert occ['patient_reg_no'] == 'PAT999'

    def test_cancelled_allocation_frees_room(self, auth_user, test_setup):
        """
        When allocation or booking is cancelled, room must be AVAILABLE and NOT OCCUPIED,
        even if RoomBooking table still has status='BOOKED'.
        """
        rf = RequestFactory()
        target_date = test_setup['target_date']
        target_date_str = target_date.strftime('%Y-%m-%d')
        room1 = test_setup['room1']
        slot1 = test_setup['slot1']
        patient = test_setup['patient']

        alloc = TherapyAllocation.objects.create(
            patient=patient,
            therapy_name='Cancelled Therapy',
            from_date=target_date,
            to_date=target_date,
            days=1,
            status='cancelled'  # CANCELLED!
        )
        booking = Booking.objects.create(
            allocation=alloc,
            date=target_date,
            timeslot=slot1,
            room=room1,
            status='cancelled',  # CANCELLED!
            snapshot_therapy_name='Cancelled Therapy'
        )
        # RoomBooking row erroneously remains with status='BOOKED'
        RoomBooking.objects.create(
            room=room1,
            date=target_date,
            time_slot=slot1,
            therapy_name='Cancelled Therapy',
            patient_id=patient.id,
            status='BOOKED',
            visit=booking,
            therapy=alloc
        )

        # Room must be AVAILABLE
        req = rf.get(f'/sheduling/room-availability/api/available-rooms/?date={target_date_str}&time=06:30&floor=all')
        req.user = auth_user
        resp = get_available_rooms_api(req)
        data = json.loads(resp.content)
        available_nos = [r['room_no'] for r in data['rooms']]
        assert 'TEST-TR-1' in available_nos

        # Room must NOT be in occupied rooms
        req = rf.get(f'/sheduling/room-availability/api/occupied-rooms/?date={target_date_str}&time=06:30&floor=all')
        req.user = auth_user
        resp = get_occupied_rooms_api(req)
        data = json.loads(resp.content)
        occupied_nos = [r['room_no'] for r in data['occupied_rooms']]
        assert 'TEST-TR-1' not in occupied_nos

    def test_booking_without_roombooking_table_row_is_occupied(self, auth_user, test_setup):
        """
        When a booking is scheduled in Sheduling.Booking with room assigned, but no
        Patient.RoomBooking row exists, it must still be recognized as OCCUPIED.
        """
        rf = RequestFactory()
        target_date = test_setup['target_date']
        target_date_str = target_date.strftime('%Y-%m-%d')
        room2 = test_setup['room2']
        slot2 = test_setup['slot2']
        patient = test_setup['patient']

        alloc = TherapyAllocation.objects.create(
            patient=patient,
            therapy_name='Kizhi Therapy',
            from_date=target_date,
            to_date=target_date,
            days=1,
            status='allocated'
        )
        Booking.objects.create(
            allocation=alloc,
            date=target_date,
            timeslot=slot2,
            room=room2,
            status='scheduled',
            snapshot_therapy_name='Kizhi Therapy'
        )
        # Notice: NO RoomBooking row created

        # Room TEST-TR-2 must be occupied at slot 2
        req = rf.get(f'/sheduling/room-availability/api/occupied-rooms/?date={target_date_str}&time=08:30&floor=all')
        req.user = auth_user
        resp = get_occupied_rooms_api(req)
        data = json.loads(resp.content)
        occupied_nos = [r['room_no'] for r in data['occupied_rooms']]
        assert 'TEST-TR-2' in occupied_nos

        # Room TEST-TR-2 must NOT be in available rooms for slot 2
        req = rf.get(f'/sheduling/room-availability/api/available-rooms/?date={target_date_str}&time=08:30&floor=all')
        req.user = auth_user
        resp = get_available_rooms_api(req)
        data = json.loads(resp.content)
        available_nos = [r['room_no'] for r in data['rooms']]
        assert 'TEST-TR-2' not in available_nos
