"""
Strict Patient-Therapist Gender Matching Test Suite

Validates that ALL therapist allocation and rescheduling algorithms adhere strictly
to the gender-matching business rules:
1. Male patients (adults and children aged 5 or older) MUST be allocated to MALE therapists.
2. Female patients (of any age, including children and adults) MUST be allocated to FEMALE therapists.
3. THE ONLY EXCEPTION: Male children strictly less than 5 years old (< 5.0) MUST be
   allocated to FEMALE therapists.
4. Strict enforcement: Under NO circumstances (even under therapist shortage, grade substitution,
   continuity override, or emergency reschedule) should an opposite-gender therapist be allocated.
   If a matching-gender therapist is unavailable, the allocation must fail or leave the slot unassigned,
   rather than cross-allocating.

Algorithms tested:
- Gender resolution engine: `final_allocation.resolve_desired_gender`, `reshedule.resolve_desired_gender`,
  `resheduleMorningandNight.normalize_patient_gender`
- Direct therapist allocation: `final_allocation.allocate_therapists`
- End-to-end bulk allocation pipeline: `final_allocation.bulk_allocate_for_date`
- Reschedule allocation engine: `reshedule.allocate_therapists`,
  `reshedule.allocate_therapists_with_grade_substitution`, `reshedule.allocate_therapy_for_visit`
- Emergency morning/night reschedule: `resheduleMorningandNight.available_candidates_by_level_and_bathing`,
  `resheduleMorningandNight.expand_candidates_with_grade_substitution`
"""
import pytest
from datetime import date, time, timedelta
from unittest.mock import patch
from django.test import TestCase

from Sheduling.models import PatientSnapshot, TherapyAllocation, Booking, TherapistContinuityPlan
from masters.models import SlotMaster, TherapistGrade, TherapistMaster, TherapyMaster
from Patient.models import TreatmentRoom, RoomName, TherapistBooking, RoomBooking

from final_allocation import resolve_desired_gender, allocate_therapists, bulk_allocate_for_date
from reshedule import (
    resolve_desired_gender as reshedule_resolve_desired_gender,
    allocate_therapists as reshedule_allocate_therapists,
    allocate_therapists_with_grade_substitution as reshedule_allocate_with_sub,
    allocate_therapy_for_visit as reshedule_allocate_visit,
)
from resheduleMorningandNight import (
    normalize_patient_gender,
    available_candidates_by_level_and_bathing,
    expand_candidates_with_grade_substitution,
)


TARGET_DATE = date(2099, 6, 20)
TARGET_DATE_STR = TARGET_DATE.isoformat()


# ---------------------------------------------------------------------------
# Helpers for master data creation
# ---------------------------------------------------------------------------
def _get_or_create_slot(number, slot_time):
    obj, _ = SlotMaster.objects.get_or_create(
        slot_number=number,
        defaults={"slot_time": slot_time, "is_active": True},
    )
    return obj


def _get_or_create_grade(name, order):
    obj, _ = TherapistGrade.objects.get_or_create(
        name=name,
        defaults={"display_order": order, "is_active": True},
    )
    return obj


def _get_or_create_therapy(code, name, grade_counts, bathing="No"):
    obj, _ = TherapyMaster.objects.get_or_create(
        therapy_code=code,
        defaults={
            "therapy_name": name,
            "therapy_category": "General",
            "therapy_duration": "30",
            "bathing_required": bathing,
            "treatment_room_required": "Yes",
            "no_of_super_senior_therapist": grade_counts.get("super_senior", 0),
            "no_of_senior_therapist": grade_counts.get("senior", 0),
            "no_of_junior_therapist": grade_counts.get("junior", 0),
            "no_of_trainee_therapist": grade_counts.get("trainee", 0),
            "total_no_of_therapist": sum(grade_counts.values()),
            "is_active": True,
        },
    )
    return obj


def _get_or_create_therapist(code, name, gender, grade, emp_code, is_helping=False):
    obj, _ = TherapistMaster.objects.get_or_create(
        therapist_code=code,
        defaults={
            "therapist_name": name,
            "therapist_gender": gender,
            "therapist_grade": grade,
            "employee_code": emp_code,
            "is_bathing_therapist": True,
            "is_helping_therapist": is_helping,
            "is_active": True,
        },
    )
    # Ensure gender is exact
    if obj.therapist_gender != gender:
        obj.therapist_gender = gender
        obj.save(update_fields=["therapist_gender"])
    return obj


def _get_or_create_room(room_no):
    room_name, _ = RoomName.objects.get_or_create(name=f"Room {room_no}", defaults={"is_active": True})
    obj, _ = TreatmentRoom.objects.get_or_create(
        room_no=room_no,
        defaults={"room_name": room_name, "floor": "G", "is_active": True},
    )
    return obj


