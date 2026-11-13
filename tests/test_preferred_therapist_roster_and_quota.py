"""
Comprehensive test suite for:
1. Doctor Monthly Quota (max 5 patients per month, showcase quota left, allowance toggle).
2. Scheduling Dashboard Preferred Therapist page (only allowed patients, max 7 therapists, primary/secondary bathing).
3. Therapist Week Offs visibility.
4. Strict 7-Therapist Scheduling Pool (only those 7 can be scheduled, never outsiders).
5. Bathing Therapist Primary -> Secondary substitution when Primary is off.
6. Continuity and Replacement within the 7-therapist pool (4 available kept, 1 off replaced from remaining 2).
"""
import pytest
from datetime import date, time
from django.test import TestCase, Client
from django.utils import timezone
from django.core.exceptions import ValidationError

from authentication.models import CustomUser, DoctorProfile
from masters.models import SlotMaster, TherapistGrade, TherapistMaster, TherapistLeaveMaster, TherapyMaster
from Patient.models import Repeated_Visitors, TreatmentRoom, RoomName, TherapistBooking
from Sheduling.models import (
    DoctorPatientPreferenceAllowance,
    PatientPreferredTherapistRoster,
    PatientSnapshot,
    TherapyAllocation,
    Booking,
)
from Sheduling.preferred_therapist_service import (
    toggle_doctor_patient_allowance,
    save_preferred_therapist_roster,
    get_active_preferred_roster,
    get_therapists_with_schedule_info,
    pick_bathing_therapist_from_roster,
)
from final_allocation import allocate_therapists, assign_continuity_therapists_pass1


