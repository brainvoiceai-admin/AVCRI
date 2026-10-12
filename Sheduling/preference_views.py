import json
from django.http import JsonResponse
from django.shortcuts import render, get_object_or_404
from django.views.decorators.http import require_http_methods
from django.contrib.auth.decorators import login_required
from django.utils import timezone
from django.db import transaction

from authentication.decorators import role_required
from masters.models import TherapistMaster
from MySql_Data_pull.models import Visit, Registration
from .models import TherapistPreferenceRequest, TherapistPreferenceAuditLog
from final_allocation import is_patient_active


def get_patient_treating_doctor(patient_id):
    """
    Look up treating doctor code and name for a patient from Registration / Treatment.
    """
    if not patient_id:
        return None, None
    patient_id_str = str(patient_id).strip()

    try:
        from MySql_Data_pull.models import Registration, doctor_master
        reg = Registration.objects.using('therapy_db').filter(pat_reg_no=patient_id_str).first()
        if reg and reg.doctcode:
            doc_code_str = str(reg.doctcode).strip()
            if '.' in doc_code_str:
                doc_code_str = doc_code_str.split('.')[0]
            
            doc = doctor_master.objects.using('therapy_db').filter(Doct_Code=doc_code_str).first()
            if not doc and doc_code_str.isdigit():
                doc = doctor_master.objects.using('therapy_db').filter(Doct_Code=doc_code_str.zfill(4)).first()
            
            if doc and doc.Doct_Name:
                name = doc.Doct_Name.strip()
                if not name.lower().startswith('dr'):
                    name = f"Dr. {name}"
                return doc_code_str, name
    except Exception as e:
        print(f"Error resolving treating doctor: {e}")

    try:
        from MySql_Data_pull.models import Treatment, doctor_master
        treat = Treatment.objects.using('therapy_db').filter(Pat_Reg_No=patient_id_str).exclude(Treat_Doc_Code__isnull=True).first()
        if treat and treat.Treat_Doc_Code:
            doc_code_str = str(treat.Treat_Doc_Code).strip()
            if '.' in doc_code_str:
                doc_code_str = doc_code_str.split('.')[0]
            doc = doctor_master.objects.using('therapy_db').filter(Doct_Code=doc_code_str).first()
            if doc and doc.Doct_Name:
                name = doc.Doct_Name.strip()
                if not name.lower().startswith('dr'):
                    name = f"Dr. {name}"
                return doc_code_str, name
    except Exception:
        pass

    return None, None


from zoneinfo import ZoneInfo


def format_local_dt(dt):
    """
    Format a datetime in the local timezone (Asia/Kolkata / IST).
    """
    if not dt:
        return '—'
    try:
        ist = ZoneInfo('Asia/Kolkata')
        if timezone.is_naive(dt):
            dt = timezone.make_aware(dt, timezone.utc)
        local_dt = dt.astimezone(ist)
        return local_dt.strftime('%d/%m/%Y %H:%M')
    except Exception:
        return dt.strftime('%d/%m/%Y %H:%M')


def is_user_treating_doctor(user, pref_req_or_patient_id):
    """
    Check if the given user is the assigned Treating Doctor for the patient.
    Requires exact doctor code or doctor name token match.
    """
    if not user or not user.is_authenticated:
        return False

    patient_id = getattr(pref_req_or_patient_id, 'patient_id', pref_req_or_patient_id)
    doc_code = getattr(pref_req_or_patient_id, 'treating_doctor_code', None)
    doc_name = getattr(pref_req_or_patient_id, 'treating_doctor_name', None)

    if not doc_code or not doc_name:
        resolved_code, resolved_name = get_patient_treating_doctor(patient_id)
        doc_code = doc_code or resolved_code
        doc_name = doc_name or resolved_name

    user_full = (user.get_full_name() or user.username or '').strip().lower()
    user_emp = str(getattr(user, 'employee_code', '') or getattr(user, 'doctor_id', '') or getattr(user, 'username', '') or '').strip().lower()

    # Match by doctor code
    if doc_code and user_emp:
        dc_str = str(doc_code).strip().lower()
        if dc_str == user_emp:
            return True
        try:
            from .hospital_doctor_lookup import doctor_code_string_variants
            if dc_str in [v.lower() for v in doctor_code_string_variants(user_emp)]:
                return True
        except Exception:
            pass

    # Match by doctor name tokens
    if doc_name:
        import re
        d_tokens = set(re.findall(r'\b[a-z0-9]+\b', doc_name.lower())) - {'dr', 'doctor'}
        u_tokens = set(re.findall(r'\b[a-z0-9]+\b', user_full.lower())) - {'dr', 'doctor'}
        username_tokens = set(re.findall(r'\b[a-z0-9]+\b', user.username.lower())) - {'dr', 'doctor'}
        u_tokens.update(username_tokens)

        # Significant tokens (> 1 char)
        d_sig = {t for t in d_tokens if len(t) > 1} or d_tokens
        u_sig = {t for t in u_tokens if len(t) > 1} or u_tokens

        if d_sig and u_sig and d_sig.intersection(u_sig):
            return True

    return False


