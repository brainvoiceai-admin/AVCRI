import pytest
import json
from datetime import date, timedelta, time
from django.utils import timezone
from django.core.exceptions import ValidationError
from django.test import RequestFactory

from masters.models import (
    TherapistGrade, SlotMaster, TherapyMaster, TherapistMaster,
    TherapistPreferenceConfig, get_doctor_monthly_quota, get_max_preferred_therapists
)
from Patient.models import TreatmentRoom, RoomName, TherapistBooking, Therapist
from Sheduling.models import (
    PatientSnapshot, TherapyAllocation, Booking, BookingAssignment,
    DoctorPatientPreferenceAllowance, PatientPreferredTherapistRoster
)
from authentication.models import CustomUser
from Sheduling.preferred_therapist_service import (
    toggle_doctor_patient_allowance,
    save_preferred_therapist_roster,
    reassign_patient_upcoming_bookings_with_roster
)
from Sheduling.views import therapy_entry


@pytest.fixture
def config_setup():
    grade, _ = TherapistGrade.objects.get_or_create(name="Senior Therapist", defaults={"display_order": 1})
    slot, _ = SlotMaster.objects.get_or_create(
        slot_time=time(10, 0),
        defaults={"slot_name": "Slot 1: 10:00 AM", "slot_number": 1, "is_active": True}
    )
    rn, _ = RoomName.objects.get_or_create(name="0014")
    room, _ = TreatmentRoom.objects.get_or_create(room_no="TR-14", defaults={"room_name": rn})
    
    # 3-therapist therapy
    therapy3, _ = TherapyMaster.objects.get_or_create(
        therapy_code="THEB017",
        defaults={
            "therapy_name": "Dhanyamala Dhara (3)",
            "therapy_category": "Medium",
            "therapy_duration": "45",
            "bathing_required": "Yes",
            "treatment_room_required": "Yes",
            "no_of_senior_therapist": 1,
            "no_of_junior_therapist": 1,
            "no_of_trainee_therapist": 1,
            "total_no_of_therapist": 3,
            "is_active": True
        }
    )

    doc_user, _ = CustomUser.objects.get_or_create(
        username="dr_config_test",
        defaults={"first_name": "Config", "last_name": "Doctor", "role": "doctor"}
    )

    therapists = []
    for i in range(1, 10):
        t, _ = TherapistMaster.objects.get_or_create(
            therapist_code=f"THP_TEST_{i}",
            defaults={
                "therapist_name": f"Therapist {i}",
                "therapist_gender": "Female",
                "therapist_grade": grade,
                "is_bathing_therapist": (i <= 3),
                "is_active": True
            }
        )
        therapists.append(t)

    # Ensure clean config
    TherapistPreferenceConfig.objects.all().delete()
    config = TherapistPreferenceConfig.get_config()

    return {
        "config": config,
        "slot": slot,
        "room": room,
        "therapy3": therapy3,
        "doc_user": doc_user,
        "therapists": therapists
    }


@pytest.mark.django_db
def test_therapist_preference_config_master_defaults_and_helpers(config_setup):
    """Test TherapistPreferenceConfig defaults and dynamic getter functions."""
    config = config_setup["config"]
    assert config.doctor_monthly_quota == 5
    assert config.max_preferred_therapists == 7
    assert get_doctor_monthly_quota() == 5
    assert get_max_preferred_therapists() == 7

    # Dynamically change limits
    config.doctor_monthly_quota = 10
    config.max_preferred_therapists = 4
    config.save()

    assert get_doctor_monthly_quota() == 10
    assert get_max_preferred_therapists() == 4


