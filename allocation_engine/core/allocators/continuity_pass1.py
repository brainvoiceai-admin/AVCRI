"""
Shared Pass-1 Continuity Priority Pass allocator (Layer 1B).

Unifies `assign_continuity_therapists_pass1` from `final_allocation.py` and `reshedule.py`
via `Pass1Config`, while guaranteeing that `create_bookings=False` is strictly read-only
(skipping both `create_therapist_booking_safe` and `displace_non_vip_therapist_for_slot`).
"""

from dataclasses import dataclass
from math import inf

from allocation_engine.core.allocators.therapist_availability import get_therapist_gender
from allocation_engine.core.primitives.booking_persistence import create_therapist_booking_safe
from allocation_engine.core.primitives.patient_utils import resolve_desired_gender
from allocation_engine.core.primitives.shift_utils import (
    _shift_eligibility_sets_for_slot,
    _shift_enforcement_enabled,
)
from allocation_engine.core.primitives.therapy_catalog import (
    get_therapist_grade_name,
    therapist_requirements,
    therapy_needs_bath,
)
from allocation_engine.rules.hard_treatment import (
    get_slot_session,
    is_hard_treatment,
    patient_has_hard_treatment_in_session,
)
from allocation_engine.rules.senior_tag import (
    get_senior_tag_count_for_therapist,
    is_treatment_requiring_senior_tag,
)


@dataclass(frozen=True)
class Pass1Config:
    """Explicit behavioral flags preserving scheduling vs rescheduling Pass-1 differences."""
    mode: str = "scheduling"
    check_same_slot_conflict: bool = True
    enforce_shift_and_oncall: bool = True
    exclude_helping_from_continuity: bool = True
    expand_preferred_roster_therapists: bool = True
    exclude_unpreferred_therapists: bool = True
    fallback_bathing_from_history: bool = False
    fallback_to_previous_day_bookings: bool = False
    set_bath_assigned_in_loop: bool = True
    validate_senior_not_bathing: bool = True


SCHEDULING_PASS1_CONFIG = Pass1Config(
    mode="scheduling",
    check_same_slot_conflict=True,
    enforce_shift_and_oncall=True,
    exclude_helping_from_continuity=True,
    expand_preferred_roster_therapists=True,
    exclude_unpreferred_therapists=True,
    fallback_bathing_from_history=False,
    fallback_to_previous_day_bookings=False,
    set_bath_assigned_in_loop=True,
    validate_senior_not_bathing=True,
)

RESCHEDULING_PASS1_CONFIG = Pass1Config(
    mode="rescheduling",
    check_same_slot_conflict=False,
    enforce_shift_and_oncall=False,
    exclude_helping_from_continuity=False,
    expand_preferred_roster_therapists=False,
    exclude_unpreferred_therapists=False,
    fallback_bathing_from_history=True,
    fallback_to_previous_day_bookings=True,
    set_bath_assigned_in_loop=False,
    validate_senior_not_bathing=False,
)


