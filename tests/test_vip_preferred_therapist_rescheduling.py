import pytest
import json
from datetime import date, timedelta, time
from django.utils import timezone

from masters.models import (
    TherapistMaster, TherapistGrade, SlotMaster, TherapyMaster,
    TherapistLeaveMaster
)
from Patient.models import TherapistBooking, Therapist, TreatmentRoom, RoomName
from Sheduling.models import (
    PatientSnapshot, TherapyAllocation, Booking, BookingAssignment,
    DoctorPatientPreferenceAllowance, PatientPreferredTherapistRoster,
    FinalScheduleRun
)
from authentication.models import CustomUser, Module
from Sheduling.preferred_therapist_service import (
    save_preferred_therapist_roster,
    reassign_patient_upcoming_bookings_with_roster,
    get_active_preferred_roster
)
from final_allocation import bulk_allocate_for_date


@pytest.fixture
def base_setup(db):
    grade, _ = TherapistGrade.objects.get_or_create(
        name="Senior Therapist", defaults={"display_order": 1, "is_active": True}
    )
    slot, _ = SlotMaster.objects.get_or_create(
        slot_number=1,
        defaults={
            "slot_time": time(10, 0),
            "slot_name": "Slot 1 (10:00 - 10:45)",
            "is_active": True
        }
    )
    room_name, _ = RoomName.objects.get_or_create(name="TR-3")
    room, _ = TreatmentRoom.objects.get_or_create(
        room_no="TR-3",
        defaults={"room_name": room_name}
    )
    therapy, _ = TherapyMaster.objects.get_or_create(
        therapy_code="TH001",
        defaults={
            "therapy_name": "Dhanyamala Dhara",
            "therapy_category": "General",
            "therapy_duration": "45",
            "bathing_required": "Yes",
            "treatment_room_required": "Yes",
            "no_of_senior_therapist": 2,
            "total_no_of_therapist": 2,
            "is_active": True
        }
    )

    doc_user, _ = CustomUser.objects.get_or_create(
        username="dr_tara",
        defaults={"first_name": "Tara", "last_name": "Jayasri", "role": "doctor"}
    )

    # Create female therapists
    t1, _ = TherapistMaster.objects.get_or_create(
        therapist_code="THP_ADH",
        defaults={
            "therapist_name": "Adhithya",
            "therapist_gender": "Female",
            "therapist_grade": grade,
            "is_bathing_therapist": True,
            "is_active": True
        }
    )
    t2, _ = TherapistMaster.objects.get_or_create(
        therapist_code="THP_AIS",
        defaults={
            "therapist_name": "Aishwarya",
            "therapist_gender": "Female",
            "therapist_grade": grade,
            "is_bathing_therapist": True,
            "is_active": True
        }
    )
    t3, _ = TherapistMaster.objects.get_or_create(
        therapist_code="THP_AJI",
        defaults={
            "therapist_name": "Ajitha",
            "therapist_gender": "Female",
            "therapist_grade": grade,
            "is_bathing_therapist": False,
            "is_active": True
        }
    )
    t4, _ = TherapistMaster.objects.get_or_create(
        therapist_code="THP_BIN",
        defaults={
            "therapist_name": "Bindu",
            "therapist_gender": "Female",
            "therapist_grade": grade,
            "is_bathing_therapist": True,
            "is_active": True
        }
    )

    return {
        "grade": grade,
        "slot": slot,
        "room": room,
        "therapy": therapy,
        "doc_user": doc_user,
        "therapists": [t1, t2, t3, t4]
    }


@pytest.mark.django_db
def test_vip_patient_scheduled_first_and_gets_preferred_therapists(base_setup):
    """
    VIP patient should be scheduled ahead of non-VIP patient and receive
    their preferred therapists even if both patients compete for the same slot.
    """
    slot = base_setup["slot"]
    room = base_setup["room"]
    therapy = base_setup["therapy"]
    doc_user = base_setup["doc_user"]
    t1, t2, t3, t4 = base_setup["therapists"]

    target_date = date.today() + timedelta(days=1)
    target_date_str = target_date.strftime("%Y-%m-%d")

    # 1. VIP Patient
    vip_pat = PatientSnapshot.objects.create(
        pat_reg_no="229082022",
        pat_name="RAJANI SURESH",
        pat_sex="Female",
        pat_age=55,
        is_vip=True,
        pat_room_no="NR-11"
    )
    vip_alloc = TherapyAllocation.objects.create(
        patient=vip_pat,
        therapy_name=therapy.therapy_name,
        therapy_code=therapy.therapy_code,
        timeslot=slot,
        room=room,
        from_date=target_date,
        to_date=target_date,
        days=1,
        is_vip=True,
        allocated_by=doc_user
    )
    vip_bk = Booking.objects.create(
        allocation=vip_alloc,
        date=target_date,
        timeslot=slot,
        status="draft",
        is_vip=True
    )

    # Configure preferred roster for VIP patient: Adhithya (primary) & Aishwarya (secondary)
    DoctorPatientPreferenceAllowance.objects.create(
        doctor=doc_user,
        patient_reg_no=vip_pat.pat_reg_no,
        year=target_date.year,
        month=target_date.month,
        is_active=True
    )
    save_preferred_therapist_roster(
        patient_reg_no=vip_pat.pat_reg_no,
        therapist_codes=[t1.therapist_code, t2.therapist_code, t3.therapist_code],
        primary_bathing_code=t1.therapist_code,
        secondary_bathing_code=t2.therapist_code,
        configured_by=doc_user
    )

    # 2. Non-VIP Patient competing for same date and slot
    non_vip_pat = PatientSnapshot.objects.create(
        pat_reg_no="10001",
        pat_name="Regular Patient",
        pat_sex="Female",
        pat_age=40,
        is_vip=False,
        pat_room_no="101"
    )
    non_vip_alloc = TherapyAllocation.objects.create(
        patient=non_vip_pat,
        therapy_name=therapy.therapy_name,
        therapy_code=therapy.therapy_code,
        timeslot=slot,
        room=room,
        from_date=target_date,
        to_date=target_date,
        days=1,
        is_vip=False,
        allocated_by=doc_user
    )
    non_vip_bk = Booking.objects.create(
        allocation=non_vip_alloc,
        date=target_date,
        timeslot=slot,
        status="draft",
        is_vip=False
    )

    # Run allocation for target_date
    res = bulk_allocate_for_date(target_date_str)
    assert res.get("success") is True or res.get("successful_count", 0) > 0

    vip_bk.refresh_from_db()
    assert vip_bk.status == "scheduled"

    # Verify VIP patient got their preferred therapists (including primary bathing Adhithya)
    vip_tb = TherapistBooking.objects.filter(visit=vip_alloc, date=target_date, status="BOOKED")
    assigned_codes = {tb.therapist.therapist_code for tb in vip_tb}
    assert t1.therapist_code in assigned_codes, f"Expected primary bathing therapist {t1.therapist_code} to be assigned"
    # Bathing therapist must have is_bathing=True
    bathing_tb = vip_tb.filter(is_bathing=True).first()
    assert bathing_tb is not None
    assert bathing_tb.therapist.therapist_code == t1.therapist_code