def get_active_patient_therapist_preferences(patient_id):
    """
    Helper function for scheduling algorithm & backend validation.
    Returns (preferred_codes_set, unpreferred_codes_set) for an active approved patient preference.
    If patient is discharged or inactive, deactivates active preferences and returns (set(), set()).
    """
    if not patient_id:
        return set(), set()

    patient_id_str = str(patient_id).strip()

    # Check discharge status
    if not is_patient_active(patient_id_str):
        # Auto-deactivate active preferences on discharge
        active_prefs = TherapistPreferenceRequest.objects.filter(
            patient_id=patient_id_str,
            is_active=True
        )
        for pref in active_prefs:
            pref.is_active = False
            pref.status = 'DEACTIVATED'
            pref.deactivated_at = timezone.now()
            pref.deactivated_reason = 'Patient Discharged'
            pref.save()

            TherapistPreferenceAuditLog.objects.create(
                preference_request=pref,
                patient_id=patient_id_str,
                action='DEACTIVATED_DISCHARGE',
                action_date=timezone.now(),
                notes='Automatically deactivated preference due to patient discharge'
            )
        return set(), set()

    active_pref = TherapistPreferenceRequest.objects.filter(
        patient_id=patient_id_str,
        status='APPROVED',
        is_active=True
    ).order_by('-action_date', '-id').first()

    if not active_pref:
        return set(), set()

    preferred_codes = set(active_pref.preferred_therapist_codes or [])
    unpreferred_codes = set(active_pref.unpreferred_therapist_codes or [])

    # If ManyToMany exists, complement from DB relations
    if active_pref.preferred_therapists.exists():
        preferred_codes.update(active_pref.preferred_therapists.values_list('therapist_code', flat=True))
    if active_pref.unpreferred_therapists.exists():
        unpreferred_codes.update(active_pref.unpreferred_therapists.values_list('therapist_code', flat=True))

    return preferred_codes, unpreferred_codes


