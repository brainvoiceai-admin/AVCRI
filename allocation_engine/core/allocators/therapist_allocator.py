"""
Shared therapist allocator & grade-substitution fallback (Layer 1B).

Unifies `allocate_therapists` from `final_allocation.py` and `reshedule.py`
via an explicit `TherapistAllocationConfig`, and hosts
`allocate_therapists_with_grade_substitution`.

Read-only preview guarantee:
- When `config.create_audit_logs=False`, `HelpingTherapistAllocationLog` is NOT written.
- When `config.allow_vip_displacement=False`, `displace_non_vip_therapist_for_slot` is NOT called.
"""

from dataclasses import dataclass, replace

from allocation_engine.core.allocators.therapist_availability import (
    TherapistAvailabilityContext,
    get_therapist_gender,
)
from allocation_engine.core.primitives.patient_utils import resolve_desired_gender
from allocation_engine.core.primitives.therapy_catalog import get_therapist_grade_name


@dataclass(frozen=True)
class TherapistAllocationConfig:
    """Explicit behavioral flags preserving scheduling vs rescheduling differences."""
    mode: str = "scheduling"
    support_avoid_therapists: bool = True
    filter_helping_from_last_therapists: bool = True
    helping_substitution_strict: bool = True
    enforce_five_then_six_cap: bool = True
    guarantee_helping_therapist: bool = False
    pass_therapy_name_to_bathing_picker: bool = True
    last_therapist_bathing_guard: bool = False
    create_audit_logs: bool = True
    allow_vip_displacement: bool = True


SCHEDULING_THERAPIST_CONFIG = TherapistAllocationConfig(
    mode="scheduling",
    support_avoid_therapists=True,
    filter_helping_from_last_therapists=True,
    helping_substitution_strict=True,
    enforce_five_then_six_cap=True,
    guarantee_helping_therapist=False,
    pass_therapy_name_to_bathing_picker=True,
    last_therapist_bathing_guard=False,
    create_audit_logs=True,
    allow_vip_displacement=True,
)

RESCHEDULING_THERAPIST_CONFIG = TherapistAllocationConfig(
    mode="rescheduling",
    support_avoid_therapists=False,
    filter_helping_from_last_therapists=False,
    helping_substitution_strict=False,
    enforce_five_then_six_cap=False,
    guarantee_helping_therapist=True,
    pass_therapy_name_to_bathing_picker=False,
    last_therapist_bathing_guard=True,
    create_audit_logs=True,
    allow_vip_displacement=True,
)


def _log_helping_therapist_allocation(
    *,
    enabled: bool,
    patient_id,
    therapist,
    date,
    time_slot,
    therapy_requirements,
    reason_for_fallback: str,
    shortage_condition: str,
):
    if not enabled:
        return
    try:
        from Sheduling.models import HelpingTherapistAllocationLog

        HelpingTherapistAllocationLog.objects.create(
            patient_id=str(patient_id or ''),
            helping_therapist=therapist,
            date=date,
            time_slot=str(getattr(time_slot, 'slot_number', time_slot) or ''),
            therapy_name=str((therapy_requirements or {}).get('therapy_name', '')),
            reason_for_fallback=reason_for_fallback,
            shortage_condition=shortage_condition,
            is_supporting_backup=True,
        )
        print(
            f"[AUDIT HelpingTherapistLog] Logged fallback allocation of Helping Therapist "
            f"{therapist.therapist_code} for patient {patient_id}"
        )
    except Exception as log_err:
        print(f"[ERROR HelpingTherapistLog] {log_err}")


