import pytest
from datetime import date, timedelta
from unittest.mock import patch
from django.utils import timezone
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError

from masters.models import (
    TherapistMaster,
    TherapistGrade,
    TherapistPreferenceConfig,
    get_doctor_monthly_quota,
    get_max_preferred_therapists,
)
from Sheduling.models import (
    DoctorPatientPreferenceAllowance,
    PatientPreferredTherapistRoster,
    PatientSnapshot,
    TherapyAllocation,
)
from Sheduling.preferred_therapist_service import (
    toggle_doctor_patient_allowance,
    save_preferred_therapist_roster,
    get_active_preferred_roster,
)

User = get_user_model()


@pytest.fixture
def team_setup(db):
    """Set up doctors, therapists, and configuration."""
    TherapistPreferenceConfig.objects.all().delete()
    config = TherapistPreferenceConfig.objects.create(
        name="Team Config",
        doctor_monthly_quota=5,
        max_preferred_therapists=7,
        is_active=True,
    )

    doc_a = User.objects.create_user(username="dr_arun", password="password", role="doctor")
    doc_b = User.objects.create_user(username="dr_bhavna", password="password", role="doctor")

    grade, _ = TherapistGrade.objects.get_or_create(name="Senior Therapist")

    therapists = []
    for i in range(1, 15):
        t, _ = TherapistMaster.objects.get_or_create(
            therapist_code=f"TH_TEAM_{i}",
            defaults={
                "therapist_name": f"Therapist {i}",
                "therapist_gender": "Female",
                "therapist_grade": grade,
                "is_bathing_therapist": True,
                "is_active": True,
            }
        )
        therapists.append(t)

    return {
        "config": config,
        "doc_a": doc_a,
        "doc_b": doc_b,
        "therapists": therapists,
    }


@pytest.mark.django_db
def test_hospital_shared_doctor_team_quota(team_setup):
    """
    Test 1: Total quota is 5 for the whole doctor team.
    If Dr. A uses 1, only 4 remain for Dr. B and all doctors.
    """
    doc_a = team_setup["doc_a"]
    doc_b = team_setup["doc_b"]
    now = timezone.now()

    # Initial quota: 0 used, 5 remaining
    q_init = DoctorPatientPreferenceAllowance.get_monthly_quota(year=now.year, month=now.month)
    assert q_init["used"] == 0
    assert q_init["remaining"] == 5

    # Dr. A treats patient A1
    p_a1 = PatientSnapshot.objects.create(pat_reg_no="PAT_A1", pat_name="Patient A1", pat_sex="Female")
    TherapyAllocation.objects.create(
        patient=p_a1,
        therapy_name="Dhanyamala Dhara",
        from_date=date.today(),
        to_date=date.today() + timedelta(days=5),
        days=6,
        allocated_by=doc_a,
    )

    therapists = team_setup["therapists"]

    # Dr. A grants preferred allowance
    res_a1 = toggle_doctor_patient_allowance(
        doc_a, "PAT_A1", patient_name="Patient A1", allow_preferred=True, allow_unpreferred=True
    )
    assert res_a1["status"] == "allowed"
    # Quota is NOT minused yet because scheduling has not assigned therapists
    assert res_a1["quota"]["used"] == 0
    assert res_a1["quota"]["remaining"] == 5

    # Scheduling team assigns preferred therapists to PAT_A1
    save_preferred_therapist_roster(
        patient_reg_no="PAT_A1",
        therapist_codes=[therapists[0].therapist_code, therapists[1].therapist_code],
        primary_bathing_code=therapists[0].therapist_code,
        secondary_bathing_code=therapists[1].therapist_code,
        configured_by=doc_a,
    )

    # NOW quota is minused!
    q_after_a1 = DoctorPatientPreferenceAllowance.get_monthly_quota(year=now.year, month=now.month)
    assert q_after_a1["used"] == 1
    assert q_after_a1["remaining"] == 4

    # Dr. B checks quota: Dr. B sees used=1, remaining=4 (SHARED TEAM QUOTA!)
    q_doc_b = DoctorPatientPreferenceAllowance.get_monthly_quota(doc_b, year=now.year, month=now.month)
    assert q_doc_b["used"] == 1
    assert q_doc_b["remaining"] == 4

    # Dr. B treats patient B1 and grants preferred allowance
    p_b1 = PatientSnapshot.objects.create(pat_reg_no="PAT_B1", pat_name="Patient B1", pat_sex="Female")
    TherapyAllocation.objects.create(
        patient=p_b1,
        therapy_name="Dhanyamala Dhara",
        from_date=date.today(),
        to_date=date.today() + timedelta(days=5),
        days=6,
        allocated_by=doc_b,
    )
    res_b1 = toggle_doctor_patient_allowance(
        doc_b, "PAT_B1", patient_name="Patient B1", allow_preferred=True, allow_unpreferred=False
    )
    assert res_b1["status"] == "allowed"
    # Prior to scheduling assignment, quota is still 1 used, 4 remaining
    assert res_b1["quota"]["used"] == 1
    assert res_b1["quota"]["remaining"] == 4

    # Scheduling team assigns preferred therapists to PAT_B1
    save_preferred_therapist_roster(
        patient_reg_no="PAT_B1",
        therapist_codes=[therapists[2].therapist_code, therapists[3].therapist_code],
        primary_bathing_code=therapists[2].therapist_code,
        secondary_bathing_code=therapists[3].therapist_code,
        configured_by=doc_b,
    )

    # NOW quota used becomes 2, remaining becomes 3
    q_after_b1 = DoctorPatientPreferenceAllowance.get_monthly_quota(year=now.year, month=now.month)
    assert q_after_b1["used"] == 2
    assert q_after_b1["remaining"] == 3