@pytest.mark.django_db
def test_auto_reassign_tomorrow_bookings_when_preference_changed(base_setup):
    """
    If tomorrow's schedule has already run with old therapists, updating the preference
    today must automatically reassign tomorrow's booking to the new preferred therapists.
    """
    slot = base_setup["slot"]
    room = base_setup["room"]
    therapy = base_setup["therapy"]
    doc_user = base_setup["doc_user"]
    t1, t2, t3, t4 = base_setup["therapists"]

    tomorrow = date.today() + timedelta(days=1)

    vip_pat = PatientSnapshot.objects.create(
        pat_reg_no="999000111",
        pat_name="VIP PATIENT 2",
        pat_sex="Female",
        pat_age=50,
        is_vip=True,
        pat_room_no="CT-2"
    )
    alloc = TherapyAllocation.objects.create(
        patient=vip_pat,
        therapy_name=therapy.therapy_name,
        therapy_code=therapy.therapy_code,
        timeslot=slot,
        room=room,
        from_date=tomorrow,
        to_date=tomorrow,
        days=1,
        is_vip=True
    )
    booking = Booking.objects.create(
        allocation=alloc,
        date=tomorrow,
        timeslot=slot,
        status="scheduled",
        is_vip=True
    )

    # Initially assigned old therapists (e.g. Bindu t4 and Ajitha t3)
    TherapistBooking.objects.create(
        therapist=t4,
        date=tomorrow,
        time_slot=slot,
        therapy_name=therapy.therapy_name,
        patient_id=vip_pat.id,
        visit=alloc,
        is_bathing=True,
        status="BOOKED"
    )
    TherapistBooking.objects.create(
        therapist=t3,
        date=tomorrow,
        time_slot=slot,
        therapy_name=therapy.therapy_name,
        patient_id=vip_pat.id,
        visit=alloc,
        is_bathing=False,
        status="BOOKED"
    )
    th4, _ = Therapist.objects.get_or_create(therapist_code=t4.therapist_code)
    th3, _ = Therapist.objects.get_or_create(therapist_code=t3.therapist_code)
    BookingAssignment.objects.create(booking=booking, therapist=th4, status="assigned", booking_date=tomorrow, booking_timeslot=slot)
    BookingAssignment.objects.create(booking=booking, therapist=th3, status="assigned", booking_date=tomorrow, booking_timeslot=slot)

    # Now, doctor allows and updates preferences TODAY to Adhithya (t1) & Aishwarya (t2)
    DoctorPatientPreferenceAllowance.objects.create(
        doctor=doc_user,
        patient_reg_no=vip_pat.pat_reg_no,
        year=date.today().year,
        month=date.today().month,
        is_active=True
    )

    # Saving roster triggers automatic reassignment of upcoming bookings!
    save_preferred_therapist_roster(
        patient_reg_no=vip_pat.pat_reg_no,
        therapist_codes=[t1.therapist_code, t2.therapist_code],
        primary_bathing_code=t1.therapist_code,
        secondary_bathing_code=t2.therapist_code,
        configured_by=doc_user
    )

    # Verify that tomorrow's booking was auto-reassigned with t1 (Adhithya) & t2 (Aishwarya)!
    updated_tbs = TherapistBooking.objects.filter(visit=alloc, date=tomorrow, status="BOOKED")
    new_assigned_codes = {tb.therapist.therapist_code for tb in updated_tbs}

    assert t1.therapist_code in new_assigned_codes, f"Expected {t1.therapist_code} in {new_assigned_codes}"
    assert t2.therapist_code in new_assigned_codes, f"Expected {t2.therapist_code} in {new_assigned_codes}"
    assert t4.therapist_code not in new_assigned_codes, f"Old therapist {t4.therapist_code} should have been replaced"

    # Check that BookingAssignment records were also updated
    updated_bas = BookingAssignment.objects.filter(booking=booking, status="assigned")
    ba_codes = {ba.therapist.therapist_code for ba in updated_bas}
    assert t1.therapist_code in ba_codes
    assert t2.therapist_code in ba_codes


