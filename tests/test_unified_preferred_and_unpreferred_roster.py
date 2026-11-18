from datetime import date, timedelta
from django.test import TestCase
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.utils import timezone

from authentication.models import CustomUser, DoctorProfile
from masters.models import TherapistMaster, TherapistGrade
from Patient.models import Repeated_Visitors
from Sheduling.models import (
    PatientSnapshot,
    DoctorPatientPreferenceAllowance,
    PatientPreferredTherapistRoster,
    TherapyAllocation,
)
from Sheduling.preferred_therapist_service import (
    toggle_doctor_patient_allowance,
    save_preferred_therapist_roster,
    get_active_preferred_roster,
)
from Sheduling.preference_views import get_active_patient_therapist_preferences

User = get_user_model()


class TestUnifiedPreferredAndUnpreferredRoster(TestCase):
    """
    Tests ensuring unified preferred & unpreferred therapist configuration:
    - Doctor allows patient in My Patients.
    - Scheduling team marks preferred and/or unpreferred therapists.
    - Allocation logic strictly respects unpreferred therapist exclusion.
    """

    @classmethod
    def setUpTestData(cls):
        # 1. Create doctor user
        cls.doc_user = User.objects.create_user(
            username="dr_unpref_test",
            password="password123",
            first_name="Test",
            last_name="Doctor",
            role="doctor"
        )
        DoctorProfile.objects.create(
            user=cls.doc_user,
            doctor_id="DOC_UNPREF_99",
            specialization="Ayurveda",
            department="Panchakarma",
            qualification="BAMS",
            experience_years=10
        )

        # 2. Grades
        cls.grade_senior, _ = TherapistGrade.objects.get_or_create(name="Senior Therapist", defaults={"display_order": 1})
        cls.grade_junior, _ = TherapistGrade.objects.get_or_create(name="Junior Therapist", defaults={"display_order": 2})

        # 3. Female Therapists
        cls.th_p1 = TherapistMaster.objects.create(
            therapist_code="TH_PREF_F1",
            therapist_name="Preferred Female One",
            therapist_gender="Female",
            therapist_grade=cls.grade_senior,
            is_active=True,
            is_bathing_therapist=True
        )
        cls.th_p2 = TherapistMaster.objects.create(
            therapist_code="TH_PREF_F2",
            therapist_name="Preferred Female Two",
            therapist_gender="Female",
            therapist_grade=cls.grade_junior,
            is_active=True,
            is_bathing_therapist=True
        )
        cls.th_unpref = TherapistMaster.objects.create(
            therapist_code="TH_UNPREF_F3",
            therapist_name="Unpreferred Female Three",
            therapist_gender="Female",
            therapist_grade=cls.grade_senior,
            is_active=True,
            is_bathing_therapist=True
        )

        # 4. VIP Patient
        cls.pat_reg = "99001"
        Repeated_Visitors.objects.create(
            register_number=99001,
            is_vip=True,
            total_visits=3
        )
        cls.patient_snapshot = PatientSnapshot.objects.create(
            pat_reg_no=cls.pat_reg,
            pat_name="VIP Patient Preference Test",
            pat_room_no="CT-101",
            pat_sex="Female",
            pat_age="35",
            is_vip=True
        )
        TherapyAllocation.objects.create(
            patient=cls.patient_snapshot,
            therapy_code="TH_TEST",
            allocated_by=cls.doc_user,
            from_date=timezone.now().date(),
            to_date=timezone.now().date(),
            days=1
        )

    def test_workflow_doctor_allows_and_scheduling_marks_preferred_and_unpreferred(self):
        # 1. Doctor allows patient in My Patients
        allow_res = toggle_doctor_patient_allowance(
            doctor_user=self.doc_user,
            patient_reg_no=self.pat_reg,
            patient_name="VIP Patient Preference Test",
            room_no="CT-101"
        )
        print("DEBUG ALLOW_RES:", allow_res)
        self.assertTrue(allow_res.get('is_allowed'))

        # 2. Scheduling team saves roster with both Preferred & Unpreferred therapists
        roster = save_preferred_therapist_roster(
            patient_reg_no=self.pat_reg,
            therapist_codes=[self.th_p1.therapist_code, self.th_p2.therapist_code],
            primary_bathing_code=self.th_p1.therapist_code,
            secondary_bathing_code=self.th_p2.therapist_code,
            unpreferred_codes=[self.th_unpref.therapist_code],
            configured_by=self.doc_user,
            notes="Configured by scheduling team"
        )

        self.assertIsNotNone(roster)
        self.assertEqual(len(roster.therapist_codes), 2)
        self.assertEqual(len(roster.unpreferred_therapist_codes), 1)
        self.assertIn(self.th_unpref.therapist_code, roster.unpreferred_therapist_codes)

        # 3. get_active_preferred_roster returns both preferred & unpreferred codes
        roster_info = get_active_preferred_roster(self.pat_reg)
        self.assertIsNotNone(roster_info)
        self.assertIn(self.th_p1.therapist_code, roster_info['therapist_codes_set'])
        self.assertIn(self.th_unpref.therapist_code, roster_info['unpreferred_codes_set'])

        # 4. get_active_patient_therapist_preferences returns preferences from roster
        pref_codes, unpref_codes = get_active_patient_therapist_preferences(self.pat_reg)
        self.assertIn(self.th_p1.therapist_code, pref_codes)
        self.assertIn(self.th_unpref.therapist_code, unpref_codes)

    def test_overlap_between_preferred_and_unpreferred_is_rejected(self):
        # Patient is allowed
        toggle_doctor_patient_allowance(
            doctor_user=self.doc_user,
            patient_reg_no=self.pat_reg,
            patient_name="VIP Patient Preference Test",
            room_no="CT-101"
        )

        # Try saving same therapist as both preferred and unpreferred
        with self.assertRaises(ValidationError) as cm:
            save_preferred_therapist_roster(
                patient_reg_no=self.pat_reg,
                therapist_codes=[self.th_p1.therapist_code, self.th_p2.therapist_code],
                primary_bathing_code=self.th_p1.therapist_code,
                secondary_bathing_code=self.th_p2.therapist_code,
                unpreferred_codes=[self.th_p1.therapist_code],  # OVERLAP!
                configured_by=self.doc_user
            )
        self.assertIn("cannot be marked as both Preferred and Unpreferred", str(cm.exception))

    def test_saving_only_unpreferred_therapist_without_preferred(self):
        # Patient is allowed
        toggle_doctor_patient_allowance(
            doctor_user=self.doc_user,
            patient_reg_no=self.pat_reg,
            patient_name="VIP Patient Preference Test",
            room_no="CT-101"
        )

        # Save ONLY unpreferred therapist (no preferred pool)
        roster = save_preferred_therapist_roster(
            patient_reg_no=self.pat_reg,
            therapist_codes=[],
            unpreferred_codes=[self.th_unpref.therapist_code],
            configured_by=self.doc_user
        )

        self.assertIsNotNone(roster)
        self.assertEqual(len(roster.therapist_codes), 0)
        self.assertEqual(len(roster.unpreferred_therapist_codes), 1)

        pref_codes, unpref_codes = get_active_patient_therapist_preferences(self.pat_reg)
        self.assertEqual(len(pref_codes), 0)
        self.assertIn(self.th_unpref.therapist_code, unpref_codes)

    def test_male_patient_gender_filtering_and_validation(self):
        # 1. Create Male therapists
        th_m1 = TherapistMaster.objects.create(
            therapist_code="TH_MALE_1",
            therapist_name="Male Therapist One",
            therapist_gender="Male",
            therapist_grade=self.grade_senior,
            is_active=True,
            is_bathing_therapist=True
        )
        th_m2 = TherapistMaster.objects.create(
            therapist_code="TH_MALE_2",
            therapist_name="Male Therapist Two",
            therapist_gender="Male",
            therapist_grade=self.grade_junior,
            is_active=True,
            is_bathing_therapist=True
        )
        th_m_unpref = TherapistMaster.objects.create(
            therapist_code="TH_MALE_UNPREF",
            therapist_name="Male Therapist Unpref",
            therapist_gender="Male",
            therapist_grade=self.grade_senior,
            is_active=True,
            is_bathing_therapist=True
        )

        # 2. Create Male VIP Patient
        male_reg = "99002"
        Repeated_Visitors.objects.create(
            register_number=99002,
            is_vip=True,
            total_visits=2
        )
        male_snap = PatientSnapshot.objects.create(
            pat_reg_no=male_reg,
            pat_name="Male VIP Patient",
            pat_room_no="102",
            pat_sex="Male",
            pat_age="45",
            is_vip=True
        )
        TherapyAllocation.objects.create(
            patient=male_snap,
            therapy_code="TH_TEST_MALE",
            allocated_by=self.doc_user,
            from_date=timezone.now().date(),
            to_date=timezone.now().date(),
            days=1
        )

        # 3. Doctor allows male patient
        toggle_doctor_patient_allowance(
            doctor_user=self.doc_user,
            patient_reg_no=male_reg,
            patient_name="Male VIP Patient",
            room_no="102"
        )

        # 4. Attempting to assign female therapist to male patient preferred roster -> REJECTED
        with self.assertRaises(ValidationError) as cm:
            save_preferred_therapist_roster(
                patient_reg_no=male_reg,
                therapist_codes=[th_m1.therapist_code, self.th_p1.therapist_code],  # th_p1 is Female!
                primary_bathing_code=th_m1.therapist_code,
                secondary_bathing_code=self.th_p1.therapist_code,
                configured_by=self.doc_user
            )
        self.assertIn("Only Male therapists can be selected", str(cm.exception))

        # 5. Attempting to assign female therapist to male patient unpreferred roster -> REJECTED
        with self.assertRaises(ValidationError) as cm2:
            save_preferred_therapist_roster(
                patient_reg_no=male_reg,
                therapist_codes=[th_m1.therapist_code, th_m2.therapist_code],
                primary_bathing_code=th_m1.therapist_code,
                secondary_bathing_code=th_m2.therapist_code,
                unpreferred_codes=[self.th_p1.therapist_code],  # th_p1 is Female!
                configured_by=self.doc_user
            )
        self.assertIn("Only Male therapists can be selected", str(cm2.exception))

        # 6. Valid male therapists assignment (preferred + unpreferred) -> SUCCEEDS
        roster = save_preferred_therapist_roster(
            patient_reg_no=male_reg,
            therapist_codes=[th_m1.therapist_code, th_m2.therapist_code],
            primary_bathing_code=th_m1.therapist_code,
            secondary_bathing_code=th_m2.therapist_code,
            unpreferred_codes=[th_m_unpref.therapist_code],
            configured_by=self.doc_user
        )
        self.assertIsNotNone(roster)
        self.assertEqual(len(roster.therapist_codes), 2)
        self.assertEqual(len(roster.unpreferred_therapist_codes), 1)
        self.assertIn(th_m_unpref.therapist_code, roster.unpreferred_therapist_codes)