@login_required
@require_http_methods(["POST"])
def create_therapist_preference_api(request):
    """
    API to submit a Preferred / Unpreferred Therapist preference request.
    Creates a new request with status='PENDING' requiring Treating Doctor approval.
    """
    try:
        data = json.loads(request.body.decode('utf-8'))
    except Exception:
        return JsonResponse({'status': 'error', 'message': 'Invalid JSON data'}, status=400)

    patient_id = data.get('patient_id')
    patient_name = data.get('patient_name', '')
    visit_id = data.get('visit_id')
    preferred_codes = data.get('preferred_therapist_codes', [])
    unpreferred_codes = data.get('unpreferred_therapist_codes', [])
    request_notes = data.get('notes', '')

    if not patient_id:
        return JsonResponse({'status': 'error', 'message': 'Patient ID is required.'}, status=400)

    patient_id_str = str(patient_id).strip()

    # Verify patient active status
    if not is_patient_active(patient_id_str):
        return JsonResponse({'status': 'error', 'message': 'Cannot create therapist preferences for a discharged patient.'}, status=400)

    # Check overlapping therapists
    preferred_set = set(preferred_codes)
    unpreferred_set = set(unpreferred_codes)
    overlap = preferred_set.intersection(unpreferred_set)
    if overlap:
        return JsonResponse({
            'status': 'error',
            'message': f'Therapist(s) {", ".join(overlap)} cannot be marked as both Preferred and Unpreferred.'
        }, status=400)

    # Resolve therapist objects and names
    preferred_objs = list(TherapistMaster.objects.filter(therapist_code__in=preferred_codes, is_active=True))
    unpreferred_objs = list(TherapistMaster.objects.filter(therapist_code__in=unpreferred_codes, is_active=True))

    preferred_names = [t.therapist_name for t in preferred_objs]
    unpreferred_names = [t.therapist_name for t in preferred_objs if False] # reset comprehension for unpreferred
    unpreferred_names = [t.therapist_name for t in unpreferred_objs]

    # Resolve Visit if provided
    visit_obj = None
    if visit_id:
        try:
            visit_obj = Visit.objects.filter(id=visit_id).first()
        except Exception:
            pass

    # Lookup patient name if missing
    if not patient_name:
        try:
            reg = Registration.objects.using('therapy_db').filter(pat_reg_no=patient_id_str).first()
            if reg and getattr(reg, 'pat_name', None):
                patient_name = reg.pat_name
        except Exception:
            pass

    # Resolve treating doctor
    doc_code, doc_name = get_patient_treating_doctor(patient_id_str)

    with transaction.atomic():
        # Deactivate any previous PENDING requests for this patient (replace with latest submission)
        TherapistPreferenceRequest.objects.filter(
            patient_id=patient_id_str,
            status='PENDING'
        ).update(status='DEACTIVATED', is_active=False, deactivated_at=timezone.now(), deactivated_reason='Replaced by new request')

        user_full_name = request.user.get_full_name() or request.user.username
        user_role = getattr(request.user, 'role', 'User')

        pref_req = TherapistPreferenceRequest.objects.create(
            patient_id=patient_id_str,
            patient_name=patient_name or f"Patient {patient_id_str}",
            treating_doctor_code=doc_code,
            treating_doctor_name=doc_name,
            visit=visit_obj,
            preferred_therapist_codes=list(preferred_set),
            preferred_therapist_names=preferred_names,
            unpreferred_therapist_codes=list(unpreferred_set),
            unpreferred_therapist_names=unpreferred_names,
            status='PENDING',
            is_active=False,
            requested_by=request.user,
            requested_by_name=user_full_name,
            requested_by_role=user_role,
            request_date=timezone.now(),
            request_notes=request_notes
        )

        if preferred_objs:
            pref_req.preferred_therapists.set(preferred_objs)
        if unpreferred_objs:
            pref_req.unpreferred_therapists.set(unpreferred_objs)

        # Record audit log
        TherapistPreferenceAuditLog.objects.create(
            preference_request=pref_req,
            patient_id=patient_id_str,
            action='CREATED',
            action_by=request.user,
            action_by_name=user_full_name,
            action_date=timezone.now(),
            details={
                'preferred': list(preferred_set),
                'unpreferred': list(unpreferred_set)
            },
            notes=request_notes
        )

    return JsonResponse({
        'status': 'success',
        'message': 'Therapist preference request submitted successfully. Sent to Treating Doctor for approval.',
        'request_id': pref_req.id,
        'pref_status': 'PENDING',
        'status_display': 'Approval Pending'
    })