@pytest.mark.django_db
def test_displace_non_vip_when_vip_preference_is_updated(base_setup):
    """
    If a non-VIP patient was assigned a therapist that the VIP patient newly prefers,
    the non-VIP patient should be displaced to an alternative available therapist,
    giving the VIP patient their newly preferred therapist.
    """
    slot = base_setup["slot"]
    room = base_setup["room"]
    therapy = base_setup["therapy"]
    doc_user = base_setup["doc_user"]
    t1, t2, t3, t4 = base_setup["therapists"]

    tomorrow = date.today() + timedelta(days=1)

    # 1. Non-VIP patient has booked t1 (Adhithya) at tomorrow's slot
    non_vip_pat = PatientSnapshot.objects.create(
        pat_reg_no="NONVIP123",
        pat_name="Non VIP Patient",
        pat_sex="Female",
        pat_age=30,
        is_vip=False,
        pat_room_no="102"
    )
    non_vip_alloc = TherapyAllocation.objects.create(
        patient=non_vip_pat,
        therapy_name=therapy.therapy_name,
        therapy_code=therapy.therapy_code,
        timeslot=slot,
        room=room,
        from_date=tomorrow,
        to_date=tomorrow,
        days=1,
        is_vip=False
    )
    non_vip_bk = Booking.objects.create(
        allocation=non_vip_alloc,
        date=tomorrow,
        timeslot=slot,
        status="scheduled",
        is_vip=False
    )
    TherapistBooking.objects.create(
        therapist=t1,
        date=tomorrow,
        time_slot=slot,
        therapy_name=therapy.therapy_name,
        patient_id=non_vip_pat.id,
        visit=non_vip_alloc,
        is_bathing=False,
        status="BOOKED"
    )
    th1, _ = Therapist.objects.get_or_create(therapist_code=t1.therapist_code)
    BookingAssignment.objects.create(booking=non_vip_bk, therapist=th1, status="assigned", booking_date=tomorrow, booking_timeslot=slot)

    # 2. VIP patient booking for tomorrow currently has t4 (Bindu)
    vip_pat = PatientSnapshot.objects.create(
        pat_reg_no="VIP777888",
        pat_name="VIP PATIENT 3",
        pat_sex="Female",
        pat_age=52,
        is_vip=True,
        pat_room_no="CT-3"
    )
    vip_alloc = TherapyAllocation.objects.create(
        patient=vip_pat,
        therapy_name=therapy.therapy_name,
        therapy_code=therapy.therapy_code,
        timeslot=slot,
        room=room,
        from_date=tomorrow,
        to_date=tomorrow,
        days=1,
        is_vip=True
    )
    vip_bk = Booking.objects.create(
        allocation=vip_alloc,
        date=tomorrow,
        timeslot=slot,
        status="scheduled",
        is_vip=True
    )
    TherapistBooking.objects.create(
        therapist=t4,
        date=tomorrow,
        time_slot=slot,
        therapy_name=therapy.therapy_name,
        patient_id=vip_pat.id,
        visit=vip_alloc,
        is_bathing=True,
        status="BOOKED"
    )
    th4, _ = Therapist.objects.get_or_create(therapist_code=t4.therapist_code)
    BookingAssignment.objects.create(booking=vip_bk, therapist=th4, status="assigned", booking_date=tomorrow, booking_timeslot=slot)

    # 3. Preference for VIP is updated to Primary Bathing: t1 (Adhithya)
    DoctorPatientPreferenceAllowance.objects.create(
        doctor=doc_user,
        patient_reg_no=vip_pat.pat_reg_no,
        year=date.today().year,
        month=date.today().month,
        is_active=True
    )
    save_preferred_therapist_roster(
        patient_reg_no=vip_pat.pat_reg_no,
        therapist_codes=[t1.therapist_code, t2.therapist_code],
        primary_bathing_code=t1.therapist_code,
        secondary_bathing_code=t2.therapist_code,
        configured_by=doc_user
    )

    # 4. Verify VIP patient now has t1 and preferred roster allocated
    vip_tbs = TherapistBooking.objects.filter(visit=vip_alloc, date=tomorrow, status="BOOKED")
    assert vip_tbs.count() == 2, "VIP therapy requires 2 therapists and should have both allocated"
    vip_codes = [tb.therapist.therapist_code for tb in vip_tbs]
    assert t1.therapist_code in vip_codes, "VIP should now have t1 (Adhithya)"

    # 5. Verify non-VIP patient was displaced to an alternative available therapist (e.g. t2 or t3 or t4)
    non_vip_tbs = TherapistBooking.objects.filter(visit=non_vip_alloc, date=tomorrow, status="BOOKED")
    assert non_vip_tbs.count() == 1
    displaced_assigned = non_vip_tbs.first().therapist.therapist_code
    assert displaced_assigned != t1.therapist_code, "Non-VIP must no longer hold t1"