@pytest.mark.django_db
def test_dynamic_doctor_monthly_quota_enforcement(config_setup):
    """Updating doctor_monthly_quota in master immediately restricts or expands doctor allowance."""
    config = config_setup["config"]
    doc_user = config_setup["doc_user"]
    now = timezone.now()

    # Set quota limit to 2 in master
    config.doctor_monthly_quota = 2
    config.save()
    assert get_doctor_monthly_quota() == 2

    # Create 3 patients and active therapy allocations by doc_user (so doc_user is treating doctor)
    for p_id in ["PAT_Q1", "PAT_Q2", "PAT_Q3"]:
        ps = PatientSnapshot.objects.create(pat_reg_no=p_id, pat_name=f"Pat {p_id}")
        TherapyAllocation.objects.create(
            patient=ps,
            therapy_name="Dhanyamala Dhara",
            from_date=date.today(),
            to_date=date.today() + timedelta(days=5),
            days=6,
            allocated_by=doc_user
        )

    therapists = config_setup["therapists"]

    # Allow 1st patient: doctor allows, quota not minused until scheduling assigns therapists
    r1 = toggle_doctor_patient_allowance(doc_user, "PAT_Q1", patient_name="Pat 1")
    assert r1["status"] == "allowed"
    assert r1["quota"]["used"] == 0
    assert r1["quota"]["remaining"] == 2

    # Scheduling assigns therapists for 1st patient -> quota is minused: used=1, remaining=1
    save_preferred_therapist_roster(
        patient_reg_no="PAT_Q1",
        therapist_codes=[therapists[0].therapist_code, therapists[1].therapist_code],
        primary_bathing_code=therapists[0].therapist_code,
        secondary_bathing_code=therapists[1].therapist_code,
        configured_by=doc_user,
    )
    q1 = DoctorPatientPreferenceAllowance.get_monthly_quota()
    assert q1["used"] == 1
    assert q1["remaining"] == 1

    # Allow 2nd patient: doctor allows, quota remains used=1 until assigned
    r2 = toggle_doctor_patient_allowance(doc_user, "PAT_Q2", patient_name="Pat 2")
    assert r2["status"] == "allowed"
    assert r2["quota"]["used"] == 1
    assert r2["quota"]["remaining"] == 1

    # Scheduling assigns therapists for 2nd patient -> quota is minused: used=2, remaining=0
    save_preferred_therapist_roster(
        patient_reg_no="PAT_Q2",
        therapist_codes=[therapists[2].therapist_code, therapists[3].therapist_code],
        primary_bathing_code=therapists[2].therapist_code,
        secondary_bathing_code=therapists[3].therapist_code,
        configured_by=doc_user,
    )
    q2 = DoctorPatientPreferenceAllowance.get_monthly_quota()
    assert q2["used"] == 2
    assert q2["remaining"] == 0

    # 3rd patient should be blocked by the quota of 2
    r3 = toggle_doctor_patient_allowance(doc_user, "PAT_Q3", patient_name="Pat 3")
    assert r3["status"] == "quota_exceeded"
    assert "limit of 2 patients" in r3["error"]

    # Now increase quota in master to 5
    config.doctor_monthly_quota = 5
    config.save()

    # Now 3rd patient succeeds!
    r3_retry = toggle_doctor_patient_allowance(doc_user, "PAT_Q3", patient_name="Pat 3")
    assert r3_retry["status"] == "allowed"
    assert r3_retry["quota"]["used"] == 2
    assert r3_retry["quota"]["remaining"] == 3

    # When scheduling assigns therapists to 3rd patient, used becomes 3, remaining becomes 2
    save_preferred_therapist_roster(
        patient_reg_no="PAT_Q3",
        therapist_codes=[therapists[4].therapist_code, therapists[5].therapist_code],
        primary_bathing_code=therapists[4].therapist_code,
        secondary_bathing_code=therapists[5].therapist_code,
        configured_by=doc_user,
    )
    q3 = DoctorPatientPreferenceAllowance.get_monthly_quota()
    assert q3["used"] == 3
    assert q3["remaining"] == 2