@pytest.mark.django_db
def test_unpreferred_allowance_is_unlimited_and_does_not_consume_quota(team_setup):
    """
    Test 2: Unpreferred allowance can be given UNLIMITED.
    Only preferred allowance consumes quota (up to 5).
    Even when preferred quota is 5/5, unpreferred allowance can still be granted.
    """
    doc_a = team_setup["doc_a"]
    now = timezone.now()

    # Fill up the 5 preferred quota slots by allowing and assigning therapists
    for i in range(1, 6):
        reg = f"PAT_FULL_{i}"
        ps = PatientSnapshot.objects.create(pat_reg_no=reg, pat_name=f"Patient {i}", pat_sex="Female")
        TherapyAllocation.objects.create(
            patient=ps,
            therapy_name="Kativasthi",
            from_date=date.today(),
            to_date=date.today() + timedelta(days=5),
            days=6,
            allocated_by=doc_a,
        )
        r = toggle_doctor_patient_allowance(doc_a, reg, allow_preferred=True, allow_unpreferred=False)
        assert r["status"] == "allowed"
        save_preferred_therapist_roster(
            patient_reg_no=reg,
            therapist_codes=[team_setup["therapists"][(i-1)*2].therapist_code, team_setup["therapists"][(i-1)*2 + 1].therapist_code],
            primary_bathing_code=team_setup["therapists"][(i-1)*2].therapist_code,
            secondary_bathing_code=team_setup["therapists"][(i-1)*2 + 1].therapist_code,
            configured_by=doc_a,
        )

    q_full = DoctorPatientPreferenceAllowance.get_monthly_quota(year=now.year, month=now.month)
    assert q_full["used"] == 5
    assert q_full["remaining"] == 0

    # 6th patient: Attempting preferred allowance fails due to quota limit
    p6 = PatientSnapshot.objects.create(pat_reg_no="PAT_FULL_6", pat_name="Patient 6", pat_sex="Female")
    TherapyAllocation.objects.create(
        patient=p6,
        therapy_name="Kativasthi",
        from_date=date.today(),
        to_date=date.today() + timedelta(days=5),
        days=6,
        allocated_by=doc_a,
    )
    r_pref_fail = toggle_doctor_patient_allowance(doc_a, "PAT_FULL_6", allow_preferred=True, allow_unpreferred=False)
    assert r_pref_fail["status"] == "quota_exceeded"

    # BUT granting UNPREFERRED allowance succeeds because it is UNLIMITED!
    r_unpref_ok = toggle_doctor_patient_allowance(doc_a, "PAT_FULL_6", allow_preferred=False, allow_unpreferred=True)
    assert r_unpref_ok["status"] == "allowed"
    assert r_unpref_ok["is_allowed"] is True
    assert r_unpref_ok["allow_preferred"] is False
    assert r_unpref_ok["allow_unpreferred"] is True
    # Quota used remains 5 (not 6)
    assert r_unpref_ok["quota"]["used"] == 5