@pytest.mark.django_db
def test_bulk_allocate_preempts_non_vip_for_vip_preferred_therapist(base_setup):
    """
    When non-VIP patient is already allocated VIP's preferred therapist at tomorrow's slot:
    Running bulk allocation for tomorrow must preempt the preferred therapist from non-VIP,
    assign that preferred therapist to the VIP patient (VIP does not fail),
    and allocate a new available therapist to the non-VIP patient.
    """
    slot = base_setup["slot"]
    room = base_setup["room"]
    therapy = base_setup["therapy"]
    doc_user = base_setup["doc_user"]
    t1, t2, t3, t4 = base_setup["therapists"]

    tomorrow = date.today() + timedelta(days=1)
    tomorrow_str = tomorrow.strftime("%Y-%m-%d")

    # 1. Non-VIP patient is already scheduled with t1 (Adhithya)
    non_vip_pat = PatientSnapshot.objects.create(
        pat_reg_no="NONVIP_EXISTING",
        pat_name="Existing Non-VIP Patient",
        pat_sex="Female",
        pat_age=35,
        is_vip=False,
        pat_room_no="105"
    )
    non_vip_alloc = TherapyAllocation.objects.create(
        patient=non_vip_pat,
        therapy_name=therapy.therapy_name,
        therapy_code=therapy.therapy_code,
        timeslot=slot,
        room=room,
        from_date=tomorrow,
        to_date=tomorrow,
        days=1,
        is_vip=False
    )
    non_vip_bk = Booking.objects.create(
        allocation=non_vip_alloc,
        date=tomorrow,
        timeslot=slot,
        status="scheduled",
        is_vip=False
    )
    # Existing booking holding t1
    TherapistBooking.objects.create(
        therapist=t1,
        date=tomorrow,
        time_slot=slot,
        therapy_name=therapy.therapy_name,
        patient_id=non_vip_pat.id,
        visit=non_vip_alloc,
        is_bathing=False,
        status="BOOKED"
    )
    th1, _ = Therapist.objects.get_or_create(therapist_code=t1.therapist_code)
    BookingAssignment.objects.create(
        booking=non_vip_bk,
        therapist=th1,
        status="assigned",
        booking_date=tomorrow,
        booking_timeslot=slot
    )

    # 2. VIP patient needs t1 (preferred) and t2
    vip_pat = PatientSnapshot.objects.create(
        pat_reg_no="VIP_PREEMPT_PAT",
        pat_name="VIP Preempt Patient",
        pat_sex="Female",
        pat_age=45,
        is_vip=True,
        pat_room_no="NR-12"
    )
    room2_name, _ = RoomName.objects.get_or_create(name="TR-4")
    room2, _ = TreatmentRoom.objects.get_or_create(room_no="TR-4", defaults={"room_name": room2_name})

    vip_alloc = TherapyAllocation.objects.create(
        patient=vip_pat,
        therapy_name=therapy.therapy_name,
        therapy_code=therapy.therapy_code,
        timeslot=slot,
        room=room2,
        from_date=tomorrow,
        to_date=tomorrow,
        days=1,
        is_vip=True,
        allocated_by=doc_user
    )
    vip_bk = Booking.objects.create(
        allocation=vip_alloc,
        date=tomorrow,
        timeslot=slot,
        status="draft",
        is_vip=True
    )

    # Configure preferred roster: t1 is preferred
    DoctorPatientPreferenceAllowance.objects.create(
        doctor=doc_user,
        patient_reg_no=vip_pat.pat_reg_no,
        year=tomorrow.year,
        month=tomorrow.month,
        is_active=True
    )
    save_preferred_therapist_roster(
        patient_reg_no=vip_pat.pat_reg_no,
        therapist_codes=[t1.therapist_code, t2.therapist_code, t3.therapist_code],
        primary_bathing_code=t1.therapist_code,
        secondary_bathing_code=t2.therapist_code,
        configured_by=doc_user
    )

    # 3. Run bulk allocation for tomorrow
    res = bulk_allocate_for_date(tomorrow_str)

    # 4. VIP patient must NOT get failed!
    vip_bk.refresh_from_db()
    assert vip_bk.status == "scheduled", f"VIP booking status should be scheduled, got {vip_bk.status} (reason: {vip_bk.failure_reason})"

    # VIP must receive t1 (preempted from non-VIP)
    vip_tbs = TherapistBooking.objects.filter(visit=vip_alloc, date=tomorrow, status="BOOKED")
    vip_assigned_codes = {tb.therapist.therapist_code for tb in vip_tbs}
    assert t1.therapist_code in vip_assigned_codes, f"VIP should have received preferred therapist {t1.therapist_code}"

    # 5. Non-VIP patient must have received a new therapist
    non_vip_bk.refresh_from_db()
    assert non_vip_bk.status == "scheduled"
    non_vip_tbs = TherapistBooking.objects.filter(visit=non_vip_alloc, date=tomorrow, status="BOOKED")
    non_vip_assigned_codes = {tb.therapist.therapist_code for tb in non_vip_tbs}
    assert t1.therapist_code not in non_vip_assigned_codes, f"Non-VIP should no longer have {t1.therapist_code}"
    assert len(non_vip_assigned_codes) == 1, "Non-VIP should have new replacement therapist"


@pytest.mark.django_db
def test_preemption_when_no_alternative_therapist_marks_non_vip_failed_for_rescheduling(base_setup):
    """
    If non-VIP is holding the VIP's preferred therapist, but NO other therapist is available at that slot:
    The preferred therapist must still be rescheduled to the VIP patient (VIP does not fail),
    and the non-VIP booking must be marked as failed/needs rescheduling with a clear failure reason.
    """
    slot = base_setup["slot"]
    room = base_setup["room"]
    therapy = base_setup["therapy"]
    doc_user = base_setup["doc_user"]
    t1, t2, t3, t4 = base_setup["therapists"]

    # Deactivate t2, t3, t4 so ONLY t1 is available
    TherapistMaster.objects.filter(id__in=[t2.id, t3.id, t4.id]).update(is_active=False)

    tomorrow = date.today() + timedelta(days=1)

    # 1-therapist therapy
    therapy_single, _ = TherapyMaster.objects.get_or_create(
        therapy_code="TH_SINGLE",
        defaults={
            "therapy_name": "Single Therapist Therapy",
            "therapy_category": "General",
            "therapy_duration": "45",
            "bathing_required": "No",
            "treatment_room_required": "Yes",
            "no_of_senior_therapist": 1,
            "total_no_of_therapist": 1,
            "is_active": True
        }
    )

    # 1. Non-VIP patient is currently booked with t1
    non_vip_pat = PatientSnapshot.objects.create(
        pat_reg_no="NONVIP_SOLO",
        pat_name="Non-VIP Solo Patient",
        pat_sex="Female",
        pat_age=28,
        is_vip=False,
        pat_room_no="108"
    )
    non_vip_alloc = TherapyAllocation.objects.create(
        patient=non_vip_pat,
        therapy_name=therapy_single.therapy_name,
        therapy_code=therapy_single.therapy_code,
        timeslot=slot,
        room=room,
        from_date=tomorrow,
        to_date=tomorrow,
        days=1,
        is_vip=False
    )
    non_vip_bk = Booking.objects.create(
        allocation=non_vip_alloc,
        date=tomorrow,
        timeslot=slot,
        status="scheduled",
        is_vip=False
    )
    TherapistBooking.objects.create(
        therapist=t1,
        date=tomorrow,
        time_slot=slot,
        therapy_name=therapy_single.therapy_name,
        patient_id=non_vip_pat.id,
        visit=non_vip_alloc,
        status="BOOKED"
    )
    th1, _ = Therapist.objects.get_or_create(therapist_code=t1.therapist_code)
    BookingAssignment.objects.create(
        booking=non_vip_bk,
        therapist=th1,
        status="assigned",
        booking_date=tomorrow,
        booking_timeslot=slot
    )

    # 2. VIP patient needs t1
    from Sheduling.preferred_therapist_service import displace_non_vip_therapist_for_slot
    # Displace non-VIP holding t1
    freed = displace_non_vip_therapist_for_slot(t1, tomorrow, slot)
    assert freed is True

    # Check non-VIP status: because no alternative was active, non-VIP booking is marked failed for rescheduling
    non_vip_bk.refresh_from_db()
    assert non_vip_bk.status == "failed"
    assert "Displaced: Preferred therapist reassigned to VIP patient" in non_vip_bk.failure_reason

    # Verify t1 is now free from non-VIP
    assert not TherapistBooking.objects.filter(therapist=t1, date=tomorrow, time_slot=slot, status="BOOKED").exists()


