from datetime import timedelta
from collections import defaultdict
from django.db.models import Exists, OuterRef, Q, Count
from django.http import JsonResponse
from django.utils.dateparse import parse_date
from django.views.decorators.http import require_http_methods
from .decorators import api_access_required, scheduling_access_required
from Patient.models import TherapistBooking, Repeated_Visitors
from masters.models import (
    TherapistMaster, TherapistLeaveMaster, EmergencyLeave, 
    get_staying_room_display_number, TherapistDeputation, 
    TherapistTreatmentOmission, TherapistOnCallLog
)
from Sheduling.models import (
    PatientSnapshot, Booking, BookingAssignment,
    DoctorPatientPreferenceAllowance, PatientPreferredTherapistRoster,
    TherapistPreferenceRequest, SchedulingAuditLog, AllocationChange,
    BookingRescheduleHistory
)
from authentication.models import PatientProfile
from .preferred_therapist_service import is_cottage_room, normalize_patient_reg_no
from .views import get_room_sort_key

ALL_SUB_REASONS = {
    'green': [
        "• Same primary therapist retained from previous session.",
        "• Continuity score: 100%."
    ],
    'purple': [
        "1. Occupied as Primary: Assigned to another patient as their regular therapist (because they were that patient's prior continuity therapist).",
        "2. Assigned Newly: Assigned to another patient as a new allocation.",
        "3. Assigned as Substitute: Covered another patient's session as an emergency/leave substitute.",
        "4. Occupied as Bathing: Assigned as a bathing therapist to another patient at this slot."
    ],
    'red': [
        "1. Algorithm Slot Mismatch: Patient's treatment was shifted to a slot where the therapist was free, but preference/load-balancing picked someone else.",
        "2. Manual Override: Schedulers manually chose another therapist without an exclusion rule.",
        "3. Grade / Workload Cap: Previous therapist hit the daily maximum session threshold."
    ],
    'gray': [
        "1. Weekly Off: Scheduled regular weekly off day.",
        "2. Emergency / Sick Leave: Approved emergency leave.",
        "3. Deputed / On-Call: Therapist deputed to another facility/duty (SCH_REQ_065).",
        "4. Treatment Omission: Therapist has an approved exemption for this specific therapy (SCH_REQ_097)."
    ],
    'blue': [
        "1. Patient / VIP Preference: Assigned per VIP/Cottage patient's preferred choice (SCH_REQ_067).",
        "2. Doctor Preference: Assigned per Doctor's explicit order (DOC_REQ_008).",
        "3. Language Match: Assigned to satisfy patient language preference."
    ]
}

STATUS_LABELS = {
    'green': "Continuity Maintained",
    'purple': "Conflict / Assigned Elsewhere",
    'violet': "Conflict / Assigned Elsewhere",
    'red': "Avoidable Break / Unassigned",
    'gray': "Unavailable / On Leave",
    'blue': "Preference Allocation"
}

CORE_MEANINGS = {
    'green': "Correctly assigned to ongoing therapist.",
    'purple': "Previous therapist is on duty, but occupied with another patient.",
    'violet': "Previous therapist is on duty, but occupied with another patient.",
    'red': "Previous therapist is free and available, but was not assigned.",
    'gray': "Previous therapist is legitimately not in the active pool.",
    'blue': "Assigned specifically due to a registered preference."
}