@pytest.mark.django_db
def test_quota_retention_on_patient_discharge(team_setup):
    """
    Test 3: If a preference-allowed patient gets discharged,
    the quota is retained and automatically released back into the pool.
    """
    doc_a = team_setup["doc_a"]
    now = timezone.now()

    # Patient is active initially
    ps = PatientSnapshot.objects.create(pat_reg_no="PAT_DISCHARGE", pat_name="Discharge Patient", pat_sex="Female")
    TherapyAllocation.objects.create(
        patient=ps,
        therapy_name="Dhanyamala Dhara",
        from_date=date.today(),
        to_date=date.today() + timedelta(days=5),
        days=6,
        allocated_by=doc_a,
    )

    with patch("final_allocation.is_patient_active", return_value=True):
        res = toggle_doctor_patient_allowance(doc_a, "PAT_DISCHARGE", allow_preferred=True, allow_unpreferred=True)
        assert res["status"] == "allowed"

        save_preferred_therapist_roster(
            patient_reg_no="PAT_DISCHARGE",
            therapist_codes=[team_setup["therapists"][0].therapist_code, team_setup["therapists"][1].therapist_code],
            primary_bathing_code=team_setup["therapists"][0].therapist_code,
            secondary_bathing_code=team_setup["therapists"][1].therapist_code,
            configured_by=doc_a,
        )

        q1 = DoctorPatientPreferenceAllowance.get_monthly_quota(year=now.year, month=now.month)
        assert q1["used"] == 1
        assert q1["remaining"] == 4

    # Now the patient is discharged (is_patient_active returns False)
    with patch("final_allocation.is_patient_active", return_value=False):
        # When get_monthly_quota is evaluated, discharged patient quota is released/retained!
        q_after_discharge = DoctorPatientPreferenceAllowance.get_monthly_quota(year=now.year, month=now.month)
        assert q_after_discharge["used"] == 0
        assert q_after_discharge["remaining"] == 5

        # Allowance record has been auto-deactivated
        al = DoctorPatientPreferenceAllowance.objects.get(patient_reg_no="PAT_DISCHARGE")
        assert al.is_active is False
        assert "[Discharge Quota Retained]" in al.notes


@pytest.mark.django_db
def test_roster_validates_separate_preferred_and_unpreferred_permissions(team_setup):
    """
    Test 4: Scheduling team cannot configure preferred therapists if only unpreferred was allowed,
    and cannot configure unpreferred therapists if only preferred was allowed.
    """
    doc_a = team_setup["doc_a"]
    therapists = team_setup["therapists"]

    # Patient with UNPREFERRED ONLY
    ps_unpref = PatientSnapshot.objects.create(pat_reg_no="PAT_UNPREF_ONLY", pat_name="Unpref Only", pat_sex="Female")
    TherapyAllocation.objects.create(
        patient=ps_unpref,
        therapy_name="Dhanyamala Dhara",
        from_date=date.today(),
        to_date=date.today() + timedelta(days=5),
        days=6,
        allocated_by=doc_a,
    )
    toggle_doctor_patient_allowance(doc_a, "PAT_UNPREF_ONLY", allow_preferred=False, allow_unpreferred=True)

    # Attempting to save preferred therapists raises ValidationError
    with pytest.raises(ValidationError, match="not granted Preferred Therapist allowance"):
        save_preferred_therapist_roster(
            patient_reg_no="PAT_UNPREF_ONLY",
            therapist_codes=[therapists[0].therapist_code, therapists[1].therapist_code],
            primary_bathing_code=therapists[0].therapist_code,
            secondary_bathing_code=therapists[1].therapist_code,
            configured_by=doc_a,
        )

    # Saving unpreferred therapists succeeds!
    roster = save_preferred_therapist_roster(
        patient_reg_no="PAT_UNPREF_ONLY",
        unpreferred_codes=[therapists[2].therapist_code],
        configured_by=doc_a,
    )
    assert roster.unpreferred_therapist_codes == [therapists[2].therapist_code]

    # Patient with PREFERRED ONLY
    ps_pref = PatientSnapshot.objects.create(pat_reg_no="PAT_PREF_ONLY", pat_name="Pref Only", pat_sex="Female")
    TherapyAllocation.objects.create(
        patient=ps_pref,
        therapy_name="Dhanyamala Dhara",
        from_date=date.today(),
        to_date=date.today() + timedelta(days=5),
        days=6,
        allocated_by=doc_a,
    )
    toggle_doctor_patient_allowance(doc_a, "PAT_PREF_ONLY", allow_preferred=True, allow_unpreferred=False)

    # Attempting to save unpreferred therapists raises ValidationError
    with pytest.raises(ValidationError, match="not granted Unpreferred Therapist exclusion"):
        save_preferred_therapist_roster(
            patient_reg_no="PAT_PREF_ONLY",
            unpreferred_codes=[therapists[3].therapist_code],
            configured_by=doc_a,
        )