@pytest.mark.django_db
def test_vip_patient_never_fails_when_preferred_therapist_on_leave(base_setup):
    """
    If a VIP patient's preferred therapist is on leave, the VIP patient must not get marked as failed;
    they should automatically fall back to another available therapist and be scheduled successfully.
    """
    slot = base_setup["slot"]
    room = base_setup["room"]
    therapy = base_setup["therapy"]
    doc_user = base_setup["doc_user"]
    t1, t2, t3, t4 = base_setup["therapists"]

    tomorrow = date.today() + timedelta(days=1)
    tomorrow_str = tomorrow.strftime("%Y-%m-%d")

    # Put t1 (preferred) on leave tomorrow
    TherapistLeaveMaster.objects.create(
        therapist=t1,
        leave_day=tomorrow.weekday(),
        is_active=True
    )

    # VIP Patient prefers t1
    vip_pat = PatientSnapshot.objects.create(
        pat_reg_no="VIP_LEAVE_FALLBACK",
        pat_name="VIP Leave Fallback Patient",
        pat_sex="Female",
        pat_age=60,
        is_vip=True,
        pat_room_no="NR-11"
    )
    vip_alloc = TherapyAllocation.objects.create(
        patient=vip_pat,
        therapy_name=therapy.therapy_name,
        therapy_code=therapy.therapy_code,
        timeslot=slot,
        room=room,
        from_date=tomorrow,
        to_date=tomorrow,
        days=1,
        is_vip=True,
        allocated_by=doc_user
    )
    vip_bk = Booking.objects.create(
        allocation=vip_alloc,
        date=tomorrow,
        timeslot=slot,
        status="draft",
        is_vip=True
    )

    DoctorPatientPreferenceAllowance.objects.create(
        doctor=doc_user,
        patient_reg_no=vip_pat.pat_reg_no,
        year=tomorrow.year,
        month=tomorrow.month,
        is_active=True
    )
    save_preferred_therapist_roster(
        patient_reg_no=vip_pat.pat_reg_no,
        therapist_codes=[t1.therapist_code, t2.therapist_code, t3.therapist_code],
        primary_bathing_code=t1.therapist_code,
        secondary_bathing_code=t2.therapist_code,
        configured_by=doc_user
    )

    # Run allocation
    bulk_allocate_for_date(tomorrow_str)

    # VIP patient must NOT fail!
    vip_bk.refresh_from_db()
    assert vip_bk.status == "scheduled", f"VIP booking should be scheduled, got {vip_bk.status} (reason: {vip_bk.failure_reason})"
    vip_tbs = TherapistBooking.objects.filter(visit=vip_alloc, date=tomorrow, status="BOOKED")
    assert vip_tbs.count() == 2, "VIP therapy must have allocated required therapists"
    assigned_codes = {tb.therapist.therapist_code for tb in vip_tbs}
    assert t1.therapist_code not in assigned_codes, "t1 was on leave and should not be assigned"
    assert t2.therapist_code in assigned_codes, "Secondary preferred therapist t2 should be assigned"