def allocate_therapists(
    date,
    time_slot,
    therapy_requirements,
    last_therapists=None,
    needs_bathing=False,
    patient_gender=None,
    avoid_therapists=None,
    patient_id=None,
    allow_helping_fallback=False,
    patient_age=None,
    *,
    config: TherapistAllocationConfig = SCHEDULING_THERAPIST_CONFIG,
):
    """
    Allocate therapists for a therapy slot while preserving all scheduling and
    rescheduling rules controlled by `config`.
    """
    from masters.models import TherapistMaster, is_therapist_omitted_for_treatment
    from Patient.models import TherapistBooking

    allocated = []

    # Check if patient is VIP
    is_vip = False
    if patient_id:
        try:
            from Sheduling.vip_service import is_patient_vip
            is_vip = is_patient_vip(patient_id)
        except Exception:
            is_vip = False

    # If patient_age not passed directly, attempt lookup via patient_id
    if patient_age is None and patient_id:
        try:
            from Sheduling.models import PatientSnapshot
            ps = PatientSnapshot.objects.filter(pat_reg_no=str(patient_id)).first()
            if ps and ps.pat_age:
                patient_age = ps.pat_age
        except Exception:
            pass

    # Retrieve active doctor-approved unpreferred therapist preferences for exclusion
    unpreferred_codes = set()
    if patient_id:
        try:
            from Sheduling.preference_views import get_active_patient_therapist_preferences
            _, pref_u = get_active_patient_therapist_preferences(patient_id)
            unpreferred_codes.update(pref_u)
        except Exception as e:
            print(f"[DEBUG TherapistPref] Error fetching preferences for patient {patient_id}: {e}")

    # Retrieve active preferred therapist roster (VIP & Repeated patients)
    preferred_roster_info = None
    if patient_id:
        try:
            from Sheduling.preferred_therapist_service import get_active_preferred_roster
            preferred_roster_info = get_active_preferred_roster(patient_id)
        except Exception as e:
            print(f"[DEBUG PreferredRoster] Error checking roster for patient {patient_id}: {e}")

    # Build exclusion set
    if config.support_avoid_therapists:
        # For VIP patients, avoid_therapists (continuity locks of other patients) do NOT block VIP
        if is_vip:
            exclusion_set = set(unpreferred_codes)
        else:
            exclusion_set = set(avoid_therapists or [])
            if unpreferred_codes:
                exclusion_set.update(unpreferred_codes)
    else:
        exclusion_set = set(unpreferred_codes)

    # Preload availability context (leaves, deputation, omission, shift, difficulty category)
    avail_ctx = TherapistAvailabilityContext(date, time_slot, therapy_requirements)

    if avail_ctx.omitted_codes:
        exclusion_set.update(avail_ctx.omitted_codes)

    # Clean last_therapists list
    if last_therapists:
        if unpreferred_codes:
            last_therapists = [c for c in last_therapists if c not in unpreferred_codes]
        if avail_ctx.omitted_codes:
            last_therapists = [c for c in last_therapists if c not in avail_ctx.omitted_codes]
        if config.filter_helping_from_last_therapists:
            filtered_last = []
            for c in last_therapists:
                try:
                    tm = TherapistMaster.objects.filter(therapist_code=c, is_active=True).first()
                    if tm and getattr(tm, 'is_helping_therapist', False):
                        continue
                    filtered_last.append(c)
                except Exception:
                    filtered_last.append(c)
            last_therapists = filtered_last

    # Normalize patient gender (Rule: Male children below 5 should be assigned to a female therapist)
    desired_gender = resolve_desired_gender(patient_gender, patient_age)

    grade_map = {
        "Super Senior Therapist": therapy_requirements.get("super_senior", 0),
        "Senior Therapist": therapy_requirements.get("senior", 0),
        "Junior Therapist": therapy_requirements.get("junior", 0),
        "Trainee Therapist": therapy_requirements.get("trainee", 0),
    }

    bathing_therapists_count = (therapy_requirements or {}).get("bathing_therapists_count", 0) or 0
    total_required = (therapy_requirements or {}).get("total") or sum(v for v in grade_map.values() if v > 0)
    num_bathing_needed = bathing_therapists_count if bathing_therapists_count > 0 else (1 if needs_bathing else 0)

    def _get_vip_displacement_exclusions(target_t=None):
        ex = set(exclusion_set)
        if preferred_roster_info:
            ex.update(preferred_roster_info.get('therapist_codes', []))
        ex.update(getattr(a, 'therapist_code', '') for a in allocated if getattr(a, 'therapist_code', None))
        if target_t and getattr(target_t, 'therapist_code', None):
            ex.add(getattr(target_t, 'therapist_code', ''))
        return ex

    def _try_vip_displacement(target_t) -> bool:
        if not (is_vip and config.allow_vip_displacement):
            return False
        from Sheduling.preferred_therapist_service import displace_non_vip_therapist_for_slot

        return bool(
            displace_non_vip_therapist_for_slot(
                target_t,
                date,
                time_slot,
                exclude_therapist_codes=_get_vip_displacement_exclusions(target_t),
            )
        )

    def check_grade_availability(grade, gender_filter, is_helping=False):
        """Check how many therapists of a specific grade and gender are available."""
        candidates_qs = TherapistMaster.objects.filter(
            therapist_grade__name__iexact=grade,
            is_active=True,
            is_helping_therapist=is_helping,
        )
        if not config.enforce_five_then_six_cap and exclusion_set:
            candidates_qs = candidates_qs.exclude(therapist_code__in=exclusion_set)
        if gender_filter:
            candidates_qs = candidates_qs.filter(therapist_gender__istartswith=gender_filter[0])

        available_count = 0
        for t in candidates_qs:
            if t in allocated:
                continue
            if avail_ctx.is_shift_blocked(t):
                continue
            if avail_ctx.is_on_leave(t):
                continue
            if avail_ctx.is_booked_at_slot(t):
                continue
            if config.enforce_five_then_six_cap:
                if (
                    not avail_ctx.can_assign(t, allocated=allocated, allow_extra=False)
                    and not avail_ctx.can_assign(t, allocated=allocated, allow_extra=True)
                ):
                    continue
            else:
                if avail_ctx.get_daily_session_count(t, allocated=allocated) >= 6:
                    continue
            available_count += 1
        return available_count

    def _find_and_allocate_candidates(target_grade, needed_original, is_helping_flag=False):
        needed = needed_original
        if needed <= 0:
            return 0

        if is_helping_flag and config.helping_substitution_strict:
            substitution_hierarchy = {
                "Trainee Therapist": ["Junior Therapist", "Senior Therapist"],
                "Junior Therapist": ["Senior Therapist"],
                "Senior Therapist": [],
                "Super Senior Therapist": [],
            }
        else:
            substitution_hierarchy = {
                "Trainee Therapist": ["Junior Therapist", "Senior Therapist", "Super Senior Therapist"],
                "Junior Therapist": ["Senior Therapist", "Super Senior Therapist", "Trainee Therapist"],
                "Senior Therapist": ["Super Senior Therapist", "Junior Therapist", "Trainee Therapist"],
                "Super Senior Therapist": ["Senior Therapist", "Junior Therapist", "Trainee Therapist"],
            }

        search_grades = [target_grade] + substitution_hierarchy.get(target_grade, [])
        assigned_cnt = 0

        for current_grade_search in search_grades:
            if needed <= 0:
                break

            if preferred_roster_info:
                # Candidate pool is strictly the roster (do not filter by is_helping_therapist)
                candidates_qs = TherapistMaster.objects.filter(
                    therapist_grade__name__iexact=current_grade_search,
                    is_active=True,
                    therapist_code__in=preferred_roster_info['therapist_codes_set'],
                )
            else:
                candidates_qs = TherapistMaster.objects.filter(
                    therapist_grade__name__iexact=current_grade_search,
                    is_active=True,
                    is_helping_therapist=is_helping_flag,
                )

            if exclusion_set:
                candidates_qs = candidates_qs.exclude(therapist_code__in=exclusion_set)

            if desired_gender:
                candidates_qs = candidates_qs.filter(therapist_gender__istartswith=desired_gender[0])

            current_bath_allocated = sum(1 for a in allocated if getattr(a, 'is_bathing_therapist', False))
            bathing_still_needed = max(0, num_bathing_needed - current_bath_allocated)
            if bathing_still_needed > 0 and (total_required - len(allocated) <= bathing_still_needed):
                candidates_qs = candidates_qs.filter(is_bathing_therapist=True)

            candidates_list = list(candidates_qs)
            available_candidates = []
            for t in candidates_list:
                if t in allocated:
                    continue
                if avail_ctx.is_on_leave(t):
                    continue
                if avail_ctx.is_shift_blocked(t):
                    continue
                if avail_ctx.is_booked_at_slot(t):
                    if not _try_vip_displacement(t):
                        continue

                if desired_gender and get_therapist_gender(t) != desired_gender:
                    continue

                session_count = avail_ctx.get_daily_session_count(t, allocated=allocated)
                category_session_count = avail_ctx.get_daily_category_count(t)
                if config.enforce_five_then_six_cap:
                    if is_vip or session_count < 5 or session_count == 5:
                        available_candidates.append((t, category_session_count, session_count))
                else:
                    available_candidates.append((t, category_session_count, session_count))

            available_candidates.sort(
                key=lambda x: (
                    0 if (bathing_still_needed > 0 and getattr(x[0], 'is_bathing_therapist', False)) else 1,
                    x[1],
                    x[2],
                    getattr(x[0], "id", 0) or 0,
                )
            )

            ordered_candidates = available_candidates
            if config.support_avoid_therapists and avoid_therapists:
                try:
                    avoid_set = set(avoid_therapists)
                except TypeError:
                    avoid_set = set(str(c) for c in (avoid_therapists or []))

                primary = []
                secondary = []
                for cand in available_candidates:
                    t = cand[0]
                    code = getattr(t, "therapist_code", None)
                    if code and code in avoid_set:
                        secondary.append(cand)
                    else:
                        primary.append(cand)
                ordered_candidates = primary + secondary

            if config.enforce_five_then_six_cap:
                all_at_limit = (
                    all(total_count >= 5 for _, _, total_count in ordered_candidates)
                    if ordered_candidates
                    else False
                )
                allow_extra = all_at_limit
            else:
                allow_extra = True

            for t, _category_session_count, session_count in ordered_candidates:
                if needed <= 0:
                    break
                if not is_vip:
                    if config.enforce_five_then_six_cap:
                        if not allow_extra and session_count >= 5:
                            continue
                        if allow_extra and session_count >= 6:
                            continue
                    else:
                        if session_count >= 6:
                            continue

                if bathing_still_needed > 0 and (total_required - len(allocated) <= bathing_still_needed):
                    if not getattr(t, 'is_bathing_therapist', False):
                        continue

                allocated.append(t)
                needed -= 1
                assigned_cnt += 1

                if is_helping_flag:
                    _log_helping_therapist_allocation(
                        enabled=config.create_audit_logs,
                        patient_id=patient_id,
                        therapist=t,
                        date=date,
                        time_slot=time_slot,
                        therapy_requirements=therapy_requirements,
                        reason_for_fallback="Primary therapist shortage/failure",
                        shortage_condition=(
                            f"Therapist shortage detected for grade {target_grade} on {date} slot {time_slot}. "
                            "Primary therapist pool exhausted or unavailable."
                        ),
                    )

            # VIP Fallback: if patient has preferred roster but this grade could not be fully satisfied from roster
            if is_vip and needed > 0 and preferred_roster_info:
                has_other_vip_conflict = False
                pref_codes = preferred_roster_info.get('therapist_codes', [])
                for p_code in pref_codes:
                    conf_tb_qs = TherapistBooking.objects.filter(
                        date=date,
                        time_slot=time_slot,
                        therapist__therapist_code=p_code,
                        status='BOOKED',
                    )
                    if patient_id:
                        if str(patient_id).isdigit():
                            conf_tb_qs = conf_tb_qs.exclude(patient_id=int(patient_id))
                        conf_tb_qs = conf_tb_qs.exclude(visit__patient__pat_reg_no=str(patient_id))
                    for conf_tb in conf_tb_qs:
                        c_pat = getattr(getattr(conf_tb, 'visit', None), 'patient', None)
                        if patient_id and (
                            getattr(c_pat, 'pat_reg_no', None) == str(patient_id)
                            or str(conf_tb.patient_id) == str(patient_id)
                        ):
                            continue
                        from Sheduling.vip_service import is_patient_vip
                        if is_patient_vip(c_pat) or is_patient_vip(conf_tb.patient_id):
                            has_other_vip_conflict = True
                            break
                    if has_other_vip_conflict:
                        break

                if not has_other_vip_conflict:
                    fb_qs = TherapistMaster.objects.filter(
                        therapist_grade__name__iexact=current_grade_search,
                        is_active=True,
                    ).exclude(therapist_code__in=preferred_roster_info.get('therapist_codes_set', set()))
                    if exclusion_set:
                        fb_qs = fb_qs.exclude(therapist_code__in=exclusion_set)
                    if desired_gender:
                        fb_qs = fb_qs.filter(therapist_gender__istartswith=desired_gender[0])
                    for fb_t in fb_qs:
                        if needed <= 0:
                            break
                        if fb_t in allocated or avail_ctx.is_on_leave(fb_t):
                            continue
                        if avail_ctx.is_shift_blocked(fb_t):
                            continue
                        if avail_ctx.is_booked_at_slot(fb_t):
                            if not _try_vip_displacement(fb_t):
                                continue
                        if bathing_still_needed > 0 and (total_required - len(allocated) <= bathing_still_needed):
                            if not getattr(fb_t, 'is_bathing_therapist', False):
                                continue
                        allocated.append(fb_t)
                        needed -= 1
                        assigned_cnt += 1

        return assigned_cnt

    def _pick_helping_therapist():
        if preferred_roster_info and not is_vip:
            return None
        ht_qs = TherapistMaster.objects.filter(is_active=True, is_helping_therapist=True)
        if exclusion_set:
            ht_qs = ht_qs.exclude(therapist_code__in=exclusion_set)
        if desired_gender:
            ht_qs = ht_qs.filter(therapist_gender__istartswith=desired_gender[0])

        candidates = []
        for t in ht_qs:
            if t in allocated:
                continue
            if avail_ctx.is_on_leave(t):
                continue
            if avail_ctx.is_shift_blocked(t):
                continue
            if avail_ctx.is_booked_at_slot(t):
                if not _try_vip_displacement(t):
                    continue
            if desired_gender and get_therapist_gender(t) != desired_gender:
                continue
            total_sessions = avail_ctx.get_daily_session_count(t, allocated=allocated)
            if not is_vip and total_sessions >= 6:
                continue
            category_sessions = avail_ctx.get_daily_category_count(t)

            t_grade = get_therapist_grade_name(t)
            grade_score = 2
            if grade_map.get(t_grade, 0) > 0:
                grade_score = 0
            else:
                for req_g, cnt in grade_map.items():
                    if cnt > 0:
                        if t_grade == "Super Senior Therapist":
                            grade_score = 1
                            break
                        elif t_grade == "Senior Therapist" and req_g in ["Junior Therapist", "Trainee Therapist"]:
                            grade_score = 1
                            break
                        elif t_grade == "Junior Therapist" and req_g in ["Trainee Therapist"]:
                            grade_score = 1
                            break

            bath_score = 0 if (needs_bathing and getattr(t, 'is_bathing_therapist', False)) else 1
            candidates.append((grade_score, bath_score, category_sessions, total_sessions, getattr(t, 'id', 0), t))

        if not candidates:
            return None
        candidates.sort(key=lambda x: (x[0], x[1], x[2], x[3], x[4]))
        return candidates[0][5]

    # -----------------------
    # STEP 1 – Normal Scheduling (First Attempt: consider only is_helping_therapist=False)
    # -----------------------
    # PREFERRED ROSTER: Designate & Allocate Bathing Therapist FIRST
    if preferred_roster_info and needs_bathing:
        current_bath_allocated = sum(1 for a in allocated if getattr(a, 'is_bathing_therapist', False))
        if current_bath_allocated < num_bathing_needed:
            try:
                from Sheduling.preferred_therapist_service import pick_bathing_therapist_from_roster

                picker_kwargs = dict(
                    is_vip=is_vip and config.allow_vip_displacement,
                    exclude_therapist_codes=_get_vip_displacement_exclusions(),
                )
                if config.pass_therapy_name_to_bathing_picker:
                    picker_kwargs['therapy_name'] = avail_ctx.th_code_req or avail_ctx.th_name_req
                picked_bath, bath_role = pick_bathing_therapist_from_roster(
                    preferred_roster_info, date, time_slot, **picker_kwargs
                )
                if picked_bath and picked_bath not in allocated:
                    bath_avail = True
                    if avail_ctx.is_on_leave(picked_bath):
                        bath_avail = False
                    elif (avail_ctx.th_code_req or avail_ctx.th_name_req) and is_therapist_omitted_for_treatment(
                        picked_bath, avail_ctx.th_code_req or avail_ctx.th_name_req
                    ):
                        bath_avail = False
                    elif avail_ctx.is_shift_blocked(picked_bath):
                        bath_avail = False
                    elif avail_ctx.is_booked_at_slot(picked_bath):
                        if not _try_vip_displacement(picked_bath):
                            bath_avail = False
                    elif desired_gender and get_therapist_gender(picked_bath) != desired_gender:
                        bath_avail = False
                    elif exclusion_set and picked_bath.therapist_code in exclusion_set:
                        bath_avail = False
                    elif (
                        not is_vip
                        and not avail_ctx.can_assign(picked_bath, allocated=allocated, allow_extra=False)
                        and not avail_ctx.can_assign(picked_bath, allocated=allocated, allow_extra=True)
                    ):
                        bath_avail = False

                    if bath_avail:
                        allocated.append(picked_bath)
                        bath_grade = get_therapist_grade_name(picked_bath)
                        if grade_map.get(bath_grade, 0) > 0:
                            grade_map[bath_grade] -= 1
                        else:
                            sub_hierarchy = {
                                "Trainee Therapist": ["Junior Therapist", "Senior Therapist", "Super Senior Therapist"],
                                "Junior Therapist": ["Senior Therapist", "Super Senior Therapist", "Trainee Therapist"],
                                "Senior Therapist": ["Super Senior Therapist", "Junior Therapist", "Trainee Therapist"],
                                "Super Senior Therapist": ["Senior Therapist", "Junior Therapist", "Trainee Therapist"],
                            }
                            decremented = False
                            for g in sub_hierarchy.get(bath_grade, []):
                                if grade_map.get(g, 0) > 0:
                                    grade_map[g] -= 1
                                    decremented = True
                                    break
                            if not decremented:
                                for g in ["Trainee Therapist", "Junior Therapist", "Senior Therapist", "Super Senior Therapist"]:
                                    if grade_map.get(g, 0) > 0:
                                        grade_map[g] -= 1
                                        break
                        print(
                            f"[PREFERRED ROSTER] Pre-allocated designated bathing therapist "
                            f"{picked_bath.therapist_code} ({bath_role}, {bath_grade})"
                        )
            except Exception as e:
                print(f"[PREFERRED ROSTER] Error resolving designated bathing therapist: {e}")

    if last_therapists:
        for code in last_therapists:
            if config.mode == "scheduling":
                if preferred_roster_info and code not in preferred_roster_info.get('therapist_codes_set', set()):
                    continue
                if exclusion_set and code in exclusion_set:
                    continue
            try:
                t = TherapistMaster.objects.get(therapist_code=code, is_active=True)
                if t in allocated:
                    continue
                if getattr(t, 'is_helping_therapist', False):
                    if not (preferred_roster_info and t.therapist_code in preferred_roster_info['therapist_codes_set']):
                        continue
            except TherapistMaster.DoesNotExist:
                continue

            therapist_grade_name = get_therapist_grade_name(t)
            grade_substitution_map = {
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
                for needed_grade, substitutes in grade_substitution_map.items():
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
                priority_order = ["Trainee Therapist", "Junior Therapist", "Senior Therapist", "Super Senior Therapist"]
                for priority_grade in priority_order:
                    if grade_map.get(priority_grade, 0) > 0:
                        grade_to_decrement = priority_grade
                        break

            if desired_gender and get_therapist_gender(t) != desired_gender:
                continue
            if config.last_therapist_bathing_guard:
                has_bath_allocated = any(getattr(a, 'is_bathing_therapist', False) for a in allocated)
                if (
                    needs_bathing
                    and not has_bath_allocated
                    and (total_required - len(allocated) <= 1)
                    and not getattr(t, 'is_bathing_therapist', False)
                ):
                    continue
            if avail_ctx.is_on_leave(t):
                continue
            if avail_ctx.is_shift_blocked(t):
                continue
            if avail_ctx.is_booked_at_slot(t):
                if not _try_vip_displacement(t):
                    continue

            if not is_vip:
                if config.enforce_five_then_six_cap:
                    if not avail_ctx.can_assign(t, allocated=allocated, allow_extra=False):
                        if not avail_ctx.can_assign(t, allocated=allocated, allow_extra=True):
                            continue
                else:
                    if avail_ctx.get_daily_session_count(t, allocated=allocated) >= 6:
                        continue

            allocated.append(t)
            if grade_to_decrement and grade_map.get(grade_to_decrement, 0) > 0:
                grade_map[grade_to_decrement] -= 1

    # Rescheduling mode: proactively allocate a helping therapist before primary pool when requested
    if config.guarantee_helping_therapist and (allow_helping_fallback or is_vip) and len(allocated) < total_required:
        ht = _pick_helping_therapist()
        if ht:
            allocated.append(ht)
            ht_grade = get_therapist_grade_name(ht)
            if grade_map.get(ht_grade, 0) > 0:
                grade_map[ht_grade] -= 1
            else:
                decremented = False
                for g in ["Trainee Therapist", "Junior Therapist", "Senior Therapist", "Super Senior Therapist"]:
                    if grade_map.get(g, 0) > 0:
                        grade_map[g] -= 1
                        decremented = True
                        break
                if not decremented:
                    for g, c in grade_map.items():
                        if c > 0:
                            grade_map[g] -= 1
                            break
            _log_helping_therapist_allocation(
                enabled=config.create_audit_logs,
                patient_id=patient_id,
                therapist=ht,
                date=date,
                time_slot=time_slot,
                therapy_requirements=therapy_requirements,
                reason_for_fallback="Reschedule with helping therapist requested",
                shortage_condition=f"Assigned Helping Therapist {ht.therapist_code} ({ht_grade}) on {date} slot {time_slot}",
            )

    # Allocate remaining using Normal Primary Therapists (is_helping_therapist=False)
    for grade, needed_original in list(grade_map.items()):
        if needed_original <= 0:
            continue
        if config.guarantee_helping_therapist and len(allocated) >= total_required:
            continue
        assigned_cnt = _find_and_allocate_candidates(grade, needed_original, is_helping_flag=False)
        grade_map[grade] -= assigned_cnt

    # If additional therapists are still required (total_required > len(allocated))
    if len(allocated) < total_required:
        needed_additional = total_required - len(allocated)
        candidate_grades = ["Trainee Therapist", "Junior Therapist", "Senior Therapist", "Super Senior Therapist"]
        grade_availabilities = [
            (g, check_grade_availability(g, desired_gender, is_helping=False))
            for g in candidate_grades
        ]
        grade_availabilities.sort(key=lambda x: x[1], reverse=True)

        for g, avail in grade_availabilities:
            if needed_additional <= 0:
                break
            if avail > 0:
                assigned = _find_and_allocate_candidates(g, needed_additional, is_helping_flag=False)
                needed_additional -= assigned

    # -----------------------
    # STEP 2 & 3 – Helping Therapist Fallback & Rescheduling Guarantee
    # -----------------------
    if config.guarantee_helping_therapist:
        # Rescheduling mode: allocate additional helping therapists if still short
        while allow_helping_fallback and len(allocated) < total_required:
            extra_ht = _pick_helping_therapist()
            if not extra_ht:
                break
            allocated.append(extra_ht)
            ht_grade = get_therapist_grade_name(extra_ht)
            for g in ["Trainee Therapist", "Junior Therapist", "Senior Therapist", "Super Senior Therapist"]:
                if grade_map.get(g, 0) > 0:
                    grade_map[g] -= 1
                    break
            _log_helping_therapist_allocation(
                enabled=config.create_audit_logs,
                patient_id=patient_id,
                therapist=extra_ht,
                date=date,
                time_slot=time_slot,
                therapy_requirements=therapy_requirements,
                reason_for_fallback="Primary therapist shortage/failure",
                shortage_condition=f"Assigned additional Helping Therapist {extra_ht.therapist_code} ({ht_grade}) on {date} slot {time_slot}",
            )

        # FINAL GUARANTEE: If allow_helping_fallback is True, ensure at least ONE helping therapist is included
        if allow_helping_fallback and len(allocated) >= total_required:
            has_ht = any(getattr(t, 'is_helping_therapist', False) for t in allocated)
            if not has_ht:
                ht = _pick_helping_therapist()
                if ht:
                    continuity_codes = set(last_therapists or [])
                    replaced = False
                    for idx in range(len(allocated) - 1, -1, -1):
                        cand = allocated[idx]
                        cand_code = getattr(cand, 'therapist_code', None)
                        if cand_code not in continuity_codes:
                            allocated[idx] = ht
                            replaced = True
                            break
                    if not replaced and len(allocated) > 0:
                        allocated[-1] = ht
                    _log_helping_therapist_allocation(
                        enabled=config.create_audit_logs,
                        patient_id=patient_id,
                        therapist=ht,
                        date=date,
                        time_slot=time_slot,
                        therapy_requirements=therapy_requirements,
                        reason_for_fallback="Guarantee Helping Therapist inclusion on reschedule",
                        shortage_condition=f"Replaced regular therapist with Helping Therapist {ht.therapist_code} on {date} slot {time_slot}",
                    )
    else:
        # Scheduling mode: helping therapist fallback only on shortage
        shortage = total_required - len(allocated)
        if shortage > 0 and (allow_helping_fallback or is_vip):
            if last_therapists:
                for code in last_therapists:
                    if len(allocated) >= total_required:
                        break
                    try:
                        t = TherapistMaster.objects.get(
                            therapist_code=code, is_active=True, is_helping_therapist=True
                        )
                    except TherapistMaster.DoesNotExist:
                        continue
                    if t in allocated or avail_ctx.is_on_leave(t):
                        continue
                    if avail_ctx.is_shift_blocked(t):
                        continue
                    if avail_ctx.is_booked_at_slot(t):
                        if not _try_vip_displacement(t):
                            continue
                    if desired_gender and get_therapist_gender(t) != desired_gender:
                        continue
                    if needs_bathing and not t.is_bathing_therapist:
                        continue
                    if not is_vip and not avail_ctx.can_assign(t, allocated=allocated, allow_extra=True):
                        continue

                    allocated.append(t)
                    _log_helping_therapist_allocation(
                        enabled=config.create_audit_logs,
                        patient_id=patient_id,
                        therapist=t,
                        date=date,
                        time_slot=time_slot,
                        therapy_requirements=therapy_requirements,
                        reason_for_fallback="Primary therapist shortage/failure",
                        shortage_condition="Continuity Helping Therapist fallback triggered due to primary therapist shortage.",
                    )

            for grade, needed_original in list(grade_map.items()):
                if needed_original <= 0:
                    continue
                assigned_cnt = _find_and_allocate_candidates(grade, needed_original, is_helping_flag=True)
                grade_map[grade] -= assigned_cnt

    return allocated


def allocate_therapists_with_grade_substitution(
    date,
    time_slot,
    therapy_requirements,
    last_therapists=None,
    needs_bathing=False,
    patient_gender=None,
    allow_helping_fallback=False,
    patient_age=None,
    patient_id=None,
    *,
    create_audit_logs: bool = True,
):
    """
    Fallback allocation function that allows aggressive grade substitution:
    - Senior/Super Senior can substitute for Junior/Trainee when they're unavailable
    - Senior and Super Senior can substitute for each other (bidirectional)
    """
    from masters.models import TherapistMaster

    allocated = []
    exclusion_set = set()

    if patient_id:
        try:
            from Sheduling.preference_views import get_active_patient_therapist_preferences
            _, pref_u = get_active_patient_therapist_preferences(patient_id)
            if pref_u:
                exclusion_set.update(pref_u)
                if last_therapists:
                    last_therapists = [c for c in last_therapists if c not in pref_u]
        except Exception as e:
            print(f"[DEBUG TherapistPref fallback] Error for patient {patient_id}: {e}")

    avail_ctx = TherapistAvailabilityContext(date, time_slot, therapy_requirements)

    if avail_ctx.omitted_codes:
        exclusion_set.update(avail_ctx.omitted_codes)
        if last_therapists:
            last_therapists = [c for c in last_therapists if c not in avail_ctx.omitted_codes]

    desired_gender = resolve_desired_gender(patient_gender, patient_age)

    grade_map = {
        "Super Senior Therapist": therapy_requirements.get("super_senior", 0),
        "Senior Therapist": therapy_requirements.get("senior", 0),
        "Junior Therapist": therapy_requirements.get("junior", 0),
        "Trainee Therapist": therapy_requirements.get("trainee", 0),
    }

    # Use last therapists first (if available)
    if last_therapists:
        for code in last_therapists:
            try:
                t = TherapistMaster.objects.get(therapist_code=code, is_active=True)
            except TherapistMaster.DoesNotExist:
                continue
            therapist_grade_name = get_therapist_grade_name(t)

            can_use = False
            target_grade = None

            if grade_map.get(therapist_grade_name, 0) > 0:
                can_use = True
                target_grade = therapist_grade_name
            elif therapist_grade_name == "Senior Therapist":
                if grade_map.get("Super Senior Therapist", 0) > 0:
                    can_use = True
                    target_grade = "Super Senior Therapist"
                elif grade_map.get("Junior Therapist", 0) > 0:
                    can_use = True
                    target_grade = "Junior Therapist"
                elif grade_map.get("Trainee Therapist", 0) > 0:
                    can_use = True
                    target_grade = "Trainee Therapist"
            elif therapist_grade_name == "Super Senior Therapist":
                if grade_map.get("Senior Therapist", 0) > 0:
                    can_use = True
                    target_grade = "Senior Therapist"
                elif grade_map.get("Junior Therapist", 0) > 0:
                    can_use = True
                    target_grade = "Junior Therapist"
                elif grade_map.get("Trainee Therapist", 0) > 0:
                    can_use = True
                    target_grade = "Trainee Therapist"

            if not can_use:
                continue

            if desired_gender and get_therapist_gender(t) != desired_gender:
                continue
            has_bath_allocated = any(getattr(a, 'is_bathing_therapist', False) for a in allocated)
            if (
                needs_bathing
                and not has_bath_allocated
                and (sum(grade_map.values()) <= 1)
                and not getattr(t, 'is_bathing_therapist', False)
            ):
                continue
            if avail_ctx.is_on_leave(t):
                continue
            if avail_ctx.is_booked_at_slot(t):
                continue
            if avail_ctx.is_shift_blocked(t):
                continue

            if avail_ctx.get_daily_session_count(t) >= 6:
                continue

            allocated.append(t)
            grade_map[target_grade] -= 1

    # Allocate remaining with aggressive substitution
    grade_order = ["Trainee Therapist", "Junior Therapist", "Senior Therapist", "Super Senior Therapist"]

    for target_grade in grade_order:
        needed = grade_map.get(target_grade, 0)
        if needed <= 0:
            continue

        if target_grade == "Trainee Therapist":
            substitution_grades = ["Junior Therapist", "Senior Therapist", "Super Senior Therapist"]
        elif target_grade == "Junior Therapist":
            substitution_grades = ["Senior Therapist", "Super Senior Therapist"]
        elif target_grade == "Senior Therapist":
            substitution_grades = ["Super Senior Therapist"]
        elif target_grade == "Super Senior Therapist":
            substitution_grades = ["Senior Therapist"]
        else:
            substitution_grades = []

        grades_to_try = [target_grade] + substitution_grades

        for search_grade in grades_to_try:
            if needed <= 0:
                break

            _p_roster = None
            if patient_id:
                try:
                    from Sheduling.preferred_therapist_service import get_active_preferred_roster
                    _p_roster = get_active_preferred_roster(patient_id)
                except Exception:
                    _p_roster = None

            if _p_roster:
                candidates_qs = TherapistMaster.objects.filter(
                    therapist_grade__name=search_grade,
                    is_active=True,
                    therapist_code__in=_p_roster['therapist_codes_set'],
                )
            else:
                candidates_qs = TherapistMaster.objects.filter(
                    therapist_grade__name=search_grade,
                    is_active=True,
                    is_helping_therapist=False,
                )
            if exclusion_set:
                candidates_qs = candidates_qs.exclude(therapist_code__in=exclusion_set)
            if desired_gender:
                candidates_qs = candidates_qs.filter(therapist_gender__istartswith=desired_gender[0])

            has_bath_allocated = any(getattr(a, 'is_bathing_therapist', False) for a in allocated)
            if needs_bathing and not has_bath_allocated and (sum(grade_map.values()) <= 1):
                candidates_qs = candidates_qs.filter(is_bathing_therapist=True)

            scored_candidates = []
            for t in list(candidates_qs):
                if t in allocated:
                    continue
                if avail_ctx.is_on_leave(t):
                    continue
                if avail_ctx.is_booked_at_slot(t):
                    continue
                if avail_ctx.is_shift_blocked(t):
                    continue
                if desired_gender and get_therapist_gender(t) != desired_gender:
                    continue

                session_count = avail_ctx.get_daily_session_count(t)
                scored_candidates.append((t, session_count))

            scored_candidates.sort(
                key=lambda x: (
                    0 if (needs_bathing and not has_bath_allocated and getattr(x[0], 'is_bathing_therapist', False)) else 1,
                    x[1],
                    getattr(x[0], "id", 0) or 0,
                )
            )

            for t, session_count in scored_candidates:
                if needed <= 0:
                    break
                if session_count >= 6:
                    continue
                if (
                    needs_bathing
                    and (sum(grade_map.values()) <= 1)
                    and not any(getattr(a, 'is_bathing_therapist', False) for a in allocated)
                ):
                    if not getattr(t, 'is_bathing_therapist', False):
                        continue

                allocated.append(t)
                needed -= 1
                grade_map[target_grade] -= 1

    total_required = sum(grade_map.values()) + len(allocated)
    shortage = total_required - len(allocated)
    if shortage > 0 and allow_helping_fallback:
        ht_qs = TherapistMaster.objects.filter(is_active=True, is_helping_therapist=True)
        if desired_gender:
            ht_qs = ht_qs.filter(therapist_gender__istartswith=desired_gender[0])
        if needs_bathing:
            ht_qs = ht_qs.filter(is_bathing_therapist=True)

        for ht in ht_qs:
            if len(allocated) >= total_required:
                break
            if ht in allocated or avail_ctx.is_on_leave(ht):
                continue
            if avail_ctx.is_shift_blocked(ht):
                continue
            if avail_ctx.is_booked_at_slot(ht):
                continue
            if avail_ctx.get_daily_session_count(ht) >= 6:
                continue

            allocated.append(ht)
            _log_helping_therapist_allocation(
                enabled=create_audit_logs,
                patient_id='',
                therapist=ht,
                date=date,
                time_slot=time_slot,
                therapy_requirements=therapy_requirements,
                reason_for_fallback="Reschedule same-slot helping therapist fallback",
                shortage_condition=f"Assigned Helping Therapist {ht.therapist_code} in same slot {time_slot} during rescheduling",
            )

    # FINAL GUARANTEE for fallback grade substitution: ensure at least one helping therapist is included
    if allow_helping_fallback and len(allocated) >= total_required:
        has_ht = any(getattr(t, 'is_helping_therapist', False) for t in allocated)
        if not has_ht:
            ht_qs = TherapistMaster.objects.filter(is_active=True, is_helping_therapist=True)
            if desired_gender:
                ht_qs = ht_qs.filter(therapist_gender__istartswith=desired_gender[0])
            for ht in ht_qs:
                if ht in allocated or avail_ctx.is_on_leave(ht):
                    continue
                if avail_ctx.is_shift_blocked(ht):
                    continue
                if avail_ctx.is_booked_at_slot(ht):
                    continue
                if avail_ctx.get_daily_session_count(ht) >= 6:
                    continue
                continuity_codes = set(last_therapists or [])
                replaced = False
                for idx in range(len(allocated) - 1, -1, -1):
                    cand = allocated[idx]
                    cand_code = getattr(cand, 'therapist_code', None)
                    if cand_code not in continuity_codes:
                        allocated[idx] = ht
                        replaced = True
                        break
                if not replaced and len(allocated) > 0:
                    allocated[-1] = ht
                break

    return allocated


def make_readonly_therapist_config(base_config: TherapistAllocationConfig) -> TherapistAllocationConfig:
    """Return a copy of `base_config` with all DB writes (audit logs + VIP displacement) disabled."""
    return replace(base_config, create_audit_logs=False, allow_vip_displacement=False)