@pytest.mark.django_db
def test_dynamic_max_preferred_therapists_limit_enforcement(config_setup):
    """Updating max_preferred_therapists in master immediately adjusts max allowed therapist selection."""
    config = config_setup["config"]
    doc_user = config_setup["doc_user"]
    therapists = config_setup["therapists"]

    # Set max limit to 3 in master
    config.max_preferred_therapists = 3
    config.save()
    assert get_max_preferred_therapists() == 3

    # Allow patient
    ps = PatientSnapshot.objects.create(pat_reg_no="PAT_LIMIT_TEST", pat_name="Limit Patient", pat_sex="Female")
    TherapyAllocation.objects.create(
        patient=ps,
        therapy_name="Dhanyamala Dhara",
        from_date=date.today(),
        to_date=date.today() + timedelta(days=5),
        days=6,
        allocated_by=doc_user
    )
    toggle_doctor_patient_allowance(doc_user, "PAT_LIMIT_TEST", patient_name="Limit Patient")

    # Attempting to save 4 therapists should raise ValidationError
    codes_4 = [t.therapist_code for t in therapists[:4]]
    with pytest.raises(ValidationError) as exc:
        save_preferred_therapist_roster(
            patient_reg_no="PAT_LIMIT_TEST",
            therapist_codes=codes_4,
            primary_bathing_code=codes_4[0],
            secondary_bathing_code=codes_4[1],
            configured_by=doc_user
        )
    assert "maximum of 3 preferred therapists" in str(exc.value)

    # Saving 3 therapists succeeds
    codes_3 = [t.therapist_code for t in therapists[:3]]
    roster = save_preferred_therapist_roster(
        patient_reg_no="PAT_LIMIT_TEST",
        therapist_codes=codes_3,
        primary_bathing_code=codes_3[0],
        secondary_bathing_code=codes_3[1],
        configured_by=doc_user
    )
    assert len(roster.therapist_codes) == 3


@pytest.mark.django_db
def test_backend_double_click_deduplication(config_setup):
    """Double-clicking or repeating allocate request within 15s safely deduplicates without duplicating allocations."""
    slot = config_setup["slot"]
    room = config_setup["room"]
    therapy3 = config_setup["therapy3"]
    doc_user = config_setup["doc_user"]

    tomorrow = date.today() + timedelta(days=1)
    to_date = tomorrow + timedelta(days=6)

    factory = RequestFactory()
    payload = {
        "patient_reg_no": "PAT_DEDUP_001",
        "patient_name": "Dedup Test Patient",
        "patient_room_no": "TR-14",
        "patient_sex": "Female",
        "patient_age": 45,
        "therapy_code": therapy3.therapy_code,
        "therapy_name": therapy3.therapy_name,
        "timeslot": slot.slot_time.strftime("%H:%M"),
        "from_date": tomorrow.isoformat(),
        "to_date": to_date.isoformat(),
        "is_vip": True
    }

    # First request
    req1 = factory.post(
        "/therapy-entry/?action=allocate",
        data=json.dumps(payload),
        content_type="application/json"
    )
    req1.user = doc_user
    resp1 = therapy_entry(req1)
    assert resp1.status_code == 201
    data1 = json.loads(resp1.content.decode("utf-8"))
    assert data1["status"] == "ok"
    alloc_id_1 = data1["allocation_id"]

    # Verify 1 allocation created
    assert TherapyAllocation.objects.filter(patient__pat_reg_no="PAT_DEDUP_001").count() == 1

    # Second request immediately (simulating double click)
    req2 = factory.post(
        "/therapy-entry/?action=allocate",
        data=json.dumps(payload),
        content_type="application/json"
    )
    req2.user = doc_user
    resp2 = therapy_entry(req2)
    assert resp2.status_code == 200
    data2 = json.loads(resp2.content.decode("utf-8"))
    assert data2["status"] == "ok"
    assert data2.get("deduplicated") is True
    assert data2["allocation_id"] == alloc_id_1

    # Total allocations must STILL be 1, never 2!
    assert TherapyAllocation.objects.filter(patient__pat_reg_no="PAT_DEDUP_001").count() == 1