# ===========================================================================
# 1. Unit Tests: Gender Resolution Rules across modules
# ===========================================================================
class TestGenderResolutionAlgorithm(TestCase):
    """
    Validates resolve_desired_gender and normalize_patient_gender across all variations
    of gender, age, and edge cases.
    """

    def test_female_patients_always_require_female_therapist(self):
        """Female patients of ANY age must resolve to 'female'."""
        female_test_cases = [
            ("Female", "25"),
            ("female", "45"),
            ("F", "70"),
            ("FEMALE", "30 years"),
            ("Female", "0"),
            ("Female", "1"),
            ("Female", "2"),
            ("Female", "4"),
            ("Female", "5"),
            ("Female", "12"),
            ("Female", None),
            ("Female", ""),
            ("Female", "unknown"),
        ]
        for gender, age in female_test_cases:
            res_final = resolve_desired_gender(gender, age)
            res_resh = reshedule_resolve_desired_gender(gender, age)
            res_norm = normalize_patient_gender(gender, age)

            assert res_final == "female", f"final_allocation failed for ({gender}, {age}): got {res_final}"
            assert res_resh == "female", f"reshedule failed for ({gender}, {age}): got {res_resh}"
            assert res_norm == "female", f"resheduleMorningandNight failed for ({gender}, {age}): got {res_norm}"

    def test_male_adults_require_male_therapist(self):
        """Male adult patients (age >= 5 or default) must resolve to 'male'."""
        male_adult_cases = [
            ("Male", "25"),
            ("male", "30"),
            ("M", "60"),
            ("MALE", "45 years"),
            ("Male", None),
            ("Male", ""),
            ("Male", "unknown"),
        ]
        for gender, age in male_adult_cases:
            res_final = resolve_desired_gender(gender, age)
            res_resh = reshedule_resolve_desired_gender(gender, age)
            res_norm = normalize_patient_gender(gender, age)

            assert res_final == "male", f"final_allocation failed for ({gender}, {age}): got {res_final}"
            assert res_resh == "male", f"reshedule failed for ({gender}, {age}): got {res_resh}"
            assert res_norm == "male", f"resheduleMorningandNight failed for ({gender}, {age}): got {res_norm}"

    def test_male_child_under_5_exception_requires_female_therapist(self):
        """
        THE ONLY EXCEPTION: Male child strictly less than 5 years old (< 5.0)
        MUST resolve to 'female'.
        """
        exception_cases = [
            ("Male", "0"),
            ("Male", "1"),
            ("Male", "2"),
            ("Male", "3"),
            ("Male", "4"),
            ("Male", "4.5"),
            ("Male", "4.9"),
            ("male", "4 years"),
            ("M", "3 yrs"),
            ("Male", 3),
            ("Male", 4.0),
        ]
        for gender, age in exception_cases:
            res_final = resolve_desired_gender(gender, age)
            res_resh = reshedule_resolve_desired_gender(gender, age)
            res_norm = normalize_patient_gender(gender, age)

            assert res_final == "female", (
                f"EXCEPTION FAILURE: Male child age {age} should resolve to 'female', "
                f"got {res_final} (final), {res_resh} (resh), {res_norm} (norm)"
            )

    def test_male_child_5_or_above_is_not_an_exception(self):
        """
        Male child aged 5 or above (>= 5.0) is NOT an exception and
        MUST resolve to 'male'.
        """
        boundary_cases = [
            ("Male", "5"),
            ("Male", "5.0"),
            ("Male", "5 years"),
            ("Male", 5),
            ("Male", "6"),
            ("Male", "8"),
            ("Male", "12"),
            ("male", "15 years"),
        ]
        for gender, age in boundary_cases:
            res_final = resolve_desired_gender(gender, age)
            res_resh = reshedule_resolve_desired_gender(gender, age)
            res_norm = normalize_patient_gender(gender, age)

            assert res_final == "male", (
                f"BOUNDARY FAILURE: Male child age {age} (>= 5) should resolve to 'male', "
                f"got {res_final} (final), {res_resh} (resh), {res_norm} (norm)"
            )