@api_access_required
def continuity_matrix_api(request):
    """
    API to return Therapist Continuity Matrix data with comprehensive continuity analysis:
    - 🟢 Green: Continuity Maintained (retained from previous session, 100% score)
    - 🟣 Purple: Conflict / Assigned Elsewhere (occupied with another patient)
    - 🔴 Red: Avoidable Break / Unassigned (free and available, but not assigned)
    - ⚪ Grey: Unavailable / On Leave (weekly off, emergency leave, deputation, omission)
    - 🔵 Blue: Preference Allocation (VIP/Cottage preference, doctor preference, language match)
    """
    try:
        from_date_str = request.GET.get('from_date')
        to_date_str = request.GET.get('to_date')
        exclude_leave_str = request.GET.get('exclude_leave', 'true')
        
        if not from_date_str or not to_date_str:
            return JsonResponse({'error': 'Date range required'}, status=400)
             
        try:
            from_date = parse_date(from_date_str)
            to_date = parse_date(to_date_str)
        except Exception:
            return JsonResponse({'error': 'Invalid date format'}, status=400)
            
        exclude_leave = (exclude_leave_str.lower() == 'true')
        
        # 1. Fetch Schedule Data
        # Strategy: Use Booking model (per-date) as the source of truth for validity.
        from Sheduling.models import Booking
        valid_bookings_qs = Booking.objects.filter(
            date__range=[from_date, to_date]
        ).exclude(
            status='cancelled'
        ).exclude(
            status='failed'
        ).values_list('allocation_id', 'date', 'timeslot_id')
        
        valid_pairs = set((aid, d, tid) for aid, d, tid in valid_bookings_qs)
        
        # 1b. Fetch Valid Assignments (source of truth for therapists per booking)
        from Sheduling.models import BookingAssignment
        valid_assignments_qs = BookingAssignment.objects.filter(
            booking__date__range=[from_date, to_date],
            status='assigned'
        ).exclude(
            booking__status='cancelled'
        ).exclude(
            booking__status='failed'
        ).values_list('booking__allocation_id', 'booking__date', 'booking__timeslot_id', 'therapist_id')
        
        valid_assignments = set(valid_assignments_qs)
        
        valid_slot_map = {}
        for aid, d, tid in valid_bookings_qs:
            valid_slot_map[(aid, d)] = tid
        
        valid_assignments_subquery = BookingAssignment.objects.filter(
            booking__allocation_id=OuterRef('visit_id'),
            booking__date=OuterRef('date'),
            booking__timeslot_id=OuterRef('time_slot_id'),
            therapist__therapist_code=OuterRef('therapist__therapist_code'),
            status='assigned'
        ).exclude(
            booking__status='cancelled'
        ).exclude(
            booking__status='failed'
        )

        bookings = TherapistBooking.objects.filter(
            date__range=[from_date, to_date]
        ).exclude(
            status__icontains='fail'
        ).annotate(
            has_valid_assignment=Exists(valid_assignments_subquery)
        ).filter(
            Q(has_valid_assignment=True) |
            (Q(visit_id__isnull=True) & ~Q(status__icontains='cancel'))
        ).select_related('therapist', 'visit__patient', 'time_slot').order_by('date')
        
        # 2. Build Master & Absence Caches
        tm_qs = TherapistMaster.objects.select_related('therapist_grade').all()
        therapist_master_map = {t.id: t for t in tm_qs}
        therapist_code_to_id = {t.therapist_code: t.id for t in tm_qs}
        therapist_bathing_map = {t.id: bool(t.is_bathing_therapist) for t in tm_qs}

        # Weekly leaves cache
        weekly_leaves_qs = TherapistLeaveMaster.objects.filter(is_active=True).values('therapist_id', 'leave_day', 'leave_day_name')
        weekly_off_map = defaultdict(set)              # weekday_int -> set of therapist_ids
        weekly_off_therapist_days = defaultdict(set)   # therapist_id -> set of weekday_ints
        weekly_off_therapist_names = defaultdict(dict) # therapist_id -> {weekday_int: name}
        for w in weekly_leaves_qs:
            weekly_off_map[w['leave_day']].add(w['therapist_id'])
            weekly_off_therapist_days[w['therapist_id']].add(w['leave_day'])
            weekly_off_therapist_names[w['therapist_id']][w['leave_day']] = w.get('leave_day_name') or ''

        # Emergency leaves cache
        emergency_leave_cache = defaultdict(dict)  # date -> {therapist_id: {reason: str, leave_type: str}}
        e_leaves = EmergencyLeave.objects.filter(
            from_date__lte=to_date,
            to_date__gte=from_date
        ).exclude(status__icontains='reject')
        for el in e_leaves:
            curr_d = max(el.from_date, from_date)
            end_d = min(el.to_date, to_date)
            while curr_d <= end_d:
                if el.therapist_id:
                    emergency_leave_cache[curr_d][el.therapist_id] = {
                        'reason': el.leave_type or getattr(el, 'raw_payload', '') or 'Emergency / Sick Leave'
                    }
                curr_d += timedelta(days=1)

        # Deputation cache (SCH_REQ_065)
        deputation_cache = defaultdict(dict)  # date -> {therapist_id: {destination: str}}
        try:
            deputations = TherapistDeputation.objects.filter(
                status='approved',
                start_date__lte=to_date,
                end_date__gte=from_date
            )
            for dep in deputations:
                curr_d = max(dep.start_date, from_date)
                end_d = min(dep.end_date or dep.start_date, to_date)
                while curr_d <= end_d:
                    if dep.therapist_id:
                        deputation_cache[curr_d][dep.therapist_id] = {
                            'destination': dep.destination or 'External Duty / Facility'
                        }
                    curr_d += timedelta(days=1)
        except Exception:
            pass

        # Therapist On-Call / Standby logs (SCH_REQ_065)
        oncall_standby_cache = defaultdict(set)  # date -> set of therapist_ids
        try:
            oncalls = TherapistOnCallLog.objects.filter(
                start_date__lte=to_date,
                end_date__gte=from_date
            )
            for oc in oncalls:
                if oc.status == 'turned_off':  # Turned OFF = Standby / On-call duty
                    curr_d = max(oc.start_date, from_date)
                    end_d = min(oc.end_date or oc.start_date, to_date)
                    while curr_d <= end_d:
                        if oc.therapist_id:
                            oncall_standby_cache[curr_d].add(oc.therapist_id)
                        curr_d += timedelta(days=1)
        except Exception:
            pass

        # Treatment Omission cache (SCH_REQ_097)
        omission_set = set()  # (therapist_id, therapy_name_lower)
        try:
            omissions = TherapistTreatmentOmission.objects.filter(
                Q(status='approved') | Q(is_active=True)
            ).select_related('treatment')
            for om in omissions:
                if om.therapist_id and om.treatment and om.treatment.therapy_name:
                    omission_set.add((om.therapist_id, om.treatment.therapy_name.strip().lower()))
        except Exception:
            pass

        # 3. Preference Caches (SCH_REQ_067, DOC_REQ_008, Language)
        rosters_by_reg = {}
        try:
            active_rosters = list(PatientPreferredTherapistRoster.objects.filter(is_active=True))
            for r in active_rosters:
                rc = normalize_patient_reg_no(r.patient_reg_no)
                if rc:
                    rosters_by_reg[rc] = r
                    digits = ''.join(ch for ch in rc if ch.isdigit())
                    if digits:
                        rosters_by_reg[digits] = r
        except Exception:
            pass

        allowances_by_reg = {}
        try:
            active_allowances = list(DoctorPatientPreferenceAllowance.objects.filter(is_active=True))
            for a in active_allowances:
                rc = normalize_patient_reg_no(a.patient_reg_no)
                if rc:
                    allowances_by_reg[rc] = a
                    digits = ''.join(ch for ch in rc if ch.isdigit())
                    if digits:
                        allowances_by_reg[digits] = a
        except Exception:
            pass

        pref_reqs_by_pat_id = defaultdict(list)
        try:
            active_pref_reqs = list(TherapistPreferenceRequest.objects.filter(is_active=True))
            for pr in active_pref_reqs:
                pref_reqs_by_pat_id[str(pr.patient_id)].append(pr)
        except Exception:
            pass

        vip_regs = set()
        try:
            vip_regs = set(str(v) for v in Repeated_Visitors.objects.filter(is_vip=True).values_list('register_number', flat=True))
        except Exception:
            pass

        vip_profile_regs = set()
        try:
            vip_profile_regs = set(normalize_patient_reg_no(v) for v in PatientProfile.objects.filter(is_vip=True).values_list('patient_reg_no', flat=True))
        except Exception:
            pass

        # Workload counts & occupation mappings
        all_active_tb = TherapistBooking.objects.filter(
            date__range=[from_date, to_date]
        ).exclude(status__icontains='fail').exclude(status__icontains='cancel').select_related('visit__patient', 'therapist')

        daily_therapist_counts = defaultdict(lambda: defaultdict(int))  # date -> therapist_id -> count
        therapist_slot_assignments = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))  # date -> slot_id -> therapist_id -> [booking_info]
        therapist_patient_dates = defaultdict(set)  # (therapist_id, patient_reg_clean) -> set of dates

        for b in all_active_tb:
            daily_therapist_counts[b.date][b.therapist_id] += 1
            
            p_name = ''
            p_reg = ''
            if b.visit and b.visit.patient:
                p_name = b.visit.patient.pat_name or ''
                p_reg = b.visit.patient.pat_reg_no or ''
            elif b.patient_id:
                p_name = f"ID {b.patient_id}"
                p_reg = str(b.patient_id)
            
            p_reg_clean = normalize_patient_reg_no(p_reg)
            if p_reg_clean:
                therapist_patient_dates[(b.therapist_id, p_reg_clean)].add(b.date)
                digits = ''.join(ch for ch in p_reg_clean if ch.isdigit())
                if digits:
                    therapist_patient_dates[(b.therapist_id, digits)].add(b.date)

            v_key = b.visit_id if b.visit_id is not None else f"no_visit_{b.patient_id}_{b.therapy_name}"
            therapist_slot_assignments[b.date][b.time_slot_id][b.therapist_id].append({
                'visit_key': v_key,
                'patient_name': p_name,
                'patient_reg_no': p_reg,
                'is_bathing': bool(b.is_bathing),
                'therapy_name': b.therapy_name or ''
            })

        # Emergency substitutes set
        emergency_substitutes_set = set()  # (date, therapist_code)
        try:
            sched_audit_qs = SchedulingAuditLog.objects.filter(
                schedule_date__range=[from_date, to_date],
                change_type='emergency_replacement'
            )
            for sa in sched_audit_qs:
                if sa.replacement_therapist_code:
                    emergency_substitutes_set.add((sa.schedule_date, sa.replacement_therapist_code))
        except Exception:
            pass

        # Manual overrides set
        manual_override_allocs = set()  # (visit_id, date)
        try:
            alloc_changes = AllocationChange.objects.filter(
                created_at__date__range=[from_date, to_date]
            ).values_list('allocation_id', 'created_at__date')
            for aid, adate in alloc_changes:
                manual_override_allocs.add((aid, adate))
        except Exception:
            pass

        # Helper to check if a therapist is assigned due to registered preference
        def check_therapist_preference(p_info, t_id, t_code, t_name):
            reg_clean = normalize_patient_reg_no(p_info.get('reg_no', ''))
            room_no = p_info.get('room_no', '')
            digits = ''.join(ch for ch in reg_clean if ch.isdigit())

            # 1. Doctor Preference (DOC_REQ_008)
            doc_name = ''
            has_doc_pref = False
            
            if reg_clean in allowances_by_reg:
                allowance = allowances_by_reg[reg_clean]
                doc_name = allowance.doctor_name or 'Treating Doctor'
                if reg_clean in rosters_by_reg:
                    r = rosters_by_reg[reg_clean]
                    if t_code in (r.therapist_codes or []) or t_code in [r.primary_bathing_code, r.secondary_bathing_code]:
                        has_doc_pref = True
                else:
                    has_doc_pref = True

            pat_id_str = str(p_info.get('id', ''))
            if not has_doc_pref and pat_id_str in pref_reqs_by_pat_id:
                for req in pref_reqs_by_pat_id[pat_id_str]:
                    if t_code in (req.preferred_therapist_codes or []) or (t_id and t_id in req.preferred_therapists.values_list('id', flat=True)):
                        if req.treating_doctor_code or req.treating_doctor_name or 'Doctor' in (req.requested_by_role or ''):
                            has_doc_pref = True
                            doc_name = req.treating_doctor_name or 'Treating Doctor'
                            break

            if has_doc_pref:
                return (
                    True,
                    'doctor_preference',
                    'Doctor Preference',
                    "2. Doctor Preference: Assigned per Doctor's explicit order (DOC_REQ_008).",
                    f"Assigned per Doctor's explicit order (DOC_REQ_008) by {doc_name}."
                )

            # 2. Language Match
            if pat_id_str in pref_reqs_by_pat_id:
                for req in pref_reqs_by_pat_id[pat_id_str]:
                    notes = (req.request_notes or '').lower()
                    if any(w in notes for w in ['language', 'mother tongue', 'tamil', 'malayalam', 'hindi', 'kannada', 'telugu']):
                        if t_code in (req.preferred_therapist_codes or []):
                            return (
                                True,
                                'language_match',
                                'Language Match',
                                "3. Language Match: Assigned to satisfy patient language preference.",
                                "Assigned to satisfy patient language preference."
                            )

            # 3. Patient / VIP Preference (SCH_REQ_067)
            is_vip = (reg_clean in vip_profile_regs) or (digits in vip_regs)
            is_cottage = is_cottage_room(room_no)
            has_roster = False
            if reg_clean in rosters_by_reg:
                r = rosters_by_reg[reg_clean]
                if t_code in (r.therapist_codes or []) or t_code in [r.primary_bathing_code, r.secondary_bathing_code]:
                    has_roster = True

            if is_vip or is_cottage or has_roster:
                vip_tag = "VIP" if is_vip else ("Cottage" if is_cottage else "Preferred Roster")
                return (
                    True,
                    'vip_preference',
                    'Patient / VIP Preference',
                    "1. Patient / VIP Preference: Assigned per VIP/Cottage patient's preferred choice (SCH_REQ_067).",
                    f"Assigned per VIP/Cottage patient's preferred choice (SCH_REQ_067) [{vip_tag} Patient, Room {room_no or '—'}]."
                )

            return (False, '', '', '', '')

        # 4. Schedule Map Construction
        patient_info = {}
        schedule_map = defaultdict(lambda: defaultdict(lambda: defaultdict(lambda: defaultdict(lambda: {'therapists': {}, 'slot_key': ''}))))
        alloc_slot_id_map = {}
        pat_key_to_booking_patient_id = {}
        
        for b in bookings:
            if b.visit_id is not None:
                if (b.visit_id, b.date, b.time_slot_id) not in valid_pairs:
                    continue
            
            pat_snapshot_id = None
            if b.visit and b.visit.patient:
                pat_snapshot_id = b.visit.patient.id
            
            pat_key = pat_snapshot_id if pat_snapshot_id is not None else b.patient_id
            if pat_key is None:
                continue
            
            if pat_key not in pat_key_to_booking_patient_id:
                pat_key_to_booking_patient_id[pat_key] = b.patient_id if b.patient_id is not None else None
            
            if pat_key not in patient_info:
                if b.visit and b.visit.patient:
                    patient_info[pat_key] = {
                        'id': pat_key,
                        'name': b.visit.patient.pat_name or f"ID {pat_key}",
                        'reg_no': b.visit.patient.pat_reg_no or str(pat_key),
                        'room_no': b.visit.patient.pat_room_no or '—'
                    }
                elif b.patient_id:
                    try:
                        s = PatientSnapshot.objects.filter(id=b.patient_id).first()
                        if s:
                            patient_info[pat_key] = {
                                'id': pat_key, 
                                'name': s.pat_name or f"ID {pat_key}", 
                                'reg_no': s.pat_reg_no or str(pat_key), 
                                'room_no': s.pat_room_no or '—'
                            }
                        else:
                            patient_info[pat_key] = {'id': pat_key, 'name': f"ID {pat_key}", 'reg_no': str(pat_key), 'room_no': '—'}
                    except Exception:
                        patient_info[pat_key] = {'id': pat_key, 'name': f"ID {pat_key}", 'reg_no': str(pat_key), 'room_no': '—'}
                else:
                    patient_info[pat_key] = {'id': pat_key, 'name': f"ID {pat_key}", 'reg_no': str(pat_key), 'room_no': '—'}

            t_id = b.therapist.id
            t_name = b.therapy_name.strip() if b.therapy_name else "General"
            
            slot_key = "No Slot"
            if b.time_slot:
                slot_time = b.time_slot.slot_time if hasattr(b.time_slot, 'slot_time') else str(b.time_slot)
                try:
                    from datetime import datetime
                    if isinstance(slot_time, str):
                        for fmt in ['%H:%M:%S', '%H:%M', '%I:%M %p', '%I:%M:%S %p']:
                            try:
                                time_obj = datetime.strptime(slot_time, fmt).time()
                                slot_key = time_obj.strftime('%I:%M %p')
                                break
                            except Exception:
                                continue
                        else:
                            slot_key = slot_time
                    else:
                        slot_key = slot_time.strftime('%I:%M %p') if hasattr(slot_time, 'strftime') else str(slot_time)
                except Exception:
                    slot_key = str(slot_time)
                
                alloc_slot_id_map[(b.visit_id, slot_key)] = b.time_slot_id
            
            visit_key = b.visit_id if b.visit_id is not None else f"no_visit_{b.patient_id}_{t_name}"
            d_str = b.date.strftime('%Y-%m-%d')
            
            cell = schedule_map[pat_key][t_name][visit_key][d_str]
            cell['therapists'][t_id] = {
                'id': t_id,
                'name': b.therapist.therapist_name,
                'is_bathing': b.is_bathing
            }
            if not cell['slot_key']:
                cell['slot_key'] = slot_key
            cell['time_slot_id'] = b.time_slot_id

        # 5. Construct Matrix Rows
        rows = []
        date_cols = []
        curr = from_date
        while curr <= to_date:
            date_cols.append(curr.strftime('%Y-%m-%d'))
            curr += timedelta(days=1)
            
        def pat_matrix_sort_key(pk):
            p = patient_info[pk]
            room_no = get_staying_room_display_number(p.get('room_no'))
            room_key = get_room_sort_key(room_no)
            name = (p.get('name') or '').lower()
            reg_no = (p.get('reg_no') or '').lower()
            return (room_key, name, reg_no)
            
        sorted_pat_keys = sorted(schedule_map.keys(), key=pat_matrix_sort_key)
        
        for pat_key in sorted_pat_keys:
            p_info = patient_info[pat_key]
            p_reg_clean = normalize_patient_reg_no(p_info.get('reg_no', ''))
            raw_patient_id = pat_key_to_booking_patient_id.get(pat_key)
            therapies_data = schedule_map[pat_key]
            sorted_t_names = sorted(therapies_data.keys())
            
            for t_name in sorted_t_names:
                visits_data = therapies_data[t_name]
                sorted_visit_keys = sorted(visits_data.keys(), key=lambda k: k if isinstance(k, int) else 0)
                
                for visit_key in sorted_visit_keys:
                    dates_data = visits_data[visit_key]
                    
                    slot_counts = {}
                    for ds, cell_data in dates_data.items():
                        sk = cell_data.get('slot_key', '')
                        if sk:
                            slot_counts[sk] = slot_counts.get(sk, 0) + 1
                    row_slot = max(slot_counts, key=slot_counts.get) if slot_counts else 'No Slot'
                    
                    row = {
                        'patient': p_info,
                        'therapy_name': t_name,
                        'slot': row_slot,
                        'cells': {}
                    }
                    
                    baseline_set = None
                    prev_session_set = None
                    
                    for d_str in date_cols:
                        curr_data = dates_data.get(d_str, {'therapists': {}, 'slot_key': ''})
                        curr_objs = curr_data.get('therapists', {})
                        curr_set = set(curr_objs.keys())
                        curr_time_slot_id = curr_data.get('time_slot_id')
                        curr_slot_label = curr_data.get('slot_key') or row_slot
                        
                        if not curr_set:
                            row['cells'][d_str] = {'therapists': [], 'status': 'empty'}
                            continue
                            
                        date_obj = parse_date(d_str)
                        reference_set = set()
                        
                        if baseline_set is None:
                            # DAY 1: Look for prior history before matrix start date
                            query = None
                            if isinstance(visit_key, int):
                                query = TherapistBooking.objects.filter(
                                    visit_id=visit_key,
                                    date__lt=date_obj
                                ).exclude(status__icontains='cancel').exclude(status__icontains='fail')
                                if curr_time_slot_id:
                                    query = query.filter(time_slot_id=curr_time_slot_id)
                            else:
                                query = TherapistBooking.objects.filter(
                                    therapy_name=t_name,
                                    date__lt=date_obj
                                ).exclude(status__icontains='cancel').exclude(status__icontains='fail')
                                if raw_patient_id is not None:
                                    query = query.filter(patient_id=raw_patient_id)
                                else:
                                    query = query.filter(visit__patient__id=pat_key)
                                if curr_time_slot_id:
                                    query = query.filter(time_slot_id=curr_time_slot_id)
                            
                            last_booking = query.order_by('-date').first() if query else None
                            if last_booking:
                                valid_assignments_sub_prev = BookingAssignment.objects.filter(
                                    booking__allocation_id=OuterRef('visit_id'),
                                    booking__date=OuterRef('date'),
                                    booking__timeslot_id=OuterRef('time_slot_id'),
                                    therapist__therapist_code=OuterRef('therapist__therapist_code'),
                                    status='assigned'
                                ).exclude(booking__status__icontains='cancel').exclude(booking__status__icontains='fail')

                                prev_query = TherapistBooking.objects.filter(
                                    visit_id=last_booking.visit_id,
                                    date=last_booking.date,
                                    time_slot_id=last_booking.time_slot_id
                                ).exclude(status__icontains='cancel').exclude(status__icontains='fail').annotate(
                                    has_valid_assignment=Exists(valid_assignments_sub_prev)
                                ).filter(has_valid_assignment=True)
                                
                                reference_set = set(prev_query.values_list('therapist_id', flat=True))
                            
                            if not reference_set:
                                # First session establish baseline
                                reference_set = curr_set
                            
                            baseline_set = reference_set
                        else:
                            # Day 2+ — compare against baseline continuity reference
                            reference_set = baseline_set

                        missing_set = reference_set - curr_set
                        
                        # Pre-analyze reasons for any missing reference therapists
                        missing_explanations = []
                        for m_id in sorted(missing_set):
                            m_tm = therapist_master_map.get(m_id)
                            m_name = m_tm.therapist_name if m_tm else f"Therapist {m_id}"
                            m_code = m_tm.therapist_code if m_tm else ''
                            m_is_b = therapist_bathing_map.get(m_id, False)

                            # 1. Check Leave / Exemption (Grey)
                            t_name_clean = t_name.strip().lower()
                            is_omitted = (m_id, t_name_clean) in omission_set
                            is_deputed = date_obj in deputation_cache and m_id in deputation_cache[date_obj]
                            is_oncall = m_id in oncall_standby_cache.get(date_obj, set())
                            is_emergency = date_obj in emergency_leave_cache and m_id in emergency_leave_cache[date_obj]
                            is_weekly_off = date_obj.weekday() in weekly_off_therapist_days.get(m_id, set())

                            if is_omitted:
                                missing_explanations.append({
                                    'm_id': m_id,
                                    'm_name': m_name,
                                    'is_bathing': m_is_b,
                                    'status': 'gray',
                                    'sub_code': 'treatment_omission',
                                    'sub_title': 'Treatment Omission',
                                    'sub_detail': '4. Treatment Omission: Therapist has an approved exemption for this specific therapy (SCH_REQ_097).',
                                    'sub_notes': f'Previous therapist {m_name} has an approved exemption for therapy "{t_name}" (SCH_REQ_097).'
                                })
                            elif is_deputed:
                                dep_info = deputation_cache[date_obj][m_id]
                                missing_explanations.append({
                                    'm_id': m_id,
                                    'm_name': m_name,
                                    'is_bathing': m_is_b,
                                    'status': 'gray',
                                    'sub_code': 'deputed_on_call',
                                    'sub_title': 'Deputed / On-Call',
                                    'sub_detail': '3. Deputed / On-Call: Therapist deputed to another facility/duty (SCH_REQ_065).',
                                    'sub_notes': f'Previous therapist {m_name} deputed to {dep_info.get("destination", "external duty")} (SCH_REQ_065).'
                                })
                            elif is_oncall:
                                missing_explanations.append({
                                    'm_id': m_id,
                                    'm_name': m_name,
                                    'is_bathing': m_is_b,
                                    'status': 'gray',
                                    'sub_code': 'deputed_on_call',
                                    'sub_title': 'Deputed / On-Call',
                                    'sub_detail': '3. Deputed / On-Call: Therapist deputed to another facility/duty (SCH_REQ_065).',
                                    'sub_notes': f'Previous therapist {m_name} placed on on-call / standby duty (SCH_REQ_065).'
                                })
                            elif is_emergency:
                                el_info = emergency_leave_cache[date_obj][m_id]
                                missing_explanations.append({
                                    'm_id': m_id,
                                    'm_name': m_name,
                                    'is_bathing': m_is_b,
                                    'status': 'gray',
                                    'sub_code': 'emergency_leave',
                                    'sub_title': 'Emergency / Sick Leave',
                                    'sub_detail': '2. Emergency / Sick Leave: Approved emergency leave.',
                                    'sub_notes': f'Previous therapist {m_name} on approved emergency leave ({el_info.get("reason", "Approved Sick/Emergency Leave")}).'
                                })
                            elif is_weekly_off:
                                day_name = weekly_off_therapist_names.get(m_id, {}).get(date_obj.weekday()) or date_obj.strftime("%A")
                                missing_explanations.append({
                                    'm_id': m_id,
                                    'm_name': m_name,
                                    'is_bathing': m_is_b,
                                    'status': 'gray',
                                    'sub_code': 'weekly_off',
                                    'sub_title': 'Weekly Off',
                                    'sub_detail': '1. Weekly Off: Scheduled regular weekly off day.',
                                    'sub_notes': f'Previous therapist {m_name} on scheduled regular weekly off day ({day_name}).'
                                })
                            else:
                                # 2. Check if occupied elsewhere at this slot (Purple)
                                other_asgns = therapist_slot_assignments[date_obj][curr_time_slot_id].get(m_id, [])
                                other_filtered = [oa for oa in other_asgns if oa['visit_key'] != visit_key]
                                
                                if other_filtered:
                                    oa = other_filtered[0]
                                    other_p_name = oa['patient_name'] or 'another patient'
                                    other_p_reg = oa['patient_reg_no'] or '—'
                                    
                                    if oa['is_bathing']:
                                        missing_explanations.append({
                                            'm_id': m_id,
                                            'm_name': m_name,
                                            'is_bathing': m_is_b,
                                            'status': 'purple',
                                            'sub_code': 'occupied_bathing',
                                            'sub_title': 'Occupied as Bathing',
                                            'sub_detail': '4. Occupied as Bathing: Assigned as a bathing therapist to another patient at this slot.',
                                            'sub_notes': f'Previous therapist {m_name} assigned as bathing therapist to {other_p_name} ({other_p_reg}) at {curr_slot_label}.'
                                        })
                                    elif (date_obj, m_code) in emergency_substitutes_set:
                                        missing_explanations.append({
                                            'm_id': m_id,
                                            'm_name': m_name,
                                            'is_bathing': m_is_b,
                                            'status': 'purple',
                                            'sub_code': 'assigned_substitute',
                                            'sub_title': 'Assigned as Substitute',
                                            'sub_detail': '3. Assigned as Substitute: Covered another patient\'s session as an emergency/leave substitute.',
                                            'sub_notes': f'Previous therapist {m_name} covered {other_p_name}\'s session as an emergency/leave substitute.'
                                        })
                                    else:
                                        # Check if m_id treated that other patient previously
                                        other_reg_clean = normalize_patient_reg_no(other_p_reg)
                                        prior_dates = [d for d in therapist_patient_dates.get((m_id, other_reg_clean), set()) if d < date_obj]
                                        if prior_dates:
                                            missing_explanations.append({
                                                'm_id': m_id,
                                                'm_name': m_name,
                                                'is_bathing': m_is_b,
                                                'status': 'purple',
                                                'sub_code': 'occupied_as_primary',
                                                'sub_title': 'Occupied as Primary',
                                                'sub_detail': '1. Occupied as Primary: Assigned to another patient as their regular therapist (because they were that patient\'s prior continuity therapist).',
                                                'sub_notes': f'Previous therapist {m_name} assigned to {other_p_name} ({other_p_reg}) as their regular continuity therapist.'
                                            })
                                        else:
                                            missing_explanations.append({
                                                'm_id': m_id,
                                                'm_name': m_name,
                                                'is_bathing': m_is_b,
                                                'status': 'purple',
                                                'sub_code': 'assigned_newly',
                                                'sub_title': 'Assigned Newly',
                                                'sub_detail': '2. Assigned Newly: Assigned to another patient as a new allocation.',
                                                'sub_notes': f'Previous therapist {m_name} assigned to {other_p_name} ({other_p_reg}) as a new allocation at {curr_slot_label}.'
                                            })
                                else:
                                    # 3. Free & Available, but not assigned (Red)
                                    daily_cnt = daily_therapist_counts[date_obj].get(m_id, 0)
                                    has_override = (visit_key, date_obj) in manual_override_allocs
                                    
                                    if daily_cnt >= 5:
                                        missing_explanations.append({
                                            'm_id': m_id,
                                            'm_name': m_name,
                                            'is_bathing': m_is_b,
                                            'status': 'red',
                                            'sub_code': 'workload_cap',
                                            'sub_title': 'Grade / Workload Cap',
                                            'sub_detail': '3. Grade / Workload Cap: Previous therapist hit the daily maximum session threshold.',
                                            'sub_notes': f'Previous therapist {m_name} hit daily maximum session threshold ({daily_cnt} sessions on {d_str}).'
                                        })
                                    elif has_override:
                                        missing_explanations.append({
                                            'm_id': m_id,
                                            'm_name': m_name,
                                            'is_bathing': m_is_b,
                                            'status': 'red',
                                            'sub_code': 'manual_override',
                                            'sub_title': 'Manual Override',
                                            'sub_detail': '2. Manual Override: Schedulers manually chose another therapist without an exclusion rule.',
                                            'sub_notes': 'Schedulers manually chose another therapist without an exclusion rule.'
                                        })
                                    else:
                                        missing_explanations.append({
                                            'm_id': m_id,
                                            'm_name': m_name,
                                            'is_bathing': m_is_b,
                                            'status': 'red',
                                            'sub_code': 'algorithm_mismatch',
                                            'sub_title': 'Algorithm Slot Mismatch',
                                            'sub_detail': '1. Algorithm Slot Mismatch: Patient\'s treatment was shifted to a slot where the therapist was free, but preference/load-balancing picked someone else.',
                                            'sub_notes': f'Previous therapist {m_name} was free at this slot, but algorithm load-balancing selected another therapist.'
                                        })

                        # Evaluate currently assigned therapists
                        therapist_list = []
                        for t_id in sorted(curr_objs.keys()):
                            t_data = curr_objs[t_id].copy()
                            t_tm = therapist_master_map.get(t_id)
                            t_code = t_tm.therapist_code if t_tm else ''
                            t_name_disp = t_data.get('name', '')
                            is_b = t_data.get('is_bathing', False)

                            is_pref, pref_code, pref_title, pref_detail, pref_notes = check_therapist_preference(
                                p_info, t_id, t_code, t_name_disp
                            )

                            if is_pref:
                                # Preference Allocation (Blue)
                                t_data['status'] = 'blue'
                                t_data['status_label'] = STATUS_LABELS['blue']
                                t_data['core_meaning'] = CORE_MEANINGS['blue']
                                t_data['sub_reason_code'] = pref_code
                                t_data['sub_reason_title'] = pref_title
                                t_data['sub_reason_detail'] = pref_detail
                                t_data['sub_reason_notes'] = pref_notes
                                t_data['continuity_score'] = "100%" if (t_id in reference_set or (prev_session_set and t_id in prev_session_set)) else "0%"
                                t_data['previous_therapist_name'] = missing_explanations[0]['m_name'] if missing_explanations else t_name_disp
                                t_data['all_sub_reasons'] = ALL_SUB_REASONS['blue']

                            elif t_id in reference_set or (prev_session_set and t_id in prev_session_set):
                                # Continuity Maintained (Green)
                                t_data['status'] = 'green'
                                t_data['status_label'] = STATUS_LABELS['green']
                                t_data['core_meaning'] = CORE_MEANINGS['green']
                                t_data['sub_reason_code'] = 'primary_retained'
                                t_data['sub_reason_title'] = 'Same Primary Therapist Retained'
                                t_data['sub_reason_detail'] = "• Same primary therapist retained from previous session.<br>• Continuity score: 100%."
                                t_data['sub_reason_notes'] = "Same primary therapist retained from previous session. Continuity score: 100%."
                                t_data['continuity_score'] = "100%"
                                t_data['previous_therapist_name'] = t_name_disp
                                t_data['all_sub_reasons'] = ALL_SUB_REASONS['green']

                            else:
                                # Match with an unclaimed missing explanation
                                matched_exp = None
                                for exp in missing_explanations:
                                    if not exp.get('claimed') and exp['is_bathing'] == is_b:
                                        matched_exp = exp
                                        exp['claimed'] = True
                                        break
                                if not matched_exp:
                                    for exp in missing_explanations:
                                        if not exp.get('claimed'):
                                            matched_exp = exp
                                            exp['claimed'] = True
                                            break

                                if matched_exp:
                                    status_key = matched_exp['status']
                                    t_data['status'] = status_key
                                    t_data['status_label'] = STATUS_LABELS[status_key]
                                    t_data['core_meaning'] = CORE_MEANINGS[status_key]
                                    t_data['sub_reason_code'] = matched_exp['sub_code']
                                    t_data['sub_reason_title'] = matched_exp['sub_title']
                                    t_data['sub_reason_detail'] = matched_exp['sub_detail']
                                    t_data['sub_reason_notes'] = matched_exp['sub_notes']
                                    t_data['continuity_score'] = "0%"
                                    t_data['previous_therapist_name'] = matched_exp['m_name']
                                    t_data['all_sub_reasons'] = ALL_SUB_REASONS[status_key]
                                else:
                                    # Addition
                                    t_data['status'] = 'green'
                                    t_data['status_label'] = STATUS_LABELS['green']
                                    t_data['core_meaning'] = CORE_MEANINGS['green']
                                    t_data['sub_reason_code'] = 'primary_retained'
                                    t_data['sub_reason_title'] = 'Same Primary Therapist Retained'
                                    t_data['sub_reason_detail'] = "• Same primary therapist retained from previous session.<br>• Continuity score: 100%."
                                    t_data['sub_reason_notes'] = "Additional therapist assigned to treatment."
                                    t_data['continuity_score'] = "100%"
                                    t_data['previous_therapist_name'] = t_name_disp
                                    t_data['all_sub_reasons'] = ALL_SUB_REASONS['green']

                            therapist_list.append(t_data)

                        prev_session_set = curr_set
                        
                        row['cells'][d_str] = {
                            'therapists': therapist_list,
                            'status': 'active',
                            'slot': curr_data.get('slot_key', '')
                        }
                    
                    rows.append(row)
            
        response = JsonResponse({
            'columns': date_cols,
            'rows': rows,
            'meta': {
                'total_bookings_fetched': bookings.count(),
                'total_patients': len(schedule_map),
                'total_rows': len(rows),
                'date_range': f"{from_date} to {to_date}"
            }
        })
        response['Cache-Control'] = 'no-cache, no-store, must-revalidate'
        return response

    except Exception as e:
        import traceback
        return JsonResponse({
            'error': f"Server Error: {str(e)}",
            'detail': traceback.format_exc()
        }, status=500)