@pytest.mark.django_db
def test_multi_therapist_reassignment_excludes_cancelled_allocations(config_setup):
    """
    Dhanyamala Dhara (3) requires 3 therapists.
    When duplicate allocation was cancelled:
    - Cancelled allocation must NOT be rescheduled or collide.
    - Active allocation must receive all 3 preferred therapists from the roster.
    """
    slot = config_setup["slot"]
    room = config_setup["room"]
    therapy3 = config_setup["therapy3"]
    doc_user = config_setup["doc_user"]
    t1, t2, t3, t4, t5, *_ = config_setup["therapists"]

    tomorrow = date.today() + timedelta(days=1)
    to_date = tomorrow + timedelta(days=6)

    pat = PatientSnapshot.objects.create(
        pat_reg_no="PAT_MULTI_3",
        pat_name="Multi Therapist Patient",
        pat_sex="Female",
        pat_age=55,
        is_vip=True,
        pat_room_no="105"
    )

    # Active allocation
    alloc_active = TherapyAllocation.objects.create(
        patient=pat,
        therapy_name=therapy3.therapy_name,
        therapy_code=therapy3.therapy_code,
        timeslot=slot,
        room=room,
        from_date=tomorrow,
        to_date=to_date,
        days=7,
        status="allocated",
        is_vip=True
    )
    # Active booking for tomorrow
    bk_active = Booking.objects.create(
        allocation=alloc_active,
        date=tomorrow,
        timeslot=slot,
        status="scheduled",
        is_vip=True
    )
    # Active booking for next week (draft)
    bk_draft = Booking.objects.create(
        allocation=alloc_active,
        date=tomorrow + timedelta(days=2),
        timeslot=slot,
        status="draft",
        is_vip=True
    )

    # Duplicate cancelled allocation
    alloc_cancelled = TherapyAllocation.objects.create(
        patient=pat,
        therapy_name=therapy3.therapy_name,
        therapy_code=therapy3.therapy_code,
        timeslot=slot,
        room=room,
        from_date=tomorrow,
        to_date=to_date,
        days=7,
        status="cancelled",
        is_vip=True
    )
    bk_canc = Booking.objects.create(
        allocation=alloc_cancelled,
        date=tomorrow,
        timeslot=slot,
        status="cancelled",
        is_vip=True
    )
    # Stale booking assignment on cancelled
    th5, _ = Therapist.objects.get_or_create(therapist_code=t5.therapist_code)
    BookingAssignment.objects.create(booking=bk_canc, therapist=th5, status="assigned", booking_date=tomorrow, booking_timeslot=slot)
    TherapistBooking.objects.create(
        therapist=t5, date=tomorrow, time_slot=slot, therapy_name=therapy3.therapy_name,
        patient_id=pat.id, visit=alloc_cancelled, is_bathing=False, status="BOOKED"
    )

    # Configure preference roster: t1 (Primary Bathing), t2 (Secondary), t3, t4
    DoctorPatientPreferenceAllowance.objects.create(
        doctor=doc_user,
        patient_reg_no=pat.pat_reg_no,
        year=date.today().year,
        month=date.today().month,
        is_active=True
    )
    save_preferred_therapist_roster(
        patient_reg_no=pat.pat_reg_no,
        therapist_codes=[t1.therapist_code, t2.therapist_code, t3.therapist_code, t4.therapist_code],
        primary_bathing_code=t1.therapist_code,
        secondary_bathing_code=t2.therapist_code,
        configured_by=doc_user
    )

    # 1. Active allocation must have all 3 therapists assigned!
    active_tbs = TherapistBooking.objects.filter(visit=alloc_active, date=tomorrow, status="BOOKED")
    assert active_tbs.count() == 3, f"Expected 3 therapists for {therapy3.therapy_name}, got {active_tbs.count()}"
    active_codes = set(tb.therapist.therapist_code for tb in active_tbs)
    assert active_codes == {t1.therapist_code, t2.therapist_code, t3.therapist_code}

    # Primary bathing must be t1
    bathing_tbs = [tb for tb in active_tbs if tb.is_bathing]
    assert len(bathing_tbs) == 1
    assert bathing_tbs[0].therapist.therapist_code == t1.therapist_code

    # 2. Cancelled allocation must have ZERO therapist bookings and remain cancelled
    cancelled_tbs = TherapistBooking.objects.filter(visit=alloc_cancelled, date=tomorrow)
    assert cancelled_tbs.count() == 0
    bk_canc.refresh_from_db()
    assert bk_canc.status == "cancelled"

    # 3. Draft booking for future unrun date must remain draft
    bk_draft.refresh_from_db()
    assert bk_draft.status == "draft"