# ===========================================================================
# 2. Test Class: Direct Allocation Algorithm (final_allocation.allocate_therapists)
# ===========================================================================
@pytest.mark.django_db(transaction=True)
class TestDirectAllocationGenderMatching(TestCase):
    """
    Tests direct therapist allocation in final_allocation.allocate_therapists
    under various conditions including mixed pools, shortages, continuity, and helping fallbacks.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.slot1 = _get_or_create_slot(101, time(7, 0))
        cls.slot2 = _get_or_create_slot(102, time(8, 0))
        cls.grade_senior = _get_or_create_grade("Senior Therapist", 2)
        cls.grade_junior = _get_or_create_grade("Junior Therapist", 3)

        cls.therapy_single_senior = _get_or_create_therapy(
            "T_GNDR_1S", "Single Senior Test Therapy", {"senior": 1}
        )
        cls.therapy_multi = _get_or_create_therapy(
            "T_GNDR_MULTI", "Multi Therapist Test Therapy", {"senior": 1, "junior": 1}
        )

        # Primary Therapists
        cls.th_male_sr1 = _get_or_create_therapist("TH_M_SR1", "Male Senior 1", "Male", cls.grade_senior, "EMP_M_SR1")
        cls.th_male_sr2 = _get_or_create_therapist("TH_M_SR2", "Male Senior 2", "Male", cls.grade_senior, "EMP_M_SR2")
        cls.th_male_jr1 = _get_or_create_therapist("TH_M_JR1", "Male Junior 1", "Male", cls.grade_junior, "EMP_M_JR1")

        cls.th_fem_sr1 = _get_or_create_therapist("TH_F_SR1", "Female Senior 1", "Female", cls.grade_senior, "EMP_F_SR1")
        cls.th_fem_sr2 = _get_or_create_therapist("TH_F_SR2", "Female Senior 2", "Female", cls.grade_senior, "EMP_F_SR2")
        cls.th_fem_jr1 = _get_or_create_therapist("TH_F_JR1", "Female Junior 1", "Female", cls.grade_junior, "EMP_F_JR1")

        # Helping Therapists
        cls.th_male_help = _get_or_create_therapist("TH_M_HELP", "Male Helper", "Male", cls.grade_senior, "EMP_M_HELP", is_helping=True)
        cls.th_fem_help = _get_or_create_therapist("TH_F_HELP", "Female Helper", "Female", cls.grade_senior, "EMP_F_HELP", is_helping=True)

    def tearDown(self):
        TherapistBooking.objects.filter(date=TARGET_DATE).delete()

    def test_allocate_male_adult_assigns_male_therapist(self):
        """Male adult patient (age 30) must be allocated ONLY Male therapist(s)."""
        reqs = {"senior": 1}
        allocated = allocate_therapists(
            date=TARGET_DATE,
            time_slot=self.slot1,
            therapy_requirements=reqs,
            patient_gender="Male",
            patient_age="30",
        )
        assert len(allocated) == 1, f"Expected 1 allocated therapist, got {len(allocated)}"
        assert allocated[0].therapist_gender == "Male", (
            f"Male adult allocated to wrong gender: {allocated[0].therapist_gender} ({allocated[0].therapist_code})"
        )

    def test_allocate_female_adult_assigns_female_therapist(self):
        """Female adult patient (age 28) must be allocated ONLY Female therapist(s)."""
        reqs = {"senior": 1}
        allocated = allocate_therapists(
            date=TARGET_DATE,
            time_slot=self.slot1,
            therapy_requirements=reqs,
            patient_gender="Female",
            patient_age="28",
        )
        assert len(allocated) == 1
        assert allocated[0].therapist_gender == "Female", (
            f"Female adult allocated to wrong gender: {allocated[0].therapist_gender} ({allocated[0].therapist_code})"
        )

    def test_allocate_female_child_assigns_female_therapist(self):
        """Female child (age 3) must be allocated ONLY Female therapist(s)."""
        reqs = {"senior": 1}
        allocated = allocate_therapists(
            date=TARGET_DATE,
            time_slot=self.slot1,
            therapy_requirements=reqs,
            patient_gender="Female",
            patient_age="3",
        )
        assert len(allocated) == 1
        assert allocated[0].therapist_gender == "Female", (
            f"Female child allocated to wrong gender: {allocated[0].therapist_gender} ({allocated[0].therapist_code})"
        )

    def test_allocate_male_child_under_5_assigns_female_therapist(self):
        """Male child < 5 (age 4) must be allocated ONLY Female therapist(s) (exception rule)."""
        reqs = {"senior": 1}
        allocated = allocate_therapists(
            date=TARGET_DATE,
            time_slot=self.slot1,
            therapy_requirements=reqs,
            patient_gender="Male",
            patient_age="4",
        )
        assert len(allocated) == 1
        assert allocated[0].therapist_gender == "Female", (
            f"Male child < 5 MUST be allocated to Female therapist, got: {allocated[0].therapist_gender} ({allocated[0].therapist_code})"
        )

    def test_allocate_male_child_5_or_above_assigns_male_therapist(self):
        """Male child >= 5 (age 5) must be allocated ONLY Male therapist(s)."""
        reqs = {"senior": 1}
        allocated = allocate_therapists(
            date=TARGET_DATE,
            time_slot=self.slot1,
            therapy_requirements=reqs,
            patient_gender="Male",
            patient_age="5",
        )
        assert len(allocated) == 1
        assert allocated[0].therapist_gender == "Male", (
            f"Male child age 5 MUST be allocated to Male therapist, got: {allocated[0].therapist_gender} ({allocated[0].therapist_code})"
        )

    def test_multi_therapist_all_assigned_match_gender(self):
        """When therapy requires multiple therapists, EVERY assigned therapist must match gender rule."""
        reqs = {"senior": 1, "junior": 1}

        # Case 1: Male adult -> all Male
        allocated_m = allocate_therapists(
            date=TARGET_DATE,
            time_slot=self.slot1,
            therapy_requirements=reqs,
            patient_gender="Male",
            patient_age="35",
        )
        assert len(allocated_m) == 2
        for t in allocated_m:
            assert t.therapist_gender == "Male", f"Multi-therapist male patient got {t.therapist_gender}"

        # Case 2: Male child < 5 -> all Female
        allocated_child = allocate_therapists(
            date=TARGET_DATE,
            time_slot=self.slot2,
            therapy_requirements=reqs,
            patient_gender="Male",
            patient_age="3",
        )
        assert len(allocated_child) == 2
        for t in allocated_child:
            assert t.therapist_gender == "Female", f"Multi-therapist male child < 5 got {t.therapist_gender}"

    def test_strictness_no_cross_gender_when_matching_pool_exhausted(self):
        """
        STRICT MATCHING: When matching gender therapists are unavailable (e.g. all male therapists booked),
        the allocator must NOT assign opposite gender therapists even if female therapists are completely free.
        """
        # Book all male primary therapists (seniors and junior) at slot1
        TherapistBooking.objects.create(
            therapist=self.th_male_sr1, date=TARGET_DATE, time_slot=self.slot1, status="BOOKED"
        )
        TherapistBooking.objects.create(
            therapist=self.th_male_sr2, date=TARGET_DATE, time_slot=self.slot1, status="BOOKED"
        )
        TherapistBooking.objects.create(
            therapist=self.th_male_jr1, date=TARGET_DATE, time_slot=self.slot1, status="BOOKED"
        )

        reqs = {"senior": 1}
        # Female therapists are completely free at slot1, but patient is Male adult
        allocated = allocate_therapists(
            date=TARGET_DATE,
            time_slot=self.slot1,
            therapy_requirements=reqs,
            patient_gender="Male",
            patient_age="40",
            allow_helping_fallback=False,
        )
        # MUST NOT assign female therapist!
        assert len(allocated) == 0, (
            f"Strict gender matching violated: Allocated opposite gender therapist(s): {allocated}"
        )

    def test_strictness_no_cross_gender_female_pool_exhausted(self):
        """
        STRICT MATCHING: When female therapists are all booked,
        the allocator must NOT assign male therapists to a female patient.
        """
        # Book all female primary therapists at slot1
        TherapistBooking.objects.create(
            therapist=self.th_fem_sr1, date=TARGET_DATE, time_slot=self.slot1, status="BOOKED"
        )
        TherapistBooking.objects.create(
            therapist=self.th_fem_sr2, date=TARGET_DATE, time_slot=self.slot1, status="BOOKED"
        )
        TherapistBooking.objects.create(
            therapist=self.th_fem_jr1, date=TARGET_DATE, time_slot=self.slot1, status="BOOKED"
        )

        reqs = {"senior": 1}
        # Male therapists are completely free at slot1, but patient is Female
        allocated = allocate_therapists(
            date=TARGET_DATE,
            time_slot=self.slot1,
            therapy_requirements=reqs,
            patient_gender="Female",
            patient_age="30",
            allow_helping_fallback=False,
        )
        # MUST NOT assign male therapist!
        assert len(allocated) == 0, (
            f"Strict gender matching violated: Allocated male therapist to female patient: {allocated}"
        )

    def test_strictness_no_cross_gender_male_child_under_5_when_female_pool_exhausted(self):
        """
        STRICT MATCHING: For male child < 5 (requires female therapist),
        when all female therapists are booked, allocator must NOT assign male therapists.
        """
        # Book all female primary therapists at slot1
        TherapistBooking.objects.create(
            therapist=self.th_fem_sr1, date=TARGET_DATE, time_slot=self.slot1, status="BOOKED"
        )
        TherapistBooking.objects.create(
            therapist=self.th_fem_sr2, date=TARGET_DATE, time_slot=self.slot1, status="BOOKED"
        )
        TherapistBooking.objects.create(
            therapist=self.th_fem_jr1, date=TARGET_DATE, time_slot=self.slot1, status="BOOKED"
        )

        reqs = {"senior": 1}
        # Male therapists are free, but patient is Male child age 3 (needs female)
        allocated = allocate_therapists(
            date=TARGET_DATE,
            time_slot=self.slot1,
            therapy_requirements=reqs,
            patient_gender="Male",
            patient_age="3",
            allow_helping_fallback=False,
        )
        assert len(allocated) == 0, (
            f"Strict gender matching violated: Male child < 5 was allocated male therapist: {allocated}"
        )

    def test_helping_therapist_fallback_strictly_respects_gender(self):
        """
        When primary therapists are exhausted and helping fallback triggers,
        helping therapists of the opposite gender must NEVER be assigned.
        """
        # Book all male primary therapists (seniors and junior)
        TherapistBooking.objects.create(
            therapist=self.th_male_sr1, date=TARGET_DATE, time_slot=self.slot1, status="BOOKED"
        )
        TherapistBooking.objects.create(
            therapist=self.th_male_sr2, date=TARGET_DATE, time_slot=self.slot1, status="BOOKED"
        )
        TherapistBooking.objects.create(
            therapist=self.th_male_jr1, date=TARGET_DATE, time_slot=self.slot1, status="BOOKED"
        )

        reqs = {"senior": 1}
        # Male patient: Female helper and female primaries free, male helper free
        allocated = allocate_therapists(
            date=TARGET_DATE,
            time_slot=self.slot1,
            therapy_requirements=reqs,
            patient_gender="Male",
            patient_age="30",
            allow_helping_fallback=True,
        )
        assert len(allocated) == 1
        assert allocated[0].therapist_code == self.th_male_help.therapist_code
        assert allocated[0].therapist_gender == "Male"

    def test_strict_rejection_of_wrong_gender_continuity_therapist(self):
        """
        If last_therapists contains an opposite-gender therapist (e.g. from prior bad data),
        allocate_therapists MUST reject it and not assign it.
        """
        reqs = {"senior": 1}
        # Female patient, but last_therapists specifies Male therapist
        allocated = allocate_therapists(
            date=TARGET_DATE,
            time_slot=self.slot1,
            therapy_requirements=reqs,
            last_therapists=[self.th_male_sr1.therapist_code],
            patient_gender="Female",
            patient_age="30",
        )
        # Should allocate Female therapist, NEVER the requested male continuity therapist
        assert len(allocated) == 1
        assert allocated[0].therapist_code != self.th_male_sr1.therapist_code
        assert allocated[0].therapist_gender == "Female"


# ===========================================================================
# 3. Test Class: End-to-End Bulk Allocation Pipeline (final_allocation.bulk_allocate_for_date)
# ===========================================================================
@pytest.mark.django_db(transaction=True)
class TestBulkAllocationGenderMatchingPipeline(TestCase):
    """
    Validates that the complete production bulk allocation pipeline
    strictly assigns therapists matching the gender rules across all patient types simultaneously.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.slot = _get_or_create_slot(201, time(9, 0))
        cls.grade_senior = _get_or_create_grade("Senior Therapist", 2)

        cls.therapy = _get_or_create_therapy(
            "T_GNDR_BULK", "Bulk Allocation Test Therapy", {"senior": 1}
        )

        # 3 Male therapists and 3 Female therapists
        cls.tm1 = _get_or_create_therapist("TH_BLK_M1", "Bulk Male 1", "Male", cls.grade_senior, "EMP_BLK_M1")
        cls.tm2 = _get_or_create_therapist("TH_BLK_M2", "Bulk Male 2", "Male", cls.grade_senior, "EMP_BLK_M2")
        cls.tm3 = _get_or_create_therapist("TH_BLK_M3", "Bulk Male 3", "Male", cls.grade_senior, "EMP_BLK_M3")

        cls.tf1 = _get_or_create_therapist("TH_BLK_F1", "Bulk Female 1", "Female", cls.grade_senior, "EMP_BLK_F1")
        cls.tf2 = _get_or_create_therapist("TH_BLK_F2", "Bulk Female 2", "Female", cls.grade_senior, "EMP_BLK_F2")
        cls.tf3 = _get_or_create_therapist("TH_BLK_F3", "Bulk Female 3", "Female", cls.grade_senior, "EMP_BLK_F3")

        cls.room1 = _get_or_create_room("BLK_R1")
        cls.room2 = _get_or_create_room("BLK_R2")
        cls.room3 = _get_or_create_room("BLK_R3")
        cls.room4 = _get_or_create_room("BLK_R4")
        cls.room5 = _get_or_create_room("BLK_R5")

    def _create_patient_booking(self, reg_no, name, sex, age, room):
        patient = PatientSnapshot.objects.create(
            pat_reg_no=reg_no,
            pat_name=name,
            pat_sex=sex,
            pat_age=age,
        )
        allocation = TherapyAllocation.objects.create(
            patient=patient,
            therapy_code=self.therapy.therapy_code,
            therapy_name=self.therapy.therapy_name,
            from_date=TARGET_DATE,
            to_date=TARGET_DATE + timedelta(days=6),
            days=7,
            timeslot=self.slot,
            room=room,
            required_therapist_roles=[{"role": "senior", "count": 1}],
            status="draft",
        )
        booking = Booking.objects.create(
            allocation=allocation,
            date=TARGET_DATE,
            timeslot=self.slot,
            room=room,
            status="draft",
        )
        return patient, allocation, booking

    @patch("final_allocation.is_patient_active")
    def test_bulk_allocation_all_patient_categories(self, mock_is_active):
        """
        Run bulk allocation with 5 concurrent patients:
        1. Adult Male (age 35) -> must get MALE therapist
        2. Adult Female (age 28) -> must get FEMALE therapist
        3. Female Child (age 3) -> must get FEMALE therapist
        4. Male Child < 5 (age 4) -> must get FEMALE therapist (EXCEPTION)
        5. Male Child >= 5 (age 5) -> must get MALE therapist
        """
        mock_is_active.return_value = True

        pat_m_adult, _, bk_m_adult = self._create_patient_booking("800001", "Adult Male", "Male", "35", self.room1)
        pat_f_adult, _, bk_f_adult = self._create_patient_booking("800002", "Adult Female", "Female", "28", self.room2)
        pat_f_child, _, bk_f_child = self._create_patient_booking("800003", "Female Child", "Female", "3", self.room3)
        pat_m_child_u5, _, bk_m_child_u5 = self._create_patient_booking("800004", "Male Child Under 5", "Male", "4", self.room4)
        pat_m_child_o5, _, bk_m_child_o5 = self._create_patient_booking("800005", "Male Child 5yo", "Male", "5", self.room5)

        # Run bulk allocation pipeline
        result = bulk_allocate_for_date(TARGET_DATE_STR)
        assert result["success"] is True, f"bulk_allocate_for_date failed: {result}"

        # Helper to get booked therapist for patient
        def get_booked_therapists(patient_id):
            return TherapistBooking.objects.filter(
                patient_id=patient_id,
                date=TARGET_DATE,
                status="BOOKED",
            ).select_related("therapist")

        # 1. Adult Male -> Male therapist
        tb_m_adult = get_booked_therapists(pat_m_adult.id)
        assert tb_m_adult.count() == 1, f"Adult Male should have 1 booking, got {tb_m_adult.count()}"
        assert tb_m_adult.first().therapist.therapist_gender == "Male", (
            f"Adult Male got therapist gender {tb_m_adult.first().therapist.therapist_gender}"
        )

        # 2. Adult Female -> Female therapist
        tb_f_adult = get_booked_therapists(pat_f_adult.id)
        assert tb_f_adult.count() == 1
        assert tb_f_adult.first().therapist.therapist_gender == "Female", (
            f"Adult Female got therapist gender {tb_f_adult.first().therapist.therapist_gender}"
        )

        # 3. Female Child -> Female therapist
        tb_f_child = get_booked_therapists(pat_f_child.id)
        assert tb_f_child.count() == 1
        assert tb_f_child.first().therapist.therapist_gender == "Female", (
            f"Female Child got therapist gender {tb_f_child.first().therapist.therapist_gender}"
        )

        # 4. Male Child < 5 -> Female therapist (THE ONLY EXCEPTION)
        tb_m_u5 = get_booked_therapists(pat_m_child_u5.id)
        assert tb_m_u5.count() == 1
        assert tb_m_u5.first().therapist.therapist_gender == "Female", (
            f"EXCEPTION VIOLATION: Male child < 5 MUST have Female therapist, "
            f"got {tb_m_u5.first().therapist.therapist_gender} ({tb_m_u5.first().therapist.therapist_code})"
        )

        # 5. Male Child >= 5 -> Male therapist
        tb_m_o5 = get_booked_therapists(pat_m_child_o5.id)
        assert tb_m_o5.count() == 1
        assert tb_m_o5.first().therapist.therapist_gender == "Male", (
            f"Male child age 5 MUST have Male therapist, "
            f"got {tb_m_o5.first().therapist.therapist_gender} ({tb_m_o5.first().therapist.therapist_code})"
        )

    @patch("final_allocation.is_patient_active")
    def test_bulk_allocation_strictness_fails_booking_rather_than_cross_allocate(self, mock_is_active):
        """
        If NO male therapists are available, a male patient's booking must FAIL,
        and NEVER be cross-allocated to an available female therapist.
        """
        mock_is_active.return_value = True

        # Pre-book all 3 male therapists at slot
        for tm in [self.tm1, self.tm2, self.tm3]:
            TherapistBooking.objects.create(
                therapist=tm, date=TARGET_DATE, time_slot=self.slot, status="BOOKED"
            )

        pat, alloc, bk = self._create_patient_booking("800099", "Strict Male Patient", "Male", "40", self.room1)

        bulk_allocate_for_date(TARGET_DATE_STR)

        bk.refresh_from_db()
        # Booking should be failed due to unavailability, NOT scheduled with a female therapist
        assert bk.status == "failed", f"Booking should have failed, but has status: {bk.status}"
        assert bk.failure_reason != "", "Booking should record failure reason"

        female_bookings_for_male = TherapistBooking.objects.filter(
            patient_id=pat.id,
            date=TARGET_DATE,
            therapist__therapist_gender="Female",
            status="BOOKED",
        )
        assert female_bookings_for_male.count() == 0, (
            "CRITICAL: Male patient was illegally allocated a Female therapist during shortage!"
        )

    def tearDown(self):
        TherapistBooking.objects.filter(date=TARGET_DATE).delete()
        RoomBooking.objects.filter(date=TARGET_DATE).delete()
        TherapistContinuityPlan.objects.filter(date=TARGET_DATE).delete()
        Booking.objects.filter(date=TARGET_DATE).delete()
        TherapyAllocation.objects.filter(therapy_code=self.therapy.therapy_code).delete()
        PatientSnapshot.objects.filter(pat_reg_no__startswith="8000").delete()