@login_required
@require_http_methods(["GET"])
def get_patient_therapist_preference_api(request, patient_id):
    """
    Get current therapist preference status for a patient.
    """
    patient_id_str = str(patient_id).strip()

    # Check discharge status
    if not is_patient_active(patient_id_str):
        # Auto-deactivate active preferences
        TherapistPreferenceRequest.objects.filter(
            patient_id=patient_id_str,
            is_active=True
        ).update(is_active=False, status='DEACTIVATED', deactivated_at=timezone.now(), deactivated_reason='Patient Discharged')

    pref_req = TherapistPreferenceRequest.objects.filter(patient_id=patient_id_str).exclude(status='DEACTIVATED').order_by('-created_at').first()

    if not pref_req:
        return JsonResponse({
            'has_preference': False,
            'status': 'NONE',
            'status_display': 'Not Requested',
            'can_edit': True,
            'preferred_therapists': [],
            'unpreferred_therapists': []
        })

    preferred_list = []
    for code, name in zip(pref_req.preferred_therapist_codes or [], pref_req.preferred_therapist_names or []):
        preferred_list.append({'code': code, 'name': name})
    # Fallback to ManyToMany if JSON was empty
    if not preferred_list and pref_req.preferred_therapists.exists():
        for t in pref_req.preferred_therapists.all():
            preferred_list.append({'code': t.therapist_code, 'name': t.therapist_name})

    unpreferred_list = []
    for code, name in zip(pref_req.unpreferred_therapist_codes or [], pref_req.unpreferred_therapist_names or []):
        unpreferred_list.append({'code': code, 'name': name})
    if not unpreferred_list and pref_req.unpreferred_therapists.exists():
        for t in pref_req.unpreferred_therapists.all():
            unpreferred_list.append({'code': t.therapist_code, 'name': t.therapist_name})

    can_edit = (pref_req.status not in ['PENDING', 'APPROVED'])

    treating_doc_name = pref_req.treating_doctor_name
    if not treating_doc_name:
        _, treating_doc_name = get_patient_treating_doctor(patient_id_str)

    return JsonResponse({
        'has_preference': True,
        'request_id': pref_req.id,
        'status': pref_req.status,
        'status_display': pref_req.get_status_display(),
        'is_active': pref_req.is_active,
        'can_edit': can_edit,
        'preferred_therapists': preferred_list,
        'unpreferred_therapists': unpreferred_list,
        'treating_doctor_name': treating_doc_name or '',
        'requested_by': pref_req.requested_by_name or '—',
        'request_date': format_local_dt(pref_req.request_date),
        'approved_by': pref_req.approved_by_name or '—',
        'action_date': format_local_dt(pref_req.action_date),
        'rejection_reason': pref_req.rejection_reason or ''
    })


@login_required
@role_required(['doctor', 'admin', 'super_admin', 'scheduling_staff'])
def therapist_preference_approvals_view(request):
    """
    Doctor Dashboard section / page for reviewing Therapist Preference Requests.
    """
    pending_count = TherapistPreferenceRequest.objects.filter(status='PENDING').count()
    approved_count = TherapistPreferenceRequest.objects.filter(status='APPROVED', is_active=True).count()
    rejected_count = TherapistPreferenceRequest.objects.filter(status='REJECTED').count()

    context = {
        'dashboard_title': 'Therapist Preference Approvals',
        'pending_count': pending_count,
        'approved_count': approved_count,
        'rejected_count': rejected_count,
        'is_doctor': request.user.role in ['doctor', 'admin', 'super_admin']
    }
    return render(request, 'dashboards/scheduling/therapist_preference_approvals.html', context)


@login_required
@require_http_methods(["GET"])
def get_pending_preference_requests_api(request):
    """
    API returning pending, approved, and rejected therapist preference requests for Doctor review.
    Includes can_approve flag based on whether the logged-in user is the Treating Doctor (or super_admin).
    """
    status_filter = request.GET.get('status', 'PENDING').upper()
    qs = TherapistPreferenceRequest.objects.all()

    if status_filter != 'ALL':
        qs = qs.filter(status=status_filter)

    requests_data = []
    for r in qs.order_by('-request_date')[:100]:
        pref_list = []
        for code, name in zip(r.preferred_therapist_codes or [], r.preferred_therapist_names or []):
            if name and name != code:
                pref_list.append(f"{name} ({code})")
            else:
                pref_list.append(code)
        pref_names = ", ".join(pref_list) if pref_list else (", ".join(r.preferred_therapist_codes) if r.preferred_therapist_codes else "None")

        unpref_list = []
        for code, name in zip(r.unpreferred_therapist_codes or [], r.unpreferred_therapist_names or []):
            if name and name != code:
                unpref_list.append(f"{name} ({code})")
            else:
                unpref_list.append(code)
        unpref_names = ", ".join(unpref_list) if unpref_list else (", ".join(r.unpreferred_therapist_codes) if r.unpreferred_therapist_codes else "None")

        doc_name = r.treating_doctor_name
        if not doc_name and r.patient_id:
            _, doc_name = get_patient_treating_doctor(r.patient_id)

        can_approve = is_user_treating_doctor(request.user, r)

        requests_data.append({
            'id': r.id,
            'patient_id': r.patient_id,
            'patient_name': r.patient_name or f"Patient {r.patient_id}",
            'treating_doctor_name': doc_name or '—',
            'can_approve': can_approve,
            'treatment_name': r.treatment_name or "All Treatments",
            'preferred_therapists_display': pref_names,
            'unpreferred_therapists_display': unpref_names,
            'preferred_codes': r.preferred_therapist_codes,
            'unpreferred_codes': r.unpreferred_therapist_codes,
            'requested_by': r.requested_by_name or 'System User',
            'requested_by_role': r.requested_by_role or '',
            'request_date': format_local_dt(r.request_date),
            'status': r.status,
            'status_display': r.get_status_display(),
            'is_active': r.is_active,
            'approved_by': r.approved_by_name or '—',
            'action_date': format_local_dt(r.action_date),
            'rejection_reason': r.rejection_reason or '',
            'notes': r.request_notes or ''
        })

    return JsonResponse({'status': 'success', 'requests': requests_data})


