import pytest
from datetime import date, timedelta, time
from django.utils import timezone

from masters.models import (
    TherapistMaster, TherapistGrade, SlotMaster, TherapyMaster,
    TherapistLeaveMaster
)
from Patient.models import TherapistBooking, Therapist, TreatmentRoom, RoomName
from Sheduling.models import (
    PatientSnapshot, TherapyAllocation, Booking, BookingAssignment,
    DoctorPatientPreferenceAllowance, PatientPreferredTherapistRoster
)
from authentication.models import CustomUser
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
