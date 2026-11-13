"""
Views and API endpoints for:
1. Doctor's Profile / Doctor View: My Patients (VIP & Repeated), Doctor Monthly Quota (max 5/month), Allowance toggle.
2. Scheduling Dashboard: Preferred Therapist Assignment for Allowed Patients (up to 7 therapists, primary/secondary bathing, week off display).
"""
import json
from datetime import datetime
from django.shortcuts import render, get_object_or_404
from django.http import JsonResponse
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_http_methods
from django.utils import timezone
from django.db.models import Q
from django.core.exceptions import ValidationError

from authentication.decorators import role_required
from masters.models import TherapistMaster, TherapistLeaveMaster, get_staying_room_display_number
from Patient.models import Repeated_Visitors
from .models import (
    PatientSnapshot,
    DoctorPatientPreferenceAllowance,
    PatientPreferredTherapistRoster,
    TherapyAllocation,
)
from .preferred_therapist_service import (
    resolve_patient_vip_and_repeated,
    is_cottage_room,
    resolve_treating_doctor_for_patient,
    is_user_patient_treating_doctor,
    get_therapists_with_schedule_info,
    toggle_doctor_patient_allowance,
    save_preferred_therapist_roster,
    get_active_preferred_roster,
)
from .hospital_doctor_lookup import (
    pat_reg_nos_for_hospital_doctor,
    chunked_q_pat_reg_in,
    get_doctor_codes_for_user,
)


@login_required
@role_required(['doctor', 'admin', 'super_admin'])
def doctor_patients_vip_repeated_view(request):
    """
    Page in Doctor's Profile / Doctor Area:
    View all patients linked to the doctor with filter options for:
      - All Patients
      - VIP Patients
      - Repeated Patients
      - Allowed for Preferred Therapist
    Shows monthly quota (max 5 allowed patients per calendar month) and remaining quota.
    """
    now = timezone.now()
    quota = DoctorPatientPreferenceAllowance.get_monthly_quota(request.user, now.year, now.month)

    context = {
        'dashboard_title': 'My Patients — VIP & Preferred Therapist Allocation',
        'quota': quota,
        'current_month_name': now.strftime("%B %Y"),
        'user_role': getattr(request.user, 'role', ''),
        'doctor_name': request.user.get_full_name() or request.user.username,
    }
    return render(request, 'dashboards/doctorsAndHelpDesk/doctor_patients_vip_repeated.html', context)