@login_required
@role_required(['doctor', 'admin', 'super_admin'])
@require_http_methods(["POST"])
def doctor_approve_therapist_preference_api(request, request_id):
    """
    Doctor Approval Action: Approve a requested therapist preference.
    Strict Check: Only the patient's assigned Treating Doctor (or super_admin) can approve.
    """
    pref_req = get_object_or_404(TherapistPreferenceRequest, id=request_id)

    if not is_patient_active(pref_req.patient_id):
        return JsonResponse({'status': 'error', 'message': 'Cannot approve preferences for a discharged patient.'}, status=400)

    # Enforce Treating Doctor approval authorization
    if not is_user_treating_doctor(request.user, pref_req):
        doc_display = pref_req.treating_doctor_name or 'assigned doctor'
        return JsonResponse({
            'status': 'error',
            'message': f'Only the patient\'s designated Treating Doctor ({doc_display}) can approve or reject this preference request.'
        }, status=403)

    try:
        data = json.loads(request.body.decode('utf-8')) if request.body else {}
    except Exception:
        data = {}

    approval_notes = data.get('notes', '')

    with transaction.atomic():
        # Deactivate all existing active preferences for this patient
        TherapistPreferenceRequest.objects.filter(
            patient_id=pref_req.patient_id,
            is_active=True
        ).exclude(id=pref_req.id).update(
            is_active=False,
            status='DEACTIVATED',
            deactivated_at=timezone.now(),
            deactivated_reason='Replaced by new doctor approved preference'
        )

        doctor_full_name = request.user.get_full_name() or request.user.username
        pref_req.status = 'APPROVED'
        pref_req.is_active = True
        pref_req.approved_by = request.user
        pref_req.approved_by_name = doctor_full_name
        pref_req.action_date = timezone.now()
        pref_req.save()

        # Audit log entry
        TherapistPreferenceAuditLog.objects.create(
            preference_request=pref_req,
            patient_id=pref_req.patient_id,
            action='APPROVED',
            action_by=request.user,
            action_by_name=doctor_full_name,
            action_date=timezone.now(),
            details={
                'approved_preferred': pref_req.preferred_therapist_codes,
                'approved_unpreferred': pref_req.unpreferred_therapist_codes
            },
            notes=approval_notes
        )

    # Immediately re-allocate future bookings for this patient to apply the approved preference
    try:
        reallocate_patient_future_bookings(pref_req.patient_id)
    except Exception as e:
        print(f"Error reallocating bookings after preference approval: {e}")

    return JsonResponse({
        'status': 'success',
        'message': f'Therapist preference for patient {pref_req.patient_name} approved successfully by {doctor_full_name}. Future bookings updated.',
        'pref_status': 'APPROVED',
        'is_active': True
    })


