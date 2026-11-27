"""
Scheduling Pass-0 Continuity Plan Builder (Layer 3A).

Builds `TherapistContinuityPlan` rows for a target date and returns `slot_avoid_map`
(`dict[slot_id, set[therapist_code]]`) used by scheduling Pass 2.

Must NEVER import `allocation_engine.rescheduling`, `reshedule`, or `resheduleMorningandNight`.
"""


def build_continuity_plan_for_date(target_date):
    """
    Build TherapistContinuityPlan rows for all draft bookings on `target_date`
    and return `slot_avoid_map` mapping `time_slot_id -> set[therapist_code]`.
    """
    from Sheduling.models import TherapistContinuityPlan

    # ---------------------------------------
    # Phase 1: Build continuity plan in DB
    # ---------------------------------------
    try:
        from Sheduling.models import Booking as _Booking
        from Patient.models import TherapistBooking as _TB
        from masters.models import SlotMaster as _SlotMaster, TherapistMaster as _TM, TherapyMaster as _ThM
        from django.db.models import Max, Q

        # Clear existing plan for this date
        TherapistContinuityPlan.objects.filter(date=target_date).delete()

        # Draft bookings for this date
        draft_bookings = _Booking.objects.filter(
            date=target_date,
            status='draft',
        ).select_related('allocation', 'timeslot', 'allocation__patient')

        for booking in draft_bookings:
            allocation = booking.allocation
            patient = getattr(allocation, 'patient', None)
            slot = booking.timeslot
            if not allocation or not patient or not slot:
                continue

            patient_snapshot_id = getattr(patient, 'id', None)
            patient_name = getattr(patient, 'pat_name', '') or ''
            current_therapy_name = allocation.therapy_name

            pref_roster = None
            try:
                from Sheduling.preferred_therapist_service import get_active_preferred_roster
                for pid_check in [patient_snapshot_id, getattr(patient, 'pat_reg_no', None)]:
                    if not pid_check:
                        continue
                    pref_roster = get_active_preferred_roster(pid_check)
                    if pref_roster:
                        break
            except Exception:
                pref_roster = None

            # Resolve TherapyMaster for robust matching
            therapy_obj = None
            therapy_code = getattr(allocation, 'therapy_code', None)
            if therapy_code:
                therapy_obj = _ThM.objects.filter(therapy_code=therapy_code).first()
            if not therapy_obj and current_therapy_name:
                therapy_obj = _ThM.objects.filter(therapy_name__iexact=current_therapy_name).first()

            print(f"[CONTINUITY PLAN] ----")
            print(f"[CONTINUITY PLAN] Building for date={target_date}, slot={getattr(slot,'slot_time',None)}(id={getattr(slot,'id',None)}), "
                  f"patient_id={patient_snapshot_id}, patient_name='{patient_name}', therapy='{current_therapy_name}'")

            # SAME-THERAPY continuity (any slot; we will re-use therapists in today's slot)
            same_therapy_date = None
            if current_therapy_name:
                base_same_qs = _TB.objects.filter(
                    patient_id=patient_snapshot_id,
                    status='BOOKED',
                    date__lt=target_date,  # ONLY look at days before the target date
                )
                if therapy_obj:
                    # Match either by therapy FK or by case-insensitive name when therapy FK is null
                    base_same_qs = base_same_qs.filter(
                        Q(therapy=therapy_obj) | Q(therapy__isnull=True, therapy_name__iexact=current_therapy_name)
                    )
                else:
                    base_same_qs = base_same_qs.filter(therapy_name__iexact=current_therapy_name)
                same_therapy_date = base_same_qs.aggregate(Max('date'))['date__max']

            continuity_rows = []

            # PREFERRED ROSTER: Add all preferred therapists at highest priority (-3000..)
            if pref_roster and pref_roster.get('therapist_codes'):
                p_code = pref_roster.get('primary_bathing_code')
                s_code = pref_roster.get('secondary_bathing_code')
                unpref_set = pref_roster.get('unpreferred_codes_set', set())
                roster_added = 0
                for r_idx, code in enumerate(pref_roster['therapist_codes']):
                    if code in unpref_set:
                        continue
                    t_obj = _TM.objects.filter(therapist_code=code, is_active=True).first()
                    if t_obj:
                        is_bath = (code == p_code) or (code == s_code and not p_code) or bool(getattr(t_obj, 'is_bathing_therapist', False))
                        continuity_rows.append({
                            "therapist": t_obj,
                            "is_bathing": is_bath,
                            "priority": -3000 + r_idx,
                            "source_date": target_date,
                        })
                        roster_added += 1
                if roster_added:
                    print(f"[CONTINUITY PLAN]   Injected {roster_added} preferred roster therapists at top priority (-3000..)")

            # FROM START OF THERAPY: Add all therapists who have done this allocation from from_date to today (in order of first appearance).
            # Use distinct priorities (-1000, -999, ...) so order is preserved: first-day therapist always tried first when they return from leave.
            therapy_start_date = getattr(allocation, 'from_date', None)
            if therapy_start_date and slot:
                try:
                    from_start_qs = _TB.objects.filter(
                        visit_id=allocation.id,
                        date__gte=therapy_start_date,
                        date__lt=target_date,
                        time_slot=slot,
                        status='BOOKED',
                    ).select_related('therapist').order_by('date', 'created_at')
                    seen_from_start = set()
                    from_start_index = 0
                    for tb in from_start_qs:
                        if not tb.therapist:
                            continue
                        if not getattr(tb.therapist, 'is_active', True):
                            continue
                        if getattr(tb.therapist, 'is_helping_therapist', False):
                            if not (pref_roster and tb.therapist.therapist_code in pref_roster.get('therapist_codes_set', set())):
                                continue
                        tid = getattr(tb.therapist, 'id', None)
                        if tid is None or tid in seen_from_start:
                            continue
                        seen_from_start.add(tid)
                        continuity_rows.append({
                            "therapist": tb.therapist,
                            "is_bathing": bool(getattr(tb, 'is_bathing', False)),
                            "priority": -1000 + from_start_index,
                            "source_date": tb.date,
                        })
                        from_start_index += 1
                    if seen_from_start:
                        print(f"[CONTINUITY PLAN]   From start of therapy (priority -1000..): {len(seen_from_start)} therapists in order of first appearance")
                except Exception as e:
                    print(f"[CONTINUITY PLAN]   Error building from-start list: {e}")

            def _add_rows_for_date(source_date, base_priority):
                if not source_date:
                    return
                
                # First, check ALL TherapistBooking records for this patient and date (without filters)
                all_tb_for_date = _TB.objects.filter(
                    patient_id=patient_snapshot_id,
                    date=source_date,
                )
                print(f"[CONTINUITY PLAN]   DEBUG: Total TherapistBooking records for patient {patient_snapshot_id} on {source_date}: {all_tb_for_date.count()}")
                if all_tb_for_date.exists():
                    for tb_debug in all_tb_for_date[:5]:  # Show first 5 for debugging
                        print(f"[CONTINUITY PLAN]   DEBUG: TB pk={tb_debug.pk}, status={tb_debug.status}, therapy_name='{tb_debug.therapy_name}', visit_id={tb_debug.visit_id}, therapist_id={tb_debug.therapist_id}")
                
                base_prev_qs = _TB.objects.filter(
                    patient_id=patient_snapshot_id,
                    status='BOOKED',
                    date=source_date,
                )
                print(f"[CONTINUITY PLAN]   DEBUG: After status='BOOKED' filter: {base_prev_qs.count()} records")
                
                # Don't exclude visit=allocation - we want therapists from previous allocations
                # The exclude was preventing us from finding therapists from previous dates
                # base_prev_qs = base_prev_qs.exclude(visit=allocation)
                
                if base_priority in (0, 1) and current_therapy_name:
                    # Same-therapy rows
                    before_filter_count = base_prev_qs.count()
                    if therapy_obj:
                        base_prev_qs = base_prev_qs.filter(
                            Q(therapy=therapy_obj) | Q(therapy__isnull=True, therapy_name__iexact=current_therapy_name)
                        )
                    else:
                        base_prev_qs = base_prev_qs.filter(therapy_name__iexact=current_therapy_name)
                    print(f"[CONTINUITY PLAN]   DEBUG: After therapy filter (before={before_filter_count}, after={base_prev_qs.count()}): therapy_name='{current_therapy_name}', therapy_obj={therapy_obj}")
                print(f"[CONTINUITY PLAN]   Querying TherapistBooking for date {source_date}: found {base_prev_qs.count()} records")
                prev_qs = base_prev_qs.select_related('therapist')
                rows_added = 0
                for tb in prev_qs:
                    if not tb.therapist:
                        print(f"[CONTINUITY PLAN]   Skipping TherapistBooking {tb.pk} - no therapist")
                        continue
                    if not getattr(tb.therapist, 'is_active', True):
                        print(f"[CONTINUITY PLAN]   Skipping TherapistBooking {tb.pk} - therapist {tb.therapist.therapist_code} is INACTIVE")
                        continue
                    if getattr(tb.therapist, 'is_helping_therapist', False):
                        if not (pref_roster and tb.therapist.therapist_code in pref_roster.get('therapist_codes_set', set())):
                            print(f"[CONTINUITY PLAN]   Skipping TherapistBooking {tb.pk} - therapist {tb.therapist.therapist_code} is HELPING THERAPIST")
                            continue
                    # CRITICAL FIX: Only mark as bathing if the TherapistBooking record actually has is_bathing=True
                    # Do NOT use therapist.is_bathing_therapist attribute - that just means they CAN be a bathing therapist,
                    # not that they WERE the bathing therapist on this specific day
                    # Only ONE therapist per visit/date/slot should have is_bathing=True
                    tb_is_bathing = bool(getattr(tb, 'is_bathing', False))
                    therapist_can_bathe = bool(getattr(tb.therapist, 'is_bathing_therapist', False))
                    continuity_rows.append({
                        "therapist": tb.therapist,
                        "is_bathing": tb_is_bathing,  # ONLY use actual is_bathing flag from TherapistBooking
                        "priority": base_priority,
                        "source_date": source_date,
                    })
                    if tb_is_bathing:
                        print(f"[CONTINUITY PLAN]   ✓ Therapist {tb.therapist.therapist_code} marked as bathing (is_bathing=True in TherapistBooking)")
                    elif therapist_can_bathe:
                        print(f"[CONTINUITY PLAN]   ℹ Therapist {tb.therapist.therapist_code} CAN be bathing therapist but was NOT on {source_date} (is_bathing=False)")
                    rows_added += 1
                print(f"[CONTINUITY PLAN]   Added {rows_added} therapists from date {source_date} (priority {base_priority})")

            # Use MOST RECENT date (not just yesterday) - prioritize by recency
            # Always use the most recent date found, whether it's yesterday or older
            if same_therapy_date:
                # Use most recent same-therapy date (whether yesterday or older)
                print(f"[CONTINUITY PLAN]   Same-therapy most recent date: {same_therapy_date}")
                _add_rows_for_date(same_therapy_date, 0)  # Priority 0 for same-therapy regardless of how old
            else:
                print(f"[CONTINUITY PLAN]   No same-therapy history found")

            # If none found, ANY-THERAPY continuity (use most recent date)
            if not continuity_rows:
                any_date = _TB.objects.filter(
                    patient_id=patient_snapshot_id,
                    status='BOOKED',
                    date__lt=target_date,  # ONLY look at days before the target date
                ).aggregate(Max('date'))['date__max']
                if any_date:
                    print(f"[CONTINUITY PLAN]   Any-therapy most recent date: {any_date}")
                    # DEBUG: Check all records first
                    all_any_tb = _TB.objects.filter(
                        patient_id=patient_snapshot_id,
                        date=any_date,
                    )
                    print(f"[CONTINUITY PLAN]   DEBUG: Total TherapistBooking for any-therapy date {any_date}: {all_any_tb.count()}")
                    if all_any_tb.exists():
                        for tb_debug in all_any_tb[:5]:
                            print(f"[CONTINUITY PLAN]   DEBUG: TB pk={tb_debug.pk}, status='{tb_debug.status}', therapy_name='{tb_debug.therapy_name}', visit_id={tb_debug.visit_id}, therapist_id={tb_debug.therapist_id}")
                    
                    prev_any_qs = _TB.objects.filter(
                        patient_id=patient_snapshot_id,
                        status='BOOKED',
                        date=any_date,  # Use most recent date
                    )
                    print(f"[CONTINUITY PLAN]   DEBUG: After status='BOOKED' filter for any-therapy: {prev_any_qs.count()} records")
                    
                    # Don't exclude visit=allocation - we want therapists from previous allocations
                    prev_any_qs = prev_any_qs.exclude(visit_id=allocation.id if allocation and hasattr(allocation, 'id') else None)
                    prev_any_qs = prev_any_qs.select_related('therapist')
                    
                    rows_added_any = 0
                    for tb in prev_any_qs:
                        if not tb.therapist:
                            print(f"[CONTINUITY PLAN]   DEBUG: Skipping TherapistBooking {tb.pk} - no therapist")
                            continue
                        if not getattr(tb.therapist, 'is_active', True):
                            print(f"[CONTINUITY PLAN]   DEBUG: Skipping TherapistBooking {tb.pk} - therapist {tb.therapist.therapist_code} is INACTIVE")
                            continue
                        if getattr(tb.therapist, 'is_helping_therapist', False):
                            if not (pref_roster and tb.therapist.therapist_code in pref_roster.get('therapist_codes_set', set())):
                                print(f"[CONTINUITY PLAN]   DEBUG: Skipping TherapistBooking {tb.pk} - therapist {tb.therapist.therapist_code} is HELPING THERAPIST")
                                continue
                        # CRITICAL FIX: Only mark as bathing if the TherapistBooking record actually has is_bathing=True
                        # Do NOT use therapist.is_bathing_therapist attribute - that just means they CAN be a bathing therapist,
                        # not that they WERE the bathing therapist on this specific day
                        continuity_rows.append({
                            "therapist": tb.therapist,
                            "is_bathing": bool(getattr(tb, 'is_bathing', False)),  # ONLY use actual is_bathing flag from TherapistBooking
                            "priority": 2,
                            "source_date": any_date,
                        })
                        rows_added_any += 1
                    print(f"[CONTINUITY PLAN]   Found {rows_added_any} therapists from any-therapy date {any_date}")
                else:
                    print(f"[CONTINUITY PLAN]   No any-therapy history found")

            # Enforce strict preferred roster pool and unpreferred therapist exclusion
            if pref_roster and pref_roster.get('therapist_codes_set'):
                roster_pool = pref_roster['therapist_codes_set']
                continuity_rows = [r for r in continuity_rows if getattr(r['therapist'], 'therapist_code', None) in roster_pool]
            if pref_roster and pref_roster.get('unpreferred_codes_set'):
                unpref_pool = pref_roster['unpreferred_codes_set']
                continuity_rows = [r for r in continuity_rows if getattr(r['therapist'], 'therapist_code', None) not in unpref_pool]

            # Enforce treatment omissions: Never include therapists who omitted this treatment in continuity plan
            from masters.models import is_therapist_omitted_for_treatment
            treatment_to_check = therapy_obj or current_therapy_name or getattr(allocation, 'therapy_code', None)
            if treatment_to_check:
                continuity_rows = [
                    r for r in continuity_rows
                    if not is_therapist_omitted_for_treatment(r['therapist'], treatment_to_check)
                ]

            if continuity_rows:
                print(f"[CONTINUITY PLAN]   Raw continuity candidates:")
                for r in continuity_rows:
                    t = r["therapist"]
                    t_name = getattr(t, "therapist_name", "")
                    t_code = getattr(t, "therapist_code", "")
                    grade_name = getattr(getattr(t, "therapist_grade", None), "name", "")
                    print(f"    - {t_name} ({t_code}), grade='{grade_name}', "
                          f"is_bathing={r['is_bathing']}, priority={r['priority']}, source_date={r['source_date']}")
            else:
                print(f"[CONTINUITY PLAN]   No continuity candidates found for this patient/therapy/slot")

            # Deduplicate by therapist id and persist
            seen_ids = set()
            for r in sorted(continuity_rows, key=lambda x: (x["priority"], x["therapist"].id)):
                tid = r["therapist"].id
                if tid in seen_ids:
                    continue
                seen_ids.add(tid)
                TherapistContinuityPlan.objects.create(
                    date=target_date,
                    time_slot=slot,
                    patient=patient,
                    allocation=allocation,
                    therapist=r["therapist"],
                    therapy_name=current_therapy_name,
                    is_bathing=r["is_bathing"],
                    priority=r["priority"],
                    source_date=r["source_date"],
                )

            print(f"[CONTINUITY PLAN]   Persisted {len(seen_ids)} unique continuity rows for this booking")
    except Exception as e:
        print(f"[DEBUG ContinuityPlan] Error building continuity plan: {e}")

    # ---------------------------------------
    # Build slot_avoid_map from continuity plan
    # ---------------------------------------
    slot_avoid_map = {}
    try:
        plan_qs = TherapistContinuityPlan.objects.filter(date=target_date).select_related('time_slot', 'therapist')
        for row in plan_qs:
            slot_id = row.time_slot_id
            code = row.therapist.therapist_code
            if slot_id not in slot_avoid_map:
                slot_avoid_map[slot_id] = set()
            slot_avoid_map[slot_id].add(code)
    except Exception as e:
        print(f"[DEBUG ContinuityPlan] Error building slot_avoid_map from plan: {e}")


    return slot_avoid_map