@login_required
@role_required(['doctor', 'admin', 'super_admin'])
@require_http_methods(["GET"])
def get_doctor_patients_vip_repeated_api(request):
    """
    API returning doctor's patients with VIP & Repeated status,
    allowance toggle status, and monthly quota.
    Query params:
      - filter: 'ALL', 'VIP', 'REPEATED', 'ALLOWED' (default 'ALL')
      - search: string query (name, reg no, room)
      - page: int (1-based)
      - page_size: int (default 25)
    """
    now = timezone.now()
    filter_type = request.GET.get('filter', 'ALL').upper()
    search_query = request.GET.get('search', '').strip().lower()

    try:
        page = max(1, int(request.GET.get('page', 1)))
        page_size = max(5, min(100, int(request.GET.get('page_size', 25))))
    except ValueError:
        page = 1
        page_size = 25

    # 1. Resolve doctor information and doctor codes
    doc_codes = set()
    my_patient_regs = set()
    is_doctor = (
        getattr(request.user, 'role', '') in ['doctor', 'doctor_admin'] or
        (hasattr(request.user, 'doctor_profile') and request.user.doctor_profile is not None)
    )
    is_admin = getattr(request.user, 'role', '') in ['admin', 'super_admin']

    if is_doctor:
        try:
            doc_codes = set(get_doctor_codes_for_user(request.user))
        except Exception:
            pass

        # Include patients prescribed by this doctor
        try:
            from .models import PrescriptionScheduling
            ps_regs = PrescriptionScheduling.objects.filter(doctor=request.user).values_list('patient__pat_reg_no', flat=True)
            my_patient_regs.update(str(r).strip() for r in ps_regs if r)
        except Exception:
            pass

        # Include patients allocated by this doctor
        alloc_regs = TherapyAllocation.objects.filter(allocated_by=request.user).values_list('patient__pat_reg_no', flat=True)
        my_patient_regs.update(str(r).strip() for r in alloc_regs if r)

    # Include patients already allowed by this doctor
    allow_regs = DoctorPatientPreferenceAllowance.objects.filter(
        doctor=request.user,
        year=now.year,
        month=now.month
    ).values_list('patient_reg_no', flat=True)
    my_patient_regs.update(str(r).strip() for r in allow_regs if r)

    from final_allocation import is_patient_active

    # Preload active allocations for today / ongoing
    active_alloc_regs = set(
        str(r).strip() for r in TherapyAllocation.objects.filter(
            to_date__gte=now.date(),
            status__in=['draft', 'allocated']
        ).values_list('patient__pat_reg_no', flat=True) if r
    )

    # Helper function to check if a patient belongs to this doctor
    def patient_belongs_to_doctor(reg_no, doctcode=None):
        if is_admin:
            return True
        if not is_doctor:
            return False
        # 1. Direct doctcode check
        if doctcode:
            dc_clean = str(doctcode).split('.')[0].strip()
            if dc_clean in doc_codes:
                return True
            if dc_clean.isdigit() and str(int(dc_clean)) in doc_codes:
                return True
        # 2. Check if linked in local DB (prescriptions, allocations, allowances)
        if reg_no in my_patient_regs:
            return True
        # 3. Fallback only if doctcode is absent
        if not doctcode:
            return is_user_patient_treating_doctor(request.user, reg_no)
        return False

    # 2. Bulk fetch active admitted IP patients and their doctors from therapy_db
    active_hospital_regs = {}
    active_doc_cache = {}
    try:
        from MySql_Data_pull.models import Registration, doctor_master
        # pat_status='Y' strictly filters ONLY currently admitted active IP patients!
        reg_qs = Registration.objects.using('therapy_db').filter(pat_status='Y')

        for r in reg_qs.values('pat_reg_no', 'pat_name', 'pat_room_no', 'pat_age', 'pat_sex', 'doctcode', 'dct_team'):
            r_reg = str(r['pat_reg_no']).strip()
            active_hospital_regs[r_reg] = r
            if r.get('doctcode'):
                dc = str(r['doctcode']).split('.')[0].strip()
                if dc:
                    active_doc_cache[dc] = None

        if active_doc_cache:
            doc_search = list(active_doc_cache.keys()) + [k.zfill(4) for k in active_doc_cache.keys() if k.isdigit()]
            for dm in doctor_master.objects.using('therapy_db').filter(Doct_Code__in=doc_search):
                d_name = dm.Doct_Name.strip() if dm.Doct_Name else ''
                if d_name and not d_name.lower().startswith(('dr', 'vaidya')):
                    d_name = f"Dr. {d_name}"
                code_key = str(dm.Doct_Code).strip()
                active_doc_cache[code_key] = d_name
                if code_key.isdigit():
                    active_doc_cache[str(int(code_key))] = d_name
    except Exception:
        # Hospital DB offline / unreachable (falls back to active PatientSnapshot)
        pass

    # 3. Build active patient list (STRICTLY ACTIVE ONLY!)
    seen_regs = set()
    patient_snapshots = []

    # Case A: Hospital DB is reachable and returned active patients
    if active_hospital_regs:
        existing_snaps = {
            str(ps.pat_reg_no).strip(): ps
            for ps in PatientSnapshot.objects.filter(chunked_q_pat_reg_in(list(active_hospital_regs.keys()), 'pat_reg_no'))
        }
        for r_reg, h_data in active_hospital_regs.items():
            if r_reg in seen_regs:
                continue

            # If doctor user (not admin), strictly include ONLY this doctor's patients!
            if is_doctor and not is_admin:
                if not patient_belongs_to_doctor(r_reg, h_data.get('doctcode')):
                    continue

            seen_regs.add(r_reg)

            raw_room = str(h_data.get('pat_room_no') or '').strip()
            room_norm = get_staying_room_display_number(raw_room) or raw_room

            snap = existing_snaps.get(r_reg)
            if not snap:
                snap = PatientSnapshot(
                    pat_reg_no=r_reg,
                    pat_name=h_data.get('pat_name') or f"Patient {r_reg}",
                    pat_room_no=room_norm,
                    pat_age=str(h_data.get('pat_age') or ''),
                    pat_sex=str(h_data.get('pat_sex') or ''),
                )
            else:
                if room_norm:
                    snap.pat_room_no = room_norm
                if h_data.get('pat_name'):
                    snap.pat_name = h_data['pat_name']
                if h_data.get('pat_age'):
                    snap.pat_age = str(h_data['pat_age'])
                if h_data.get('pat_sex'):
                    snap.pat_sex = str(h_data['pat_sex'])
            patient_snapshots.append(snap)

    # Case B: Offline mode or test environment
    if not active_hospital_regs:
        base_qs = PatientSnapshot.objects.filter(
            Q(pat_reg_no__in=active_alloc_regs) | ~Q(pat_room_no__isnull=True)
        ).exclude(pat_room_no='').exclude(pat_room_no__iexact='N/A').exclude(pat_room_no__iexact='None').exclude(pat_room_no='0')

        if is_doctor and not is_admin and my_patient_regs:
            doc_local_snaps = list(base_qs.filter(chunked_q_pat_reg_in(list(my_patient_regs), 'pat_reg_no')))
            found_regs = {str(ps.pat_reg_no).strip() for ps in doc_local_snaps}
            for mr in my_patient_regs - found_regs:
                if is_patient_active(mr):
                    doc_local_snaps.append(PatientSnapshot(pat_reg_no=mr, pat_name=f"Patient {mr}", pat_room_no='Active'))
            candidates = doc_local_snaps
        else:
            candidates = list(base_qs.order_by('-updated_at')[:150])

        for ps in candidates:
            r_reg = str(ps.pat_reg_no).strip()
            if r_reg in seen_regs:
                continue
            if not is_patient_active(r_reg):
                continue
            if is_doctor and not is_admin and not patient_belongs_to_doctor(r_reg):
                continue
            seen_regs.add(r_reg)
            patient_snapshots.append(ps)

    # Include any active patients locally allocated/prescribed/allowed by this doctor
    if is_doctor and not is_admin and my_patient_regs:
        missing_my_regs = my_patient_regs - seen_regs
        for mr in missing_my_regs:
            if is_patient_active(mr):
                ps = PatientSnapshot.objects.filter(pat_reg_no=mr).first()
                if ps and ps.pat_room_no and str(ps.pat_room_no).upper() not in ['N/A', 'NONE', '0', '']:
                    seen_regs.add(mr)
                    patient_snapshots.append(ps)
                elif mr in active_alloc_regs:
                    seen_regs.add(mr)
                    patient_snapshots.append(ps or PatientSnapshot(pat_reg_no=mr, pat_name=f"Patient {mr}", pat_room_no='Active'))

    # Preload active allowances for this month
    active_allowances = {
        a.patient_reg_no: a
        for a in DoctorPatientPreferenceAllowance.objects.filter(
            doctor=request.user,
            year=now.year,
            month=now.month,
            is_active=True
        )
    }

    # Preload rosters
    rosters_map = {
        r.patient_reg_no: r
        for r in PatientPreferredTherapistRoster.objects.filter(is_active=True)
    }

    # Process and filter patients
    patient_items = []
    vip_count = 0
    cottage_repeated_count = 0
    allowed_count = 0
    total_active_count = 0

    for ps in patient_snapshots:
        reg_no = str(ps.pat_reg_no or '').strip()
        name = ps.pat_name or f"Patient {reg_no}"
        room = get_staying_room_display_number(ps.pat_room_no) if ps.pat_room_no else ''
        gender = ps.pat_sex or '—'
        age = ps.pat_age or '—'

        # If data present in active_hospital_regs, update details
        h_row = active_hospital_regs.get(reg_no)
        if h_row:
            name = h_row.get('pat_name') or name
            age = str(h_row.get('pat_age') or age)
            gender = h_row.get('pat_sex') or gender
            if h_row.get('pat_room_no'):
                raw_h_room = str(h_row['pat_room_no']).strip()
                room = get_staying_room_display_number(raw_h_room) or raw_h_room

        # Strictly exclude patients with N/A room and no active allocation
        has_alloc = reg_no in active_alloc_regs
        is_my_doc_pat = bool(is_doctor and not is_admin and (
            (h_row and str(h_row.get('doctcode') or '').split('.')[0].strip() in doc_codes) or
            reg_no in my_patient_regs
        ))
        if (not room or str(room).strip().upper() in ['N/A', 'NONE', '0', '']) and not has_alloc and not is_my_doc_pat:
            continue

        # If doctor user (not admin), verify patient belongs to doctor
        if is_doctor and not is_admin:
            dc_val = h_row.get('doctcode') if h_row else None
            if not patient_belongs_to_doctor(reg_no, dc_val):
                continue
            is_treating_doctor = True
        else:
            is_treating_doctor = is_user_patient_treating_doctor(request.user, reg_no) if is_doctor else True

        total_active_count += 1

        vip_rep = resolve_patient_vip_and_repeated(reg_no, room_no=ps.pat_room_no or room)
        is_vip = vip_rep['is_vip']
        is_repeated = vip_rep['is_repeated']
        is_cottage = vip_rep['is_cottage']
        is_cottage_repeated = vip_rep['is_cottage_repeated']
        is_eligible = vip_rep['is_eligible']
        total_visits = vip_rep['total_visits']

        if is_vip:
            vip_count += 1
        if is_cottage_repeated:
            cottage_repeated_count += 1

        is_allowed = reg_no in active_allowances
        if is_allowed:
            allowed_count += 1

        roster_obj = rosters_map.get(reg_no)
        has_roster = bool(roster_obj and (roster_obj.therapist_codes or roster_obj.unpreferred_therapist_codes))
        roster_pref_count = len(roster_obj.therapist_codes) if roster_obj and roster_obj.therapist_codes else 0
        roster_unpref_count = len(roster_obj.unpreferred_therapist_codes) if roster_obj and roster_obj.unpreferred_therapist_codes else 0
        roster_therapist_count = roster_pref_count

        # Filter criteria:
        if filter_type == 'VIP' and not is_vip:
            continue
        if filter_type in ['REPEATED', 'COTTAGE_REPEATED'] and not is_cottage_repeated:
            continue
        if filter_type == 'ALLOWED' and not is_allowed:
            continue

        # Search filter
        if search_query:
            match_name = search_query in name.lower()
            match_reg = search_query in reg_no.lower()
            match_room = search_query in str(room).lower()
            if not (match_name or match_reg or match_room):
                continue

        # Resolve Treating Doctor Name & Code
        doc_code = ''
        doc_name = ''

        # 1. Check pre-fetched active hospital doctor cache
        if h_row and h_row.get('doctcode'):
            dc_clean = str(h_row['doctcode']).split('.')[0].strip()
            doc_code = dc_clean
            doc_name = active_doc_cache.get(dc_clean) or active_doc_cache.get(dc_clean.zfill(4)) or ''

        # 2. If not found in cache, use resolve_treating_doctor_for_patient
        if not doc_name or doc_name == "Not Assigned":
            u_res, c_res, n_res = resolve_treating_doctor_for_patient(reg_no)
            doc_code = c_res or doc_code
            doc_name = n_res or doc_name

        if doc_name and not doc_name.lower().startswith(('dr', 'vaidya')) and doc_name != "Not Assigned":
            doc_name = f"Dr. {doc_name}"

        patient_items.append({
            'patient_reg_no': reg_no,
            'patient_name': name,
            'patient_age': age,
            'patient_gender': gender,
            'room_no': room,
            'is_vip': is_vip,
            'is_repeated': is_repeated,
            'is_cottage': is_cottage,
            'is_cottage_repeated': is_cottage_repeated,
            'is_eligible': is_eligible,
            'total_visits': total_visits,
            'is_allowed': is_allowed,
            'has_roster': has_roster,
            'roster_therapist_count': roster_therapist_count,
            'roster_pref_count': roster_pref_count,
            'roster_unpref_count': roster_unpref_count,
            'allowance_id': active_allowances[reg_no].id if is_allowed else None,
            'treating_doctor_name': doc_name if (doc_name and doc_name != 'Not Assigned') else (f"Dr. {doc_code}" if doc_code else 'Not Assigned'),
            'treating_doctor_code': doc_code or '',
            'is_treating_doctor': is_treating_doctor,
        })

    # Pagination
    total_matching = len(patient_items)
    start_idx = (page - 1) * page_size
    end_idx = start_idx + page_size
    paged_items = patient_items[start_idx:end_idx]

    quota = DoctorPatientPreferenceAllowance.get_monthly_quota(request.user, now.year, now.month)

    return JsonResponse({
        'status': 'success',
        'patients': paged_items,
        'total': total_matching,
        'page': page,
        'page_size': page_size,
        'total_pages': max(1, (total_matching + page_size - 1) // page_size),
        'quota': quota,
        'counts': {
            'all': total_active_count,
            'vip': vip_count,
            'repeated': cottage_repeated_count,
            'allowed': allowed_count,
        }
    })





@login_required
@role_required(['doctor', 'admin', 'super_admin'])
@require_http_methods(["POST"])
def toggle_doctor_patient_allowance_api(request):
    """
    API for Doctor to mark / unmark a patient as allowed for preferred therapist assignment.
    Enforces the monthly quota limit of 5 patients per month.
    """
    try:
        data = json.loads(request.body.decode('utf-8'))
    except Exception:
        return JsonResponse({'status': 'error', 'message': 'Invalid JSON data'}, status=400)

    patient_reg_no = data.get('patient_reg_no')
    patient_name = data.get('patient_name', '')
    notes = data.get('notes', '')
    room_no = data.get('room_no', None)

    if not patient_reg_no:
        return JsonResponse({'status': 'error', 'message': 'Patient registration number is required'}, status=400)

    result = toggle_doctor_patient_allowance(
        doctor_user=request.user,
        patient_reg_no=patient_reg_no,
        patient_name=patient_name,
        notes=notes,
        room_no=room_no
    )

    if result.get('status') == 'not_treating_doctor':
        return JsonResponse({
            'status': 'error',
            'error_type': 'not_treating_doctor',
            'message': result.get('error'),
            'quota': result.get('quota')
        }, status=403)

    if result.get('status') == 'ineligible':
        return JsonResponse({
            'status': 'error',
            'error_type': 'ineligible',
            'message': result.get('error'),
            'quota': result.get('quota')
        }, status=400)

    if result.get('status') == 'quota_exceeded':
        return JsonResponse({
            'status': 'error',
            'error_type': 'quota_exceeded',
            'message': result.get('error'),
            'quota': result.get('quota')
        }, status=400)

    return JsonResponse({
        'status': 'success',
        'is_allowed': result.get('is_allowed'),
        'message': result.get('message'),
        'quota': result.get('quota')
    })


@login_required
@role_required(['scheduling_staff', 'admin', 'super_admin', 'doctor'])
def scheduling_preferred_therapists_view(request):
    """
    Scheduling Dashboard Page:
    Shows ONLY the patients that have been allowed by their doctor
    to receive preferred therapist assignment.
    Allows marking up to 7 therapists, designating 1 Primary and 1 Secondary Bathing Therapist.
    Displays week offs for all therapists.
    """
    now = timezone.now()
    allowed_count = DoctorPatientPreferenceAllowance.objects.filter(is_active=True).count()
    roster_count = PatientPreferredTherapistRoster.objects.filter(is_active=True).count()

    context = {
        'dashboard_title': 'Preferred Therapist Assignment — Allowed Patients',
        'allowed_count': allowed_count,
        'roster_count': roster_count,
        'pending_count': max(0, allowed_count - roster_count),
        'user_role': getattr(request.user, 'role', ''),
    }
    return render(request, 'dashboards/scheduling/preferred_therapist_assignment.html', context)


@login_required
@role_required(['scheduling_staff', 'admin', 'super_admin', 'doctor'])
@require_http_methods(["GET"])
def get_allowed_patients_preferred_therapists_api(request):
    """
    API returning ONLY patients allowed by their doctor for preferred therapist assignment.
    Includes current roster details, primary and secondary bathing therapists.
    """
    now = timezone.now()
    status_filter = request.GET.get('status', 'ALL').upper()
    search_query = request.GET.get('search', '').strip().lower()

    # Query only active allowances
    allowances = DoctorPatientPreferenceAllowance.objects.filter(is_active=True).select_related('doctor').order_by('-updated_at')

    patient_records = []
    configured_count = 0
    pending_count = 0

    for al in allowances:
        reg_no = al.patient_reg_no
        name = al.patient_name or f"Patient {reg_no}"
        doc_display = al.doctor_name or al.doctor.get_full_name() or al.doctor.username
        if not doc_display.lower().startswith('dr'):
            doc_display = f"Dr. {doc_display}"

        ps = PatientSnapshot.objects.filter(pat_reg_no=reg_no).first()
        room = get_staying_room_display_number(ps.pat_room_no) if ps and ps.pat_room_no else '—'
        age = ps.pat_age if ps and ps.pat_age else '—'
        gender = ps.pat_sex if ps and ps.pat_sex else '—'

        if not gender or gender == '—' or not age or age == '—':
            try:
                from MySql_Data_pull.models import Registration
                d = ''.join(ch for ch in str(reg_no) if ch.isdigit())
                if d:
                    h_r = Registration.objects.using('therapy_db').filter(pat_reg_no=int(d)).values('pat_sex', 'pat_age').first()
                    if h_r:
                        if not gender or gender == '—':
                            gender = h_r.get('pat_sex') or '—'
                        if not age or age == '—':
                            age = h_r.get('pat_age') or '—'
            except Exception:
                pass

        from final_allocation import resolve_desired_gender
        raw_desired = resolve_desired_gender(gender if gender != '—' else None, age if age != '—' else None)
        desired_gender = raw_desired.capitalize() if raw_desired else 'Male'

        vip_rep = resolve_patient_vip_and_repeated(reg_no, room_no=ps.pat_room_no if ps else None)
        is_vip = vip_rep['is_vip']
        is_repeated = vip_rep['is_repeated']
        is_cottage = vip_rep['is_cottage']
        is_cottage_repeated = vip_rep['is_cottage_repeated']
        total_visits = vip_rep['total_visits']

        roster = PatientPreferredTherapistRoster.objects.filter(patient_reg_no=reg_no, is_active=True).first()
        is_configured = bool(roster and (roster.therapist_codes or roster.unpreferred_therapist_codes))

        if is_configured:
            configured_count += 1
        else:
            pending_count += 1

        if status_filter == 'CONFIGURED' and not is_configured:
            continue
        if status_filter == 'PENDING' and is_configured:
            continue

        if search_query:
            match_name = search_query in name.lower()
            match_reg = search_query in reg_no.lower()
            match_doc = search_query in doc_display.lower()
            if not (match_name or match_reg or match_doc):
                continue

        # Build roster info if configured
        roster_data = None
        if roster and is_configured:
            # Build therapist details with week offs
            codes = roster.therapist_codes or []
            therapist_objs = {t.therapist_code: t for t in TherapistMaster.objects.filter(therapist_code__in=codes).select_related('therapist_grade').prefetch_related('leaves')}

            therapists_detail = []
            for c in codes:
                t_obj = therapist_objs.get(c)
                if t_obj:
                    leaves = list(t_obj.leaves.filter(is_active=True))
                    week_off_str = ", ".join(l.leave_day_name for l in leaves if l.leave_day_name) or "None"
                    therapists_detail.append({
                        'code': t_obj.therapist_code,
                        'name': t_obj.therapist_name,
                        'grade': t_obj.therapist_grade.name if t_obj.therapist_grade else "Therapist",
                        'gender': t_obj.therapist_gender,
                        'is_bathing': t_obj.is_bathing_therapist,
                        'week_off': week_off_str,
                    })
                else:
                    therapists_detail.append({
                        'code': c,
                        'name': c,
                        'grade': '—',
                        'gender': '—',
                        'is_bathing': False,
                        'week_off': 'None',
                    })

            # Primary bathing therapist info
            pb_obj = roster.primary_bathing_therapist or therapist_objs.get(roster.primary_bathing_code)
            pb_week_off = "None"
            pb_name = roster.primary_bathing_code or '—'
            if pb_obj:
                pb_leaves = list(pb_obj.leaves.filter(is_active=True))
                pb_week_off = ", ".join(l.leave_day_name for l in pb_leaves if l.leave_day_name) or "None"
                pb_name = pb_obj.therapist_name

            # Secondary bathing therapist info
            sb_obj = roster.secondary_bathing_therapist or therapist_objs.get(roster.secondary_bathing_code)
            sb_week_off = "None"
            sb_name = roster.secondary_bathing_code or '—'
            if sb_obj:
                sb_leaves = list(sb_obj.leaves.filter(is_active=True))
                sb_week_off = ", ".join(l.leave_day_name for l in sb_leaves if l.leave_day_name) or "None"
                sb_name = sb_obj.therapist_name

            # Unpreferred therapists info
            unpref_codes = roster.unpreferred_therapist_codes or []
            unpref_objs = {t.therapist_code: t for t in TherapistMaster.objects.filter(therapist_code__in=unpref_codes).select_related('therapist_grade').prefetch_related('leaves')}
            unpreferred_detail = []
            for uc in unpref_codes:
                u_obj = unpref_objs.get(uc)
                if u_obj:
                    u_leaves = list(u_obj.leaves.filter(is_active=True))
                    u_week_off_str = ", ".join(l.leave_day_name for l in u_leaves if l.leave_day_name) or "None"
                    unpreferred_detail.append({
                        'code': u_obj.therapist_code,
                        'name': u_obj.therapist_name,
                        'grade': u_obj.therapist_grade.name if u_obj.therapist_grade else "Therapist",
                        'gender': u_obj.therapist_gender,
                        'is_bathing': u_obj.is_bathing_therapist,
                        'week_off': u_week_off_str,
                    })
                else:
                    unpreferred_detail.append({
                        'code': uc,
                        'name': uc,
                        'grade': '—',
                        'gender': '—',
                        'is_bathing': False,
                        'week_off': 'None',
                    })

            roster_data = {
                'id': roster.id,
                'therapist_codes': codes,
                'therapist_count': len(codes),
                'therapists_detail': therapists_detail,
                'unpreferred_codes': unpref_codes,
                'unpreferred_count': len(unpref_codes),
                'unpreferred_detail': unpreferred_detail,
                'primary_bathing_code': roster.primary_bathing_code,
                'primary_bathing_name': pb_name,
                'primary_bathing_week_off': pb_week_off,
                'secondary_bathing_code': roster.secondary_bathing_code,
                'secondary_bathing_name': sb_name,
                'secondary_bathing_week_off': sb_week_off,
                'configured_by': roster.configured_by.get_full_name() or roster.configured_by.username if roster.configured_by else 'Scheduling Team',
                'updated_at': roster.updated_at.strftime('%d/%m/%Y %H:%M') if roster.updated_at else '—',
            }

        patient_records.append({
            'patient_reg_no': reg_no,
            'patient_name': name,
            'room_no': room,
            'age': age,
            'gender': gender,
            'desired_gender': desired_gender,
            'is_vip': is_vip,
            'is_repeated': is_repeated,
            'is_cottage': is_cottage,
            'is_cottage_repeated': is_cottage_repeated,
            'total_visits': total_visits,
            'doctor_name': doc_display,
            'allowed_date': al.created_at.strftime('%d/%m/%Y') if al.created_at else '—',
            'is_configured': is_configured,
            'roster': roster_data,
        })

    return JsonResponse({
        'status': 'success',
        'patients': patient_records,
        'counts': {
            'total_allowed': len(allowances),
            'configured': configured_count,
            'pending': pending_count,
        }
    })


@login_required
@role_required(['scheduling_staff', 'admin', 'super_admin', 'doctor'])
@require_http_methods(["GET"])
def get_therapists_with_leaves_api(request):
    """
    API returning active therapists with their weekly off day(s),
    grade, gender, and bathing qualification for selection in scheduling modal.
    Supports filtering by gender:
      - ?gender=Female or ?gender=Male
      - ?patient_reg_no=... (automatically resolves patient gender)
    """
    gender = request.GET.get('gender', '').strip()
    patient_reg_no = request.GET.get('patient_reg_no', '').strip()

    if not gender and patient_reg_no:
        from final_allocation import resolve_desired_gender
        ps = PatientSnapshot.objects.filter(pat_reg_no=patient_reg_no).first()
        if ps and ps.pat_sex:
            gender = resolve_desired_gender(ps.pat_sex, ps.pat_age)
        else:
            try:
                from MySql_Data_pull.models import Registration
                d = ''.join(ch for ch in str(patient_reg_no) if ch.isdigit())
                if d:
                    h_r = Registration.objects.using('therapy_db').filter(pat_reg_no=int(d)).values('pat_sex', 'pat_age').first()
                    if h_r:
                        gender = resolve_desired_gender(h_r.get('pat_sex'), h_r.get('pat_age'))
            except Exception:
                pass

    therapists = get_therapists_with_schedule_info(gender=gender)
    return JsonResponse({
        'status': 'success',
        'gender_filter': gender or 'ALL',
        'therapists': therapists,
        'total': len(therapists),
    })


@login_required
@role_required(['scheduling_staff', 'admin', 'super_admin', 'doctor'])
@require_http_methods(["POST"])
def save_patient_preferred_roster_api(request):
    """
    API to save or update up to 7 preferred therapists, designating:
      - 1 Primary Bathing Therapist
      - 1 Secondary Bathing Therapist
    Validates:
      - Patient must be marked as allowed by doctor
      - Therapists list: 1 to 7 therapists
      - Primary and Secondary bathing therapists must be in the selected list
      - Primary != Secondary
    """
    try:
        data = json.loads(request.body.decode('utf-8'))
    except Exception:
        return JsonResponse({'status': 'error', 'message': 'Invalid JSON data'}, status=400)

    patient_reg_no = data.get('patient_reg_no')
    therapist_codes = data.get('therapist_codes', [])
    unpreferred_codes = data.get('unpreferred_codes', data.get('unpreferred_therapist_codes', []))
    primary_bathing_code = data.get('primary_bathing_code')
    secondary_bathing_code = data.get('secondary_bathing_code')
    notes = data.get('notes', '')

    if not patient_reg_no:
        return JsonResponse({'status': 'error', 'message': 'Patient registration number is required.'}, status=400)

    try:
        roster = save_preferred_therapist_roster(
            patient_reg_no=patient_reg_no,
            therapist_codes=therapist_codes,
            primary_bathing_code=primary_bathing_code,
            secondary_bathing_code=secondary_bathing_code,
            configured_by=request.user,
            notes=notes,
            unpreferred_codes=unpreferred_codes
        )
    except ValidationError as ve:
        return JsonResponse({'status': 'error', 'message': str(ve.message if hasattr(ve, 'message') else ve)}, status=400)
    except Exception as e:
        return JsonResponse({'status': 'error', 'message': f'Error saving therapist preferences: {str(e)}'}, status=500)

    return JsonResponse({
        'status': 'success',
        'message': f'Therapist preferences saved successfully for patient {patient_reg_no} ({len(roster.therapist_codes)} preferred, {len(roster.unpreferred_therapist_codes)} excluded).',
        'roster_id': roster.id,
        'patient_reg_no': roster.patient_reg_no,
        'therapist_count': len(roster.therapist_codes),
        'unpreferred_count': len(roster.unpreferred_therapist_codes),
        'primary_bathing_code': roster.primary_bathing_code,
        'secondary_bathing_code': roster.secondary_bathing_code,
    })