def reallocate_patient_future_bookings(patient_id):
    """
    Re-evaluate and update therapist allocations for all upcoming bookings of a patient
    when a new doctor-approved therapist preference becomes active.
    """
    if not patient_id:
        return
    try:
        from datetime import date
        from Sheduling.models import Booking, BookingAssignment, TherapyAllocation
        from final_allocation import allocate_therapists, therapist_requirements, create_therapist_booking_safe
        from Patient.models import TherapistBooking, Therapist

        patient_id_str = str(patient_id).strip()
        today = date.today()

        # Query all upcoming non-cancelled bookings for this patient
        from Sheduling.models import FinalScheduleRun
        upcoming_bookings = Booking.objects.filter(
            allocation__patient__pat_reg_no=patient_id_str,
            date__gte=today
        ).exclude(status='cancelled').select_related('allocation', 'timeslot', 'allocation__patient').order_by('date', 'timeslot_id')

        affected_allocations = set()

        for booking in upcoming_bookings:
            alloc = booking.allocation
            if not alloc or not booking.timeslot:
                continue

            affected_allocations.add(alloc)

            # Check if Final Schedule was actually run for this booking's date
            has_final_schedule = FinalScheduleRun.objects.filter(run_date=booking.date).exists()

            if not has_final_schedule:
                # Final Schedule has NOT been run for this date -> MUST remain/be set to 'draft'
                TherapistBooking.objects.filter(
                    visit_id=alloc.id,
                    date=booking.date,
                    time_slot=booking.timeslot
                ).delete()
                try:
                    BookingAssignment.objects.filter(booking=booking).delete()
                except Exception:
                    pass
                booking.status = 'draft'
                booking.save(update_fields=['status', 'updated_at'])
                continue

            # FinalScheduleRun EXISTS for this date -> re-evaluate scheduled therapists excluding unpreferred ones
            pat_sex = getattr(getattr(alloc, 'patient', None), 'pat_sex', None)
            req = therapist_requirements(alloc)
            req_total = int(req.get("total", 1) or 1)

            if req_total == 0:
                continue

            allocated_therapists = allocate_therapists(
                booking.date,
                booking.timeslot,
                req,
                patient_gender=pat_sex,
                patient_id=patient_id_str
            )

            if allocated_therapists and len(allocated_therapists) >= req_total:
                TherapistBooking.objects.filter(
                    visit_id=alloc.id,
                    date=booking.date,
                    time_slot=booking.timeslot
                ).delete()

                try:
                    BookingAssignment.objects.filter(booking=booking).delete()
                except Exception:
                    pass

                ba_count = 0
                for t in allocated_therapists:
                    create_therapist_booking_safe(
                        therapist=t,
                        date=booking.date,
                        time_slot=booking.timeslot,
                        visit=alloc,
                        therapy_name=alloc.therapy_name,
                        patient_id=patient_id_str
                    )
                    try:
                        therapist_obj, _ = Therapist.objects.get_or_create(
                            therapist_code=t.therapist_code,
                            defaults={
                                'therapist_name': getattr(t, 'therapist_name', t.therapist_code),
                                'therapist_grade': getattr(getattr(t, 'therapist_grade', None), 'name', '') or '',
                                'is_bathing_therapist': getattr(t, 'is_bathing_therapist', False)
                            }
                        )
                        BookingAssignment.objects.create(
                            booking=booking,
                            therapist=therapist_obj,
                            booking_date=booking.date,
                            booking_timeslot=booking.timeslot,
                            role=getattr(getattr(t, 'therapist_grade', None), 'name', '') or '',
                            assigned_for='booking',
                            status='assigned'
                        )
                        ba_count += 1
                    except Exception as ba_err:
                        print(f"[REALLOCATE PREF] Error creating BookingAssignment for therapist {getattr(t, 'therapist_code', 'unknown')}: {ba_err}")

                if ba_count >= req_total:
                    booking.status = 'scheduled'
                    booking.save(update_fields=['status', 'updated_at'])
                else:
                    booking.status = 'failed'
                    booking.failure_reason = 'insufficient_therapists_assigned'
                    booking.save(update_fields=['status', 'failure_reason', 'updated_at'])
            else:
                TherapistBooking.objects.filter(
                    visit_id=alloc.id,
                    date=booking.date,
                    time_slot=booking.timeslot
                ).delete()
                try:
                    BookingAssignment.objects.filter(booking=booking).delete()
                except Exception:
                    pass
                booking.status = 'failed'
                booking.failure_reason = 'Excluded/unpreferred therapist restriction - no eligible therapist available'
                booking.save(update_fields=['status', 'failure_reason', 'updated_at'])

        # Update parent allocation status based on booking status summary
        for alloc in affected_allocations:
            b_statuses = set(Booking.objects.filter(allocation=alloc).exclude(status='cancelled').values_list('status', flat=True))
            if 'scheduled' in b_statuses:
                if alloc.status != 'allocated':
                    alloc.status = 'allocated'
                    alloc.save(update_fields=['status'])
            elif 'draft' in b_statuses or not b_statuses:
                if alloc.status != 'draft':
                    alloc.status = 'draft'
                    alloc.save(update_fields=['status'])
            elif b_statuses and b_statuses.issubset({'failed'}):
                if alloc.status != 'failed':
                    alloc.status = 'failed'
                    alloc.save(update_fields=['status'])
    except Exception as e:
        print(f"[REALLOCATE PREF] Error reallocating future bookings for patient {patient_id}: {e}")