# ===========================================================================
# 4. Test Class: Reschedule Allocation Engine (reshedule.py)
# ===========================================================================
@pytest.mark.django_db(transaction=True)
class TestRescheduleAlgorithmGenderMatching(TestCase):
    """
    Validates that the reschedule engine (reshedule.py) enforces strict gender matching
    in allocate_therapists, allocate_therapists_with_grade_substitution, and allocate_therapy_for_visit.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.slot = _get_or_create_slot(301, time(10, 0))
        cls.grade_super_sr = _get_or_create_grade("Super Senior Therapist", 1)
        cls.grade_senior = _get_or_create_grade("Senior Therapist", 2)
        cls.grade_junior = _get_or_create_grade("Junior Therapist", 3)

        cls.therapy = _get_or_create_therapy(
            "T_GNDR_RSH", "Reschedule Test Therapy", {"senior": 1}
        )

        cls.tm_sr = _get_or_create_therapist("TH_RSH_M_SR", "Reschedule Male Sr", "Male", cls.grade_senior, "EMP_RSH_M_SR")
        cls.tm_ssr = _get_or_create_therapist("TH_RSH_M_SSR", "Reschedule Male SuperSr", "Male", cls.grade_super_sr, "EMP_RSH_M_SSR")

        cls.tf_sr = _get_or_create_therapist("TH_RSH_F_SR", "Reschedule Female Sr", "Female", cls.grade_senior, "EMP_RSH_F_SR")
        cls.tf_ssr = _get_or_create_therapist("TH_RSH_F_SSR", "Reschedule Female SuperSr", "Female", cls.grade_super_sr, "EMP_RSH_F_SSR")

        cls.room = _get_or_create_room("RSH_R1")

    def tearDown(self):
        TherapistBooking.objects.filter(date=TARGET_DATE).delete()
        RoomBooking.objects.filter(date=TARGET_DATE).delete()
        Booking.objects.filter(date=TARGET_DATE).delete()
        TherapyAllocation.objects.filter(therapy_code=self.therapy.therapy_code).delete()
        PatientSnapshot.objects.filter(pat_reg_no__startswith="7000").delete()

    def test_reschedule_allocate_therapists_strict_gender(self):
        """reshedule.allocate_therapists respects male, female, and male child < 5 rules."""
        reqs = {"senior": 1}

        # 1. Male adult -> Male
        alloc_m = reshedule_allocate_therapists(
            date=TARGET_DATE, time_slot=self.slot, therapy_requirements=reqs,
            patient_gender="Male", patient_age="30"
        )
        assert len(alloc_m) == 1
        assert alloc_m[0].therapist_gender == "Male"

        # 2. Female adult -> Female
        alloc_f = reshedule_allocate_therapists(
            date=TARGET_DATE, time_slot=self.slot, therapy_requirements=reqs,
            patient_gender="Female", patient_age="30"
        )
        assert len(alloc_f) == 1
        assert alloc_f[0].therapist_gender == "Female"

        # 3. Male child < 5 -> Female (exception)
        alloc_child = reshedule_allocate_therapists(
            date=TARGET_DATE, time_slot=self.slot, therapy_requirements=reqs,
            patient_gender="Male", patient_age="4"
        )
        assert len(alloc_child) == 1
        assert alloc_child[0].therapist_gender == "Female"

        # 4. Male child >= 5 -> Male
        alloc_child_o5 = reshedule_allocate_therapists(
            date=TARGET_DATE, time_slot=self.slot, therapy_requirements=reqs,
            patient_gender="Male", patient_age="5"
        )
        assert len(alloc_child_o5) == 1
        assert alloc_child_o5[0].therapist_gender == "Male"

    def test_reschedule_grade_substitution_strictly_preserves_gender(self):
        """
        When substituting a therapist grade in reshedule.allocate_therapists_with_grade_substitution,
        only substitutes of the MATCHING gender may be used.
        """
        # Block the male senior therapist
        TherapistBooking.objects.create(
            therapist=self.tm_sr, date=TARGET_DATE, time_slot=self.slot, status="BOOKED"
        )

        reqs = {"senior": 1}
        # For a Male patient, Super Senior Male can substitute, but Female Senior/SuperSenior MUST NOT
        alloc = reshedule_allocate_with_sub(
            date=TARGET_DATE,
            time_slot=self.slot,
            therapy_requirements=reqs,
            patient_gender="Male",
            patient_age="30",
        )
        assert len(alloc) == 1
        assert alloc[0].therapist_gender == "Male"
        assert alloc[0].therapist_code == self.tm_ssr.therapist_code

    def test_reschedule_grade_substitution_refuses_cross_gender_when_pool_empty(self):
        """
        When ALL male therapists of all grades are booked, grade substitution MUST NOT
        allocate available female therapists to a male patient.
        """
        # Book all male therapists
        TherapistBooking.objects.create(therapist=self.tm_sr, date=TARGET_DATE, time_slot=self.slot, status="BOOKED")
        TherapistBooking.objects.create(therapist=self.tm_ssr, date=TARGET_DATE, time_slot=self.slot, status="BOOKED")

        reqs = {"senior": 1}
        alloc = reshedule_allocate_with_sub(
            date=TARGET_DATE,
            time_slot=self.slot,
            therapy_requirements=reqs,
            patient_gender="Male",
            patient_age="30",
        )
        assert len(alloc) == 0, f"Grade substitution cross-allocated opposite gender therapist: {alloc}"


# ===========================================================================
# 5. Test Class: Emergency Reschedule Engine (resheduleMorningandNight.py)
# ===========================================================================
@pytest.mark.django_db(transaction=True)
class TestEmergencyRescheduleGenderMatching(TestCase):
    """
    Validates candidate selection and grade substitution in resheduleMorningandNight.py
    strictly enforces desired gender matching.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.slot = _get_or_create_slot(401, time(11, 0))
        cls.grade_senior = _get_or_create_grade("Senior Therapist", 2)
        cls.grade_junior = _get_or_create_grade("Junior Therapist", 3)

        cls.tm_sr = _get_or_create_therapist("TH_EMG_M_SR", "Emg Male Sr", "Male", cls.grade_senior, "EMP_EMG_M_SR")
        cls.tf_sr = _get_or_create_therapist("TH_EMG_F_SR", "Emg Female Sr", "Female", cls.grade_senior, "EMP_EMG_F_SR")

    def tearDown(self):
        TherapistBooking.objects.filter(date=TARGET_DATE).delete()

    def test_available_candidates_strict_gender_filtering(self):
        """available_candidates_by_level_and_bathing returns ONLY requested gender candidates."""
        male_candidates = available_candidates_by_level_and_bathing(
            target_date=TARGET_DATE,
            time_slot=self.slot,
            level=self.grade_senior,
            require_bathing=False,
            desired_gender="male",
        )
        assert len(male_candidates) > 0
        for cand in male_candidates:
            assert cand.therapist_gender == "Male", f"Found non-male candidate: {cand.therapist_gender}"

        fem_candidates = available_candidates_by_level_and_bathing(
            target_date=TARGET_DATE,
            time_slot=self.slot,
            level=self.grade_senior,
            require_bathing=False,
            desired_gender="female",
        )
        assert len(fem_candidates) > 0
        for cand in fem_candidates:
            assert cand.therapist_gender == "Female", f"Found non-female candidate: {cand.therapist_gender}"

    def test_emergency_grade_substitution_preserves_gender(self):
        """expand_candidates_with_grade_substitution strictly limits candidates to desired gender."""
        candidates = expand_candidates_with_grade_substitution(
            target_date=TARGET_DATE,
            time_slot=self.slot,
            old_grade_name="Junior Therapist",
            require_bathing=False,
            desired_gender="male",
            patient_gender="Male",
            em_therapist_ids=set(),
            em_emp_codes=set(),
        )
        for cand in candidates:
            assert cand.therapist_gender == "Male", (
                f"Emergency grade substitution returned wrong gender: {cand.therapist_gender}"
            )
