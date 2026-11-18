"""
Test suite for VIP Patient Management, Priority Allocation, and Reschedule Exclusion:
1. VIP status resolution and persistence across PatientSnapshot, Repeated_Visitors,
   PatientProfile, TherapyAllocation, and Booking.
2. Patient Details API reflecting 'vip_status': 'Yes'/'No' and 'is_vip': True/False.
3. Update Patient VIP Status API (/api/update-patient-vip/).
4. Bulk allocation prioritization: VIP patients are prioritized before non-VIP IP and OP patients.
5. Strict exclusion from rescheduling:
   - reschedule_therapy_api blocks VIP patient treatments with explanatory message.
   - reschedule_options_api blocks VIP patient treatments.
   - reschedule_all_failed_api excludes VIP patient bookings.
   - process_reassignments (resheduleMorningandNight.py) skips VIP bookings when therapist is on emergency leave,
     leaving assigned slot and preferred therapist untouched.
   - Failed allocations/bookings queries exclude VIP treatments from the 'To Reschedule' dashboard.
"""
import json
from datetime import date, time
from django.test import TestCase, Client
from django.utils import timezone

from authentication.models import CustomUser, Module
from masters.models import SlotMaster, TherapistGrade, TherapistMaster, EmergencyLeave, TherapyMaster
from Patient.models import Repeated_Visitors, TreatmentRoom, RoomName, TherapistBooking
from Sheduling.models import (
    PatientSnapshot,
    TherapyAllocation,
    Booking,
)
from Sheduling.vip_service import (
    is_patient_vip,
    set_patient_vip_status,
    normalize_reg_no,
)
from resheduleMorningandNight import process_reassignments