@login_required
@role_required(['doctor', 'admin', 'super_admin'])
@require_http_methods(["POST"])
def doctor_reject_therapist_preference_api(request, request_id):
    """
    Doctor Rejection Action: Reject a requested therapist preference.
    """
    pref_req = get_object_or_404(TherapistPreferenceRequest, id=request_id)

    # Enforce Treating Doctor rejection authorization
    if not is_user_treating_doctor(request.user, pref_req):
        doc_display = pref_req.treating_doctor_name or 'assigned doctor'
        return JsonResponse({
            'status': 'error',
            'message': f'Only the patient\'s designated Treating Doctor ({doc_display}) can approve or reject this preference request.'
        }, status=403)

    try:
        data = json.loads(request.body.decode('utf-8')) if request.body else {}
    except Exception:
        data = {}

    rejection_reason = data.get('rejection_reason') or data.get('notes') or 'Rejected by Doctor'

    doctor_full_name = request.user.get_full_name() or request.user.username

    with transaction.atomic():
        pref_req.status = 'REJECTED'
        pref_req.is_active = False
        pref_req.approved_by = request.user
        pref_req.approved_by_name = doctor_full_name
        pref_req.action_date = timezone.now()
        pref_req.rejection_reason = rejection_reason
        pref_req.save()

        # Audit log entry
        TherapistPreferenceAuditLog.objects.create(
            preference_request=pref_req,
            patient_id=pref_req.patient_id,
            action='REJECTED',
            action_by=request.user,
            action_by_name=doctor_full_name,
            action_date=timezone.now(),
            details={
                'preferred': pref_req.preferred_therapist_codes,
                'unpreferred': pref_req.unpreferred_therapist_codes
            },
            notes=rejection_reason
        )

    return JsonResponse({
        'status': 'success',
        'message': f'Therapist preference request for patient {pref_req.patient_name} has been rejected.',
        'pref_status': 'REJECTED',
        'is_active': False
    })


@login_required
@require_http_methods(["GET"])
def therapist_preference_history_api(request, patient_id):
    """
    API returning audit history of therapist preferences for a patient.
    """
    patient_id_str = str(patient_id).strip()
    logs = TherapistPreferenceAuditLog.objects.filter(patient_id=patient_id_str).order_by('-action_date')

    history = []
    for log in logs:
        history.append({
            'action': log.action,
            'action_by': log.action_by_name or 'System',
            'action_date': log.action_date.strftime('%d/%m/%Y %H:%M') if log.action_date else '—',
            'details': log.details,
            'notes': log.notes or ''
        })

    return JsonResponse({'status': 'success', 'history': history})


def validate_therapist_assignment_backend(patient_id, therapist_code_or_obj):
    """
    Backend validator to ensure an unpreferred therapist is NOT assigned to a patient.
    Raises ValueError if therapist is marked unpreferred for this patient.
    """
    if not patient_id or not therapist_code_or_obj:
        return True
    patient_id_str = str(patient_id).strip()
    preferred_codes, unpreferred_codes = get_active_patient_therapist_preferences(patient_id_str)
    
    code = getattr(therapist_code_or_obj, 'therapist_code', str(therapist_code_or_obj)).strip()
    if code in unpreferred_codes:
        raise ValueError(f"Therapist '{code}' is marked as Unpreferred for patient {patient_id_str} and cannot be assigned.")
    return True