@pytest.mark.django_db
def test_vip_fails_when_preferred_therapist_assigned_to_another_vip(base_setup):
    """
    If a preferred therapist is already assigned to ANOTHER VIP patient at that slot:
    1. The preferred therapist cannot be displaced from the first VIP patient.
    2. The second VIP patient's treatment MUST get marked as failed (not forced onto random non-preferred therapists).
    3. The failure reason must clearly state that preferred therapist is assigned to another VIP patient.
    """
    slot = base_setup["slot"]
    room = base_setup["room"]
    therapy = base_setup["therapy"]
    doc_user = base_setup["doc_user"]
    t1, t2, t3, t4 = base_setup["therapists"]

    tomorrow = date.today() + timedelta(days=1)
    tomorrow_str = tomorrow.strftime("%Y-%m-%d")

    # 1. VIP 1 is scheduled with t1 & t2 at slot
    vip1_pat = PatientSnapshot.objects.create(
        pat_reg_no="VIP_FIRST",
        pat_name="First VIP Patient",
        pat_sex="Female",
        pat_age=50,
        is_vip=True,
        pat_room_no="101"
    )
    vip1_alloc = TherapyAllocation.objects.create(
        patient=vip1_pat,
        therapy_name=therapy.therapy_name,
        therapy_code=therapy.therapy_code,
        timeslot=slot,
        room=room,
        from_date=tomorrow,
        to_date=tomorrow,
        days=1,
        is_vip=True,
        allocated_by=doc_user
    )
    vip1_bk = Booking.objects.create(
        allocation=vip1_alloc,
        date=tomorrow,
        timeslot=slot,
        room=room,
        status="scheduled",
        is_vip=True
    )
    # Existing bookings for VIP 1
    TherapistBooking.objects.create(
        therapist=t1,
        date=tomorrow,
        time_slot=slot,
        therapy_name=therapy.therapy_name,
        patient_id=vip1_pat.id,
        visit=vip1_alloc,
        is_bathing=True,
        status="BOOKED"
    )
    TherapistBooking.objects.create(
        therapist=t2,
        date=tomorrow,
        time_slot=slot,
        therapy_name=therapy.therapy_name,
        patient_id=vip1_pat.id,
        visit=vip1_alloc,
        is_bathing=False,
        status="BOOKED"
    )

    # 2. VIP 2 wants t1 (and t2) at the SAME slot
    vip2_pat = PatientSnapshot.objects.create(
        pat_reg_no="VIP_SECOND",
        pat_name="Second VIP Patient",
        pat_sex="Female",
        pat_age=40,
        is_vip=True,
        pat_room_no="102"
    )
    room2_name, _ = RoomName.objects.get_or_create(name="TR-4")
    room2, _ = TreatmentRoom.objects.get_or_create(room_no="TR-4", defaults={"room_name": room2_name})

    vip2_alloc = TherapyAllocation.objects.create(
        patient=vip2_pat,
        therapy_name=therapy.therapy_name,
        therapy_code=therapy.therapy_code,
        timeslot=slot,
        room=room2,
        from_date=tomorrow,
        to_date=tomorrow,
        days=1,
        is_vip=True,
        allocated_by=doc_user
    )
    vip2_bk = Booking.objects.create(
        allocation=vip2_alloc,
        date=tomorrow,
        timeslot=slot,
        status="draft",
        is_vip=True
    )

    # Configure VIP 2 roster with t1 and t2 only
    DoctorPatientPreferenceAllowance.objects.create(
        doctor=doc_user,
        patient_reg_no=vip2_pat.pat_reg_no,
        year=tomorrow.year,
        month=tomorrow.month,
        is_active=True
    )
    save_preferred_therapist_roster(
        patient_reg_no=vip2_pat.pat_reg_no,
        therapist_codes=[t1.therapist_code, t2.therapist_code],
        primary_bathing_code=t1.therapist_code,
        secondary_bathing_code=t2.therapist_code,
        configured_by=doc_user
    )

    # 3. Run bulk allocation
    bulk_allocate_for_date(tomorrow_str)

    # VIP 1 must remain scheduled with t1 and t2
    vip1_bk.refresh_from_db()
    assert vip1_bk.status == "scheduled"
    vip1_tbs = TherapistBooking.objects.filter(visit=vip1_alloc, date=tomorrow, status="BOOKED")
    vip1_codes = {tb.therapist.therapist_code for tb in vip1_tbs}
    assert t1.therapist_code in vip1_codes
    assert t2.therapist_code in vip1_codes

    # VIP 2 MUST FAIL because preferred therapist is assigned to another VIP!
    vip2_bk.refresh_from_db()
    assert vip2_bk.status == "failed", f"Expected VIP 2 to fail due to other VIP conflict, but got {vip2_bk.status}"
    assert "another VIP patient" in vip2_bk.failure_reason, f"Unexpected failure reason: {vip2_bk.failure_reason}"


