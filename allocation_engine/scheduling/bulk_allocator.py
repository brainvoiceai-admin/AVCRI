"""
Scheduling Bulk Date Allocator (Layer 3A).

Hosts `bulk_allocate_for_date`, orchestrating:
- Pass 0: `build_continuity_plan_for_date`
- Pass 1: `assign_continuity_therapists_pass1` (patient-wise priority ordering)
- Pass 2: `expand_therapies_for_visit` (general allocation pass)

Must NEVER import `allocation_engine.rescheduling`, `reshedule`, or `resheduleMorningandNight`.
"""

import sys
from datetime import datetime, timedelta
from django.db import transaction
from django.db.models import Q

from allocation_engine.core.primitives.patient_utils import (
    is_patient_active as _canonical_is_patient_active,
)
from allocation_engine.core.primitives.therapy_catalog import (
    therapist_requirements as _core_therapist_requirements,
)
from allocation_engine.core.allocators.prioritization import get_patient_category_priority
from allocation_engine.core.allocators.continuity_pass1 import (
    SCHEDULING_PASS1_CONFIG,
    assign_continuity_therapists_pass1 as _assign_continuity_pass1_core,
)
from allocation_engine.scheduling.continuity_plan import build_continuity_plan_for_date
from allocation_engine.scheduling.visit_allocator import expand_therapies_for_visit


def is_patient_active(patient):
    """Call canonical is_patient_active while honoring legacy facade mock patches in tests."""
    legacy_mod = sys.modules.get("final_allocation")
    if legacy_mod is not None:
        patched = getattr(legacy_mod, "is_patient_active", None)
        if patched is not None and patched is not _canonical_is_patient_active:
            return patched(patient)
    return _canonical_is_patient_active(patient)


def therapist_requirements(allocation_or_therapy_obj):
    return _core_therapist_requirements(allocation_or_therapy_obj, default_total_if_missing=1)


def assign_continuity_therapists_pass1(booking, allocation, target_date, locked_therapist_slots):
    return _assign_continuity_pass1_core(
        booking=booking,
        allocation=allocation,
        target_date=target_date,
        locked_therapist_slots=locked_therapist_slots,
        create_bookings=True,
        config=SCHEDULING_PASS1_CONFIG,
    )