@pytest.mark.django_db
def test_quota_deducted_only_when_scheduling_assigns_therapists(team_setup):
    """
    Test 5: Explicit test for rule:
    'if only the approved patients therapist had been assigned by scheduling team the quota will be minused else the quota will be not minused'
    """
    doc_a = team_setup["doc_a"]
    therapists = team_setup["therapists"]
    now = timezone.now()

    # Step 1: Doctor approves 3 patients for preferred therapist
    for i in range(1, 4):
        reg = f"PAT_PENDING_{i}"
        ps = PatientSnapshot.objects.create(pat_reg_no=reg, pat_name=f"Patient {i}", pat_sex="Female")
        TherapyAllocation.objects.create(
            patient=ps,
            therapy_name="Dhanyamala Dhara",
            from_date=date.today(),
            to_date=date.today() + timedelta(days=5),
            days=6,
            allocated_by=doc_a,
        )
        res = toggle_doctor_patient_allowance(doc_a, reg, allow_preferred=True, allow_unpreferred=True)
        assert res["status"] == "allowed"

    # All 3 patients are approved, BUT scheduling has not assigned therapists yet
    # Quota MUST NOT be minused! used=0, remaining=5!
    q = DoctorPatientPreferenceAllowance.get_monthly_quota(year=now.year, month=now.month)
    assert q["used"] == 0
    assert q["remaining"] == 5

    # Step 2: Scheduling assigns preferred therapists to Patient 1 ONLY
    save_preferred_therapist_roster(
        patient_reg_no="PAT_PENDING_1",
        therapist_codes=[therapists[0].therapist_code, therapists[1].therapist_code],
        primary_bathing_code=therapists[0].therapist_code,
        secondary_bathing_code=therapists[1].therapist_code,
        configured_by=doc_a,
    )

    # NOW quota is minused for Patient 1: used=1, remaining=4
    q1 = DoctorPatientPreferenceAllowance.get_monthly_quota(year=now.year, month=now.month)
    assert q1["used"] == 1
    assert q1["remaining"] == 4

    # Step 3: Scheduling assigns preferred therapists to Patient 2
    save_preferred_therapist_roster(
        patient_reg_no="PAT_PENDING_2",
        therapist_codes=[therapists[2].therapist_code, therapists[3].therapist_code],
        primary_bathing_code=therapists[2].therapist_code,
        secondary_bathing_code=therapists[3].therapist_code,
        configured_by=doc_a,
    )

    # NOW quota used=2, remaining=3
    q2 = DoctorPatientPreferenceAllowance.get_monthly_quota(year=now.year, month=now.month)
    assert q2["used"] == 2
    assert q2["remaining"] == 3

    # Patient 3 is still pending assignment in scheduling -> does not consume quota
    al3 = DoctorPatientPreferenceAllowance.objects.get(patient_reg_no="PAT_PENDING_3")
    assert al3.allow_preferred is True