@pytest.mark.django_db
def test_failed_vip_not_hidden_in_reschedule_page_and_can_change_slot(client, base_setup):
    """
    When a VIP patient's treatment fails (e.g. because preferred therapist is with another VIP):
    1. The VIP patient must NOT be hidden in the reschedule page / API.
    2. In reschedule, the user can fetch available slots (/reschedule-options/).
    3. The user can change the time slot (/reschedule-therapy/) to a slot where preferred therapist is free.
    4. The treatment successfully schedules with their respective preferred therapist at the new slot!
    """
    slot = base_setup["slot"]
    room = base_setup["room"]
    therapy = base_setup["therapy"]
    doc_user = base_setup["doc_user"]
    t1, t2, t3, t4 = base_setup["therapists"]

    tomorrow = date.today() + timedelta(days=1)
    tomorrow_str = tomorrow.strftime("%Y-%m-%d")

    # Login client as doc_user / admin
    Module.objects.get_or_create(
        name="therapy_scheduling",
        defaults={"display_name": "Therapy Scheduling", "is_active": True},
    )
    doc_user.role = "super_admin"
    doc_user.is_superuser = True
    doc_user.save()
    client.force_login(doc_user)

    # Create slot 2 (02:30 PM - standard IP slot)
    slot2, _ = SlotMaster.objects.get_or_create(
        slot_number=2,
        defaults={
            "slot_time": time(14, 30),
            "slot_name": "Slot 2 (02:30 PM)",
            "is_active": True
        }
    )

    # VIP 1 is booked with t1 at slot 1
    vip1_pat = PatientSnapshot.objects.create(
        pat_reg_no="VIP_HOLDER",
        pat_name="Holder VIP Patient",
        pat_sex="Female",
        pat_age=50,
        is_vip=True,
        pat_room_no="NR-11"
    )
    vip1_alloc = TherapyAllocation.objects.create(
        patient=vip1_pat,
        therapy_name=therapy.therapy_name,
        therapy_code=therapy.therapy_code,
        timeslot=slot,
        room=room,
        from_date=tomorrow,
        to_date=tomorrow,
        days=1,
        is_vip=True,
        allocated_by=doc_user
    )
    Booking.objects.create(
        allocation=vip1_alloc,
        date=tomorrow,
        timeslot=slot,
        room=room,
        status="scheduled",
        is_vip=True
    )
    TherapistBooking.objects.create(
        therapist=t1,
        date=tomorrow,
        time_slot=slot,
        therapy_name=therapy.therapy_name,
        patient_id=vip1_pat.id,
        visit=vip1_alloc,
        is_bathing=True,
        status="BOOKED"
    )
    TherapistBooking.objects.create(
        therapist=t2,
        date=tomorrow,
        time_slot=slot,
        therapy_name=therapy.therapy_name,
        patient_id=vip1_pat.id,
        visit=vip1_alloc,
        is_bathing=False,
        status="BOOKED"
    )

    # VIP 2 failed at slot 1 because t1 & t2 were with VIP 1
    vip2_pat = PatientSnapshot.objects.create(
        pat_reg_no="VIP_NEEDS_RESCHED",
        pat_name="Reschedule VIP Patient",
        pat_sex="Female",
        pat_age=45,
        is_vip=True,
        pat_room_no="NR-12"
    )
    room2_name, _ = RoomName.objects.get_or_create(name="TR-4")
    room2, _ = TreatmentRoom.objects.get_or_create(room_no="TR-4", defaults={"room_name": room2_name, "is_active": True})

    vip2_alloc = TherapyAllocation.objects.create(
        patient=vip2_pat,
        therapy_name=therapy.therapy_name,
        therapy_code=therapy.therapy_code,
        timeslot=slot,
        room=room2,
        from_date=tomorrow,
        to_date=tomorrow,
        days=1,
        is_vip=True,
        allocated_by=doc_user
    )
    vip2_bk = Booking.objects.create(
        allocation=vip2_alloc,
        date=tomorrow,
        timeslot=slot,
        status="failed",
        failure_reason="Preferred therapist is assigned to another VIP patient at this slot. Change slot to reschedule.",
        is_vip=True
    )

    # Configure VIP 2 roster with t1 and t2
    DoctorPatientPreferenceAllowance.objects.create(
        doctor=doc_user,
        patient_reg_no=vip2_pat.pat_reg_no,
        year=tomorrow.year,
        month=tomorrow.month,
        is_active=True
    )
    save_preferred_therapist_roster(
        patient_reg_no=vip2_pat.pat_reg_no,
        therapist_codes=[t1.therapist_code, t2.therapist_code],
        primary_bathing_code=t1.therapist_code,
        secondary_bathing_code=t2.therapist_code,
        configured_by=doc_user
    )

    # 1. VIP 2 must NOT be hidden in API therapy-data (failed)
    res_alloc = client.get(f'/sheduling/scheduling/api/therapy-data/?date={tomorrow_str}&status=failed')
    assert res_alloc.status_code == 200
    alloc_data = res_alloc.json()
    failed_booking_ids = [b['booking_id'] for b in alloc_data.get('data', [])]
    assert vip2_bk.id in failed_booking_ids, "Failed VIP booking must NOT be hidden in therapy-data API"

    # 2. VIP 2 can get reschedule options (slot 2 is available)
    res_opt = client.post(
        '/sheduling/scheduling/api/reschedule-options/',
        data=json.dumps({
            'allocation_id': vip2_alloc.id,
            'date': tomorrow_str
        }),
        content_type='application/json'
    )
    assert res_opt.status_code == 200
    opt_data = res_opt.json()
    assert opt_data.get('success') is True
    available_slot_ids = [s['slot_id'] for s in opt_data.get('available_slots', [])]
    assert slot2.id in available_slot_ids, "Slot 2 where preferred therapist is free must be offered"

    # 3. Change time slot to slot 2 and reschedule
    res_resched = client.post(
        '/sheduling/scheduling/api/reschedule-therapy/',
        data=json.dumps({
            'allocation_id': vip2_alloc.id,
            'date': tomorrow_str,
            'target_slot_id': slot2.id
        }),
        content_type='application/json'
    )
    assert res_resched.status_code == 200
    resched_data = res_resched.json()
    assert resched_data.get('success') is True

    # 4. VIP 2 is now successfully scheduled at slot 2 with preferred therapists!
    vip2_bk.refresh_from_db()
    assert vip2_bk.status == "scheduled", f"VIP 2 should be scheduled at slot 2, got {vip2_bk.status}"
    assert vip2_bk.timeslot == slot2, f"VIP 2 slot should be updated to slot 2, got {vip2_bk.timeslot}"

    # Verify VIP 2 has t1 and t2 assigned at slot 2
    vip2_tbs = TherapistBooking.objects.filter(visit=vip2_alloc, date=tomorrow, time_slot=slot2, status="BOOKED")
    vip2_codes = {tb.therapist.therapist_code for tb in vip2_tbs}
    assert t1.therapist_code in vip2_codes, f"VIP 2 must have t1 at new slot, got {vip2_codes}"
    assert t2.therapist_code in vip2_codes, f"VIP 2 must have t2 at new slot, got {vip2_codes}"