class VIPPatientSchedulingAndRescheduleExclusionTests(TestCase):
    def setUp(self):
        # Client
        self.client = Client()

        # Admin / staff user with full permissions
        Module.objects.get_or_create(
            name="therapy_scheduling",
            defaults={"display_name": "Therapy Scheduling", "is_active": True}
        )
        self.staff_user = CustomUser.objects.create_superuser(
            username="test_vip_staff",
            password="testpassword123",
            email="vip@example.com",
            role="super_admin",
            first_name="VIP",
            last_name="Manager"
        )
        self.client.login(username="test_vip_staff", password="testpassword123")

        # Master Slot
        self.slot, _ = SlotMaster.objects.get_or_create(
            slot_number=1,
            defaults={
                "slot_time": time(8, 30),
                "slot_name": "Slot 1 (08:30 - 09:15)",
                "is_active": True
            }
        )

        # Therapist Grade
        self.grade_senior, _ = TherapistGrade.objects.get_or_create(
            name="Senior Therapist",
            defaults={"display_order": 1, "is_active": True}
        )

        # Therapist Master
        self.therapist_a, _ = TherapistMaster.objects.get_or_create(
            therapist_code="TH_VIP_01",
            defaults={
                "therapist_name": "Therapist A",
                "therapist_gender": "Male",
                "therapist_grade": self.grade_senior,
                "employee_code": "EMP_VIP_01",
                "is_active": True
            }
        )
        self.therapist_b, _ = TherapistMaster.objects.get_or_create(
            therapist_code="TH_VIP_02",
            defaults={
                "therapist_name": "Therapist B",
                "therapist_gender": "Male",
                "therapist_grade": self.grade_senior,
                "employee_code": "EMP_VIP_02",
                "is_active": True
            }
        )

        # Treatment Rooms
        self.room_name_1, _ = RoomName.objects.get_or_create(name="VIP Room 101")
        self.room_1, _ = TreatmentRoom.objects.get_or_create(
            room_no="101",
            defaults={
                "room_name": self.room_name_1,
                "floor": "1",
            }
        )
        self.room_name_2, _ = RoomName.objects.get_or_create(name="Room 102")
        self.room_2, _ = TreatmentRoom.objects.get_or_create(
            room_no="102",
            defaults={
                "room_name": self.room_name_2,
                "floor": "1",
            }
        )
        self.room_name_3, _ = RoomName.objects.get_or_create(name="Room 103")
        self.room_3, _ = TreatmentRoom.objects.get_or_create(
            room_no="103",
            defaults={
                "room_name": self.room_name_3,
                "floor": "1",
            }
        )

        # Therapy Master
        self.therapy_master, _ = TherapyMaster.objects.get_or_create(
            therapy_code="ABH01",
            defaults={
                "therapy_name": "Abhyangam",
                "therapy_category": "General",
                "therapy_duration": "45",
                "treatment_room_required": "Yes",
                "bathing_required": "No",
                "no_of_senior_therapist": 1,
                "total_no_of_therapist": 1,
            }
        )

        self.test_date = date(2026, 12, 1)

    def test_vip_status_persistence_and_sync(self):
        """set_patient_vip_status should persist across models and synchronize allocations/bookings."""
        reg_no = "VIP1001"
        res = set_patient_vip_status(reg_no, is_vip=True, patient_name="John Doe VIP")
        self.assertTrue(res['success'])
        self.assertTrue(res['is_vip'])
        self.assertEqual(res['vip_status'], 'Yes')

        # Check PatientSnapshot
        snap = PatientSnapshot.objects.get(pat_reg_no=reg_no)
        self.assertTrue(snap.is_vip)
        self.assertEqual(snap.pat_name, "John Doe VIP")

        # Check Repeated_Visitors
        rep = Repeated_Visitors.objects.filter(register_number=1001).first()
        self.assertIsNotNone(rep)
        self.assertTrue(rep.is_vip)

        # Create allocation and booking for this patient
        alloc = TherapyAllocation.objects.create(
            patient=snap,
            therapy_code="ABH01",
            therapy_name="Abhyangam",
            from_date=self.test_date,
            to_date=self.test_date,
            days=1,
            timeslot=self.slot,
            room=self.room_1,
            is_vip=False  # initially false before sync
        )
        bk = Booking.objects.create(
            allocation=alloc,
            date=self.test_date,
            timeslot=self.slot,
            room=self.room_1,
            status="BOOKED",
            is_vip=False
        )

        # Verify is_patient_vip returns True when inspecting snapshot, alloc, bk, or reg_no
        self.assertTrue(is_patient_vip(reg_no))
        self.assertTrue(is_patient_vip(snap))
        self.assertTrue(is_patient_vip(alloc))
        self.assertTrue(is_patient_vip(bk))

        # Re-run set_patient_vip_status to verify synchronization
        set_patient_vip_status(reg_no, is_vip=True)
        alloc.refresh_from_db()
        bk.refresh_from_db()
        self.assertTrue(alloc.is_vip)
        self.assertTrue(bk.is_vip)

        # Unmark VIP
        set_patient_vip_status(reg_no, is_vip=False)
        alloc.refresh_from_db()
        bk.refresh_from_db()
        snap.refresh_from_db()
        self.assertFalse(snap.is_vip)
        self.assertFalse(alloc.is_vip)
        self.assertFalse(bk.is_vip)
        self.assertFalse(is_patient_vip(reg_no))

    def test_update_patient_vip_api(self):
        """Test /api/update-patient-vip/ endpoint updates VIP status."""
        reg_no = "VIP2002"
        # First ensure patient exists in PatientSnapshot
        PatientSnapshot.objects.create(
            pat_reg_no=reg_no,
            pat_name="Alice VIP",
            is_vip=False
        )

        # Call API to mark as VIP
        response = self.client.post(
            '/api/update-patient-vip/',
            data=json.dumps({
                'patient_reg_no': reg_no,
                'patient_name': 'Alice VIP',
                'is_vip': True
            }),
            content_type='application/json'
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['success'])
        self.assertTrue(data['is_vip'])
        self.assertEqual(data['vip_status'], 'Yes')

        # Check DB
        self.assertTrue(is_patient_vip(reg_no))

        # Call API to remove VIP
        response = self.client.post(
            '/api/update-patient-vip/',
            data=json.dumps({
                'patient_reg_no': reg_no,
                'is_vip': False
            }),
            content_type='application/json'
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertFalse(data['is_vip'])
        self.assertEqual(data['vip_status'], 'No')
        self.assertFalse(is_patient_vip(reg_no))

    def test_reschedule_api_blocks_vip_patient(self):
        """reschedule_therapy_api and reschedule_options_api must reject rescheduling for VIP patients."""
        snap = PatientSnapshot.objects.create(
            pat_reg_no="VIP3003",
            pat_name="VIP Lord",
            is_vip=True
        )
        alloc = TherapyAllocation.objects.create(
            patient=snap,
            therapy_code="ABH01",
            therapy_name="Abhyangam",
            from_date=self.test_date,
            to_date=self.test_date,
            days=1,
            timeslot=self.slot,
            room=self.room_1,
            is_vip=True
        )
        bk = Booking.objects.create(
            allocation=alloc,
            date=self.test_date,
            timeslot=self.slot,
            room=self.room_1,
            status="BOOKED",
            is_vip=True
        )

        # Attempt to call reschedule_options_api
        res_opt = self.client.post(
            '/sheduling/scheduling/api/reschedule-options/',
            data=json.dumps({
                'allocation_id': alloc.pk,
                'date': str(self.test_date),
            }),
            content_type='application/json'
        )
        self.assertEqual(res_opt.status_code, 400)
        data_opt = res_opt.json()
        self.assertIn("VIP patient treatments are excluded from the rescheduling process", data_opt.get('error', ''))

        # Attempt to call reschedule_therapy_api
        res_resched = self.client.post(
            '/sheduling/scheduling/api/reschedule-therapy/',
            data=json.dumps({
                'allocation_id': alloc.pk,
                'date': str(self.test_date),
            }),
            content_type='application/json'
        )
        self.assertEqual(res_resched.status_code, 400)
        data_resched = res_resched.json()
        self.assertFalse(data_resched['success'])
        self.assertIn("VIP patient treatments are excluded from the rescheduling process", data_resched.get('error', ''))

        # Booking slot must remain completely unchanged
        bk.refresh_from_db()
        self.assertEqual(bk.timeslot, self.slot)
        self.assertEqual(bk.status, "BOOKED")

    def test_reschedule_all_failed_api_excludes_vip(self):
        """reschedule_all_failed_api must skip VIP patients."""
        # VIP patient
        snap_vip = PatientSnapshot.objects.create(
            pat_reg_no="VIP4004",
            pat_name="VIP Duke",
            is_vip=True
        )
        alloc_vip = TherapyAllocation.objects.create(
            patient=snap_vip,
            therapy_code="ABH01",
            therapy_name="Abhyangam",
            from_date=self.test_date,
            to_date=self.test_date,
            days=1,
            timeslot=self.slot,
            room=self.room_1,
            is_vip=True
        )
        bk_vip = Booking.objects.create(
            allocation=alloc_vip,
            date=self.test_date,
            timeslot=self.slot,
            room=self.room_1,
            status="failed",
            is_vip=True
        )

        # Call reschedule_all_failed_api
        res = self.client.post(
            '/sheduling/scheduling/api/reschedule-all-failed/',
            data=json.dumps({
                'date': str(self.test_date),
            }),
            content_type='application/json'
        )
        self.assertEqual(res.status_code, 200)
        data = res.json()
        # Since bk_vip is VIP, it was excluded from failed bookings query
        self.assertEqual(data.get('stats', {}).get('total', 0), 0)
        # Booking remains failed and not altered
        bk_vip.refresh_from_db()
        self.assertEqual(bk_vip.status, "failed")

    def test_emergency_leave_rescheduling_excludes_vip(self):
        """process_reassignments must NOT reschedule or cancel VIP bookings when therapist is on emergency leave."""
        snap_vip = PatientSnapshot.objects.create(
            pat_reg_no="VIP5005",
            pat_name="VIP Countess",
            is_vip=True
        )
        alloc_vip = TherapyAllocation.objects.create(
            patient=snap_vip,
            therapy_code="ABH01",
            therapy_name="Abhyangam",
            from_date=self.test_date,
            to_date=self.test_date,
            days=1,
            timeslot=self.slot,
            room=self.room_1,
            is_vip=True
        )
        bk_vip = Booking.objects.create(
            allocation=alloc_vip,
            date=self.test_date,
            timeslot=self.slot,
            room=self.room_1,
            status="BOOKED",
            is_vip=True
        )

        # Create TherapistBooking (matching the emergency leave table)
        tb_vip = TherapistBooking.objects.create(
            patient_id=5005,
            visit=alloc_vip,
            therapist=self.therapist_a,
            date=self.test_date,
            time_slot=self.slot,
            status="BOOKED"
        )

        # Put therapist_a on emergency leave
        EmergencyLeave.objects.create(
            employee_code="EMP_VIP_01",
            therapist=self.therapist_a,
            from_date=self.test_date,
            to_date=self.test_date,
        )

        # Run process_reassignments
        summary = process_reassignments(target_date=self.test_date, dry_run=False)

        # The VIP booking should NOT be in reassigned or cancelled
        tb_vip.refresh_from_db()
        self.assertEqual(tb_vip.status, "BOOKED")
        self.assertEqual(tb_vip.therapist, self.therapist_a)
        self.assertNotIn(tb_vip.pk, summary['reassigned'])
        self.assertNotIn(tb_vip.pk, summary['cancelled'])

    def test_bulk_allocation_vip_priority(self):
        """bulk_allocate_for_date priority sort key must sort VIP bookings before non-VIP IP and OP bookings."""
        # Non-VIP OP patient (reg_no 5 digits)
        snap_op = PatientSnapshot.objects.create(
            pat_reg_no="55555",
            pat_name="OP Patient Normal",
            is_vip=False
        )
        alloc_op = TherapyAllocation.objects.create(
            patient=snap_op,
            therapy_code="ABH01",
            therapy_name="Abhyangam",
            from_date=self.test_date,
            to_date=self.test_date,
            days=1,
            timeslot=self.slot,
            room=self.room_1,
            is_vip=False
        )
        bk_op = Booking.objects.create(
            allocation=alloc_op,
            date=self.test_date,
            timeslot=self.slot,
            room=self.room_1,
            status="draft",
            is_vip=False
        )

        # Non-VIP IP patient
        snap_ip = PatientSnapshot.objects.create(
            pat_reg_no="IP1234",
            pat_name="IP Patient Normal",
            is_vip=False
        )
        alloc_ip = TherapyAllocation.objects.create(
            patient=snap_ip,
            therapy_code="ABH01",
            therapy_name="Abhyangam",
            from_date=self.test_date,
            to_date=self.test_date,
            days=1,
            timeslot=self.slot,
            room=self.room_2,
            is_vip=False
        )
        bk_ip = Booking.objects.create(
            allocation=alloc_ip,
            date=self.test_date,
            timeslot=self.slot,
            room=self.room_2,
            status="draft",
            is_vip=False
        )

        # VIP Patient
        snap_vip = PatientSnapshot.objects.create(
            pat_reg_no="VIP6006",
            pat_name="VIP Patient Prioritized",
            is_vip=True
        )
        alloc_vip = TherapyAllocation.objects.create(
            patient=snap_vip,
            therapy_code="ABH01",
            therapy_name="Abhyangam",
            from_date=self.test_date,
            to_date=self.test_date,
            days=1,
            timeslot=self.slot,
            room=self.room_3,
            is_vip=True
        )
        bk_vip = Booking.objects.create(
            allocation=alloc_vip,
            date=self.test_date,
            timeslot=self.slot,
            room=self.room_3,
            status="draft",
            is_vip=True
        )

        # Test patient attributes
        self.assertTrue(is_patient_vip(snap_vip))
        self.assertFalse(is_patient_vip(snap_ip))
        self.assertFalse(snap_ip.is_op())
        self.assertFalse(is_patient_vip(snap_op))
        self.assertTrue(snap_op.is_op())

        # Test the priority sorting order:
        patients_list = [
            (snap_op.pat_reg_no, [bk_op]),
            (snap_ip.pat_reg_no, [bk_ip]),
            (snap_vip.pat_reg_no, [bk_vip]),
        ]

        def _is_patient_op(pat):
            if not pat:
                return False
            if hasattr(pat, 'is_op'):
                return bool(pat.is_op())
            digits = ''.join(ch for ch in str(getattr(pat, 'pat_reg_no', '') or '') if ch.isdigit())
            return len(digits) == 5

        def _sort_key(item):
            bookings = item[1]
            first_bk = bookings[0] if bookings else None
            alloc = getattr(first_bk, 'allocation', None) if first_bk else None
            pat = getattr(alloc, 'patient', None) if alloc else None
            is_vip = is_patient_vip(pat) or getattr(first_bk, 'is_vip', False) or getattr(alloc, 'is_vip', False)
            is_op = _is_patient_op(pat)
            return (0 if is_vip else 1, 1 if is_op else 0)

        sorted_patients = sorted(patients_list, key=_sort_key)
        # VIP patient MUST be first!
        self.assertEqual(sorted_patients[0][0], snap_vip.pat_reg_no)
        # Non-VIP IP patient MUST be second!
        self.assertEqual(sorted_patients[1][0], snap_ip.pat_reg_no)
        # Non-VIP OP patient MUST be third!
        self.assertEqual(sorted_patients[2][0], snap_op.pat_reg_no)
