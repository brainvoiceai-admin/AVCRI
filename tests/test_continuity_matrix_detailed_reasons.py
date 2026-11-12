import json
import pytest
from datetime import date, timedelta
from django.test import TestCase, RequestFactory

from Sheduling.matrix_views import continuity_matrix_api, ALL_SUB_REASONS, STATUS_LABELS, CORE_MEANINGS
from Sheduling.models import (
    PatientSnapshot, TherapyAllocation, Booking, BookingAssignment,
    DoctorPatientPreferenceAllowance, PatientPreferredTherapistRoster,
    TherapistPreferenceRequest
)
from masters.models import (
    SlotMaster, TherapistGrade, TherapistMaster, TherapyMaster,
    TherapistLeaveMaster, EmergencyLeave, TherapistDeputation,
    TherapistTreatmentOmission, TherapistOnCallLog
)
from Patient.models import TherapistBooking, Repeated_Visitors, Therapist
from authentication.models import PatientProfile


class ContinuityMatrixDetailedReasonsTest(TestCase):
    def setUp(self):
        self.rf = RequestFactory()
        self.grade = TherapistGrade.objects.create(name="Senior Therapist", display_order=1)
        
        # Patient.Therapist records (required for foreign key on BookingAssignment)
        Therapist.objects.create(therapist_code="TH_GREEN", therapist_name="Green Therapist")
        Therapist.objects.create(therapist_code="TH_PURPLE", therapist_name="Purple Therapist")
        Therapist.objects.create(therapist_code="TH_RED", therapist_name="Red Therapist")
        Therapist.objects.create(therapist_code="TH_GRAY", therapist_name="Gray Therapist")
        Therapist.objects.create(therapist_code="TH_BLUE", therapist_name="Blue Therapist")

        # masters.TherapistMaster
        self.t_green = TherapistMaster.objects.create(
            therapist_code="TH_GREEN", therapist_name="Green Therapist",
            therapist_gender="Male", therapist_grade=self.grade, employee_code="EMP001",
            is_bathing_therapist=False, is_active=True
        )
        self.t_purple = TherapistMaster.objects.create(
            therapist_code="TH_PURPLE", therapist_name="Purple Therapist",
            therapist_gender="Male", therapist_grade=self.grade, employee_code="EMP002",
            is_bathing_therapist=False, is_active=True
        )
        self.t_red = TherapistMaster.objects.create(
            therapist_code="TH_RED", therapist_name="Red Therapist",
            therapist_gender="Male", therapist_grade=self.grade, employee_code="EMP003",
            is_bathing_therapist=False, is_active=True
        )
        self.t_gray = TherapistMaster.objects.create(
            therapist_code="TH_GRAY", therapist_name="Gray Therapist",
            therapist_gender="Male", therapist_grade=self.grade, employee_code="EMP004",
            is_bathing_therapist=False, is_active=True
        )
        self.t_blue = TherapistMaster.objects.create(
            therapist_code="TH_BLUE", therapist_name="Blue Therapist",
            therapist_gender="Male", therapist_grade=self.grade, employee_code="EMP005",
            is_bathing_therapist=False, is_active=True
        )

        # Slots & Therapy
        self.slot1 = SlotMaster.objects.create(
            slot_number=1, slot_time="09:00:00", is_active=True
        )
        self.slot2 = SlotMaster.objects.create(
            slot_number=2, slot_time="14:00:00", is_active=True
        )
        self.therapy = TherapyMaster.objects.create(
            therapy_code="THP01", therapy_name="Abhyanga", therapy_category="Medium",
            therapy_duration="45", bathing_required="No", treatment_room_required="No",
            is_active=True
        )

        # Patients
        self.patient_normal = PatientSnapshot.objects.create(
            pat_name="John Normal", pat_reg_no="REG_NORM_01", pat_room_no="101"
        )
        self.patient_vip = PatientSnapshot.objects.create(
            pat_name="VIP Lord", pat_reg_no="999901", pat_room_no="CT-01"
        )
        Repeated_Visitors.objects.create(
            register_number=999901, is_vip=True, total_visits=3
        )

    def test_constants_completeness(self):
        """Verify that ALL 5 status categories have complete labels, meanings, and sub-reasons."""
        expected_statuses = ['green', 'purple', 'red', 'gray', 'blue']
        for st in expected_statuses:
            self.assertIn(st, STATUS_LABELS)
            self.assertIn(st, CORE_MEANINGS)
            self.assertIn(st, ALL_SUB_REASONS)
            self.assertGreater(len(ALL_SUB_REASONS[st]), 0)

        # Check Green
        self.assertEqual(STATUS_LABELS['green'], "Continuity Maintained")
        self.assertIn("100%", ALL_SUB_REASONS['green'][1])

        # Check Purple
        self.assertEqual(STATUS_LABELS['purple'], "Conflict / Assigned Elsewhere")
        self.assertTrue(any("Occupied as Primary" in s for s in ALL_SUB_REASONS['purple']))
        self.assertTrue(any("Occupied as Bathing" in s for s in ALL_SUB_REASONS['purple']))
        self.assertTrue(any("Assigned Newly" in s for s in ALL_SUB_REASONS['purple']))
        self.assertTrue(any("Assigned as Substitute" in s for s in ALL_SUB_REASONS['purple']))

        # Check Red
        self.assertEqual(STATUS_LABELS['red'], "Avoidable Break / Unassigned")
        self.assertTrue(any("Algorithm Slot Mismatch" in s for s in ALL_SUB_REASONS['red']))
        self.assertTrue(any("Manual Override" in s for s in ALL_SUB_REASONS['red']))
        self.assertTrue(any("Grade / Workload Cap" in s for s in ALL_SUB_REASONS['red']))

        # Check Gray
        self.assertEqual(STATUS_LABELS['gray'], "Unavailable / On Leave")
        self.assertTrue(any("Weekly Off" in s for s in ALL_SUB_REASONS['gray']))
        self.assertTrue(any("Emergency / Sick Leave" in s for s in ALL_SUB_REASONS['gray']))
        self.assertTrue(any("Deputed / On-Call" in s for s in ALL_SUB_REASONS['gray']))
        self.assertTrue(any("Treatment Omission" in s for s in ALL_SUB_REASONS['gray']))

        # Check Blue
        self.assertEqual(STATUS_LABELS['blue'], "Preference Allocation")
        self.assertTrue(any("Patient / VIP Preference" in s for s in ALL_SUB_REASONS['blue']))
        self.assertTrue(any("Doctor Preference" in s for s in ALL_SUB_REASONS['blue']))
        self.assertTrue(any("Language Match" in s for s in ALL_SUB_REASONS['blue']))

    def test_continuity_maintained_green(self):
        """When the same therapist is retained across sessions, status is green."""
        day1 = date(2026, 11, 1)
        day2 = date(2026, 11, 2)

        alloc = TherapyAllocation.objects.create(
            patient=self.patient_normal, therapy_name="Abhyanga",
            therapy_code="THP01", from_date=day1, to_date=day2, days=2,
            timeslot=self.slot1, status="scheduled"
        )
        b1 = Booking.objects.create(
            allocation=alloc, date=day1, timeslot=self.slot1, status="scheduled"
        )
        BookingAssignment.objects.create(
            booking=b1, therapist_id=self.t_green.therapist_code, status="assigned"
        )
        TherapistBooking.objects.create(
            therapist=self.t_green, visit=alloc, date=day1, time_slot=self.slot1,
            therapy_name="Abhyanga", status="BOOKED"
        )

        b2 = Booking.objects.create(
            allocation=alloc, date=day2, timeslot=self.slot1, status="scheduled"
        )
        BookingAssignment.objects.create(
            booking=b2, therapist_id=self.t_green.therapist_code, status="assigned"
        )
        TherapistBooking.objects.create(
            therapist=self.t_green, visit=alloc, date=day2, time_slot=self.slot1,
            therapy_name="Abhyanga", status="BOOKED"
        )

        req = self.rf.get(f'/sheduling/scheduling/api/continuity-matrix/?from_date={day1.isoformat()}&to_date={day2.isoformat()}')
        view_func = getattr(continuity_matrix_api, '__wrapped__', continuity_matrix_api)
        res = view_func(req)
        self.assertEqual(res.status_code, 200)

        data = json.loads(res.content)
        row = data['rows'][0]
        day2_cell = row['cells'][day2.isoformat()]
        t_info = day2_cell['therapists'][0]

        self.assertEqual(t_info['status'], 'green')
        self.assertEqual(t_info['status_label'], 'Continuity Maintained')
        self.assertEqual(t_info['core_meaning'], 'Correctly assigned to ongoing therapist.')
        self.assertEqual(t_info['sub_reason_code'], 'primary_retained')
        self.assertEqual(t_info['continuity_score'], '100%')

    def test_conflict_assigned_elsewhere_purple(self):
        """When previous therapist is occupied with another patient at this slot, status is purple."""
        day1 = date(2026, 11, 1)
        day2 = date(2026, 11, 2)

        # Patient 1 has t_green on day 1
        alloc1 = TherapyAllocation.objects.create(
            patient=self.patient_normal, therapy_name="Abhyanga",
            therapy_code="THP01", from_date=day1, to_date=day2, days=2,
            timeslot=self.slot1, status="scheduled"
        )
        b1 = Booking.objects.create(
            allocation=alloc1, date=day1, timeslot=self.slot1, status="scheduled"
        )
        BookingAssignment.objects.create(
            booking=b1, therapist_id=self.t_green.therapist_code, status="assigned"
        )
        TherapistBooking.objects.create(
            therapist=self.t_green, visit=alloc1, date=day1, time_slot=self.slot1,
            therapy_name="Abhyanga", status="BOOKED"
        )

        # On day 2, Patient 1 has t_red instead
        b2 = Booking.objects.create(
            allocation=alloc1, date=day2, timeslot=self.slot1, status="scheduled"
        )
        BookingAssignment.objects.create(
            booking=b2, therapist_id=self.t_red.therapist_code, status="assigned"
        )
        TherapistBooking.objects.create(
            therapist=self.t_red, visit=alloc1, date=day2, time_slot=self.slot1,
            therapy_name="Abhyanga", status="BOOKED"
        )

        # Meanwhile, t_green is occupied on day 2 at same slot with Patient 2
        p2 = PatientSnapshot.objects.create(pat_name="Other Patient", pat_reg_no="REG_OTHER_02")
        alloc2 = TherapyAllocation.objects.create(
            patient=p2, therapy_name="Abhyanga", therapy_code="THP01",
            from_date=day1, to_date=day2, days=2, timeslot=self.slot1, status="scheduled"
        )
        b_other = Booking.objects.create(
            allocation=alloc2, date=day2, timeslot=self.slot1, status="scheduled"
        )
        BookingAssignment.objects.create(
            booking=b_other, therapist_id=self.t_green.therapist_code, status="assigned"
        )
        TherapistBooking.objects.create(
            therapist=self.t_green, visit=alloc2, date=day2, time_slot=self.slot1,
            therapy_name="Abhyanga", status="BOOKED"
        )

        req = self.rf.get(f'/sheduling/scheduling/api/continuity-matrix/?from_date={day1.isoformat()}&to_date={day2.isoformat()}')
        view_func = getattr(continuity_matrix_api, '__wrapped__', continuity_matrix_api)
        res = view_func(req)
        self.assertEqual(res.status_code, 200)

        data = json.loads(res.content)
        row1 = [r for r in data['rows'] if r['patient']['name'] == self.patient_normal.pat_name][0]
        day2_cell = row1['cells'][day2.isoformat()]
        t_info = day2_cell['therapists'][0]

        self.assertEqual(t_info['status'], 'purple')
        self.assertEqual(t_info['status_label'], 'Conflict / Assigned Elsewhere')
        self.assertEqual(t_info['core_meaning'], 'Previous therapist is on duty, but occupied with another patient.')
        self.assertIn(t_info['sub_reason_title'], ['Occupied as Primary', 'Assigned Newly', 'Occupied as Bathing', 'Assigned as Substitute'])
        self.assertEqual(t_info['previous_therapist_name'], self.t_green.therapist_name)

    def test_conflict_occupied_as_primary_purple(self):
        """When previous therapist is occupied as primary continuity therapist for another patient."""
        day1 = date(2026, 11, 1)
        day2 = date(2026, 11, 2)

        # Patient 1 has t_green on day 1 at slot 1
        alloc1 = TherapyAllocation.objects.create(
            patient=self.patient_normal, therapy_name="Abhyanga",
            therapy_code="THP01", from_date=day1, to_date=day2, days=2,
            timeslot=self.slot1, status="scheduled"
        )
        b1 = Booking.objects.create(
            allocation=alloc1, date=day1, timeslot=self.slot1, status="scheduled"
        )
        BookingAssignment.objects.create(
            booking=b1, therapist_id=self.t_green.therapist_code, status="assigned"
        )
        TherapistBooking.objects.create(
            therapist=self.t_green, visit=alloc1, date=day1, time_slot=self.slot1,
            therapy_name="Abhyanga", status="BOOKED"
        )

        # On day 2, Patient 1 has t_red instead at slot 1
        b2 = Booking.objects.create(
            allocation=alloc1, date=day2, timeslot=self.slot1, status="scheduled"
        )
        BookingAssignment.objects.create(
            booking=b2, therapist_id=self.t_red.therapist_code, status="assigned"
        )
        TherapistBooking.objects.create(
            therapist=self.t_red, visit=alloc1, date=day2, time_slot=self.slot1,
            therapy_name="Abhyanga", status="BOOKED"
        )

        # Patient 2 had t_green on day 1 at slot 2 (different slot on day 1!), and has t_green on day 2 at slot 1
        p2 = PatientSnapshot.objects.create(pat_name="Other Patient", pat_reg_no="REG_OTHER_02")
        alloc2 = TherapyAllocation.objects.create(
            patient=p2, therapy_name="Abhyanga", therapy_code="THP01",
            from_date=day1, to_date=day2, days=2, timeslot=self.slot1, status="scheduled"
        )
        b_other1 = Booking.objects.create(
            allocation=alloc2, date=day1, timeslot=self.slot2, status="scheduled"
        )
        BookingAssignment.objects.create(
            booking=b_other1, therapist_id=self.t_green.therapist_code, status="assigned"
        )
        TherapistBooking.objects.create(
            therapist=self.t_green, visit=alloc2, date=day1, time_slot=self.slot2,
            therapy_name="Abhyanga", status="BOOKED"
        )

        b_other2 = Booking.objects.create(
            allocation=alloc2, date=day2, timeslot=self.slot1, status="scheduled"
        )
        BookingAssignment.objects.create(
            booking=b_other2, therapist_id=self.t_green.therapist_code, status="assigned"
        )
        TherapistBooking.objects.create(
            therapist=self.t_green, visit=alloc2, date=day2, time_slot=self.slot1,
            therapy_name="Abhyanga", status="BOOKED"
        )

        req = self.rf.get(f'/sheduling/scheduling/api/continuity-matrix/?from_date={day1.isoformat()}&to_date={day2.isoformat()}')
        view_func = getattr(continuity_matrix_api, '__wrapped__', continuity_matrix_api)
        res = view_func(req)
        self.assertEqual(res.status_code, 200)

        data = json.loads(res.content)
        row1 = [r for r in data['rows'] if r['patient']['name'] == self.patient_normal.pat_name][0]
        day2_cell = row1['cells'][day2.isoformat()]
        t_info = day2_cell['therapists'][0]

        self.assertEqual(t_info['status'], 'purple')
        self.assertEqual(t_info['sub_reason_code'], 'occupied_as_primary')
        self.assertEqual(t_info['sub_reason_title'], 'Occupied as Primary')

    def test_unavailable_on_leave_gray(self):
        """When previous therapist is on weekly off / leave, status is gray."""
        day1 = date(2026, 11, 1)
        day2 = date(2026, 11, 2)  # Monday, weekday=0

        # Mark t_green as weekly off on Monday (0)
        TherapistLeaveMaster.objects.create(
            therapist=self.t_green, leave_day=day2.weekday(), leave_day_name="Monday", is_active=True
        )

        alloc = TherapyAllocation.objects.create(
            patient=self.patient_normal, therapy_name="Abhyanga",
            therapy_code="THP01", from_date=day1, to_date=day2, days=2,
            timeslot=self.slot1, status="scheduled"
        )
        b1 = Booking.objects.create(
            allocation=alloc, date=day1, timeslot=self.slot1, status="scheduled"
        )
        BookingAssignment.objects.create(
            booking=b1, therapist_id=self.t_green.therapist_code, status="assigned"
        )
        TherapistBooking.objects.create(
            therapist=self.t_green, visit=alloc, date=day1, time_slot=self.slot1,
            therapy_name="Abhyanga", status="BOOKED"
        )

        # On day 2, replaced with t_red because t_green is on weekly off
        b2 = Booking.objects.create(
            allocation=alloc, date=day2, timeslot=self.slot1, status="scheduled"
        )
        BookingAssignment.objects.create(
            booking=b2, therapist_id=self.t_red.therapist_code, status="assigned"
        )
        TherapistBooking.objects.create(
            therapist=self.t_red, visit=alloc, date=day2, time_slot=self.slot1,
            therapy_name="Abhyanga", status="BOOKED"
        )

        req = self.rf.get(f'/sheduling/scheduling/api/continuity-matrix/?from_date={day1.isoformat()}&to_date={day2.isoformat()}&exclude_leave=false')
        view_func = getattr(continuity_matrix_api, '__wrapped__', continuity_matrix_api)
        res = view_func(req)
        self.assertEqual(res.status_code, 200)

        data = json.loads(res.content)
        row = data['rows'][0]
        day2_cell = row['cells'][day2.isoformat()]
        t_info = day2_cell['therapists'][0]

        self.assertEqual(t_info['status'], 'gray')
        self.assertEqual(t_info['status_label'], 'Unavailable / On Leave')
        self.assertEqual(t_info['core_meaning'], 'Previous therapist is legitimately not in the active pool.')
        self.assertEqual(t_info['sub_reason_code'], 'weekly_off')
        self.assertIn('Weekly Off', t_info['sub_reason_title'])
        self.assertEqual(t_info['previous_therapist_name'], self.t_green.therapist_name)

    def test_preference_allocation_blue(self):
        """When therapist is assigned to a VIP/Cottage patient, status is blue."""
        day1 = date(2026, 11, 1)

        alloc = TherapyAllocation.objects.create(
            patient=self.patient_vip, therapy_name="Abhyanga",
            therapy_code="THP01", from_date=day1, to_date=day1, days=1,
            timeslot=self.slot1, status="scheduled"
        )
        b1 = Booking.objects.create(
            allocation=alloc, date=day1, timeslot=self.slot1, status="scheduled"
        )
        BookingAssignment.objects.create(
            booking=b1, therapist_id=self.t_blue.therapist_code, status="assigned"
        )
        TherapistBooking.objects.create(
            therapist=self.t_blue, visit=alloc, date=day1, time_slot=self.slot1,
            therapy_name="Abhyanga", status="BOOKED"
        )

        req = self.rf.get(f'/sheduling/scheduling/api/continuity-matrix/?from_date={day1.isoformat()}&to_date={day1.isoformat()}')
        view_func = getattr(continuity_matrix_api, '__wrapped__', continuity_matrix_api)
        res = view_func(req)
        self.assertEqual(res.status_code, 200)

        data = json.loads(res.content)
        row = data['rows'][0]
        day1_cell = row['cells'][day1.isoformat()]
        t_info = day1_cell['therapists'][0]

        self.assertEqual(t_info['status'], 'blue')
        self.assertEqual(t_info['status_label'], 'Preference Allocation')
        self.assertEqual(t_info['core_meaning'], 'Assigned specifically due to a registered preference.')
        self.assertIn('SCH_REQ_067', t_info['sub_reason_detail'])