def bulk_allocate_for_date(target_date_str):
    """
    Bulk allocate all draft therapies for a specific date.
    This function is called by the Final Schedule button.
    
    Args:
        target_date_str: Date string in YYYY-MM-DD format
        
    Returns:
        dict: Summary of allocation results
    """
    from datetime import datetime
    from Sheduling.models import TherapyAllocation, TherapistContinuityPlan
    
    try:
        target_date = datetime.strptime(target_date_str, '%Y-%m-%d').date()
    except ValueError:
        return {
            'success': False,
            'error': f'Invalid date format: {target_date_str}. Expected YYYY-MM-DD'
        }
    
    # Get all draft bookings for the target date
    # We will process them in a patient-aware order (older-from_date therapies first)
    from Sheduling.models import Booking
    draft_bookings_qs = Booking.objects.filter(
        date=target_date,
        status='draft'
    ).select_related('allocation', 'allocation__patient')
    
    if not draft_bookings_qs.exists():
        return {
            'success': True,
            'message': 'No draft therapies found for the selected date',
            'total_processed': 0,
            'successful': 0,
            'failed': 0,
            'results': []
        }

    # Order bookings per patient by therapy start date (allocation.from_date) so that,
    # for the same patient, earlier-started therapies get continuity first.
    from collections import defaultdict
    by_patient = defaultdict(list)
    for b in draft_bookings_qs:
        pat = getattr(b.allocation, 'patient', None)
        pid = getattr(pat, 'id', None)
        by_patient[pid].append(b)

    # ----- INACTIVE PATIENT CHECK (bulk) -----
    # Before processing, check each patient's active status.
    # If inactive, mark all their draft bookings as failed and remove from processing.
    inactive_patient_ids = set()
    inactive_failed_count = 0
    for pid, bookings in list(by_patient.items()):
        if not bookings:
            continue
        # Get pat_reg_no from the first booking's patient snapshot
        first_pat = getattr(bookings[0].allocation, 'patient', None) if bookings[0].allocation else None
        pat_reg_no = getattr(first_pat, 'pat_reg_no', None) if first_pat else None
        if pat_reg_no and not is_patient_active(pat_reg_no):
            pat_name = getattr(first_pat, 'pat_name', 'Unknown') if first_pat else 'Unknown'
            print(f"[PATIENT STATUS] Patient {pat_reg_no} ({pat_name}) is INACTIVE - "
                  f"marking {len(bookings)} draft bookings as failed")
            for b in bookings:
                try:
                    b.status = 'failed'
                    b.failure_reason = 'Patient Inactive'
                    b.save(update_fields=['status', 'failure_reason', 'updated_at'])
                    inactive_failed_count += 1
                except Exception as e:
                    print(f"[PATIENT STATUS] Error marking booking {b.pk} as failed: {e}")
            inactive_patient_ids.add(pid)
    # Remove inactive patients from the processing map
    for pid in inactive_patient_ids:
        del by_patient[pid]
    if inactive_failed_count > 0:
        print(f"[PATIENT STATUS] Total inactive patient bookings marked as failed: {inactive_failed_count}")

    def _is_patient_op(pat):
        if not pat:
            return False
        if hasattr(pat, 'is_op'):
            return bool(pat.is_op())
        if hasattr(pat, 'pat_reg_no'):
            digits = ''.join(ch for ch in str(pat.pat_reg_no or '') if ch.isdigit())
            return len(digits) == 5
        return False

    def _booking_priority_sort_key(item):
        bookings = item[1]
        first_bk = bookings[0] if bookings else None
        alloc = getattr(first_bk, 'allocation', None) if first_bk else None
        pat = getattr(alloc, 'patient', None) if alloc else None

        from Sheduling.vip_service import is_patient_vip
        is_vip = is_patient_vip(pat) or getattr(first_bk, 'is_vip', False) or getattr(alloc, 'is_vip', False)
        is_op = _is_patient_op(pat)

        pref_roster = None
        for pid_check in [getattr(pat, 'id', None), getattr(pat, 'pat_reg_no', None)]:
            if pid_check:
                try:
                    from Sheduling.preferred_therapist_service import get_active_preferred_roster
                    pref_roster = get_active_preferred_roster(pid_check)
                    if pref_roster:
                        break
                except Exception:
                    pass
        has_roster = bool(pref_roster)

        # Priority order:
        # 0. Category tier: Wheelchair (0) -> Dhara & Pizhichil (1) -> Normal (2)
        # 1. VIP patients FIRST (priority 0)
        # 2. Patients with active preferred roster (priority 1)
        # 3. Non-VIP IP patients (priority 2, 0)
        # 4. Non-VIP OP patients (priority 2, 1)
        cat_rank = get_patient_category_priority(pat, allocation=alloc, bookings=bookings)
        pat_rank = 0 if is_vip else (1 if has_roster else 2)
        return (cat_rank, pat_rank, 1 if is_op else 0)

    ordered_bookings = []
    sorted_by_patient = sorted(
        by_patient.items(),
        key=_booking_priority_sort_key
    )
    for pid, bookings in sorted_by_patient:
        bookings.sort(key=lambda bk: getattr(bk.allocation, 'from_date', target_date))
        ordered_bookings.extend(bookings)
    
    # Derive the unique allocations from these ordered bookings (preserving sort order!)
    allocation_ids = []
    seen_alloc_ids = set()
    for b in ordered_bookings:
        aid = getattr(b.allocation, 'id', None)
        if aid and aid not in seen_alloc_ids:
            seen_alloc_ids.add(aid)
            allocation_ids.append(aid)
    alloc_map = {a.id: a for a in TherapyAllocation.objects.filter(id__in=allocation_ids)}
    draft_allocations = [alloc_map[aid] for aid in allocation_ids if aid in alloc_map]
    
    results = []
    successful_count = 0
    failed_count = 0

    # Phase 1: Build continuity plan in DB and slot_avoid_map
    slot_avoid_map = build_continuity_plan_for_date(target_date)

    # Priority-based sorting: Process patients with same treatment yesterday first for maximum continuity
    # This ensures therapists needed for continuity are assigned before others.
    # 
    # How this handles therapist conflicts:
    # 1. Patients with same therapy yesterday are processed FIRST
    # 2. When continuity therapists are assigned, they're marked as BOOKED in the database
    # 3. Later patients (without continuity needs) won't be able to claim those therapists
    # 4. If two patients both need the same therapist for continuity:
    #    - The one with more recent previous date gets processed first (higher priority)
    #    - First-come-first-served: first patient gets the therapist, second gets a replacement
    # 5. This maximizes continuity slot-wise without requiring multiprocessing or complex conflict resolution
    from Patient.models import TherapistBooking
    from masters.models import TherapyMaster
    from django.db.models import Max, Q
    
    def get_continuity_priority(allocation):
        """
        Returns a tuple (priority_score, most_recent_date) for sorting.
        Lower priority_score = higher priority (processed first).
        Priority -1: Active preferred therapist roster (highest priority)
        Priority 0: Same therapy (any slot) on most recent date
        Priority 2: Any previous therapy (any slot)
        Priority 3: No previous therapy
        """
        patient_id = getattr(allocation.patient, 'id', None)
        current_therapy_name = getattr(allocation, 'therapy_name', None)
        
        if not patient_id or not current_therapy_name:
            return (3, None)  # No continuity possible

        # Check if patient has active preferred therapist roster
        pat = getattr(allocation, 'patient', None)
        pref_roster = None
        for pid_check in [patient_id, getattr(pat, 'pat_reg_no', None)]:
            if pid_check:
                try:
                    from Sheduling.preferred_therapist_service import get_active_preferred_roster
                    pref_roster = get_active_preferred_roster(pid_check)
                    if pref_roster:
                        break
                except Exception:
                    pass
        if pref_roster and pref_roster.get('therapist_codes'):
            return (-1, target_date)

        try:
            # Resolve TherapyMaster for robust matching (by code or case-insensitive name)
            therapy_obj = None
            therapy_code = getattr(allocation, 'therapy_code', None)
            if therapy_code:
                therapy_obj = TherapyMaster.objects.filter(therapy_code=therapy_code).first()
            if not therapy_obj and current_therapy_name:
                therapy_obj = TherapyMaster.objects.filter(therapy_name__iexact=current_therapy_name).first()

            base_qs = TherapistBooking.objects.filter(
                patient_id=patient_id,
                status='BOOKED',
                date__lt=target_date,  # ONLY look at days before the target date
            )

            # First check: Same therapy (any slot) on most recent date
            if therapy_obj:
                same_therapy_qs = base_qs.filter(therapy=therapy_obj)
            else:
                same_therapy_qs = base_qs.filter(therapy_name__iexact=current_therapy_name)
            same_therapy_date = same_therapy_qs.aggregate(Max('date'))['date__max']
            if same_therapy_date:
                print(f"[CONTINUITY PRIORITY] Patient {patient_id}, therapy='{current_therapy_name}': most recent SAME-therapy date = {same_therapy_date}")
                return (0, same_therapy_date)  # Priority 0: Same therapy
            else:
                print(f"[CONTINUITY PRIORITY] Patient {patient_id}, therapy='{current_therapy_name}': no previous SAME-therapy bookings found")

            # Second check: Any previous therapy (any slot)
            any_therapy_date = base_qs.aggregate(Max('date'))['date__max']
            if any_therapy_date:
                return (2, any_therapy_date)  # Priority 2: Any previous therapy

            return (3, None)  # Priority 3: No previous therapy

        except Exception as e:
            print(f"[CONTINUITY PRIORITY] Error computing priority for patient {patient_id}, therapy='{current_therapy_name}': {e}")
            return (3, None)  # Error case: treat as no continuity
    
    # Compute priority for each allocation once (Checklist: VIP prioritized over non-VIP, Preferred Roster, IP over OP)
    from Sheduling.vip_service import is_patient_vip
    allocation_priorities = []
    for allocation in draft_allocations:
        patient_obj = getattr(allocation, 'patient', None)
        cat_rank = get_patient_category_priority(patient_obj, allocation=allocation)
        is_vip = is_patient_vip(patient_obj) or getattr(allocation, 'is_vip', False)
        vip_rank = 0 if is_vip else 1

        pref_roster = None
        for pid_check in [getattr(patient_obj, 'id', None), getattr(patient_obj, 'pat_reg_no', None)]:
            if pid_check:
                try:
                    from Sheduling.preferred_therapist_service import get_active_preferred_roster
                    pref_roster = get_active_preferred_roster(pid_check)
                    if pref_roster:
                        break
                except Exception:
                    pass
        roster_rank = 0 if pref_roster else 1

        priority_score, most_recent_date = get_continuity_priority(allocation)
        # Use date ordinal for sorting (more recent = larger ordinal = higher priority)
        # We negate it so that larger dates come first in ascending sort
        date_ordinal = -most_recent_date.toordinal() if most_recent_date else 0
        op_rank = 1 if _is_patient_op(patient_obj) else 0  # 0=IP (strict priority), 1=OP
        allocation_priorities.append((allocation, cat_rank, vip_rank, roster_rank, op_rank, priority_score, date_ordinal))
    
    # Sort: Wheelchair first (cat_rank=0), then Dhara Pizhichil (cat_rank=1), then Normal (cat_rank=2),
    # sub-sorted by VIP (vip_rank=0), preferred roster (roster_rank=0), IP (op_rank=0), priority score, most recent date
    sorted_allocations = [a for a, _, _, _, _, _, _ in sorted(allocation_priorities, key=lambda x: (x[1], x[2], x[3], x[4], x[5], x[6]))]
    
    # Count statistics
    continuity_stats = {
        'preferred_roster': sum(1 for entry in allocation_priorities if entry[5] == -1),
        'same_therapy': sum(1 for entry in allocation_priorities if entry[5] == 0),
        'any_therapy': sum(1 for entry in allocation_priorities if entry[5] == 2),
        'no_continuity': sum(1 for entry in allocation_priorities if entry[5] == 3)
    }
    print(f"[DEBUG Continuity Priority] Processing {len(sorted_allocations)} allocations:")
    print(f"  - Active Preferred Roster: {continuity_stats['preferred_roster']}")
    print(f"  - Same therapy yesterday: {continuity_stats['same_therapy']}")
    print(f"  - Any previous therapy: {continuity_stats['any_therapy']}")
    print(f"  - No continuity: {continuity_stats['no_continuity']}")
    
    # ============================================================
    # PASS 1: CONTINUITY PRIORITY PASS
    # Assign ONLY previous-day therapists and lock them
    # ============================================================
    print(f"[CONTINUITY PASS1] ========== STARTING PASS 1: CONTINUITY PRIORITY ==========")
    locked_therapist_slots = set()  # Set of (therapist_id, slot_id) tuples
    booking_continuity_map = {}  # Map booking_id -> continuity_assigned dict
    
    # Get all draft bookings for this date
    from Sheduling.models import Booking
    from collections import defaultdict
    all_draft_bookings = Booking.objects.filter(
        date=target_date,
        status='draft'
    ).select_related('allocation', 'timeslot', 'allocation__patient').order_by('allocation_id', 'timeslot_id')
    
    # Group bookings by PATIENT (not allocation) for PASS 1
    # Process one patient and all their treatments, then move to next patient
    patient_bookings_map = defaultdict(list)
    for booking in all_draft_bookings:
        patient_id = getattr(booking.allocation, 'patient', None)
        if patient_id:
            patient_id_val = getattr(patient_id, 'id', None) if hasattr(patient_id, 'id') else patient_id
            patient_bookings_map[patient_id_val].append(booking)
        else:
            # Bookings without patient - process separately
            patient_bookings_map[None].append(booking)
    
    # Sort patients by priority (same as allocations: cat_rank, vip_rank, roster_rank, op_rank, priority, date_ordinal)
    allocation_id_to_priority = {alloc.id: (cat_r, vip_r, ros_r, op_r, p, d) for alloc, cat_r, vip_r, ros_r, op_r, p, d in allocation_priorities}
    
    # Tie-breaker: earliest "from start" date in continuity plan (priority < 0).
    # Patients whose therapy started earliest get processed first so their first-day therapists (e.g. Latha) are locked for them, not for a patient who had that therapist only on a later date.
    from django.db.models import Min
    try:
        plan_earliest = dict(
            TherapistContinuityPlan.objects.filter(
                date=target_date,
                priority__lt=0
            ).values('patient_id').annotate(earliest=Min('source_date')).values_list('patient_id', 'earliest')
        )
    except Exception:
        plan_earliest = {}
    
    def get_patient_priority(patient_id):
        """Get (cat_rank, vip_rank, roster_rank, op_rank, priority_score, date_ordinal, earliest_from_start_ordinal) for sorting.
        Category rank: 0=Wheelchair, 1=Dhara & Pizhichil, 2=Normal.
        VIP patients (vip_rank=0) strictly prioritized over non-VIP (vip_rank=1).
        Patients with active preferred roster (roster_rank=0) strictly prioritized.
        IP patients (op_rank=0) strictly prioritized over OP (op_rank=1).
        Patients with earlier 'from start' date get processed first so first-day therapists are assigned to them."""
        if patient_id is None:
            return (2, 1, 1, 1, 3, 0, 999999)
        first_pat = patient_bookings_map[patient_id][0].allocation.patient if patient_bookings_map[patient_id] else None
        cat_rank = get_patient_category_priority(first_pat, bookings=patient_bookings_map[patient_id])
        
        from Sheduling.vip_service import is_patient_vip
        is_vip = is_patient_vip(first_pat)
        if not is_vip and patient_bookings_map[patient_id]:
            is_vip = any(getattr(b, 'is_vip', False) or getattr(b.allocation, 'is_vip', False) for b in patient_bookings_map[patient_id])
        vip_rank = 0 if is_vip else 1

        pref_roster = None
        for pid_check in [patient_id, getattr(first_pat, 'pat_reg_no', None) if first_pat else None]:
            if pid_check:
                try:
                    from Sheduling.preferred_therapist_service import get_active_preferred_roster
                    pref_roster = get_active_preferred_roster(pid_check)
                    if pref_roster:
                        break
                except Exception:
                    pass
        roster_rank = 0 if pref_roster else 1

        op_rank = 1 if _is_patient_op(first_pat) else 0
        min_priority = (3, 0)
        for booking in patient_bookings_map[patient_id]:
            alloc_id = booking.allocation_id
            p_tuple = allocation_id_to_priority.get(alloc_id, (cat_rank, vip_rank, roster_rank, op_rank, 3, 0))
            priority = (p_tuple[4], p_tuple[5])
            if priority[0] < min_priority[0] or (priority[0] == min_priority[0] and priority[1] > min_priority[1]):
                min_priority = priority
        earliest_sd = plan_earliest.get(patient_id)
        earliest_ord = earliest_sd.toordinal() if earliest_sd else 999999
        return (cat_rank, vip_rank, roster_rank, op_rank, min_priority[0], min_priority[1], earliest_ord)
    
    # Sort patients by priority, then by earliest from-start date (therapy started first = process first)
    sorted_patient_ids = sorted(
        patient_bookings_map.keys(),
        key=lambda pid: get_patient_priority(pid)
    )
    
    continuity_assigned_count = 0
    partial_assignments = 0  # Count of bookings with partial continuity (K < N)
    
    # PASS 1: Process PATIENT-WISE - one patient and all their treatments, then next patient
    # Assign continuity therapists and lock them, but do NOT complete bookings
    print(f"[CONTINUITY PASS1] Processing {len(sorted_patient_ids)} patients with bookings")
    
    for patient_id in sorted_patient_ids:
        patient_bookings = patient_bookings_map[patient_id]
        patient_name = getattr(patient_bookings[0].allocation.patient, 'pat_name', 'Unknown') if patient_id and patient_bookings else 'Unknown'
        
        print(f"[CONTINUITY PASS1] ===== PATIENT: {patient_name} (id={patient_id}) - Processing {len(patient_bookings)} bookings =====")
        
        # Sort this patient's bookings to match PASS 2 allocation priority so the primary
        # booking claims the slot in PASS 1 and any duplicate same-slot booking does not
        # create competing PASS 1 TherapistBooking locks.
        patient_bookings.sort(
            key=lambda bk: allocation_id_to_priority.get(
                bk.allocation_id, (2, 1, 1, 1, 3, 0)
            ) + (getattr(bk.allocation, 'from_date', target_date), bk.allocation_id or 0)
        )
        claimed_slots_for_patient = set()

        # Process all bookings for this patient
        for booking in patient_bookings:
            allocation = booking.allocation
            if not allocation:
                continue
        
            # Skip nurse treatments in PASS 1 (they don't need therapists)
            from Sheduling.nurse_allocation import is_nurse_treatment
            if is_nurse_treatment(allocation.therapy_code, allocation.therapy_name):
                booking_continuity_map[booking.pk] = None  # Mark as no continuity needed
                continue
            
            # Skip therapies with zero therapist requirements in PASS 1 (they don't need therapists)
            # Note: This does NOT include nurse treatments - they are handled above
            therapy_req = therapist_requirements(allocation)
            if therapy_req.get('total', 1) == 0:
                booking_continuity_map[booking.pk] = None  # Mark as no continuity needed
                print(f"[CONTINUITY PASS1] Skipping booking {booking.pk} - zero therapists required (total=0)")
                continue

            # If another booking for the same patient already claimed this exact slot in PASS 1,
            # skip locking continuity therapists for this duplicate same-slot booking so PASS 2
            # allocates the first booking cleanly and fails only the duplicate with patient_already_has_booking.
            bk_slot_id = getattr(booking, 'timeslot_id', None) or getattr(allocation, 'timeslot_id', None)
            if bk_slot_id:
                if bk_slot_id in claimed_slots_for_patient:
                    booking_continuity_map[booking.pk] = None
                    print(f"[CONTINUITY PASS1] Skipping booking {booking.pk} - patient {patient_id} already has an earlier booking at slot_id={bk_slot_id} in PASS 1")
                    continue
                claimed_slots_for_patient.add(bk_slot_id)
            
            # Assign continuity therapists for this booking (partial assignment is OK)
            # This will lock therapists but NOT complete the booking
            print(f"[CONTINUITY PASS1] >>> Processing booking {booking.pk} (allocation_id={allocation.id}, patient_id={getattr(allocation.patient, 'id', None)})")
            try:
                continuity_result = assign_continuity_therapists_pass1(
                    booking, allocation, target_date, locked_therapist_slots
                )
                
                if continuity_result['success']:
                    booking_continuity_map[booking.pk] = continuity_result
                    continuity_assigned_count += 1
                    assigned_count = len(continuity_result['assigned_therapists'])
                    remaining_count = continuity_result['remaining_requirements'].get('total', 0)
                    
                    if remaining_count > 0:
                        partial_assignments += 1
                        print(f"[CONTINUITY PASS1] Booking {booking.pk}: Assigned {assigned_count} continuity therapists, {remaining_count} remaining (PARTIAL - will fill in PASS 2)")
                    else:
                        print(f"[CONTINUITY PASS1] Booking {booking.pk}: Assigned {assigned_count} continuity therapists (COMPLETE)")
                else:
                    # No continuity therapists available - will be handled in PASS 2
                    booking_continuity_map[booking.pk] = None
                    print(f"[CONTINUITY PASS1] Booking {booking.pk}: No continuity therapists available (will assign all in PASS 2)")
            except Exception as e:
                print(f"[CONTINUITY PASS1] Error assigning continuity for booking {booking.pk}: {e}")
                import traceback
                traceback.print_exc()
                booking_continuity_map[booking.pk] = None
        
        print(f"[CONTINUITY PASS1] ===== FINISHED PATIENT: {patient_name} (id={patient_id}) =====")
    
    print(f"[CONTINUITY PASS1] ========== PASS 1 COMPLETE ==========")
    total_bookings_processed = sum(len(bookings) for bookings in patient_bookings_map.values())
    print(f"[CONTINUITY PASS1] - Processed {len(sorted_patient_ids)} patients")
    print(f"[CONTINUITY PASS1] - Processed {total_bookings_processed} bookings")
    print(f"[CONTINUITY PASS1] - Assigned continuity for {continuity_assigned_count} bookings")
    print(f"[CONTINUITY PASS1] - Partial assignments (need remaining slots): {partial_assignments}")
    print(f"[CONTINUITY PASS1] - Locked {len(locked_therapist_slots)} therapist-slot pairs")
    print(f"[CONTINUITY PASS1] - Moving to PASS 2 to fill remaining slots and complete bookings")
    
    # ============================================================
    # PASS 2: GENERAL ALLOCATION PASS
    # Fill remaining slots for ALL bookings and complete them
    # ============================================================
    print(f"[CONTINUITY PASS2] ========== STARTING PASS 2: GENERAL ALLOCATION ==========")
    total_bookings_count = sum(len(bookings) for bookings in patient_bookings_map.values())
    print(f"[CONTINUITY PASS2] Processing {len(sorted_allocations)} allocations ({total_bookings_count} bookings)")
    print(f"[CONTINUITY PASS2] - ALL bookings already processed in PASS 1 (continuity therapists locked)")
    print(f"[CONTINUITY PASS2] - Now processing ALL bookings again to fill remaining slots and complete them")
    print(f"[CONTINUITY PASS2] - Continuity therapists are already locked via TherapistBooking records from PASS 1")
    
    # PASS 2: Process ALL allocations (which means ALL bookings)
    # All continuity therapists are already locked from PASS 1
    # For each allocation, expand_therapies_for_visit processes ALL bookings for that allocation
    # This ensures ALL bookings go through PASS 2 to fill remaining slots and complete
    pass2_booking_count = 0
    allocation_count = 0
    for allocation in sorted_allocations:
        allocation_count += 1
        # Get bookings for this allocation to count them
        allocation_bookings = Booking.objects.filter(allocation=allocation, date=target_date, status='draft')
        pass2_booking_count += allocation_bookings.count()
        
        print(f"[CONTINUITY PASS2] Processing allocation {allocation.id} ({allocation_bookings.count()} bookings)")
        
        # Check if this therapy requires zero therapists (total_no_of_therapist = 0)
        # Note: This does NOT include nurse treatments - they go through normal flow to allocate nurses
        from Sheduling.nurse_allocation import is_nurse_treatment
        is_nurse = is_nurse_treatment(allocation.therapy_code, allocation.therapy_name)
        
        # Only auto-schedule if it's NOT a nurse treatment AND has zero therapist requirements
        if not is_nurse:
            therapy_req = therapist_requirements(allocation)
            if therapy_req.get('total', 1) == 0:
                # Mark all bookings for this allocation as scheduled (they don't need algorithm)
                allocation_bookings.update(status='scheduled')
                from Sheduling.models import BookingItem
                BookingItem.objects.filter(booking__allocation=allocation, booking__date=target_date).update(status='scheduled')
                
                successful_count += 1
                results.append({
                    'allocation_id': allocation.id,
                    'patient_name': str(allocation.patient),
                    'therapy_name': allocation.therapy_name,
                    'status': 'success',
                    'booked_tasks': allocation_bookings.count(),
                    'failed_tasks': 0,
                    'auto_scheduled': True  # Flag to indicate auto-scheduled without algorithm
                })
                print(f"[CONTINUITY PASS2] Auto-scheduled {allocation_bookings.count()} bookings for allocation {allocation.id} (zero therapists required, total=0, NOT nurse treatment)")
                continue  # Skip algorithm for this allocation
        
        # Nurse treatments go through normal flow (expand_therapies_for_visit) which will allocate nurses
        
        try:
            # PASS 2: Run the allocation algorithm for this allocation and target date.
            # expand_therapies_for_visit processes ALL bookings for this allocation.
            # It will use continuity_assigned from PASS 1 per booking via booking_continuity_map,
            # fill remaining slots, and complete bookings.
            tasks = expand_therapies_for_visit(
                allocation.id,
                target_date_str,
                create_bookings=True,
                slot_avoid_map=slot_avoid_map,
                booking_continuity_map=booking_continuity_map,  # Pass the continuity map from PASS 1
            )
            
            print(f"[CONTINUITY PASS2] expand_therapies_for_visit returned {len(tasks) if isinstance(tasks, list) else 'error'} for allocation {allocation.id}")
            
            # Analyze results - only affect bookings for this date, not overall allocation status
            if isinstance(tasks, dict) and "error" in tasks:
                # Algorithm returned an error for this date
                failed_count += 1
                results.append({
                    'allocation_id': allocation.id,
                    'patient_name': str(allocation.patient),
                    'therapy_name': allocation.therapy_name,
                    'status': 'failed',
                    'reason': tasks['error']
                })
            else:
                # Process algorithm results
                success_tasks = [t for t in tasks if t.get('status') == 'BOOKED']
                failed_tasks = [t for t in tasks if t.get('status') == 'FAILED']
                
                # Update booking statuses based on task results
                from Sheduling.models import Booking
                for task in tasks:
                    booking_id = task.get('booking_id')
                    if booking_id:
                        try:
                            booking = Booking.objects.get(id=booking_id, allocation=allocation, date=target_date)
                            if task.get('status') == 'BOOKED':
                                booking.status = 'scheduled'
                                booking.save(update_fields=['status', 'updated_at'])
                            elif task.get('status') == 'FAILED' and booking.status == 'draft':
                                booking.status = 'failed'
                                booking.failure_reason = (str(task.get('reason') or ''))[:512]
                                booking.save(update_fields=['status', 'failure_reason', 'updated_at'])
                        except Booking.DoesNotExist:
                            pass
                        except Exception as e:
                            print(f"Error updating booking {booking_id} status: {e}")
                
                if success_tasks:
                    successful_count += 1
                    results.append({
                        'allocation_id': allocation.id,
                        'patient_name': str(allocation.patient),
                        'therapy_name': allocation.therapy_name,
                        'status': 'success',
                        'booked_tasks': len(success_tasks),
                        'failed_tasks': len(failed_tasks)
                    })
                else:
                    failed_count += 1
                    reason = failed_tasks[0].get('reason', 'No available slots') if failed_tasks else 'Unknown error'
                    results.append({
                        'allocation_id': allocation.id,
                        'patient_name': str(allocation.patient),
                        'therapy_name': allocation.therapy_name,
                        'status': 'failed',
                        'reason': reason
                    })
                
                # DO NOT update overall allocation status
                # Each booking date is independent - one date can be scheduled while another remains draft
                # The TherapyAllocation.status field is not automatically updated based on booking statuses
                # This allows:
                # - Date 23rd in draft, Date 24th scheduled → perfectly fine, both remain independent
                # - Running Final Schedule for 23rd doesn't affect 24th's status
                # - Running Final Schedule for 24th doesn't affect 23rd's status
                # Only individual Booking.status is updated per date during Final Schedule
                    
        except Exception as e:
            print(f"[CONTINUITY PASS2] ❌ ERROR processing allocation {allocation.id}: {e}")
            import traceback
            traceback.print_exc()
            failed_count += 1
            results.append({
                'allocation_id': allocation.id,
                'patient_name': str(allocation.patient),
                'therapy_name': allocation.therapy_name,
                'status': 'failed',
                'reason': f'Exception: {str(e)}'
            })
    
    print(f"[CONTINUITY PASS2] ========== PASS 2 COMPLETE ==========")
    print(f"[CONTINUITY PASS2] - Processed {allocation_count} allocations")
    print(f"[CONTINUITY PASS2] - Processed {pass2_booking_count} bookings")
    
    return {
        'success': True,
        'message': f'Bulk allocation completed for {target_date_str}',
        'date': target_date_str,
        'total_processed': len(draft_allocations),
        'successful': successful_count,
        'failed': failed_count,
        'results': results
    }