class DoctorQuotaAndPreferredTherapistTests(TestCase):
    def setUp(self):
        # Create Doctor User
        self.doc_user = CustomUser.objects.create_user(
            username="test_dr_quota",
            password="testpassword123",
            role="doctor",
            first_name="Arya",
            last_name="Sharma"
        )
        self.doc_profile = DoctorProfile.objects.create(
            user=self.doc_user,
            doctor_id="DOC_Q_001",
            specialization="Ayurveda",
            department="Panchakarma",
            qualification="BAMS, MD",
            experience_years=10
        )

        # Create Scheduling Staff User
        self.staff_user = CustomUser.objects.create_user(
            username="test_sched_staff",
            password="testpassword123",
            role="scheduling_staff",
            first_name="Scheduling",
            last_name="Staff"
        )

        # Create Grades
        self.grade_super, _ = TherapistGrade.objects.get_or_create(name="Super Senior Therapist", defaults={"display_order": 1, "is_active": True})
        self.grade_senior, _ = TherapistGrade.objects.get_or_create(name="Senior Therapist", defaults={"display_order": 2, "is_active": True})
        self.grade_junior, _ = TherapistGrade.objects.get_or_create(name="Junior Therapist", defaults={"display_order": 3, "is_active": True})
        self.grade_trainee, _ = TherapistGrade.objects.get_or_create(name="Trainee Therapist", defaults={"display_order": 4, "is_active": True})

        # Create Slot
        self.slot, _ = SlotMaster.objects.get_or_create(
            slot_number=1,
            defaults={"slot_time": time(8, 0), "is_active": True}
        )

        # Create 7 Preferred Therapists
        # T1: Primary Bathing (Off on Monday, day=0)
        # T2: Secondary Bathing (Off on Thursday, day=3)
        # T3, T4, T5, T6, T7: Other pool members
        self.therapists = []
        for i in range(1, 8):
            code = f"PREF_T{i}"
            is_bath = (i in [1, 2])
            t, _ = TherapistMaster.objects.get_or_create(
                therapist_code=code,
                defaults={
                    "therapist_name": f"Preferred Therapist {i}",
                    "therapist_gender": "Male",
                    "therapist_grade": self.grade_senior,
                    "employee_code": f"EMP_PREF_{i}",
                    "is_bathing_therapist": is_bath,
                    "is_helping_therapist": False,
                    "is_active": True,
                }
            )
            self.therapists.append(t)

        # T1 week off: Monday (0)
        TherapistLeaveMaster.objects.get_or_create(therapist=self.therapists[0], leave_day=0, defaults={"is_active": True})
        # T2 week off: Thursday (3)
        TherapistLeaveMaster.objects.get_or_create(therapist=self.therapists[1], leave_day=3, defaults={"is_active": True})
        # T3 week off: Friday (4)
        TherapistLeaveMaster.objects.get_or_create(therapist=self.therapists[2], leave_day=4, defaults={"is_active": True})

        # Create 1 Outside Non-Preferred Therapist
        self.outside_therapist, _ = TherapistMaster.objects.get_or_create(
            therapist_code="OUTSIDE_T99",
            defaults={
                "therapist_name": "Outside Therapist 99",
                "therapist_gender": "Male",
                "therapist_grade": self.grade_senior,
                "employee_code": "EMP_OUTSIDE_99",
                "is_bathing_therapist": True,
                "is_helping_therapist": False,
                "is_active": True,
            }
        )

        # Create Sample VIP and Repeated Patients
        self.vip_reg = "90001"
        Repeated_Visitors.objects.update_or_create(
            register_number=90001,
            defaults={"patient_name": "VIP Patient Suresh", "total_visits": 5, "is_vip": True}
        )
        self.vip_snapshot, _ = PatientSnapshot.objects.get_or_create(
            pat_reg_no=self.vip_reg,
            defaults={"pat_name": "VIP Patient Suresh", "pat_sex": "Male", "pat_age": "50"}
        )
        # Link doc_user as treating doctor
        TherapyAllocation.objects.get_or_create(
            patient=self.vip_snapshot,
            therapy_code="TH_VIP",
            defaults={"allocated_by": self.doc_user, "from_date": timezone.now().date(), "to_date": timezone.now().date(), "days": 1}
        )

    def test_doctor_monthly_quota_limit_and_showcase(self):
        """
        Rule 1: Only 5 patients can be marked per doctor for a month.
        Showcase how many quota slots are left.
        A 6th patient attempt must be rejected.
        """
        now = timezone.now()
        # Mark 5 patients (all are Cottage Repeated patients treated by doc_user)
        for i in range(1, 6):
            reg = f"8800{i}"
            Repeated_Visitors.objects.update_or_create(register_number=int(reg), defaults={"total_visits": 3, "is_vip": False})
            ps, _ = PatientSnapshot.objects.update_or_create(pat_reg_no=reg, defaults={"pat_name": f"Cottage Patient {i}", "pat_room_no": "CT-1"})
            TherapyAllocation.objects.get_or_create(patient=ps, therapy_code=f"TH_{i}", defaults={"allocated_by": self.doc_user, "from_date": now.date(), "to_date": now.date(), "days": 1})
            res = toggle_doctor_patient_allowance(self.doc_user, reg, f"Cottage Patient {i}")
            self.assertEqual(res['status'], 'allowed')
            self.assertTrue(res['is_allowed'])

        # Check quota showcase: 5 used, 0 remaining
        quota = DoctorPatientPreferenceAllowance.get_monthly_quota(self.doc_user, now.year, now.month)
        self.assertEqual(quota['used'], 5)
        self.assertEqual(quota['remaining'], 0)
        self.assertEqual(quota['limit'], 5)

        # Attempt to mark a 6th patient in the same month -> must be rejected by quota!
        reg_6 = "88006"
        Repeated_Visitors.objects.update_or_create(register_number=int(reg_6), defaults={"total_visits": 3, "is_vip": False})
        ps_6, _ = PatientSnapshot.objects.update_or_create(pat_reg_no=reg_6, defaults={"pat_name": "Cottage Patient 6", "pat_room_no": "CT-2"})
        TherapyAllocation.objects.get_or_create(patient=ps_6, therapy_code="TH_6", defaults={"allocated_by": self.doc_user, "from_date": now.date(), "to_date": now.date(), "days": 1})
        res_sixth = toggle_doctor_patient_allowance(self.doc_user, reg_6, "Cottage Patient 6")
        self.assertEqual(res_sixth['status'], 'quota_exceeded')
        self.assertIn("Monthly quota limit of 5 patients reached", res_sixth['error'])
        self.assertEqual(res_sixth['quota']['remaining'], 0)

        # Revoking 1 patient frees up quota slot
        res_revoke = toggle_doctor_patient_allowance(self.doc_user, "88001")
        self.assertEqual(res_revoke['status'], 'revoked')
        self.assertFalse(res_revoke['is_allowed'])

        quota_after = DoctorPatientPreferenceAllowance.get_monthly_quota(self.doc_user, now.year, now.month)
        self.assertEqual(quota_after['used'], 4)
        self.assertEqual(quota_after['remaining'], 1)

    def test_scheduling_preferred_roster_configuration(self):
        """
        Rule 2: Scheduling team can mark up to 7 preferred therapists,
        designating 1 Primary Bathing and 1 Secondary Bathing Therapist.
        Week offs are available for display.
        """
        # First, doctor allows patient
        toggle_doctor_patient_allowance(self.doc_user, self.vip_reg, "VIP Patient Suresh")

        codes = [t.therapist_code for t in self.therapists] # 7 therapists
        p_code = self.therapists[0].therapist_code
        s_code = self.therapists[1].therapist_code

        # Successfully save roster
        roster = save_preferred_therapist_roster(
            patient_reg_no=self.vip_reg,
            therapist_codes=codes,
            primary_bathing_code=p_code,
            secondary_bathing_code=s_code,
            configured_by=self.staff_user
        )
        self.assertIsNotNone(roster)
        self.assertEqual(len(roster.therapist_codes), 7)
        self.assertEqual(roster.primary_bathing_code, p_code)
        self.assertEqual(roster.secondary_bathing_code, s_code)

        # Test week offs info
        therapists_info = get_therapists_with_schedule_info()
        t1_info = next(x for x in therapists_info if x['therapist_code'] == p_code)
        self.assertIn("Monday", t1_info['week_offs'])

        t2_info = next(x for x in therapists_info if x['therapist_code'] == s_code)
        self.assertIn("Thursday", t2_info['week_offs'])

    def test_roster_validations(self):
        """
        Validations:
        - Cannot exceed 7 therapists
        - Primary and Secondary cannot be identical
        - Non-allowed patient cannot be configured
        """
        # More than 7 therapists
        with self.assertRaises(ValidationError):
            save_preferred_therapist_roster(
                patient_reg_no=self.vip_reg,
                therapist_codes=[f"T{i}" for i in range(1, 9)], # 8 therapists
                primary_bathing_code="T1",
                secondary_bathing_code="T2"
            )

        # Primary == Secondary
        with self.assertRaises(ValidationError):
            save_preferred_therapist_roster(
                patient_reg_no=self.vip_reg,
                therapist_codes=[t.therapist_code for t in self.therapists[:5]],
                primary_bathing_code=self.therapists[0].therapist_code,
                secondary_bathing_code=self.therapists[0].therapist_code
            )

        # Non-allowed patient
        with self.assertRaises(ValidationError):
            save_preferred_therapist_roster(
                patient_reg_no="UNKNOWN_NON_ALLOWED_999",
                therapist_codes=[t.therapist_code for t in self.therapists[:5]],
                primary_bathing_code=self.therapists[0].therapist_code,
                secondary_bathing_code=self.therapists[1].therapist_code
            )

    def test_strict_7_therapist_scheduling_and_bathing_substitution(self):
        """
        Rule 3 & 4:
        - Once configured, ONLY the 7 therapists can be scheduled (never outsiders).
        - If treatment needs 5 therapists, schedule 5 from the 7.
        - Primary Bathing Therapist is scheduled when available.
        - When Primary Bathing Therapist is on weekly off (Monday), Secondary Bathing Therapist takes over!
        """
        toggle_doctor_patient_allowance(self.doc_user, self.vip_reg, "VIP Patient Suresh")
        codes = [t.therapist_code for t in self.therapists] # PREF_T1 .. PREF_T7
        save_preferred_therapist_roster(
            patient_reg_no=self.vip_reg,
            therapist_codes=codes,
            primary_bathing_code="PREF_T1",
            secondary_bathing_code="PREF_T2",
            configured_by=self.staff_user
        )

        req_5 = {"total": 5, "senior": 5, "super_senior": 0, "junior": 0, "trainee": 0}

        # Scenario A: Tuesday (weekday=1) -> Both T1 (off Mon) and T2 (off Thu) are available
        tuesday_date = date(2026, 11, 10) # Tuesday (weekday 1)
        self.assertEqual(tuesday_date.weekday(), 1)

        # Bathing therapist picked should be Primary (PREF_T1)
        roster_info = get_active_preferred_roster(self.vip_reg)
        bath_t, bath_role = pick_bathing_therapist_from_roster(roster_info, tuesday_date, self.slot)
        self.assertEqual(bath_t.therapist_code, "PREF_T1")
        self.assertEqual(bath_role, "primary")

        # Scenario B: Monday (weekday=0) -> T1 is on weekly off!
        monday_date = date(2026, 11, 9) # Monday (weekday 0)
        self.assertEqual(monday_date.weekday(), 0)

        # Bathing therapist picked should be Secondary (PREF_T2) because Primary (T1) is off!
        bath_t_mon, bath_role_mon = pick_bathing_therapist_from_roster(roster_info, monday_date, self.slot)
        self.assertEqual(bath_t_mon.therapist_code, "PREF_T2")
        self.assertEqual(bath_role_mon, "secondary")

        # Allocation: Allocate 5 therapists for this patient on Tuesday
        allocated = allocate_therapists(
            date=tuesday_date,
            time_slot=self.slot,
            therapy_requirements=req_5,
            needs_bathing=True,
            patient_id=self.vip_reg
        )
        self.assertEqual(len(allocated), 5)
        # Ensure ALL 5 are from the 7 roster!
        for t in allocated:
            self.assertIn(t.therapist_code, codes)
            self.assertNotEqual(t.therapist_code, "OUTSIDE_T99")

    def test_continuity_and_replacement_from_7_pool(self):
        """
        Rule 5:
        "if the treatment need 5 therapist yesterday 5 therapist got scheduled today in that 5 - 4 only available
        1 is in off then replace it from the other 2"
        """
        toggle_doctor_patient_allowance(self.doc_user, self.vip_reg, "VIP Patient Suresh")
        codes = [t.therapist_code for t in self.therapists] # PREF_T1 to PREF_T7
        save_preferred_therapist_roster(
            patient_reg_no=self.vip_reg,
            therapist_codes=codes,
            primary_bathing_code="PREF_T1",
            secondary_bathing_code="PREF_T2"
        )

        # Setup Yesterday: Wednesday (weekday 2)
        # 5 therapists scheduled yesterday: T1 (bathing), T3, T4, T5, T6
        yesterday_date = date(2026, 11, 11) # Wednesday (weekday 2)
        today_date = date(2026, 11, 12) # Thursday (weekday 3)
        self.assertEqual(today_date.weekday(), 3)

        # On Thursday (today), T2 has week off!
        # Suppose yesterday's 5 therapists were: T1, T2, T3, T4, T5
        # Today on Thursday, T2 is off. T1, T3, T4, T5 (4 therapists) are available.
        # Remaining pool has T6 and T7.
        # We need 5 therapists today. T1, T3, T4, T5 are kept from continuity,
        # and the missing 1 is replaced by picking from the remaining pool (T6 or T7)!

        req_5 = {"total": 5, "senior": 5, "super_senior": 0, "junior": 0, "trainee": 0}
        last_therapists = ["PREF_T1", "PREF_T2", "PREF_T3", "PREF_T4", "PREF_T5"]

        allocated_today = allocate_therapists(
            date=today_date,
            time_slot=self.slot,
            therapy_requirements=req_5,
            last_therapists=last_therapists,
            needs_bathing=True,
            patient_id=self.vip_reg
        )

        self.assertEqual(len(allocated_today), 5)
        allocated_codes = [t.therapist_code for t in allocated_today]

        # T2 is on leave today, so T2 must NOT be scheduled
        self.assertNotIn("PREF_T2", allocated_codes)

        # The 4 available from yesterday (T1, T3, T4, T5) should be scheduled
        for c in ["PREF_T1", "PREF_T3", "PREF_T4", "PREF_T5"]:
            self.assertIn(c, allocated_codes)

        # The replacement must come from the remaining members of the 7 pool (PREF_T6 or PREF_T7)
        replacement_found = ("PREF_T6" in allocated_codes) or ("PREF_T7" in allocated_codes)
        self.assertTrue(replacement_found)

        # Under NO circumstance should outside therapist be scheduled
        self.assertNotIn("OUTSIDE_T99", allocated_codes)


    def test_doctor_patients_vip_repeated_api_and_views(self):
        """Test Doctor View, Filter options (VIP, Repeated, Allowed), and Allowance Toggle API."""
        from django.urls import reverse
        client = Client()
        client.force_login(self.doc_user)

        # 1. Page view test
        response = client.get(reverse('doctor_patients_vip_repeated'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "My Patients (VIP & Repeated)")
        self.assertContains(response, "Preferred Therapist Monthly Quota")

        # 2. API test for all patients
        api_res = client.get(f"{reverse('doctor_patients_vip_repeated_api')}?filter=ALL")
        self.assertEqual(api_res.status_code, 200)
        data = api_res.json()
        self.assertEqual(data['status'], 'success')
        self.assertIn('quota', data)
        self.assertEqual(data['quota']['limit'], 5)

        # 3. API test for VIP filter
        vip_res = client.get(f"{reverse('doctor_patients_vip_repeated_api')}?filter=VIP")
        self.assertEqual(vip_res.status_code, 200)
        vip_data = vip_res.json()
        self.assertTrue(any(p['patient_reg_no'] == self.vip_reg for p in vip_data['patients']))

        # 4. Toggle allowance API test
        toggle_res = client.post(
            reverse('toggle_doctor_patient_allowance_api'),
            data='{"patient_reg_no": "90001", "patient_name": "VIP Patient Suresh"}',
            content_type='application/json'
        )
        self.assertEqual(toggle_res.status_code, 200)
        t_data = toggle_res.json()
        self.assertEqual(t_data['status'], 'success')
        self.assertTrue(t_data['is_allowed'])
        self.assertEqual(t_data['quota']['used'], 1)
        self.assertEqual(t_data['quota']['remaining'], 4)

    def test_scheduling_dashboard_preferred_therapists_api_and_views(self):
        """Test Scheduling View, only allowed patients showing, and roster saving."""
        from django.urls import reverse
        # Allow patient first
        toggle_doctor_patient_allowance(self.doc_user, self.vip_reg, "VIP Patient Suresh")

        client = Client()
        client.force_login(self.staff_user)

        # 1. Page view
        response = client.get(reverse('scheduling_preferred_therapists'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Preferred Therapist Assignment")

        # 2. Allowed patients API
        api_res = client.get(reverse('get_allowed_patients_preferred_therapists_api'))
        self.assertEqual(api_res.status_code, 200)
        data = api_res.json()
        self.assertEqual(data['status'], 'success')
        # Patient 90001 must be in allowed list
        self.assertTrue(any(p['patient_reg_no'] == self.vip_reg for p in data['patients']))
        # Non-allowed patients must NOT be in the list
        self.assertFalse(any(p['patient_reg_no'] == 'UNKNOWN_NOT_ALLOWED' for p in data['patients']))

        # 3. Therapists with leaves API
        th_res = client.get(reverse('get_therapists_with_leaves_api'))
        self.assertEqual(th_res.status_code, 200)
        th_data = th_res.json()
        self.assertEqual(th_data['status'], 'success')
        self.assertTrue(len(th_data['therapists']) >= 7)

        # 4. Save preferred roster API
        save_res = client.post(
            reverse('save_patient_preferred_roster_api'),
            data=f'''{{
                "patient_reg_no": "{self.vip_reg}",
                "therapist_codes": ["PREF_T1", "PREF_T2", "PREF_T3", "PREF_T4", "PREF_T5", "PREF_T6", "PREF_T7"],
                "primary_bathing_code": "PREF_T1",
                "secondary_bathing_code": "PREF_T2"
            }}''',
            content_type='application/json'
        )
        self.assertEqual(save_res.status_code, 200)
        s_data = save_res.json()
        self.assertEqual(s_data['status'], 'success')
        self.assertEqual(s_data['therapist_count'], 7)
        self.assertEqual(s_data['primary_bathing_code'], "PREF_T1")
        self.assertEqual(s_data['secondary_bathing_code'], "PREF_T2")

    def test_cottage_repeated_patient_eligibility_and_filtering(self):
        """
        Rule: ALL patients (VIP, Cottage Repeated, Non-cottage Repeated, and Standard first-time patients)
        are eligible to be allowed by their treating doctor for preferred/unpreferred therapist preferences,
        while category flags and filter=REPEATED continue to classify Cottage Repeated vs non-cottage.
        """
        from Sheduling.preferred_therapist_service import is_cottage_room, resolve_patient_vip_and_repeated
        from django.urls import reverse

        # 1. Cottage repeated patient -> Eligible & Allowed!
        reg_cottage = "77001"
        Repeated_Visitors.objects.update_or_create(register_number=77001, defaults={"patient_name": "Cottage Rep P1", "total_visits": 4, "is_vip": False})
        ps_c, _ = PatientSnapshot.objects.update_or_create(pat_reg_no=reg_cottage, defaults={"pat_name": "Cottage Rep P1", "pat_room_no": "CT-1"})
        TherapyAllocation.objects.get_or_create(patient=ps_c, therapy_code="TH_77001", defaults={"allocated_by": self.doc_user, "from_date": timezone.now().date(), "to_date": timezone.now().date(), "days": 1})

        info_cottage = resolve_patient_vip_and_repeated(reg_cottage)
        self.assertTrue(info_cottage['is_repeated'])
        self.assertTrue(info_cottage['is_cottage'])
        self.assertTrue(info_cottage['is_cottage_repeated'])
        self.assertTrue(info_cottage['is_eligible'])

        res_allow = toggle_doctor_patient_allowance(self.doc_user, reg_cottage, "Cottage Rep P1")
        self.assertEqual(res_allow['status'], 'allowed')
        self.assertTrue(res_allow['is_allowed'])

        # 2. Non-cottage repeated patient -> Also Eligible & Allowed!
        reg_normal = "77002"
        Repeated_Visitors.objects.update_or_create(register_number=77002, defaults={"patient_name": "Normal Rep P2", "total_visits": 3, "is_vip": False})
        ps_n, _ = PatientSnapshot.objects.update_or_create(pat_reg_no=reg_normal, defaults={"pat_name": "Normal Rep P2", "pat_room_no": "NR-10"})
        TherapyAllocation.objects.get_or_create(patient=ps_n, therapy_code="TH_77002", defaults={"allocated_by": self.doc_user, "from_date": timezone.now().date(), "to_date": timezone.now().date(), "days": 1})

        info_normal = resolve_patient_vip_and_repeated(reg_normal)
        self.assertTrue(info_normal['is_repeated'])
        self.assertFalse(info_normal['is_cottage'])
        self.assertFalse(info_normal['is_cottage_repeated'])
        self.assertTrue(info_normal['is_eligible'])

        res_normal_allow = toggle_doctor_patient_allowance(self.doc_user, reg_normal, "Normal Rep P2")
        self.assertEqual(res_normal_allow['status'], 'allowed')
        self.assertTrue(res_normal_allow['is_allowed'])

        # 3. Standard first-time patient (visits=1, non-VIP) -> Also Eligible & Allowed!
        reg_first_cottage = "77003"
        Repeated_Visitors.objects.update_or_create(register_number=77003, defaults={"patient_name": "First Time Cottage P3", "total_visits": 1, "is_vip": False})
        ps_fc, _ = PatientSnapshot.objects.update_or_create(pat_reg_no=reg_first_cottage, defaults={"pat_name": "First Time Cottage P3", "pat_room_no": "CT-5"})
        TherapyAllocation.objects.get_or_create(patient=ps_fc, therapy_code="TH_77003", defaults={"allocated_by": self.doc_user, "from_date": timezone.now().date(), "to_date": timezone.now().date(), "days": 1})

        info_first = resolve_patient_vip_and_repeated(reg_first_cottage)
        self.assertFalse(info_first['is_repeated'])
        self.assertTrue(info_first['is_cottage'])
        self.assertFalse(info_first['is_cottage_repeated'])
        self.assertTrue(info_first['is_eligible'])

        res_first = toggle_doctor_patient_allowance(self.doc_user, reg_first_cottage, "First Time Cottage P3")
        self.assertEqual(res_first['status'], 'allowed')
        self.assertTrue(res_first['is_allowed'])

        # 4. VIP patient in non-cottage room -> Eligible & Allowed!
        reg_vip_nc = "77004"
        Repeated_Visitors.objects.update_or_create(register_number=77004, defaults={"patient_name": "VIP Non Cottage P4", "total_visits": 1, "is_vip": True})
        ps_vnc, _ = PatientSnapshot.objects.update_or_create(pat_reg_no=reg_vip_nc, defaults={"pat_name": "VIP Non Cottage P4", "pat_room_no": "DS-1"})
        TherapyAllocation.objects.get_or_create(patient=ps_vnc, therapy_code="TH_77004", defaults={"allocated_by": self.doc_user, "from_date": timezone.now().date(), "to_date": timezone.now().date(), "days": 1})

        info_vip = resolve_patient_vip_and_repeated(reg_vip_nc)
        self.assertTrue(info_vip['is_vip'])
        self.assertFalse(info_vip['is_cottage'])
        self.assertTrue(info_vip['is_eligible'])

        res_vip = toggle_doctor_patient_allowance(self.doc_user, reg_vip_nc, "VIP Non Cottage P4")
        self.assertEqual(res_vip['status'], 'allowed')
        self.assertTrue(res_vip['is_allowed'])

        # 5. Doctor API with filter=REPEATED returns ONLY Cottage Repeated patients
        # First re-allow or leave cottage patient in snapshots
        client = Client()
        client.force_login(self.doc_user)
        api_res = client.get(reverse('doctor_patients_vip_repeated_api') + '?filter=REPEATED')
        self.assertEqual(api_res.status_code, 200)
        data = api_res.json()
        self.assertEqual(data['status'], 'success')
        regs_returned = [p['patient_reg_no'] for p in data['patients']]
        # 77001 (cottage repeated) must be returned
        self.assertIn(reg_cottage, regs_returned)
        # 77002 (non-cottage repeated) must NOT be returned
        self.assertNotIn(reg_normal, regs_returned)

    def test_only_particular_treating_doctor_can_allow(self):
        """
        Rule: Only the particular treating doctor can give access to allow preferred therapist.
        A different doctor cannot mark or allow a patient they are not treating.
        """
        from authentication.models import CustomUser, DoctorProfile
        from django.urls import reverse

        # Create Doctor B (a different doctor)
        doc_other = CustomUser.objects.create_user(
            username="test_dr_other",
            password="testpassword123",
            role="doctor",
            first_name="Dr",
            last_name="Other"
        )
        DoctorProfile.objects.create(
            user=doc_other,
            doctor_id="DOC_Q_999",
            specialization="Ayurveda",
            department="Panchakarma",
            qualification="BAMS",
            experience_years=5
        )

        # Patient 90001 is treated by self.doc_user (Dr. Arya Sharma)
        # 1. Doctor B attempts to allow Patient 90001 -> MUST BE REJECTED!
        res = toggle_doctor_patient_allowance(doc_other, self.vip_reg, "VIP Patient Suresh")
        self.assertEqual(res['status'], 'not_treating_doctor')
        self.assertIn("Only the particular treating doctor", res['error'])

        # 2. Doctor B attempts via API -> 403 Forbidden!
        client_other = Client()
        client_other.force_login(doc_other)
        api_res = client_other.post(
            reverse('toggle_doctor_patient_allowance_api'),
            data=f'{{"patient_reg_no": "{self.vip_reg}"}}',
            content_type='application/json'
        )
        self.assertEqual(api_res.status_code, 403)
        self.assertEqual(api_res.json()['error_type'], 'not_treating_doctor')

        # 3. Treating Doctor (self.doc_user) CAN allow the patient
        res_allowed = toggle_doctor_patient_allowance(self.doc_user, self.vip_reg, "VIP Patient Suresh")
        self.assertEqual(res_allowed['status'], 'allowed')
        self.assertTrue(res_allowed['is_allowed'])

        # 4. Doctor B cannot revoke it either
        res_revoke = toggle_doctor_patient_allowance(doc_other, self.vip_reg)
        self.assertEqual(res_revoke['status'], 'not_treating_doctor')
    def test_scheduling_staff_not_treated_as_doctor_and_only_treating_doctor_authorized(self):
        """
        Verify that scheduling staff (e.g. role='scheduling_staff' like Nibin or Arun)
        who allocated therapy in TherapyAllocation are NEVER displayed as 'Dr. Nibin' or 'Dr. Arun',
        are NEVER resolved as treating doctors, and can NEVER grant preferred therapist allowances.
        """
        from Sheduling.preferred_therapist_service import (
            resolve_treating_doctor_for_patient,
            is_user_patient_treating_doctor,
        )

        # Create a patient allocated by scheduling staff
        pat_staff_reg = "99991"
        Repeated_Visitors.objects.update_or_create(
            register_number=99991,
            defaults={"patient_name": "Cottage Patient CT1", "total_visits": 3, "is_vip": False}
        )
        snap, _ = PatientSnapshot.objects.get_or_create(
            pat_reg_no=pat_staff_reg,
            defaults={"pat_name": "Cottage Patient CT1", "pat_room_no": "CT-1", "pat_sex": "Male", "pat_age": "45"}
        )
        # Sched staff allocated it
        TherapyAllocation.objects.create(
            patient=snap,
            therapy_code="TH_STAFF",
            allocated_by=self.staff_user,
            from_date=timezone.now().date(),
            to_date=timezone.now().date(),
            days=1
        )

        # 1. Check resolve_treating_doctor_for_patient does NOT return staff_user as doctor
        u, code, name = resolve_treating_doctor_for_patient(pat_staff_reg)
        self.assertNotEqual(name, f"Dr. {self.staff_user.username}")
        self.assertNotEqual(u, self.staff_user)
        self.assertEqual(name, "Not Assigned")

        # 2. Staff user is NOT recognized as treating doctor
        self.assertFalse(is_user_patient_treating_doctor(self.staff_user, pat_staff_reg))

        # 3. Staff user cannot toggle allowance
        res = toggle_doctor_patient_allowance(self.staff_user, pat_staff_reg, "Cottage Patient CT1", room_no="CT-1")
        self.assertEqual(res['status'], 'not_treating_doctor')
    def test_preferred_therapists_gender_filtering_and_validation(self):
        """
        Rule: Only show and assign therapists with the matching gender of the patient.
        Female patient -> Female therapists only.
        Male patient -> Male therapists only.
        """
        # Create Female patient
        fem_reg = "90009"
        Repeated_Visitors.objects.update_or_create(
            register_number=90009,
            defaults={"patient_name": "Female VIP Patient", "total_visits": 3, "is_vip": True}
        )
        fem_snap, _ = PatientSnapshot.objects.get_or_create(
            pat_reg_no=fem_reg,
            defaults={"pat_name": "Female VIP Patient", "pat_sex": "Female", "pat_age": "40"}
        )
        # Link doc_user as treating doctor
        TherapyAllocation.objects.create(
            patient=fem_snap,
            therapy_code="TH_FEM",
            allocated_by=self.doc_user,
            from_date=timezone.now().date(),
            to_date=timezone.now().date(),
            days=1
        )
        # Allow female patient
        allow_res = toggle_doctor_patient_allowance(self.doc_user, fem_reg)
        self.assertTrue(allow_res['is_allowed'])

        # Female therapists
        fem_t1, _ = TherapistMaster.objects.get_or_create(
            therapist_code="FEM_T1",
            defaults={"therapist_name": "Female Therapist 1", "therapist_gender": "Female", "employee_code": "EMP_FEM_1", "is_bathing_therapist": True, "is_active": True}
        )
        fem_t2, _ = TherapistMaster.objects.get_or_create(
            therapist_code="FEM_T2",
            defaults={"therapist_name": "Female Therapist 2", "therapist_gender": "Female", "employee_code": "EMP_FEM_2", "is_bathing_therapist": True, "is_active": True}
        )

        # Query therapists with gender filter:
        female_list = get_therapists_with_schedule_info(gender="Female")
        self.assertTrue(all(t['gender'] == 'Female' for t in female_list))

        male_list = get_therapists_with_schedule_info(gender="Male")
        self.assertTrue(all(t['gender'] == 'Male' for t in male_list))

        # Attempt to save Male therapists for Female patient -> must raise ValidationError
        with self.assertRaises(ValidationError) as ctx:
            save_preferred_therapist_roster(
                patient_reg_no=fem_reg,
                therapist_codes=["PREF_T1", "PREF_T2"],  # Male therapists
                primary_bathing_code="PREF_T1",
                secondary_bathing_code="PREF_T2"
            )
        self.assertIn("Only Female therapists can be selected", str(ctx.exception))

        # Saving Female therapists for Female patient -> succeeds
        roster = save_preferred_therapist_roster(
            patient_reg_no=fem_reg,
            therapist_codes=["FEM_T1", "FEM_T2"],
            primary_bathing_code="FEM_T1",
            secondary_bathing_code="FEM_T2"
        )
        self.assertEqual(roster.patient_reg_no, fem_reg)