def assign_continuity_therapists_pass1(
    booking,
    allocation,
    target_date,
    locked_therapist_slots,
    create_bookings=True,
    *,
    config: Pass1Config = SCHEDULING_PASS1_CONFIG,
):
    """
    PASS 1 - Continuity Priority Pass:
    Assigns ONLY previous-day / continuity-plan therapists for a booking and locks them.
    Does NOT fill remaining slots - that's done in PASS 2.

    When `create_bookings=False`, performs NO database writes (no TherapistBooking creation
    and no VIP displacement).
    """
    from Patient.models import RoomBooking, TherapistBooking
    from Sheduling.models import TherapistContinuityPlan
    from Sheduling.vip_service import is_patient_vip
    from django.db.models import Max, Q
    from masters.models import (
        EmergencyLeave,
        SlotMaster,
        TherapistLeaveMaster,
        TherapistMaster,
        is_therapist_deputed,
        is_therapist_omitted_for_treatment,
        is_therapist_on_call_active,
        is_therapist_on_emergency_leave,
    )

    result = {
        'assigned_therapists': [],
        'remaining_requirements': {},
        'bath_assigned': None,
        'senior_therapist': None,
        'success': False,
    }

    try:
        therapy_req = therapist_requirements(allocation)
    except Exception:
        therapy_req = {
            "total": 1,
            "super_senior": 0,
            "senior": 0,
            "junior": 0,
            "trainee": 0,
            "therapy_category": None,
        }

    req_total = int(therapy_req.get("total", 1) or 1)
    if req_total == 0:
        return result

    patient_id = getattr(allocation.patient, 'id', None)
    patient_gender = getattr(getattr(allocation, 'patient', None), 'pat_sex', None)
    patient_age = getattr(getattr(allocation, 'patient', None), 'pat_age', None)
    needs_bath_flag = therapy_needs_bath(allocation) if therapy_needs_bath else False

    if config.fallback_bathing_from_history and not needs_bath_flag and patient_id:
        try:
            has_previous_bath = TherapistBooking.objects.filter(
                patient_id=patient_id,
                visit_id=allocation.id,
                is_bathing=True,
                status='BOOKED',
            ).exists()
            if has_previous_bath:
                needs_bath_flag = True
        except Exception as e:
            print(f"[RESCHEDULE] Error checking previous bathing bookings for allocation {allocation.id}: {e}")

    therapy_name = getattr(allocation, 'therapy_name', None)
    therapy_code = getattr(allocation, 'therapy_code', None)
    current_therapy_name = therapy_name

    is_vip = (
        getattr(booking, 'is_vip', False)
        or getattr(allocation, 'is_vip', False)
        or is_patient_vip(getattr(allocation, 'patient', None))
        or is_patient_vip(patient_id)
    )
    allow_vip_mutation = bool(is_vip and create_bookings)

    slot = getattr(booking, 'timeslot', None)
    if not slot:
        return result

    slot_master = None
    if isinstance(slot, SlotMaster):
        slot_master = slot
    else:
        slot_time = getattr(slot, 'slot_time', None)
        if slot_time:
            slot_master = SlotMaster.objects.filter(slot_time=slot_time, is_active=True).first()

    if not slot_master:
        return result

    # SAME-SLOT GUARD (scheduling mode): prevent mutual Pass-1 deadlock for same patient+slot
    if config.check_same_slot_conflict and patient_id:
        has_existing_slot_booking = (
            TherapistBooking.objects.filter(
                patient_id=patient_id,
                date=target_date,
                time_slot=slot_master,
                status='BOOKED',
            )
            .exclude(visit_id=allocation.id)
            .exclude(visit__status='cancelled')
            .exists()
            or RoomBooking.objects.filter(
                patient_id=patient_id,
                date=target_date,
                time_slot=slot_master,
                status__in=['BOOKED', 'scheduled'],
            )
            .exclude(visit=booking)
            .exclude(therapy_id=allocation.id)
            .exclude(
                Q(therapy__status='cancelled')
                | Q(visit__status='cancelled')
                | Q(visit__allocation__status='cancelled')
            )
            .exists()
        )
        if has_existing_slot_booking:
            print(
                f"[CONTINUITY PASS1] Skipping booking {booking.pk} - patient {patient_id} "
                f"already has a booking/lock at slot {slot_master} on {target_date}"
            )
            return result

    # HARD TREATMENT RESTRICTION
    if is_hard_treatment(allocation, therapy_name=therapy_name, therapy_code=therapy_code):
        slot_session = get_slot_session(slot_master)
        if slot_session and patient_id and patient_has_hard_treatment_in_session(
            patient_id=patient_id,
            target_date=target_date,
            session=slot_session,
            exclude_booking_id=getattr(booking, 'pk', None),
            exclude_allocation_id=getattr(allocation, 'pk', None),
        ):
            return result

    shift_filter_enabled = False
    mapped_ids, eligible_ids = (set(), set())
    if config.enforce_shift_and_oncall:
        shift_filter_enabled = _shift_enforcement_enabled()
        if shift_filter_enabled:
            mapped_ids, eligible_ids = _shift_eligibility_sets_for_slot(slot_master)

    continuity_therapists = []
    previous_bathing_therapist = None

    if patient_id:
        try:
            continuity_qs = TherapistContinuityPlan.objects.filter(
                date=target_date,
                time_slot=slot_master,
                allocation_id=allocation.id,
                patient_id=patient_id,
            ).select_related('therapist').order_by('priority', 'therapist_id')

            continuity_therapists = [
                row.therapist
                for row in continuity_qs
                if row.therapist and getattr(row.therapist, 'is_active', True)
            ]

            if needs_bath_flag:
                try:
                    therapy_start_date = getattr(allocation, 'from_date', None)
                    prev_bath_bookings_qs = TherapistBooking.objects.filter(
                        patient_id=patient_id,
                        visit_id=allocation.id,
                        time_slot=slot_master,
                        date__lt=target_date,
                        is_bathing=True,
                        status='BOOKED',
                    ).select_related('therapist').order_by('date', 'created_at')
                    if therapy_start_date:
                        prev_bath_bookings_qs = prev_bath_bookings_qs.filter(date__gte=therapy_start_date)

                    seen_therapist_ids = set()
                    therapists_from_start = []
                    for prev_bath_booking in list(prev_bath_bookings_qs):
                        if not prev_bath_booking.therapist:
                            continue
                        if not getattr(prev_bath_booking.therapist, 'is_active', True):
                            continue
                        tid = prev_bath_booking.therapist.pk
                        if tid not in seen_therapist_ids:
                            seen_therapist_ids.add(tid)
                            therapists_from_start.append(prev_bath_booking.therapist)

                    original_bathing_therapist = None
                    most_recent_bathing_therapist = therapists_from_start[-1] if therapists_from_start else None
                    day_of_week = target_date.weekday()
                    for therapist in therapists_from_start:
                        is_on_leave = False
                        if TherapistLeaveMaster.objects.filter(therapist=therapist, leave_day=day_of_week).exists():
                            is_on_leave = True
                        if not is_on_leave and is_therapist_on_emergency_leave(therapist, target_date, slot_master):
                            is_on_leave = True
                        if not is_on_leave and is_therapist_deputed(therapist, target_date):
                            is_on_leave = True
                        if not is_on_leave and is_therapist_omitted_for_treatment(
                            therapist, current_therapy_name or therapy_code
                        ):
                            is_on_leave = True
                        if not is_on_leave and TherapistBooking.objects.filter(
                            therapist=therapist,
                            date=target_date,
                            time_slot=slot_master,
                            status='BOOKED',
                        ).exists():
                            is_on_leave = True
                        if not is_on_leave:
                            original_bathing_therapist = therapist
                            break

                    if original_bathing_therapist:
                        previous_bathing_therapist = original_bathing_therapist
                        if original_bathing_therapist not in continuity_therapists:
                            continuity_therapists.insert(0, original_bathing_therapist)
                    else:
                        bath_row = next(
                            (
                                row
                                for row in continuity_qs
                                if row.is_bathing
                                and getattr(row.therapist, 'is_bathing_therapist', False)
                                and getattr(row.therapist, 'is_active', True)
                            ),
                            None,
                        )
                        if most_recent_bathing_therapist and most_recent_bathing_therapist in continuity_therapists:
                            previous_bathing_therapist = most_recent_bathing_therapist
                        elif bath_row:
                            previous_bathing_therapist = bath_row.therapist
                        else:
                            for t in continuity_therapists:
                                if getattr(t, 'is_bathing_therapist', False) and getattr(t, 'is_active', True):
                                    previous_bathing_therapist = t
                                    break
                except Exception as e:
                    print(f"[CONTINUITY PASS1] Error finding previous bathing therapist: {e}")
                    bath_row = next(
                        (
                            row
                            for row in continuity_qs
                            if row.is_bathing
                            and getattr(row.therapist, 'is_bathing_therapist', False)
                            and getattr(row.therapist, 'is_active', True)
                        ),
                        None,
                    )
                    if bath_row:
                        previous_bathing_therapist = bath_row.therapist
                    else:
                        for t in continuity_therapists:
                            if getattr(t, 'is_bathing_therapist', False) and getattr(t, 'is_active', True):
                                previous_bathing_therapist = t
                                break
        except Exception as e:
            print(f"[CONTINUITY PASS1] Error reading continuity plan: {e}")
            continuity_therapists = []

    unpreferred_codes = set()
    pat_reg_no = getattr(getattr(allocation, 'patient', None), 'pat_reg_no', None)
    if config.exclude_unpreferred_therapists:
        for pid in filter(None, [patient_id, pat_reg_no]):
            try:
                from Sheduling.preference_views import get_active_patient_therapist_preferences
                _, pref_u = get_active_patient_therapist_preferences(pid)
                unpreferred_codes.update(pref_u)
            except Exception as e:
                print(f"[CONTINUITY PASS1] Error fetching active preferences for patient {pid}: {e}")

    preferred_roster_info = None
    roster_pids = list(filter(None, [patient_id, pat_reg_no])) if config.expand_preferred_roster_therapists else list(filter(None, [patient_id]))
    for pid in roster_pids:
        try:
            from Sheduling.preferred_therapist_service import get_active_preferred_roster
            preferred_roster_info = get_active_preferred_roster(pid)
            if preferred_roster_info:
                break
        except Exception as e:
            print(f"[CONTINUITY PASS1] Error fetching preferred roster for patient {pid}: {e}")

    if preferred_roster_info:
        roster_set = preferred_roster_info['therapist_codes_set']
        continuity_therapists = [
            t for t in continuity_therapists if getattr(t, 'therapist_code', None) in roster_set
        ]

        if config.expand_preferred_roster_therapists:
            existing_tids = {getattr(t, 'id', None) for t in continuity_therapists}
            for code in preferred_roster_info.get('therapist_codes', []):
                try:
                    t_obj = TherapistMaster.objects.filter(therapist_code=code, is_active=True).first()
                    if t_obj and t_obj.id not in existing_tids:
                        continuity_therapists.append(t_obj)
                        existing_tids.add(t_obj.id)
                except Exception:
                    pass

        if needs_bath_flag:
            try:
                from Sheduling.preferred_therapist_service import pick_bathing_therapist_from_roster
                if config.expand_preferred_roster_therapists:
                    picked_bath, _ = pick_bathing_therapist_from_roster(
                        preferred_roster_info,
                        target_date,
                        slot_master,
                        is_vip=allow_vip_mutation,
                        therapy_name=current_therapy_name or therapy_code,
                    )
                else:
                    picked_bath, _ = pick_bathing_therapist_from_roster(
                        preferred_roster_info, target_date, slot_master
                    )
                if picked_bath:
                    previous_bathing_therapist = picked_bath
                    if config.expand_preferred_roster_therapists and picked_bath in continuity_therapists:
                        continuity_therapists.remove(picked_bath)
                        continuity_therapists.insert(0, picked_bath)
                    elif picked_bath not in continuity_therapists:
                        continuity_therapists.insert(0, picked_bath)
            except Exception as e:
                print(f"[CONTINUITY PASS1] Error resolving roster bathing therapist: {e}")

    # Rescheduling fallback: find previous-day therapists from TherapistBooking if plan is empty
    if config.fallback_to_previous_day_bookings and not continuity_therapists and patient_id:
        try:
            most_recent_date = (
                TherapistBooking.objects.filter(patient_id=patient_id, status='BOOKED')
                .exclude(visit=allocation)
                .aggregate(Max('date'))['date__max']
            )
            if most_recent_date:
                prev_bookings = (
                    TherapistBooking.objects.filter(
                        patient_id=patient_id, date=most_recent_date, status='BOOKED'
                    )
                    .exclude(visit=allocation)
                    .select_related('therapist')
                    .order_by('time_slot')
                )
                previous_therapist_masters = []
                seen_therapist_ids = set()
                for prev_booking in prev_bookings:
                    if prev_booking.therapist and getattr(prev_booking.therapist, 'is_active', True):
                        tid = prev_booking.therapist.pk
                        if tid not in seen_therapist_ids:
                            previous_therapist_masters.append(prev_booking.therapist)
                            seen_therapist_ids.add(tid)

                if previous_therapist_masters:
                    continuity_therapists = previous_therapist_masters
                    therapy_start_date = getattr(allocation, 'from_date', None)
                    if therapy_start_date and slot_master:
                        try:
                            from_start_qs = TherapistBooking.objects.filter(
                                visit_id=allocation.id,
                                date__gte=therapy_start_date,
                                date__lt=target_date,
                                time_slot=slot_master,
                                status='BOOKED',
                            ).select_related('therapist').order_by('date', 'created_at')
                            seen_fs = set()
                            therapists_from_start = []
                            for tb in from_start_qs:
                                if not tb.therapist or not getattr(tb.therapist, 'is_active', True):
                                    continue
                                tid = getattr(tb.therapist, 'id', None)
                                if tid is None or tid in seen_fs:
                                    continue
                                seen_fs.add(tid)
                                therapists_from_start.append(tb.therapist)
                            if therapists_from_start:
                                continuity_therapists = therapists_from_start + [
                                    t for t in continuity_therapists if t not in therapists_from_start
                                ]
                        except Exception as e:
                            print(f"[RESCHEDULE PASS1] Error building from-start list: {e}")

                    if needs_bath_flag:
                        prev_bath_bookings_qs = TherapistBooking.objects.filter(
                            patient_id=patient_id,
                            visit_id=allocation.id,
                            time_slot=slot_master,
                            date__lt=target_date,
                            is_bathing=True,
                            status='BOOKED',
                        ).select_related('therapist').order_by('date', 'created_at')
                        if therapy_start_date:
                            prev_bath_bookings_qs = prev_bath_bookings_qs.filter(date__gte=therapy_start_date)

                        seen_b = set()
                        therapists_from_start = []
                        for prev_bath_booking in list(prev_bath_bookings_qs):
                            if not prev_bath_booking.therapist or not getattr(prev_bath_booking.therapist, 'is_active', True):
                                continue
                            tid = prev_bath_booking.therapist.pk
                            if tid not in seen_b:
                                seen_b.add(tid)
                                therapists_from_start.append(prev_bath_booking.therapist)

                        original_bathing_therapist = None
                        most_recent_bathing_therapist = therapists_from_start[-1] if therapists_from_start else None
                        day_of_week = target_date.weekday()
                        for therapist in therapists_from_start:
                            is_on_leave = False
                            if TherapistLeaveMaster.objects.filter(therapist=therapist, leave_day=day_of_week).exists():
                                is_on_leave = True
                            if not is_on_leave and is_therapist_on_emergency_leave(therapist, target_date, slot_master):
                                is_on_leave = True
                            if not is_on_leave and is_therapist_deputed(therapist, target_date):
                                is_on_leave = True
                            if not is_on_leave and is_therapist_omitted_for_treatment(therapist, therapy_name):
                                is_on_leave = True
                            if not is_on_leave and TherapistBooking.objects.filter(
                                therapist=therapist,
                                date=target_date,
                                time_slot=slot_master,
                                status='BOOKED',
                            ).exists():
                                is_on_leave = True
                            if not is_on_leave:
                                original_bathing_therapist = therapist
                                break

                        if original_bathing_therapist:
                            previous_bathing_therapist = original_bathing_therapist
                            if original_bathing_therapist not in continuity_therapists:
                                continuity_therapists.insert(0, original_bathing_therapist)
                        elif most_recent_bathing_therapist and most_recent_bathing_therapist in continuity_therapists:
                            previous_bathing_therapist = most_recent_bathing_therapist
                        else:
                            for t in continuity_therapists:
                                if getattr(t, 'is_bathing_therapist', False):
                                    previous_bathing_therapist = t
                                    break
        except Exception as e:
            print(f"[RESCHEDULE PASS1] Error finding previous day therapists: {e}")
            continuity_therapists = []

    if unpreferred_codes:
        continuity_therapists = [
            t for t in continuity_therapists if getattr(t, 'therapist_code', None) not in unpreferred_codes
        ]

    # Exclude therapists who have approved omissions for this treatment
    treatment_for_omission = (
        current_therapy_name
        or therapy_code
        or getattr(allocation, 'therapy_name', None)
        or getattr(allocation, 'therapy_code', None)
    )
    if treatment_for_omission and continuity_therapists:
        continuity_therapists = [
            t for t in continuity_therapists if not is_therapist_omitted_for_treatment(t, treatment_for_omission)
        ]
    if previous_bathing_therapist and treatment_for_omission and is_therapist_omitted_for_treatment(
        previous_bathing_therapist, treatment_for_omission
    ):
        previous_bathing_therapist = None

    # Exclude Helping Therapists from Pass 1 (scheduling mode)
    if config.exclude_helping_from_continuity and continuity_therapists:
        if preferred_roster_info:
            roster_pool = preferred_roster_info.get('therapist_codes_set', set())
            continuity_therapists = [
                t
                for t in continuity_therapists
                if not getattr(t, 'is_helping_therapist', False)
                or getattr(t, 'therapist_code', None) in roster_pool
            ]
        else:
            continuity_therapists = [
                t for t in continuity_therapists if not getattr(t, 'is_helping_therapist', False)
            ]

    if not continuity_therapists:
        result['remaining_requirements'] = therapy_req.copy()
        if not result['remaining_requirements'].get('therapy_code'):
            result['remaining_requirements']['therapy_code'] = therapy_code or getattr(allocation, 'therapy_code', None)
        if not result['remaining_requirements'].get('therapy_name'):
            result['remaining_requirements']['therapy_name'] = current_therapy_name or getattr(allocation, 'therapy_name', None)
        return result

    day_of_week = target_date.weekday()
    assigned_continuity = []
    grade_map = {
        "Super Senior Therapist": therapy_req.get("super_senior", 0),
        "Senior Therapist": therapy_req.get("senior", 0),
        "Junior Therapist": therapy_req.get("junior", 0),
        "Trainee Therapist": therapy_req.get("trainee", 0),
    }

    desired_gender = resolve_desired_gender(patient_gender, patient_age)

    try:
        em_leaves_qs = EmergencyLeave.objects.filter(from_date__lte=target_date, to_date__gte=target_date)
        full_day_leaves = []
        half_day_leaves = []
        for el in em_leaves_qs:
            if el.is_half_day and (not el.half_day_date or el.half_day_date == target_date):
                half_day_leaves.append(el)
            else:
                full_day_leaves.append(el)
        full_leave_therapist_ids = set(el.therapist_id for el in full_day_leaves if el.therapist_id)
        full_leave_emp_codes = set(el.employee_code for el in full_day_leaves if el.employee_code)
    except Exception:
        full_leave_therapist_ids = set()
        full_leave_emp_codes = set()
        half_day_leaves = []

    def therapist_on_leave(t):
        if TherapistLeaveMaster.objects.filter(therapist=t, leave_day=day_of_week).exists():
            return True
        t_id = getattr(t, 'id', None)
        emp_code = getattr(t, 'employee_code', None)
        if t_id in full_leave_therapist_ids or (emp_code and emp_code in full_leave_emp_codes):
            return True
        for el in half_day_leaves:
            if (t_id and el.therapist_id == t_id) or (emp_code and el.employee_code == emp_code):
                if el.is_slot_on_leave(target_date, slot_master):
                    return True
        if is_therapist_deputed(t, target_date):
            return True
        if is_therapist_omitted_for_treatment(t, current_therapy_name or therapy_code):
            return True
        if config.enforce_shift_and_oncall and not is_therapist_on_call_active(t, target_date, slot_master):
            return True
        return False

    for t in continuity_therapists:
        if len(assigned_continuity) >= req_total:
            break
        if t in assigned_continuity:
            continue
        if not getattr(t, 'is_active', True):
            continue

        lock_key = (t.id, slot_master.id)
        if lock_key in locked_therapist_slots:
            continue

        if therapist_on_leave(t):
            continue

        if shift_filter_enabled and t.id in mapped_ids and t.id not in eligible_ids:
            continue

        if TherapistBooking.objects.filter(
            therapist=t, date=target_date, time_slot=slot_master, status='BOOKED'
        ).exists():
            if allow_vip_mutation:
                from Sheduling.preferred_therapist_service import displace_non_vip_therapist_for_slot
                cur_excl = set()
                if preferred_roster_info:
                    cur_excl.update(preferred_roster_info.get('therapist_codes', []))
                cur_excl.update(
                    getattr(a, 'therapist_code', '')
                    for a in assigned_continuity
                    if getattr(a, 'therapist_code', None)
                )
                cur_excl.add(getattr(t, 'therapist_code', ''))
                for (tid, sid) in locked_therapist_slots:
                    if sid == getattr(slot_master, 'id', None):
                        t_lock = TherapistMaster.objects.filter(id=tid).first()
                        if t_lock and t_lock.therapist_code:
                            cur_excl.add(t_lock.therapist_code)
                if not displace_non_vip_therapist_for_slot(
                    t, target_date, slot_master, exclude_therapist_codes=cur_excl
                ):
                    continue
            else:
                continue

        if desired_gender and get_therapist_gender(t) != desired_gender:
            continue

        therapist_grade_name = get_therapist_grade_name(t)
        substitution_map = {
            "Super Senior Therapist": ["Senior Therapist", "Junior Therapist", "Trainee Therapist"],
            "Senior Therapist": ["Junior Therapist", "Trainee Therapist"],
            "Junior Therapist": ["Trainee Therapist"],
            "Trainee Therapist": [],
        }

        grade_can_be_used = False
        grade_to_decrement = None
        if grade_map.get(therapist_grade_name, 0) > 0:
            grade_can_be_used = True
            grade_to_decrement = therapist_grade_name
        else:
            for needed_grade, substitutes in substitution_map.items():
                if therapist_grade_name in substitutes and grade_map.get(needed_grade, 0) > 0:
                    grade_can_be_used = True
                    grade_to_decrement = needed_grade
                    break

        if not grade_can_be_used:
            for needed_grade in grade_map:
                if grade_map.get(needed_grade, 0) > 0:
                    grade_to_decrement = needed_grade
                    grade_can_be_used = True
                    break

        if not grade_can_be_used:
            for priority_grade in ["Trainee Therapist", "Junior Therapist", "Senior Therapist", "Super Senior Therapist"]:
                if grade_map.get(priority_grade, 0) > 0:
                    grade_to_decrement = priority_grade
                    break

        if needs_bath_flag and not getattr(t, 'is_bathing_therapist', False):
            if config.set_bath_assigned_in_loop:
                has_bath_already = any(getattr(a, 'is_bathing_therapist', False) for a in assigned_continuity)
                if not has_bath_already and not result.get('bath_assigned'):
                    continue
            else:
                if not result['bath_assigned']:
                    continue

        db_count = TherapistBooking.objects.filter(
            therapist=t, date=target_date, status='BOOKED'
        ).count()
        current_pass_count = sum(1 for a in assigned_continuity if a == t)
        session_count = db_count + current_pass_count

        if not is_vip and session_count >= 6:
            continue

        assigned_continuity.append(t)
        if config.set_bath_assigned_in_loop:
            if needs_bath_flag and getattr(t, 'is_bathing_therapist', False) and not result.get('bath_assigned'):
                result['bath_assigned'] = t

        if grade_to_decrement and grade_map.get(grade_to_decrement, 0) > 0:
            grade_map[grade_to_decrement] -= 1

        locked_therapist_slots.add(lock_key)

    # Assign bathing therapist
    if needs_bath_flag and assigned_continuity:
        if preferred_roster_info:
            try:
                from Sheduling.preferred_therapist_service import pick_bathing_therapist_from_roster
                pass1_bath_excl = set()
                pass1_bath_excl.update(preferred_roster_info.get('therapist_codes', []))
                pass1_bath_excl.update(
                    getattr(a, 'therapist_code', '')
                    for a in assigned_continuity
                    if getattr(a, 'therapist_code', None)
                )
                for (tid, sid) in locked_therapist_slots:
                    if sid == getattr(slot_master, 'id', None):
                        t_lock = TherapistMaster.objects.filter(id=tid).first()
                        if t_lock and t_lock.therapist_code:
                            pass1_bath_excl.add(t_lock.therapist_code)
                picked_bath, _ = pick_bathing_therapist_from_roster(
                    preferred_roster_info,
                    target_date,
                    slot_master,
                    is_vip=allow_vip_mutation,
                    exclude_therapist_codes=pass1_bath_excl,
                )
                if picked_bath and picked_bath in assigned_continuity:
                    result['bath_assigned'] = picked_bath
            except Exception as e:
                print(f"[CONTINUITY PASS1] Error resolving preferred roster bathing therapist: {e}")

        if not result.get('bath_assigned'):
            if previous_bathing_therapist and previous_bathing_therapist in assigned_continuity:
                result['bath_assigned'] = previous_bathing_therapist
            else:
                for t in assigned_continuity:
                    if getattr(t, 'is_bathing_therapist', False):
                        result['bath_assigned'] = t
                        break

    # Check for senior tag assignment (special treatments)
    requires_senior_tag = is_treatment_requiring_senior_tag(therapy_name)
    if requires_senior_tag and assigned_continuity:
        senior_candidates = []
        bath_assigned = result.get('bath_assigned')
        for t in assigned_continuity:
            grade_name = get_therapist_grade_name(t)
            if 'Senior' in grade_name and t != bath_assigned:
                senior_candidates.append((t, grade_name))

        if senior_candidates:
            best = None
            best_count = inf
            for t, _ in senior_candidates:
                current = get_senior_tag_count_for_therapist(t, target_date)
                if current < 2 and current < best_count:
                    best = t
                    best_count = current
            if best is not None:
                result['senior_therapist'] = best

    if config.validate_senior_not_bathing and requires_senior_tag:
        if result.get('senior_therapist') and result.get('bath_assigned'):
            if result['senior_therapist'] == result['bath_assigned']:
                result['senior_therapist'] = None

    # Create TherapistBooking records to lock the therapists (skip in dry-run preview mode)
    if assigned_continuity and create_bookings:
        try:
            for t in assigned_continuity:
                is_bath = t == result['bath_assigned']
                tb_obj, _tb_created = create_therapist_booking_safe(
                    t, target_date, slot_master, therapy_name, patient_id, allocation, is_bathing=is_bath
                )
                if tb_obj is None:
                    result['assigned_therapists'] = [at for at in result['assigned_therapists'] if at != t]
                    continue
        except Exception as e:
            print(f"[CONTINUITY PASS1] ERROR creating TherapistBooking locks for booking {booking.pk}: {e}")

    result['assigned_therapists'] = assigned_continuity
    result['remaining_requirements'] = {
        "super_senior": grade_map.get("Super Senior Therapist", 0),
        "senior": grade_map.get("Senior Therapist", 0),
        "junior": grade_map.get("Junior Therapist", 0),
        "trainee": grade_map.get("Trainee Therapist", 0),
        "total": req_total - len(assigned_continuity),
        "therapy_category": therapy_req.get("therapy_category", None),
        "therapy_code": therapy_req.get("therapy_code") or therapy_code or getattr(allocation, 'therapy_code', None),
        "therapy_name": therapy_req.get("therapy_name") or therapy_name or getattr(allocation, 'therapy_name', None),
        "bathing_therapists_count": therapy_req.get("bathing_therapists_count", 0),
    }
    result['success'] = len(assigned_continuity) > 0
    return result