@pytest.mark.django_db
def test_vip_multi_therapist_partial_roster_and_preemption_schedules_successfully(base_setup):
    """
    When a VIP patient requires 3 therapists:
    - Preferred roster has 2 therapists (e.g. t1, t2), but t2 is on leave.
    - t1 is preferred and available.
    - The third needed therapist (t3) is occupied by a non-VIP patient.
    - t4 is free.
    Reassigning upcoming bookings must:
    1. Allocate t1 (preferred).
    2. Fall back to other available therapists to fulfill the remaining 2 therapists.
    3. Displace non-VIP holding t3 so VIP gets t3, and allocate t4.
    4. The VIP booking must be marked as 'scheduled' (NOT 'failed') with all 3 therapists assigned!
    5. The non-VIP patient must be displaced to an available therapist or marked for rescheduling.
    """
    slot = base_setup["slot"]
    room = base_setup["room"]
    doc_user = base_setup["doc_user"]
    t1, t2, t3, t4 = base_setup["therapists"]

    tomorrow = date.today() + timedelta(days=1)

    # 3-therapist therapy
    therapy_3, _ = TherapyMaster.objects.get_or_create(
        therapy_code="TH_TRIO",
        defaults={
            "therapy_name": "Trio Therapy",
            "therapy_category": "General",
            "therapy_duration": "45",
            "bathing_required": "Yes",
            "treatment_room_required": "Yes",
            "no_of_senior_therapist": 1,
            "total_no_of_therapist": 3,
            "is_active": True
        }
    )

    # t2 is on leave tomorrow
    TherapistLeaveMaster.objects.create(
        therapist=t2,
        leave_day=tomorrow.weekday(),
        is_active=True
    )

    # Non-VIP patient is currently holding t3 at slot
    non_vip_pat = PatientSnapshot.objects.create(
        pat_reg_no="NONVIP_HOLD_T3",
        pat_name="Non-VIP Holding T3",
        pat_sex="Female",
        pat_age=30,
        is_vip=False,
        pat_room_no="105"
    )
    non_vip_alloc = TherapyAllocation.objects.create(
        patient=non_vip_pat,
        therapy_name="Solo Therapy",
        therapy_code="TH_SOLO",
        timeslot=slot,
        room=room,
        from_date=tomorrow,
        to_date=tomorrow,
        days=1,
        is_vip=False
    )
    non_vip_bk = Booking.objects.create(
        allocation=non_vip_alloc,
        date=tomorrow,
        timeslot=slot,
        status="scheduled",
        is_vip=False
    )
    TherapistBooking.objects.create(
        therapist=t3,
        date=tomorrow,
        time_slot=slot,
        therapy_name="Solo Therapy",
        patient_id=non_vip_pat.id,
        visit=non_vip_alloc,
        status="BOOKED"
    )
    th3, _ = Therapist.objects.get_or_create(therapist_code=t3.therapist_code)
    BookingAssignment.objects.create(
        booking=non_vip_bk,
        therapist=th3,
        status="assigned",
        booking_date=tomorrow,
        booking_timeslot=slot
    )

    # VIP Patient requires 3 therapists. Preferred roster has t1 and t2 only.
    vip_pat = PatientSnapshot.objects.create(
        pat_reg_no="VIP_TRIO_PAT",
        pat_name="VIP Trio Patient",
        pat_sex="Female",
        pat_age=55,
        is_vip=True,
        pat_room_no="NR-14"
    )
    room2_name, _ = RoomName.objects.get_or_create(name="TR-4")
    room2, _ = TreatmentRoom.objects.get_or_create(room_no="TR-4", defaults={"room_name": room2_name})

    vip_alloc = TherapyAllocation.objects.create(
        patient=vip_pat,
        therapy_name=therapy_3.therapy_name,
        therapy_code=therapy_3.therapy_code,
        timeslot=slot,
        room=room2,
        from_date=tomorrow,
        to_date=tomorrow,
        days=1,
        is_vip=True,
        allocated_by=doc_user
    )
    FinalScheduleRun.objects.create(run_date=tomorrow, status='success')
    vip_bk = Booking.objects.create(
        allocation=vip_alloc,
        date=tomorrow,
        timeslot=slot,
        status="scheduled",
        is_vip=True
    )
    TherapistBooking.objects.create(
        therapist=t4,
        date=tomorrow,
        time_slot=slot,
        therapy_name=therapy_3.therapy_name,
        patient_id=vip_pat.id,
        visit=vip_alloc,
        status="BOOKED"
    )
    th4, _ = Therapist.objects.get_or_create(therapist_code=t4.therapist_code)
    BookingAssignment.objects.create(
        booking=vip_bk,
        therapist=th4,
        status="assigned",
        booking_date=tomorrow,
        booking_timeslot=slot
    )

    DoctorPatientPreferenceAllowance.objects.create(
        doctor=doc_user,
        patient_reg_no=vip_pat.pat_reg_no,
        year=tomorrow.year,
        month=tomorrow.month,
        is_active=True
    )
    save_preferred_therapist_roster(
        patient_reg_no=vip_pat.pat_reg_no,
        therapist_codes=[t1.therapist_code, t2.therapist_code],
        primary_bathing_code=t1.therapist_code,
        secondary_bathing_code=t2.therapist_code,
        configured_by=doc_user
    )

    # Reassign bookings
    reassign_patient_upcoming_bookings_with_roster(vip_pat.pat_reg_no)

    # VIP booking must be SCHEDULED (NOT failed)
    vip_bk.refresh_from_db()
    assert vip_bk.status == "scheduled", f"VIP booking must be scheduled, got {vip_bk.status} ({vip_bk.failure_reason})"

    # VIP must have 3 therapists: t1 (preferred) + 2 others (preempted t3 + t4)
    vip_tbs = TherapistBooking.objects.filter(visit=vip_alloc, date=tomorrow, status="BOOKED")
    assert vip_tbs.count() == 3, f"Expected 3 therapists for VIP, got {vip_tbs.count()}"
    vip_codes = {tb.therapist.therapist_code for tb in vip_tbs}
    assert t1.therapist_code in vip_codes, f"Preferred therapist t1 must be allocated, got {vip_codes}"

    # Non-VIP booking must no longer hold t3 (preempted for VIP)
    non_vip_tbs = TherapistBooking.objects.filter(visit=non_vip_alloc, date=tomorrow, status="BOOKED")
    for n_tb in non_vip_tbs:
        assert n_tb.therapist.therapist_code != t3.therapist_code


