# therapies/views.py
import json
from datetime import timedelta, datetime
from django.shortcuts import render
from django.http import JsonResponse, HttpResponseBadRequest
from django.apps import apps
from django.db.models import Q
from django.views.decorators.csrf import csrf_exempt
from django.utils.dateparse import parse_date
from django.utils import timezone
from django.db import transaction, IntegrityError
from authentication.models import AuditLog as AuthAuditLog
from .decorators import scheduling_access_required, scheduling_admin_required, therapist_access_required, api_access_required

EXTERNAL_DB_ALIAS = 'therapy_db'  # external SQL Server alias

def log_therapy_audit(user, action, therapy_allocation=None, description="", additional_data=None, request=None):
    """Log therapy-related audit events"""
    try:
        ip_address = None
        user_agent = ''
        
        if request:
            ip_address = getattr(request, 'META', {}).get('REMOTE_ADDR')
            user_agent = request.META.get('HTTP_USER_AGENT', '')
        
        # Prepare audit data
        audit_data = {
            'action': action,
            'user_id': user.id if user else None,
            'username': user.username if user else 'Anonymous',
            'timestamp': timezone.now().isoformat(),
        }
        
        if therapy_allocation:
            audit_data.update({
                'therapy_id': therapy_allocation.id,
                'therapy_name': therapy_allocation.therapy_name,
                'patient_reg_no': therapy_allocation.patient.pat_reg_no,
                'patient_name': therapy_allocation.patient.pat_name,
                'from_date': therapy_allocation.from_date.isoformat(),
                'to_date': therapy_allocation.to_date.isoformat(),
                'status': therapy_allocation.status,
            })
        
        if additional_data:
            audit_data.update(additional_data)
        
        # Create audit log entry
        AuthAuditLog.objects.create(
            user=user,
            action=action,
            description=description or f"Therapy {action} by {user.username if user else 'Anonymous'}",
            ip_address=ip_address,
            user_agent=user_agent,
            status='success',
            object_type='TherapyAllocation',
            object_id=str(therapy_allocation.id) if therapy_allocation else '',
            additional_data=audit_data
        )
        
        # Also create Sheduling audit log for backward compatibility
        if therapy_allocation:
            AuditLog.objects.create(
                user=user,
                action=action,
                obj_type='TherapyAllocation',
                obj_id=str(therapy_allocation.id),
                data=audit_data
            )
            
            # Create therapy notification
            create_therapy_notification(therapy_allocation, action, user, additional_data)
            
    except Exception as e:
        # Don't let audit logging break the main functionality
        print(f"Therapy audit logging error: {e}")

def get_client_ip(request):
    """Get client IP address from request"""
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        ip = x_forwarded_for.split(',')[0]
    else:
        ip = request.META.get('REMOTE_ADDR')
    return ip

def create_therapy_notification(therapy_allocation, action, user, additional_data=None):
    """Create therapy notification for relevant staff"""
    try:
        from .models import TherapyNotification
        
        # Map actions to notification types
        notification_mapping = {
            'allocate_therapy': ('therapy_allocated', 'New Therapy Allocated', 'high'),
            'cancel_therapy': ('therapy_cancelled', 'Therapy Cancelled', 'urgent'),
            'resume_therapy': ('therapy_resumed', 'Therapy Resumed', 'medium'),
            'update_therapy': ('therapy_updated', 'Therapy Updated', 'medium'),
            'remove_item': ('item_removed', 'Item Removed from Therapy', 'low'),
        }
        
        if action not in notification_mapping:
            return
        
        notification_type, title_prefix, priority = notification_mapping[action]
        
        # Create notification title and message
        patient_name = therapy_allocation.patient.pat_name or 'Unknown Patient'
        therapy_name = therapy_allocation.therapy_name
        
        title = f"{title_prefix}: {therapy_name}"
        message = f"Patient: {patient_name} ({therapy_allocation.patient.pat_reg_no})\n"
        message += f"Therapy: {therapy_name}\n"
        message += f"Period: {therapy_allocation.from_date} to {therapy_allocation.to_date}\n"
        
        if action == 'cancel_therapy' and additional_data:
            message += f"Cancelled: {additional_data.get('cancel_from')} to {additional_data.get('cancel_to')}\n"
            message += f"Reason: {additional_data.get('reason', 'No reason provided')}\n"
        elif action == 'resume_therapy' and additional_data:
            message += f"Resumed: {additional_data.get('resume_from')} to {additional_data.get('resume_to')}\n"
        elif action == 'allocate_therapy' and additional_data:
            message += f"Bookings Created: {additional_data.get('bookings_created', 0)}\n"
        
        # Create notification
        notification = TherapyNotification.objects.create(
            therapy_allocation=therapy_allocation,
            notification_type=notification_type,
            title=title,
            message=message,
            priority=priority,
            created_by=user,
            additional_data=additional_data or {}
        )
        
        # Determine target roles based on action
        if action == 'allocate_therapy':
            # Notify therapists, nurses, and admin
            target_roles = ['therapist', 'nurse', 'admin', 'super_admin']
        elif action == 'cancel_therapy':
            # Notify admin, doctors, and therapists
            target_roles = ['admin', 'super_admin', 'doctor', 'doctor_admin', 'therapist']
        elif action == 'resume_therapy':
            # Notify therapists and admin
            target_roles = ['therapist', 'admin', 'super_admin']
        elif action == 'update_therapy':
            # Notify therapists and admin
            target_roles = ['therapist', 'admin', 'super_admin']
        elif action == 'remove_item':
            # Notify admin and therapists
            target_roles = ['admin', 'super_admin', 'therapist']
        else:
            target_roles = ['admin', 'super_admin']
        
        # Send notification to target roles
        notification.send_to_roles(target_roles)
        
    except Exception as e:
        print(f"Notification creation error: {e}")

def get_model_safe(app_label, model_name):
    try:
        return apps.get_model(app_label, model_name)
    except Exception:
        return None

# External DB models (use .using(EXTERNAL_DB_ALIAS) when querying)
Registration = get_model_safe('MySql_Data_pull', 'Registration')

# Local models for lookup (existing)
TreatmentRoom = get_model_safe('Patient', 'TreatmentRoom')
# Legacy TimeSlot - will be replaced by SlotMaster
TimeSlot = get_model_safe('Patient', 'TimeSlot')

# Local Master Tables (NEW - use these instead of external DB)
ItemMaster = get_model_safe('masters', 'ItemMaster')
TherapyMaster = get_model_safe('masters', 'TherapyMaster')
SlotMaster = get_model_safe('masters', 'SlotMaster')
TherapistMaster = get_model_safe('masters', 'TherapistMaster')

# Masters
Procured = get_model_safe('masters', 'Procured')
OilClass = get_model_safe('masters', 'OilClass')
UsageType = get_model_safe('masters', 'UsageType')
PrescriptionTime = get_model_safe('masters', 'PrescriptionTime')
PrescriptionScope = get_model_safe('masters', 'PrescriptionScope')

# New scheduling models (expected to be in 'therapies' app)
TherapyAllocation = get_model_safe('Sheduling', 'TherapyAllocation')
PatientSnapshot = get_model_safe('Sheduling', 'PatientSnapshot')
Booking = get_model_safe('Sheduling', 'Booking')
BookingItem = get_model_safe('Sheduling', 'BookingItem')
BookingAssignment = get_model_safe('Sheduling', 'BookingAssignment')
CancellationRequest = get_model_safe('Sheduling', 'CancellationRequest')
AuditLog = get_model_safe('Sheduling', 'AuditLog')
NotificationQueue = get_model_safe('Sheduling', 'NotificationQueue')
TherapistModel = get_model_safe('Sheduling', 'Therapist') or get_model_safe('Patient', 'Therapist')

# Prescription models
PrescriptionAllocation = get_model_safe('Sheduling', 'PrescriptionAllocation')
PrescriptionNotification = get_model_safe('Sheduling', 'PrescriptionNotification')
PrescriptionChange = get_model_safe('Sheduling', 'PrescriptionChange')

# Optional legacy model reference (if you have patient-specific therapy list model)
PatientTherapy = get_model_safe('your_app_name', 'PatientTherapy')  # fallback, adjust if needed


def _compute_patient_type_from_reg(reg_val):
    """Return 'OP' if reg_val contains exactly 5 digits, else 'IP'."""
    if reg_val is None:
        return 'IP'
    s = str(reg_val)
    digits = ''.join(ch for ch in s if ch.isdigit())
    if len(digits) == 5:
        return 'OP'
    return 'IP'


@csrf_exempt
def therapy_entry(request):
    """
    Single endpoint:
      - GET: render template or handle lookups by ?action=...
      - POST: perform allocate/mark_completed/request_cancellation via ?action=...
    """

    # --- POST actions (allocate, mark_completed, request_cancellation) ---
    if request.method == 'POST':
        action_post = (request.GET.get('action') or '').strip().lower()
        try:
            payload = json.loads(request.body.decode('utf-8') or '{}')
        except Exception:
            return JsonResponse({'error': 'invalid_json'}, status=400)

        # ---------- cancel therapy ----------
        if action_post == 'cancel_therapy':
            allocation_id = payload.get('allocation_id')
            cancel_from = payload.get('cancel_from')
            cancel_to = payload.get('cancel_to')
            reason = payload.get('reason', '')
            
            if not allocation_id or not cancel_from or not cancel_to:
                return JsonResponse({'error': 'missing_fields'}, status=400)
            
            try:
                allocation = TherapyAllocation.objects.get(id=allocation_id)
                allocation.status = 'cancelled'
                allocation.cancelled_by = request.user if request.user.is_authenticated else None
                allocation.cancelled_at = timezone.now()
                allocation.cancellation_reason = reason
                allocation.cancelled_date_from = parse_date(cancel_from)
                allocation.cancelled_date_to = parse_date(cancel_to)
                allocation.save()
                
                # Update related bookings
                cancelled_bookings = Booking.objects.filter(
                    allocation=allocation,
                    date__gte=parse_date(cancel_from),
                    date__lte=parse_date(cancel_to)
                )
                cancelled_count = cancelled_bookings.count()
                cancelled_bookings.update(status='cancelled')
                
                # Log audit event
                log_therapy_audit(
                    user=request.user if request.user.is_authenticated else None,
                    action='cancel_therapy',
                    therapy_allocation=allocation,
                    description=f"Therapy '{allocation.therapy_name}' cancelled for patient {allocation.patient.pat_reg_no} from {cancel_from} to {cancel_to}. Reason: {reason}",
                    additional_data={
                        'cancel_from': cancel_from,
                        'cancel_to': cancel_to,
                        'reason': reason,
                        'cancelled_bookings_count': cancelled_count,
                        'cancelled_by': request.user.username if request.user.is_authenticated else 'Anonymous'
                    },
                    request=request
                )
                
                return JsonResponse({'status': 'ok', 'message': 'Therapy cancelled successfully'})
            except TherapyAllocation.DoesNotExist:
                return JsonResponse({'error': 'allocation_not_found'}, status=404)
            except Exception as e:
                return JsonResponse({'error': str(e)}, status=500)
        
        # ---------- resume therapy ----------
        if action_post == 'resume_therapy':
            allocation_id = payload.get('allocation_id')
            resume_from = payload.get('resume_from')
            resume_to = payload.get('resume_to')
            
            if not allocation_id or not resume_from or not resume_to:
                return JsonResponse({'error': 'missing_fields'}, status=400)
            
            try:
                allocation = TherapyAllocation.objects.get(id=allocation_id)
                allocation.status = 'draft'
                allocation.resumed_by = request.user if request.user.is_authenticated else None
                allocation.resumed_at = timezone.now()
                allocation.cancelled_date_from = None
                allocation.cancelled_date_to = None
                allocation.cancellation_reason = ''
                allocation.save()
                
                # Update related bookings
                resumed_bookings = Booking.objects.filter(
                    allocation=allocation,
                    date__gte=parse_date(resume_from),
                    date__lte=parse_date(resume_to)
                )
                resumed_count = resumed_bookings.count()
                resumed_bookings.update(status='scheduled')
                
                # Log audit event
                log_therapy_audit(
                    user=request.user if request.user.is_authenticated else None,
                    action='resume_therapy',
                    therapy_allocation=allocation,
                    description=f"Therapy '{allocation.therapy_name}' resumed for patient {allocation.patient.pat_reg_no} from {resume_from} to {resume_to}",
                    additional_data={
                        'resume_from': resume_from,
                        'resume_to': resume_to,
                        'resumed_bookings_count': resumed_count,
                        'resumed_by': request.user.username if request.user.is_authenticated else 'Anonymous'
                    },
                    request=request
                )
                
                return JsonResponse({'status': 'ok', 'message': 'Therapy resumed successfully'})
            except TherapyAllocation.DoesNotExist:
                return JsonResponse({'error': 'allocation_not_found'}, status=404)
            except Exception as e:
                return JsonResponse({'error': str(e)}, status=500)
        
        # ---------- update therapy ----------
        if action_post == 'update_therapy':
            allocation_id = payload.get('allocation_id')
            if not allocation_id:
                return JsonResponse({'error': 'missing_allocation_id'}, status=400)
            
            try:
                allocation = TherapyAllocation.objects.get(id=allocation_id)
                
                # Update therapy details
                if 'therapy_name' in payload:
                    allocation.therapy_name = payload['therapy_name']
                if 'items_groups' in payload:
                    allocation.items_groups = payload['items_groups']
                if 'oil_class' in payload:
                    allocation.oil_class = payload['oil_class']
                if 'usage' in payload:
                    allocation.usage = payload['usage']
                if 'procured_from' in payload:
                    allocation.procured_from = payload['procured_from']
                if 'notes' in payload:
                    allocation.notes = payload['notes']
                
                allocation.save()
                
                # Log audit event
                log_therapy_audit(
                    user=request.user if request.user.is_authenticated else None,
                    action='update_therapy',
                    therapy_allocation=allocation,
                    description=f"Therapy '{allocation.therapy_name}' updated for patient {allocation.patient.pat_reg_no}",
                    additional_data={
                        'updated_fields': list(payload.keys()),
                        'updated_by': request.user.username if request.user.is_authenticated else 'Anonymous'
                    },
                    request=request
                )
                
                return JsonResponse({'status': 'ok', 'message': 'Therapy updated successfully'})
            except TherapyAllocation.DoesNotExist:
                return JsonResponse({'error': 'allocation_not_found'}, status=404)
            except Exception as e:
                return JsonResponse({'error': str(e)}, status=500)
        
        # ---------- remove item from therapy ----------
        if action_post == 'remove_item':
            allocation_id = payload.get('allocation_id')
            item_index = payload.get('item_index')
            
            if not allocation_id or item_index is None:
                return JsonResponse({'error': 'missing_fields'}, status=400)
            
            try:
                allocation = TherapyAllocation.objects.get(id=allocation_id)
                items_groups = allocation.items_groups or []
                
                if 0 <= item_index < len(items_groups):
                    removed_item = items_groups.pop(item_index)
                    allocation.items_groups = items_groups
                    allocation.save()
                    
                    # Log audit event
                    log_therapy_audit(
                        user=request.user if request.user.is_authenticated else None,
                        action='remove_item',
                        therapy_allocation=allocation,
                        description=f"Item removed from therapy '{allocation.therapy_name}' for patient {allocation.patient.pat_reg_no}",
                        additional_data={
                            'removed_item': removed_item,
                            'remaining_items_count': len(items_groups),
                            'removed_by': request.user.username if request.user.is_authenticated else 'Anonymous'
                        },
                        request=request
                    )
                    
                    return JsonResponse({'status': 'ok', 'message': 'Item removed successfully'})
                else:
                    return JsonResponse({'error': 'invalid_item_index'}, status=400)
            except TherapyAllocation.DoesNotExist:
                return JsonResponse({'error': 'allocation_not_found'}, status=404)
            except Exception as e:
                return JsonResponse({'error': str(e)}, status=500)
        
        # ---------- allocate ----------
        if action_post == 'allocate':
            # required fields
            required = ['patient_reg_no', 'therapy_code', 'therapy_name', 'from_date', 'to_date', 'items_groups']
            missing = [k for k in required if not payload.get(k)]
            if missing:
                return JsonResponse({'error': 'missing_fields', 'missing': missing}, status=400)

            fdate = parse_date(payload['from_date'])
            tdate = parse_date(payload['to_date'])
            if not fdate or not tdate or fdate > tdate:
                return JsonResponse({'error': 'invalid_dates'}, status=400)

            # resolve timeslot (accept "HH:MM" or slot_number)
            timeslot_obj = None
            ts_val = payload.get('timeslot') or payload.get('slot') or ''
            if ts_val:
                # try HH:MM
                try:
                    parts = ts_val.split(':')
                    if len(parts) == 2:
                        hh = int(parts[0]); mm = int(parts[1])
                        from_time = datetime.strptime(f"{hh:02d}:{mm:02d}", "%H:%M").time()
                        if SlotMaster is not None:
                            timeslot_obj = SlotMaster.objects.filter(start_time=from_time, is_active=True).first()
                    else:
                        # try slot_number int
                        if SlotMaster is not None:
                            timeslot_obj = SlotMaster.objects.filter(slot_number=int(ts_val), is_active=True).first()
                except Exception:
                    timeslot_obj = None

                if timeslot_obj is None and SlotMaster is not None and ts_val:
                    return JsonResponse({'error': 'timeslot_not_found', 'timeslot': ts_val}, status=400)

            # room resolution (optional)
            room_obj = None
            room_no = payload.get('room_no') or payload.get('room')
            if room_no:
                if TreatmentRoom is not None:
                    room_obj = TreatmentRoom.objects.filter(room_no=room_no).first()
                    if not room_obj:
                        return JsonResponse({'error': 'room_not_found', 'room_no': room_no}, status=400)

            # therapists optional
            therapist_codes = payload.get('therapists') or []
            therapists = []
            if therapist_codes and TherapistModel is not None:
                qs = TherapistModel.objects.filter(therapist_code__in=therapist_codes)
                found_codes = set(t.therapist_code for t in qs)
                missing_ts = [c for c in therapist_codes if c not in found_codes]
                if missing_ts:
                    return JsonResponse({'error': 'therapists_not_found', 'missing': missing_ts}, status=400)
                therapists = list(qs)

            # ensure patient snapshot
            pat_no = str(payload['patient_reg_no'])
            ps_defaults = {
                'pat_name': payload.get('patient_name') or '',
                'pat_age': payload.get('patient_age') or '',
                'pat_sex': payload.get('patient_sex') or '',
                'pat_ref_id': payload.get('pat_ref_id') or ''
            }
            if PatientSnapshot is None:
                return JsonResponse({'error': 'PatientSnapshot model not found'}, status=500)
            ps, _ = PatientSnapshot.objects.get_or_create(pat_reg_no=pat_no, defaults=ps_defaults)
            changed = False
            if ps_defaults['pat_name'] and getattr(ps, 'pat_name', '') != ps_defaults['pat_name']:
                ps.pat_name = ps_defaults['pat_name']; changed = True
            if ps_defaults['pat_age'] and getattr(ps, 'pat_age', '') != ps_defaults['pat_age']:
                ps.pat_age = ps_defaults['pat_age']; changed = True
            if ps_defaults['pat_sex'] and getattr(ps, 'pat_sex', '') != ps_defaults['pat_sex']:
                ps.pat_sex = ps_defaults['pat_sex']; changed = True
            if ps_defaults['pat_ref_id'] and getattr(ps, 'pat_ref_id', '') != ps_defaults['pat_ref_id']:
                ps.pat_ref_id = ps_defaults['pat_ref_id']; changed = True
            if changed:
                ps.save()

            # create allocation and per-date bookings atomically (all-or-nothing)
            try:
                with transaction.atomic():
                    if TherapyAllocation is None or Booking is None or BookingItem is None or BookingAssignment is None:
                        return JsonResponse({'error': 'required models missing (TherapyAllocation/Booking/BookingItem/BookingAssignment)'}, status=500)

                    alloc = TherapyAllocation.objects.create(
                        patient=ps,
                        therapy_code=payload.get('therapy_code'),
                        therapy_name=payload.get('therapy_name'),
                        ext_int=payload.get('ext_int') or '',
                        timeslot=timeslot_obj,
                        room=room_obj,
                        items_groups=payload.get('items_groups') or [],
                        oil_class=payload.get('oil_class') or payload.get('oil_class_id') or '',
                        usage=payload.get('usage') or '',
                        procured_from=payload.get('procured') or payload.get('procured_from') or '',
                        from_date=fdate,
                        to_date=tdate,
                        days=(tdate - fdate).days + 1,
                        notes=payload.get('notes') or '',
                        status='draft',
                        allocated_by=request.user if request.user.is_authenticated else None
                    )

                    bookings_created = []
                    for i in range((tdate - fdate).days + 1):
                        single_date = fdate + timedelta(days=i)
                        # Set booking status based on therapy status
                        booking_status = 'scheduled' if alloc.status == 'allocated' else 'draft'
                        b = Booking.objects.create(allocation=alloc, date=single_date, timeslot=timeslot_obj, room=room_obj, status=booking_status)
                        created_items = []
                        for grp in payload.get('items_groups', []):
                            grp_dosage = grp.get('dosage','')
                            grp_uno = grp.get('uno','')
                            for it in grp.get('items', []):
                                bi = BookingItem.objects.create(
                                    booking=b,
                                    item_code=it.get('item_code') or it.get('id') or it.get('item_name'),
                                    item_name=it.get('item_name') or it.get('text') or '',
                                    dosage=it.get('dosage') or grp_dosage or '',
                                    uno=it.get('uno') or grp_uno or '',
                                    status=booking_status
                                )
                                created_items.append({'item_code': bi.item_code, 'item_name': bi.item_name})
                        assigns = []
                        for t in therapists:
                            a = BookingAssignment.objects.create(booking=b, booking_item=None, therapist=t, role=getattr(t,'therapist_grade',''), assigned_for='booking', status='assigned')
                            assigns.append(getattr(t,'therapist_code',''))
                        bookings_created.append({'date': single_date.isoformat(), 'booking_id': b.pk, 'items_count': len(created_items), 'therapists': assigns})

                    # Log comprehensive audit event
                    log_therapy_audit(
                        user=request.user if request.user.is_authenticated else None,
                        action='allocate_therapy',
                        therapy_allocation=alloc,
                        description=f"New therapy '{alloc.therapy_name}' allocated for patient {alloc.patient.pat_reg_no} from {alloc.from_date} to {alloc.to_date}",
                        additional_data={
                            'therapy_code': alloc.therapy_code,
                            'ext_int': alloc.ext_int,
                            'timeslot': str(alloc.timeslot) if alloc.timeslot else None,
                            'room': str(alloc.room) if alloc.room else None,
                            'oil_class': alloc.oil_class,
                            'usage': alloc.usage,
                            'procured_from': alloc.procured_from,
                            'days': alloc.days,
                            'items_groups': alloc.items_groups,
                            'bookings_created': len(bookings_created),
                            'allocated_by': request.user.username if request.user.is_authenticated else 'Anonymous'
                        },
                        request=request
                    )

                    try:
                        if NotificationQueue is not None and (payload.get('procured') or payload.get('procured_from')):
                            # queue a procurement notification aggregated for the allocation
                            NotificationQueue.objects.create(target_type='procurement', target_identifier=payload.get('procured') or payload.get('procured_from'), channel='internal', payload={'allocation_id': alloc.pk}, status='queued')
                    except Exception:
                        pass

                    return JsonResponse({'status': 'ok', 'allocation_id': alloc.pk, 'bookings_created': len(bookings_created)}, status=201)

            except IntegrityError as e:
                return JsonResponse({'error': 'conflict', 'details': str(e)}, status=409)

        # ---------- mark_completed ----------
        if action_post == 'mark_completed':
            booking_id = payload.get('booking_id')
            if not booking_id:
                return JsonResponse({'error': 'booking_id_required'}, status=400)
            if Booking is None:
                return JsonResponse({'error': 'Booking model missing'}, status=500)
            try:
                b = Booking.objects.get(pk=booking_id)
                b.status = 'completed'
                b.save(update_fields=['status','updated_at'] if hasattr(b,'updated_at') else ['status'])
                return JsonResponse({'status': 'ok', 'booking_id': booking_id})
            except Booking.DoesNotExist:
                return JsonResponse({'error': 'booking_not_found'}, status=404)

        # ---------- request_cancellation ----------
        if action_post == 'request_cancellation':
            alloc_id = payload.get('allocation_id')
            from_d = parse_date(payload.get('from_date') or '')
            to_d = parse_date(payload.get('to_date') or '')
            reason = payload.get('reason') or ''
            if not alloc_id or not from_d or not to_d:
                return JsonResponse({'error': 'allocation_id_and_dates_required'}, status=400)
            if TherapyAllocation is None or CancellationRequest is None:
                return JsonResponse({'error': 'required models missing (TherapyAllocation/CancellationRequest)'}, status=500)
            alloc_obj = TherapyAllocation.objects.filter(pk=alloc_id).first()
            if not alloc_obj:
                return JsonResponse({'error': 'allocation_not_found'}, status=404)
            CancellationRequest.objects.create(allocation=alloc_obj, requested_by=None, from_date=from_d, to_date=to_d, items=payload.get('items') or [], reason=reason, status='pending')
            return JsonResponse({'status': 'ok', 'allocation_id': alloc_id, 'from': from_d.isoformat(), 'to': to_d.isoformat()})

        return JsonResponse({'error': 'unknown_action'}, status=400)

    # ---------------- GET actions / template rendering ----------------
    action = (request.GET.get('action') or '').strip().lower()


    # search therapies
    if action == 'search_therapies':
        q = (request.GET.get('q') or '').strip()
        results = []
        if TherapyMaster is not None:
            qs = TherapyMaster.objects.filter(is_active=True).all()  # Use local master table
            if q:
                qs = qs.filter(Q(therapy_name__icontains=q) | Q(therapy_code__icontains=q))
            qs = qs[:50]
            for t in qs:
                results.append({
                    'therapy_code': getattr(t, 'therapy_code', ''),
                    'therapy_name': getattr(t, 'therapy_name', '')
                })
        return JsonResponse(results, safe=False)

    # search items (external DB)
    if action == 'search_items':
        q = (request.GET.get('q') or '').strip()
        results = []
        if ItemMaster is not None:
            try:
                qs = ItemMaster.objects.filter(is_active=True).all()  # Use local master table
                if q:
                    qs = qs.filter(Q(item_name__icontains=q) | Q(item_code__icontains=q))
                qs = qs[:50]
                for i in qs:
                    results.append({
                        'item_code': getattr(i, 'item_code', ''),
                        'item_name': getattr(i, 'item_name', ''),
                        'item_uom': getattr(i, 'unit_of_measure', '') or ''
                    })
            except Exception:
                results = []
        return JsonResponse(results, safe=False)

    # masters (procured / oil / usage / slots etc.)
    if action == 'masters':
        typ = (request.GET.get('type') or '').strip().lower()
        model = None
        if typ == 'procured':
            model = Procured
        elif typ in ('oil', 'oilclass'):
            model = OilClass
        elif typ in ('usage', 'usagetype'):
            model = UsageType
        elif typ in ('ptime', 'prescriptiontime'):
            model = PrescriptionTime
        elif typ in ('scope', 'prescriptionscope'):
            model = PrescriptionScope

        if model is None:
            return JsonResponse([], safe=False)

        out = []
        try:
            qs = model.objects.filter(is_active=True).order_by('name')[:200]
            for x in qs:
                out.append({'id': getattr(x, 'id', None), 'name': getattr(x, 'name', str(x))})
        except Exception:
            out = []
        return JsonResponse(out, safe=False)

    # slots
    if action == 'slots':
        results = []
        if SlotMaster is not None:
            try:
                qs = SlotMaster.objects.filter(is_active=True).all().order_by('slot_number')  # Use local master table
                for s in qs:
                    start = getattr(s, 'start_time', '')
                    if hasattr(start, 'strftime'):
                        start_s = start.strftime('%H:%M')
                    else:
                        start_s = str(start)
                    results.append({'slot_number': getattr(s, 'slot_number', ''), 'start_time': start_s})
            except Exception:
                results = []
        return JsonResponse({'slots': results})

    # allocation_status (per-allocation bookings)
    if action == 'allocation_status':
        alloc_id = request.GET.get('allocation_id')
        if not alloc_id or TherapyAllocation is None:
            return JsonResponse({'error': 'allocation_id required'}, status=400)
        try:
            alloc = TherapyAllocation.objects.prefetch_related('bookings__items', 'bookings__assignments').select_related('timeslot', 'room', 'patient').get(pk=alloc_id)
        except TherapyAllocation.DoesNotExist:
            return JsonResponse({'error': 'not_found'}, status=404)
        out = {
            'allocation_id': alloc.pk,
            'therapy_name': alloc.therapy_name,
            'from_date': alloc.from_date.isoformat(),
            'to_date': alloc.to_date.isoformat(),
            'bookings': []
        }
        # iterate booking objects if present (field names may vary; using related_name 'bookings' expected)
        for b in alloc.bookings.all().order_by('date'):
            items = []
            try:
                for it in b.items.all():
                    items.append({'id': it.pk, 'item_code': it.item_code, 'item_name': it.item_name, 'status': it.status})
            except Exception:
                items = []
            therapists = []
            try:
                for a in b.assignments.all():
                    therapists.append(getattr(a.therapist, 'therapist_code', '') or getattr(a.therapist, 'id', ''))
            except Exception:
                therapists = []
            slot_s = ''
            try:
                slot_s = b.timeslot.start_time.strftime('%H:%M') if getattr(b, 'timeslot', None) and getattr(b.timeslot, 'start_time', None) else ''
            except Exception:
                slot_s = ''
            out['bookings'].append({
                'booking_id': b.pk,
                'date': b.date.isoformat(),
                'slot': slot_s,
                'room': getattr(b.room, 'room_no', None),
                'therapists': therapists,
                'status': getattr(b, 'status', ''),
                'items': items
            })
        return JsonResponse(out, safe=False)

    # patient_therapies: prefer new TherapyAllocation model
    if action == 'patient_therapies':
        reg = (request.GET.get('patient_reg_no') or '').strip()
        if not reg:
            return JsonResponse([], safe=False)
        if TherapyAllocation is not None:
            qs = TherapyAllocation.objects.filter(patient__pat_reg_no=str(reg)).select_related('timeslot','room').prefetch_related('bookings')
            out = []
            for a in qs:
                out.append({
                    'allocation_id': a.pk,
                    'therapy_code': a.therapy_code,
                    'therapy_name': a.therapy_name,
                    'ext_int': a.ext_int,
                    'slot': getattr(a.timeslot,'start_time',None).strftime('%H:%M') if getattr(a,'timeslot',None) and getattr(a.timeslot,'start_time',None) else '',
                    'oil_class': a.oil_class,
                    'usage': a.usage,
                    'procured': a.procured_from,
                    'from_date': a.from_date.isoformat(),
                    'to_date': a.to_date.isoformat(),
                    'days': a.days,
                    'items_groups': a.items_groups or [],
                    'status': a.status
                })
            return JsonResponse(out, safe=False)

        # fallback if you still have any other model (PatientTherapy)
        if PatientTherapy is not None:
            out = []
            try:
                qs = PatientTherapy.objects.filter(patient__pat_reg_no=reg)[:200]
                for pt in qs:
                    out.append({
                        'therapy_code': getattr(pt, 'therapy_code', getattr(pt, 'therapy_id', '')),
                        'therapy_name': getattr(pt, 'therapy_name', '') or str(getattr(pt, 'therapy', '')),
                        'ext_int': getattr(pt, 'ext_int', ''),
                        'slot': getattr(pt, 'slot', '') and (getattr(pt.slot, 'start_time', '') if hasattr(pt, 'slot') else getattr(pt, 'slot')),
                        'oil_class': getattr(pt, 'oil_class', ''),
                        'usage': getattr(pt, 'usage', ''),
                        'procured': getattr(pt, 'procured_from', ''),
                        'from_date': getattr(pt, 'from_date', ''),
                        'to_date': getattr(pt, 'to_date', ''),
                        'days': getattr(pt, 'days', ''),
                        'items_groups': []
                    })
            except Exception:
                out = []
            return JsonResponse(out, safe=False)

        return JsonResponse([], safe=False)

    # --------------- RENDER TEMPLATE WITH masters context ---------------
    masters_context = {}

    # procured list
    try:
        if Procured is not None:
            qs = Procured.objects.filter(is_active=True).order_by('name')[:200]
            masters_context['procured_list'] = [{'id': getattr(x, 'id', None), 'name': getattr(x, 'name', str(x))} for x in qs]
        else:
            masters_context['procured_list'] = []
    except Exception:
        masters_context['procured_list'] = []

    # oil list
    try:
        if OilClass is not None:
            qs = OilClass.objects.filter(is_active=True).order_by('name')[:200]
            masters_context['oil_list'] = [{'id': getattr(x,'id', None), 'name': getattr(x,'name', str(x))} for x in qs]
        else:
            masters_context['oil_list'] = []
    except Exception:
        masters_context['oil_list'] = []

    # usage list
    try:
        if UsageType is not None:
            qs = UsageType.objects.filter(is_active=True).order_by('name')[:200]
            masters_context['usage_list'] = [{'id': getattr(x,'id', None), 'name': getattr(x,'name', str(x))} for x in qs]
        else:
            masters_context['usage_list'] = []
    except Exception:
        masters_context['usage_list'] = []

    # time slots
    try:
        if SlotMaster is not None:
            slots = []
            for s in SlotMaster.objects.filter(is_active=True).all().order_by('slot_number'):  # Use local master table
                start = getattr(s, 'start_time', '')
                if hasattr(start, 'strftime'):
                    start_s = start.strftime('%H:%M')
                else:
                    start_s = str(start)
                slots.append({'slot_number': getattr(s, 'slot_number', ''), 'start_time': start_s})
            masters_context['slots'] = slots
        else:
            masters_context['slots'] = []
    except Exception:
        masters_context['slots'] = []

    return render(request, 'updated_dash/therapy_entry.html', context={'masters': masters_context})


def prescription_entry_page(request):
    """
    Single endpoint for prescription entry:
      - GET: render template or handle lookups by ?action=...
      - POST: perform allocate/cancel/resume/update via ?action=...
    """
    
    # --- POST actions (allocate, cancel, resume, update) ---
    if request.method == 'POST':
        action_post = (request.GET.get('action') or '').strip().lower()
        try:
            payload = json.loads(request.body.decode('utf-8') or '{}')
        except Exception:
            return JsonResponse({'error': 'invalid_json'}, status=400)

        # ---------- allocate prescription ----------
        if action_post == 'allocate':
            patient_reg_no = payload.get('patient_reg_no')
            prescription_name = payload.get('prescription_name', 'Prescription')
            items_groups = payload.get('items_groups', [])
            procured_from = payload.get('procured_from', '')
            from_date = parse_date(payload.get('from_date'))
            to_date = parse_date(payload.get('to_date'))
            notes = payload.get('notes', '')
            
            if not patient_reg_no or not from_date or not to_date:
                return JsonResponse({'error': 'missing_required_fields'}, status=400)
            
            if from_date > to_date:
                return JsonResponse({'error': 'invalid_date_range'}, status=400)
            
            try:
                # Get or create patient snapshot
                ps, created = PatientSnapshot.objects.get_or_create(
                    pat_reg_no=str(patient_reg_no),
                    defaults={
                        'pat_name': payload.get('patient_name', ''),
                        'pat_age': payload.get('patient_age', ''),
                        'pat_sex': payload.get('patient_sex', ''),
                        'pat_room_no': payload.get('patient_room_no', ''),
                        'pat_ref_id': payload.get('patient_ref_id', ''),
                    }
                )
                
                # Update patient info if changed
                changed = False
                if payload.get('patient_name') and ps.pat_name != payload.get('patient_name'):
                    ps.pat_name = payload.get('patient_name'); changed = True
                if payload.get('patient_age') and ps.pat_age != payload.get('patient_age'):
                    ps.pat_age = payload.get('patient_age'); changed = True
                if payload.get('patient_sex') and ps.pat_sex != payload.get('patient_sex'):
                    ps.pat_sex = payload.get('patient_sex'); changed = True
                if payload.get('patient_ref_id') and ps.pat_ref_id != payload.get('patient_ref_id'):
                    ps.pat_ref_id = payload.get('patient_ref_id'); changed = True
                
                if changed:
                    ps.save()

                # Create prescription allocation
                allocation = PrescriptionAllocation.objects.create(
                    patient=ps,
                    prescription_name=prescription_name,
                    items_groups=items_groups,
                    procured_from=procured_from,
                    from_date=from_date,
                    to_date=to_date,
                    days=(to_date - from_date).days + 1,
                    allocated_by=request.user if request.user.is_authenticated else None,
                    notes=notes,
                    status='draft'  # Default to draft
                )
                
                # Create notification
                create_prescription_notification(allocation, 'prescription_allocated', request.user, {
                    'bookings_created': (to_date - from_date).days + 1
                })
                
                # Log audit
                log_prescription_audit(request.user, 'allocate_prescription', 'PrescriptionAllocation', str(allocation.id), {
                    'patient_reg_no': patient_reg_no,
                    'prescription_name': prescription_name,
                    'from_date': str(from_date),
                    'to_date': str(to_date)
                })
                
                return JsonResponse({'status': 'ok', 'allocation_id': allocation.id})
                
            except Exception as e:
                return JsonResponse({'error': str(e)}, status=500)

        # ---------- cancel prescription ----------
        if action_post == 'cancel_prescription':
            allocation_id = payload.get('allocation_id')
            cancel_from = payload.get('cancel_from')
            cancel_to = payload.get('cancel_to')
            reason = payload.get('reason', '')
            
            if not allocation_id or not cancel_from or not cancel_to or not reason:
                return JsonResponse({'error': 'missing_fields'}, status=400)
            
            try:
                allocation = PrescriptionAllocation.objects.get(id=allocation_id)
                allocation.status = 'cancelled'
                allocation.cancelled_by = request.user if request.user.is_authenticated else None
                allocation.cancelled_at = timezone.now()
                allocation.cancelled_date_from = parse_date(cancel_from)
                allocation.cancelled_date_to = parse_date(cancel_to)
                allocation.cancellation_reason = reason
                allocation.save()
                
                # Create notification
                create_prescription_notification(allocation, 'prescription_cancelled', request.user, {
                    'cancel_from': cancel_from,
                    'cancel_to': cancel_to,
                    'reason': reason
                })
                
                # Log audit
                log_prescription_audit(request.user, 'cancel_prescription', 'PrescriptionAllocation', str(allocation.id), {
                    'cancel_from': cancel_from,
                    'cancel_to': cancel_to,
                    'reason': reason
                })
                
                return JsonResponse({'status': 'ok', 'message': 'Prescription cancelled successfully'})
            except PrescriptionAllocation.DoesNotExist:
                return JsonResponse({'error': 'allocation_not_found'}, status=404)
            except Exception as e:
                return JsonResponse({'error': str(e)}, status=500)

        # ---------- resume prescription ----------
        if action_post == 'resume_prescription':
            allocation_id = payload.get('allocation_id')
            resume_from = payload.get('resume_from')
            resume_to = payload.get('resume_to')
            
            if not allocation_id or not resume_from or not resume_to:
                return JsonResponse({'error': 'missing_fields'}, status=400)
            
            try:
                allocation = PrescriptionAllocation.objects.get(id=allocation_id)
                allocation.status = 'draft'  # Set to draft on resume
                allocation.resumed_by = request.user if request.user.is_authenticated else None
                allocation.resumed_at = timezone.now()
                allocation.cancelled_date_from = None
                allocation.cancelled_date_to = None
                allocation.cancellation_reason = ''
                allocation.save()
                
                # Create notification
                create_prescription_notification(allocation, 'prescription_resumed', request.user, {
                    'resume_from': resume_from,
                    'resume_to': resume_to
                })
                
                # Log audit
                log_prescription_audit(request.user, 'resume_prescription', 'PrescriptionAllocation', str(allocation.id), {
                    'resume_from': resume_from,
                    'resume_to': resume_to
                })
                
                return JsonResponse({'status': 'ok', 'message': 'Prescription resumed successfully'})
            except PrescriptionAllocation.DoesNotExist:
                return JsonResponse({'error': 'allocation_not_found'}, status=404)
            except Exception as e:
                return JsonResponse({'error': str(e)}, status=500)

        # ---------- update prescription ----------
        if action_post == 'update_prescription':
            allocation_id = payload.get('allocation_id')
            prescription_name = payload.get('prescription_name')
            items_groups = payload.get('items_groups', [])
            procured_from = payload.get('procured_from', '')
            notes = payload.get('notes', '')
            
            if not allocation_id:
                return JsonResponse({'error': 'missing_allocation_id'}, status=400)
            
            try:
                allocation = PrescriptionAllocation.objects.get(id=allocation_id)
                old_data = {
                    'prescription_name': allocation.prescription_name,
                    'items_groups': allocation.items_groups,
                    'procured_from': allocation.procured_from,
                    'notes': allocation.notes
                }
                
                # Update fields
                if prescription_name:
                    allocation.prescription_name = prescription_name
                if items_groups:
                    allocation.items_groups = items_groups
                if procured_from is not None:
                    allocation.procured_from = procured_from
                if notes is not None:
                    allocation.notes = notes
                
                allocation.save()
                
                # Create notification
                create_prescription_notification(allocation, 'prescription_updated', request.user, {
                    'changes': 'Prescription details updated'
                })
                
                # Log audit
                log_prescription_audit(request.user, 'update_prescription', 'PrescriptionAllocation', str(allocation.id), {
                    'old_data': old_data,
                    'new_data': {
                        'prescription_name': allocation.prescription_name,
                        'items_groups': allocation.items_groups,
                        'procured_from': allocation.procured_from,
                        'notes': allocation.notes
                    }
                })
                
                return JsonResponse({'status': 'ok', 'message': 'Prescription updated successfully'})
            except PrescriptionAllocation.DoesNotExist:
                return JsonResponse({'error': 'allocation_not_found'}, status=404)
            except Exception as e:
                return JsonResponse({'error': str(e)}, status=500)

    # --- GET actions (lookups, masters, patient prescriptions) ---
    action = (request.GET.get('action') or '').strip().lower()
    
    # search items (external DB)
    if action == 'search_items':
        q = (request.GET.get('q') or '').strip()
        results = []
        if ItemMaster is not None:
            try:
                qs = ItemMaster.objects.filter(is_active=True).all()  # Use local master table
                if q:
                    qs = qs.filter(Q(item_name__icontains=q) | Q(item_code__icontains=q))
                qs = qs[:50]
                for i in qs:
                    results.append({
                        'item_code': getattr(i, 'item_code', ''),
                        'item_name': getattr(i, 'item_name', ''),
                        'item_uom': getattr(i, 'unit_of_measure', '') or ''
                    })
                print(results)
            except Exception:
                pass
        return JsonResponse(results, safe=False)
    
    # masters lookup
    if action == 'masters':
        master_type = request.GET.get('type', '').strip()
        results = []
        
        if master_type == 'procured':
            if Procured is not None:
                try:
                    for p in Procured.objects.filter(is_active=True)[:20]:
                        results.append({'name': getattr(p, 'name', '')})
                except Exception:
                    pass
        elif master_type == 'oil':
            if OilClass is not None:
                try:
                    for o in OilClass.objects.filter(is_active=True)[:20]:
                        results.append({'name': getattr(o, 'name', '')})
                except Exception:
                    pass
        elif master_type == 'usage':
            if UsageType is not None:
                try:
                    for u in UsageType.objects.filter(is_active=True)[:20]:
                        results.append({'name': getattr(u, 'name', '')})
                except Exception:
                    pass
        
        return JsonResponse(results, safe=False)
    
    
    # Default: render template
    return render(request, 'updated_dash/prescription_entry.html')


def create_prescription_notification(prescription_allocation, action, user, additional_data=None):
    """Create prescription notification for relevant staff"""
    try:
        if not PrescriptionNotification:
            return
        
        # Map actions to notification types
        notification_mapping = {
            'prescription_allocated': ('prescription_allocated', 'New Prescription Allocated', 'high'),
            'prescription_cancelled': ('prescription_cancelled', 'Prescription Cancelled', 'urgent'),
            'prescription_resumed': ('prescription_resumed', 'Prescription Resumed', 'medium'),
            'prescription_updated': ('prescription_updated', 'Prescription Updated', 'medium'),
        }
        
        if action not in notification_mapping:
            return
        
        notification_type, title_prefix, priority = notification_mapping[action]
        
        # Create notification title and message
        patient_name = prescription_allocation.patient.pat_name or 'Unknown Patient'
        prescription_name = prescription_allocation.prescription_name
        
        title = f"{title_prefix}: {prescription_name}"
        message = f"Patient: {patient_name} ({prescription_allocation.patient.pat_reg_no})\n"
        message += f"Prescription: {prescription_name}\n"
        message += f"Period: {prescription_allocation.from_date} to {prescription_allocation.to_date}\n"
        
        if action == 'prescription_cancelled' and additional_data:
            message += f"Cancelled: {additional_data.get('cancel_from')} to {additional_data.get('cancel_to')}\n"
            message += f"Reason: {additional_data.get('reason', 'No reason provided')}\n"
        elif action == 'prescription_resumed' and additional_data:
            message += f"Resumed: {additional_data.get('resume_from')} to {additional_data.get('resume_to')}\n"
        elif action == 'prescription_allocated' and additional_data:
            message += f"Items Created: {len(prescription_allocation.items_groups)}\n"
        
        # Create notification
        notification = PrescriptionNotification.objects.create(
            prescription_allocation=prescription_allocation,
            notification_type=notification_type,
            title=title,
            message=message,
            priority=priority,
            created_by=user,
            additional_data=additional_data or {}
        )
        
        # Determine target roles based on action
        if action == 'prescription_allocated':
            # Notify pharmacy and admin
            target_roles = ['pharmacy', 'admin', 'super_admin']
        elif action == 'prescription_cancelled':
            # Notify admin, doctors, and pharmacy
            target_roles = ['admin', 'super_admin', 'doctor', 'doctor_admin', 'pharmacy']
        elif action == 'prescription_resumed':
            # Notify pharmacy and admin
            target_roles = ['pharmacy', 'admin', 'super_admin']
        elif action == 'prescription_updated':
            # Notify pharmacy and admin
            target_roles = ['pharmacy', 'admin', 'super_admin']
        else:
            target_roles = ['admin', 'super_admin']
        
        # Send notification to target roles
        notification.send_to_roles(target_roles)
        
    except Exception as e:
        print(f"Prescription notification creation error: {e}")


def log_prescription_audit(user, action, obj_type, obj_id, data):
    """Log prescription audit event"""
    try:
        if AuditLog:
            AuditLog.objects.create(
                user=user,
                action=action,
                obj_type=obj_type,
                obj_id=obj_id,
                data=data
            )
    except Exception as e:
        print(f"Audit logging error: {e}")







@csrf_exempt
def prescription_entry_page(request):
    """
    Renders the HTML template (save your HTML as templates/prescription_entry.html).
    Also handles search_items and masters actions for the template.
    """
    # Handle POST actions (allocate, cancel, resume, update)
    if request.method == 'POST':
        action_post = (request.GET.get('action') or '').strip().lower()
        try:
            payload = json.loads(request.body.decode('utf-8') or '{}')
        except Exception:
            return JsonResponse({'error': 'invalid_json'}, status=400)

        # ---------- allocate prescription ----------
        if action_post == 'allocate':
            patient_reg_no = payload.get('patient_reg_no')
            prescription_name = payload.get('prescription_name', 'Prescription')
            items_groups = payload.get('items_groups', [])
            procured_from = payload.get('procured_from', '')
            from_date = payload.get('from_date')
            to_date = payload.get('to_date')
            days = payload.get('days', 1)
            
            if not patient_reg_no or not from_date or not to_date:
                return JsonResponse({'error': 'missing_required_fields'}, status=400)
            
            try:
                # Get or create patient snapshot
                ps, created = PatientSnapshot.objects.get_or_create(
                    pat_reg_no=str(patient_reg_no),
                    defaults={
                        'pat_name': payload.get('patient_name', ''),
                        'pat_age': payload.get('patient_age', ''),
                        'pat_sex': payload.get('patient_sex', ''),
                        'pat_room_no': payload.get('patient_room_no', ''),
                        'pat_ref_id': payload.get('patient_ref_id', ''),
                    }
                )
                
                # Update patient info if changed
                changed = False
                if payload.get('patient_name') and ps.pat_name != payload.get('patient_name'):
                    ps.pat_name = payload.get('patient_name'); changed = True
                if payload.get('patient_age') and ps.pat_age != payload.get('patient_age'):
                    ps.pat_age = payload.get('patient_age'); changed = True
                if payload.get('patient_sex') and ps.pat_sex != payload.get('patient_sex'):
                    ps.pat_sex = payload.get('patient_sex'); changed = True
                if payload.get('patient_room_no') and ps.pat_room_no != payload.get('patient_room_no'):
                    ps.pat_room_no = payload.get('patient_room_no'); changed = True
                if payload.get('patient_ref_id') and ps.pat_ref_id != payload.get('patient_ref_id'):
                    ps.pat_ref_id = payload.get('patient_ref_id'); changed = True
                if changed: ps.save()
                
                # Create prescription allocation
                allocation = PrescriptionAllocation.objects.create(
                    patient=ps,
                    prescription_name=prescription_name,
                    items_groups=json.dumps(items_groups),
                    procured_from=procured_from,
                    from_date=parse_date(from_date),
                    to_date=parse_date(to_date),
                    days=days,
                    allocated_by=request.user if request.user.is_authenticated else None,
                    status='draft'  # Default status
                )
                
                # Update patient snapshot
                ps.prescription_count = PrescriptionAllocation.objects.filter(patient=ps).count()
                ps.last_prescription_date = allocation.from_date
                ps.save()
                
                # Create notification
                create_prescription_notification(allocation, 'prescription_allocated', request.user)
                
                # Log audit
                log_prescription_audit(request.user, 'allocate_prescription', 'PrescriptionAllocation', str(allocation.id), {
                    'prescription_name': prescription_name,
                    'from_date': from_date,
                    'to_date': to_date,
                    'days': days
                })
                
                return JsonResponse({'status': 'ok', 'message': 'Prescription allocated successfully', 'allocation_id': allocation.id})
            except Exception as e:
                return JsonResponse({'error': str(e)}, status=500)

        # ---------- cancel prescription ----------
        if action_post == 'cancel_prescription':
            allocation_id = payload.get('allocation_id')
            cancel_from = payload.get('cancel_from')
            cancel_to = payload.get('cancel_to')
            reason = payload.get('reason', '').strip()
            
            if not allocation_id or not cancel_from or not cancel_to or not reason:
                return JsonResponse({'error': 'missing_fields'}, status=400)
            
            try:
                allocation = PrescriptionAllocation.objects.get(id=allocation_id)
                allocation.status = 'cancelled'
                allocation.cancelled_by = request.user if request.user.is_authenticated else None
                allocation.cancelled_at = timezone.now()
                allocation.cancelled_date_from = parse_date(cancel_from)
                allocation.cancelled_date_to = parse_date(cancel_to)
                allocation.cancellation_reason = reason
                allocation.save()
                
                # Create notification
                create_prescription_notification(allocation, 'prescription_cancelled', request.user, {
                    'cancel_from': cancel_from,
                    'cancel_to': cancel_to,
                    'reason': reason
                })
                
                # Log audit
                log_prescription_audit(request.user, 'cancel_prescription', 'PrescriptionAllocation', str(allocation.id), {
                    'cancel_from': cancel_from,
                    'cancel_to': cancel_to,
                    'reason': reason
                })
                
                return JsonResponse({'status': 'ok', 'message': 'Prescription cancelled successfully'})
            except PrescriptionAllocation.DoesNotExist:
                return JsonResponse({'error': 'allocation_not_found'}, status=404)
            except Exception as e:
                return JsonResponse({'error': str(e)}, status=500)

        # ---------- resume prescription ----------
        if action_post == 'resume_prescription':
            allocation_id = payload.get('allocation_id')
            resume_from = payload.get('resume_from')
            resume_to = payload.get('resume_to')
            
            if not allocation_id or not resume_from or not resume_to:
                return JsonResponse({'error': 'missing_fields'}, status=400)
            
            try:
                allocation = PrescriptionAllocation.objects.get(id=allocation_id)
                allocation.status = 'draft'  # Set to draft on resume
                allocation.resumed_by = request.user if request.user.is_authenticated else None
                allocation.resumed_at = timezone.now()
                allocation.cancelled_date_from = None
                allocation.cancelled_date_to = None
                allocation.cancellation_reason = ''
                allocation.save()
                
                # Create notification
                create_prescription_notification(allocation, 'prescription_resumed', request.user, {
                    'resume_from': resume_from,
                    'resume_to': resume_to
                })
                
                # Log audit
                log_prescription_audit(request.user, 'resume_prescription', 'PrescriptionAllocation', str(allocation.id), {
                    'resume_from': resume_from,
                    'resume_to': resume_to
                })
                
                return JsonResponse({'status': 'ok', 'message': 'Prescription resumed successfully'})
            except PrescriptionAllocation.DoesNotExist:
                return JsonResponse({'error': 'allocation_not_found'}, status=404)
            except Exception as e:
                return JsonResponse({'error': str(e)}, status=500)

        # ---------- update prescription ----------
        if action_post == 'update_prescription':
            allocation_id = payload.get('allocation_id')
            prescription_name = payload.get('prescription_name', '')
            items_groups = payload.get('items_groups', [])
            procured_from = payload.get('procured_from', '')
            from_date = payload.get('from_date')
            to_date = payload.get('to_date')
            days = payload.get('days', 1)
            
            if not allocation_id:
                return JsonResponse({'error': 'missing_allocation_id'}, status=400)
            
            try:
                allocation = PrescriptionAllocation.objects.get(id=allocation_id)
                
                # Update fields
                if prescription_name:
                    allocation.prescription_name = prescription_name
                if items_groups:
                    allocation.items_groups = json.dumps(items_groups)
                if procured_from:
                    allocation.procured_from = procured_from
                if from_date:
                    allocation.from_date = parse_date(from_date)
                if to_date:
                    allocation.to_date = parse_date(to_date)
                if days:
                    allocation.days = days
                
                allocation.save()
                
                # Create notification
                create_prescription_notification(allocation, 'prescription_updated', request.user)
                
                # Log audit
                log_prescription_audit(request.user, 'update_prescription', 'PrescriptionAllocation', str(allocation.id), {
                    'prescription_name': prescription_name,
                    'from_date': from_date,
                    'to_date': to_date,
                    'days': days
                })
                
                return JsonResponse({'status': 'ok', 'message': 'Prescription updated successfully'})
            except PrescriptionAllocation.DoesNotExist:
                return JsonResponse({'error': 'allocation_not_found'}, status=404)
            except Exception as e:
                return JsonResponse({'error': str(e)}, status=500)

    # Handle GET actions (search_items, masters)
    action = (request.GET.get('action') or '').strip().lower()
    
    # search items (external DB)
    if action == 'search_items':
        q = (request.GET.get('q') or '').strip()
        results = []
        if ItemMaster is not None:
            try:
                qs = ItemMaster.objects.filter(is_active=True).all()  # Use local master table
                if q:
                    qs = qs.filter(Q(item_name__icontains=q) | Q(item_code__icontains=q))
                qs = qs[:50]
                for i in qs:
                    results.append({
                        'item_code': getattr(i, 'item_code', ''),
                        'item_name': getattr(i, 'item_name', ''),
                        'item_uom': getattr(i, 'unit_of_measure', '') or ''
                    })
            except Exception:
                pass
        return JsonResponse(results, safe=False)
    
    # masters lookup
    if action == 'masters':
        master_type = request.GET.get('type', '').strip()
        results = []
        
        if master_type == 'procured':
            if Procured is not None:
                try:
                    for p in Procured.objects.filter(is_active=True)[:20]:
                        results.append({'name': getattr(p, 'name', '')})
                except Exception:
                    pass
        elif master_type == 'oil':
            if OilClass is not None:
                try:
                    for o in OilClass.objects.filter(is_active=True)[:20]:
                        results.append({'name': getattr(o, 'name', '')})
                except Exception:
                    pass
        elif master_type == 'usage':
            if UsageType is not None:
                try:
                    for u in UsageType.objects.filter(is_active=True)[:20]:
                        results.append({'name': getattr(u, 'name', '')})
                except Exception:
                    pass
        
        return JsonResponse(results, safe=False)
    
    # patient prescriptions
    if action == 'patient_prescriptions':
        patient_reg_no = request.GET.get('patient_reg_no')
        if not patient_reg_no:
            return JsonResponse({'error': 'missing_patient_reg_no'}, status=400)
        
        try:
            patient = PatientSnapshot.objects.get(pat_reg_no=patient_reg_no)
            prescriptions = PrescriptionAllocation.objects.filter(patient=patient).order_by('-created_at')
            
            results = []
            for p in prescriptions:
                results.append({
                    'id': p.id,
                    'prescription_name': p.prescription_name,
                    'items_groups': p.items_groups if isinstance(p.items_groups, (list, dict)) else (json.loads(p.items_groups) if p.items_groups else []),
                    'procured_from': p.procured_from,
                    'from_date': p.from_date.isoformat() if p.from_date else None,
                    'to_date': p.to_date.isoformat() if p.to_date else None,
                    'days': p.days,
                    'status': p.status,
                    'allocated_by': p.allocated_by.username if p.allocated_by else None,
                    'cancelled_by': p.cancelled_by.username if p.cancelled_by else None,
                    'cancelled_at': p.cancelled_at.isoformat() if p.cancelled_at else None,
                    'cancelled_date_from': p.cancelled_date_from.isoformat() if p.cancelled_date_from else None,
                    'cancelled_date_to': p.cancelled_date_to.isoformat() if p.cancelled_date_to else None,
                    'cancellation_reason': p.cancellation_reason,
                    'resumed_by': p.resumed_by.username if p.resumed_by else None,
                    'resumed_at': p.resumed_at.isoformat() if p.resumed_at else None
                })
            
            return JsonResponse(results, safe=False)
        except PatientSnapshot.DoesNotExist:
            return JsonResponse({'error': 'patient_not_found'}, status=404)
        except Exception as e:
            return JsonResponse({'error': str(e)}, status=500)
    
    # Default: render the template
    return render(request, 'updated_dash/prescription_entry.html')


def create_prescription_notification(prescription_allocation, action, user, additional_data=None):
    """Create prescription notification for relevant staff"""
    try:
        from .models import PrescriptionNotification
        
        # Map actions to notification types
        notification_mapping = {
            'prescription_allocated': ('prescription_allocated', 'New Prescription Allocated', 'high'),
            'prescription_cancelled': ('prescription_cancelled', 'Prescription Cancelled', 'urgent'),
            'prescription_resumed': ('prescription_resumed', 'Prescription Resumed', 'medium'),
            'prescription_updated': ('prescription_updated', 'Prescription Updated', 'medium'),
        }
        
        if action not in notification_mapping:
            return
        
        notification_type, title_prefix, priority = notification_mapping[action]
        
        # Create notification title and message
        patient_name = prescription_allocation.patient.pat_name or 'Unknown Patient'
        prescription_name = prescription_allocation.prescription_name
        
        title = f"{title_prefix}: {prescription_name}"
        message = f"Patient: {patient_name} ({prescription_allocation.patient.pat_reg_no})\n"
        message += f"Prescription: {prescription_name}\n"
        message += f"Period: {prescription_allocation.from_date} to {prescription_allocation.to_date}\n"
        
        if action == 'prescription_cancelled' and additional_data:
            message += f"Cancelled: {additional_data.get('cancel_from')} to {additional_data.get('cancel_to')}\n"
            message += f"Reason: {additional_data.get('reason', 'No reason provided')}\n"
        elif action == 'prescription_resumed' and additional_data:
            message += f"Resumed: {additional_data.get('resume_from')} to {additional_data.get('resume_to')}\n"
        
        # Create notification
        notification = PrescriptionNotification.objects.create(
            prescription_allocation=prescription_allocation,
            notification_type=notification_type,
            title=title,
            message=message,
            priority=priority,
            created_by=user,
            additional_data=additional_data or {}
        )
        
        # Determine target roles based on action
        if action == 'prescription_allocated':
            # Notify pharmacy, admin
            target_roles = ['pharmacy', 'admin', 'super_admin']
        elif action == 'prescription_cancelled':
            # Notify admin, doctors, pharmacy
            target_roles = ['admin', 'super_admin', 'doctor', 'doctor_admin', 'pharmacy']
        elif action == 'prescription_resumed':
            # Notify pharmacy and admin
            target_roles = ['pharmacy', 'admin', 'super_admin']
        elif action == 'prescription_updated':
            # Notify pharmacy and admin
            target_roles = ['pharmacy', 'admin', 'super_admin']
        else:
            target_roles = ['admin', 'super_admin']
        
        # Send notification to target roles
        notification.send_to_roles(target_roles)
        
    except Exception as e:
        print(f"Prescription notification creation error: {e}")


def log_prescription_audit(user, action, obj_type, obj_id, additional_data=None):
    """Log prescription-related audit events"""
    try:
        ip_address = None
        user_agent = ''
        
        # Prepare audit data
        audit_data = {
            'action': action,
            'user_id': user.id if user else None,
            'username': user.username if user else 'Anonymous',
            'timestamp': timezone.now().isoformat(),
        }
        
        if additional_data:
            audit_data.update(additional_data)
        
        # Create audit log entry
        AuthAuditLog.objects.create(
            user=user,
            action=action,
            description=f"Prescription {action} by {user.username if user else 'Anonymous'}",
            ip_address=ip_address,
            user_agent=user_agent,
            status='success',
            object_type=obj_type,
            object_id=obj_id,
            additional_data=audit_data
        )
        
        # Also create Sheduling audit log for backward compatibility
        AuditLog.objects.create(
            user=user,
            action=action,
            obj_type=obj_type,
            obj_id=obj_id,
            data=audit_data
        )
            
    except Exception as e:
        # Don't let audit logging break the main functionality
        print(f"Prescription audit logging error: {e}")









#algorithm
import json
from datetime import datetime, timedelta, time, date

from django.http import JsonResponse, HttpResponseBadRequest
from django.views.decorators.http import require_POST
from django.views.decorators.csrf import csrf_exempt
from django.db import transaction, IntegrityError

# import your new models (adjust the app name if different)
from .models import (
    PatientSnapshot,
    TherapyAllocation,
    Booking,
    BookingItem,
    BookingAssignment,
    NotificationQueue,
    AuditLog,
    AllocationChange,
   
)
from Patient.models import Therapist, TimeSlot,TreatmentRoom # or from therapies.models if Therapist located there

# helper to iterate date range inclusive
def daterange(start_date: date, end_date: date):
    d = start_date
    while d <= end_date:
        yield d
        d += timedelta(days=1)

def parse_date(s):
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except Exception:
        return None

def parse_time_hhmm(s):
    try:
        t = datetime.strptime(s, "%H:%M").time()
        return t
    except Exception:
        return None

@csrf_exempt
@require_POST
def allocate_therapy(request):
    """
    POST JSON payload expected (example below).
    Will create TherapyAllocation, Bookings, BookingItems, BookingAssignments, Notifications, Audit.
    """
    try:
        payload = json.loads(request.body)
    except json.JSONDecodeError:
        return HttpResponseBadRequest("Invalid JSON")

    # Required top-level fields (front-end should send these)
    # patient_reg_no (string), therapy_code, therapy_name, from_date, to_date
    required = ["patient_reg_no", "therapy_code", "therapy_name", "from_date", "to_date", "items_groups"]
    missing = [k for k in required if k not in payload]
    if missing:
        return JsonResponse({"error": "Missing required fields", "missing": missing}, status=400)

    # parse dates
    from_date = parse_date(payload["from_date"])
    to_date = parse_date(payload["to_date"])
    if not from_date or not to_date or from_date > to_date:
        return JsonResponse({"error": "Invalid from_date / to_date"}, status=400)

    # timeslot: accept either slot_number (int) or "HH:MM" string
    timeslot = None
    if payload.get("timeslot_slot_number") is not None:
        try:
            timeslot = SlotMaster.objects.get(slot_number=int(payload["timeslot_slot_number"]), is_active=True)  # Use local master table
        except SlotMaster.DoesNotExist:
            return JsonResponse({"error": "Slot with that slot_number not found"}, status=400)
    elif payload.get("timeslot"):
        t = parse_time_hhmm(payload["timeslot"])
        if not t:
            return JsonResponse({"error": "Invalid timeslot format, expected HH:MM"}, status=400)
        timeslot = SlotMaster.objects.filter(start_time=t, is_active=True).first()  # Use local master table
        if not timeslot:
            # Optionally create a timeslot if you want; for safety we require an existing one:
            return JsonResponse({"error": "TimeSlot with that start_time not found"}, status=400)

    # room (optional)
    room = None
    room_no = payload.get("room_no")  # optional string
    if room_no:
        room = TreatmentRoom.objects.filter(room_no=room_no).first()
        if not room:
            return JsonResponse({"error": f"TreatmentRoom {room_no} not found"}, status=400)

    # therapists: optional list of therapist_codes that should be assigned for every date
    therapist_codes = payload.get("therapists") or []
    therapists = []
    if therapist_codes:
        therapists_qs = Therapist.objects.filter(therapist_code__in=therapist_codes)
        found_codes = set(t.therapist_code for t in therapists_qs)
        missing_ts = [c for c in therapist_codes if c not in found_codes]
        if missing_ts:
            return JsonResponse({"error": "Some therapists not found", "missing_therapists": missing_ts}, status=400)
        therapists = list(therapists_qs)

    # items_groups expected as list of groups:
    # [{ "items":[{"item_code":"KAS","item_name":"Kashayam"}, ...], "dosage":"10 ml", "uno":"1" }, ...]
    items_groups = payload.get("items_groups")
    if not isinstance(items_groups, list) or len(items_groups) == 0:
        return JsonResponse({"error": "items_groups must be a non-empty list"}, status=400)

    # optional masters
    oil_class = payload.get("oil_class") or ""
    usage = payload.get("usage") or ""
    procured_from = payload.get("procured_from") or ""
    ext_int = payload.get("ext_int") or ""
    allocated_by_user_id = payload.get("allocated_by_user_id", None)

    # get request.user if available (prefer that)
    allocated_by_user = getattr(request, "user", None) if getattr(request, "user", None) and request.user.is_authenticated else None

    # create / update patient snapshot
    pat_reg_no = str(payload["patient_reg_no"])
    pat_name = payload.get("patient_name")
    pat_age = payload.get("patient_age")
    pat_sex = payload.get("patient_sex")
    pat_ref_id = payload.get("pat_ref_id")

    patient_snapshot, _ = PatientSnapshot.objects.get_or_create(
        pat_reg_no=pat_reg_no,
        defaults={
            "pat_name": pat_name,
            "pat_age": pat_age,
            "pat_sex": pat_sex,
            "pat_ref_id": pat_ref_id
        }
    )
    # update small fields if provided
    changed = False
    if pat_name and patient_snapshot.pat_name != pat_name:
        patient_snapshot.pat_name = pat_name; changed = True
    if pat_age and patient_snapshot.pat_age != pat_age:
        patient_snapshot.pat_age = pat_age; changed = True
    if pat_sex and patient_snapshot.pat_sex != pat_sex:
        patient_snapshot.pat_sex = pat_sex; changed = True
    if pat_ref_id and patient_snapshot.pat_ref_id != pat_ref_id:
        patient_snapshot.pat_ref_id = pat_ref_id; changed = True
    if changed:
        patient_snapshot.save(update_fields=["pat_name","pat_age","pat_sex","pat_ref_id","updated_at"])

    # start atomic transaction for entire allocation (all-or-nothing)
    try:
        with transaction.atomic():
            allocation = TherapyAllocation.objects.create(
                patient=patient_snapshot,
                therapy_code=payload["therapy_code"],
                therapy_name=payload["therapy_name"],
                ext_int=ext_int,
                timeslot=timeslot,
                room=room,
                items_groups=items_groups,
                oil_class=oil_class,
                usage=usage,
                procured_from=procured_from,
                from_date=from_date,
                to_date=to_date,
                days=(to_date - from_date).days + 1,
                required_therapist_roles=payload.get("required_therapist_roles", []),
                allocated_by=allocated_by_user if allocated_by_user else None,
                notes=payload.get("notes","")
            )

            created_bookings = []
            notifications_to_enqueue = []

            # iterate dates and create Booking, BookingItem, BookingAssignment
            for d in daterange(from_date, to_date):
                # create booking (UniqueConstraint on room/date/timeslot will guard)
                booking = Booking.objects.create(
                    allocation=allocation,
                    date=d,
                    timeslot=timeslot,
                    room=room,
                    status="scheduled"
                )

                # create items for this booking
                created_items = []
                for grp in items_groups:
                    grp_dosage = grp.get("dosage","")
                    grp_uno = grp.get("uno","")
                    for it in grp.get("items", []):
                        bi = BookingItem.objects.create(
                            booking=booking,
                            item_code=it.get("item_code"),
                            item_name=it.get("item_name"),
                            dosage=it.get("dosage") or grp_dosage or "",
                            uno=it.get("uno") or grp_uno or "",
                            status="scheduled"
                        )
                        created_items.append({
                            "item_code": bi.item_code,
                            "item_name": bi.item_name,
                            "dosage": bi.dosage,
                            "uno": bi.uno
                        })

                # assign therapists (same therapists assigned to each date)
                created_assignments = []
                for t in therapists:
                    assign = BookingAssignment.objects.create(
                        booking=booking,
                        booking_item=None,
                        therapist=t,
                        role=getattr(t, "therapist_grade", ""),
                        assigned_for="booking",
                        status="assigned"
                    )
                    created_assignments.append(assign)

                created_bookings.append({
                    "date": d.isoformat(),
                    "booking_id": booking.pk,
                    "items_count": len(created_items),
                    "therapists": [t.therapist_code for t in therapists],
                    "room_no": room.room_no if room else None
                })

                # prepare a notification entry for procurement / patient / therapists (simple aggregated payload)
                if procured_from:
                    notifications_to_enqueue.append({
                        "target_type": "procurement",
                        "target_identifier": procured_from,
                        "channel": "webhook",
                        "payload": {
                            "action": "reserve",
                            "allocation_id": allocation.pk,
                            "patient_reg_no": patient_snapshot.pat_reg_no,
                            "date": d.isoformat(),
                            "items": created_items
                        }
                    })

            # create notification rows
            for n in notifications_to_enqueue:
                NotificationQueue.objects.create(
                    target_type=n["target_type"],
                    target_identifier=n.get("target_identifier",""),
                    channel=n.get("channel","webhook"),
                    payload=n["payload"],
                    status="queued"
                )

            # audit + allocation change
            AuditLog.objects.create(
                user=allocated_by_user,
                action="allocate_therapy",
                obj_type="TherapyAllocation",
                obj_id=str(allocation.pk),
                data={"created_bookings": created_bookings}
            )
            AllocationChange.objects.create(
                allocation=allocation,
                changed_by=allocated_by_user,
                change_type="create_allocation",
                diff={"added": created_bookings},
                reason=payload.get("reason","")
            )

            # commit transaction end
            return JsonResponse({
                "status": "success",
                "allocation_id": allocation.pk,
                "bookings_created": len(created_bookings)
            }, status=201)

    except IntegrityError as e:
        # detect conflicts and return readable info
        conflict_info = {"error": "conflict", "details": str(e)}
        # try to detect room conflict: find any date where a Booking exists for same room/date/timeslot
        if room and timeslot:
            conflicting = Booking.objects.filter(room=room, date__gte=from_date, date__lte=to_date, timeslot=timeslot).values("date","pk")
            if conflicting.exists():
                conflict_info["room_conflicts"] = list(conflicting)
        # detect therapist conflicts
        t_conflicts = []
        for t in therapists:
            # any BookingAssignment for therapist in that date/slot
            ass_conf = BookingAssignment.objects.filter(therapist=t, booking_date__gte=from_date, booking_date__lte=to_date, booking_timeslot=timeslot, status__in=["assigned","BOOKED"]).values("booking_date","id")
            if ass_conf.exists():
                t_conflicts.append({"therapist_code": t.therapist_code, "conflicts": list(ass_conf)})
        if t_conflicts:
            conflict_info["therapist_conflicts"] = t_conflicts

        return JsonResponse(conflict_info, status=409)
    except Exception as exc:
        return JsonResponse({"error": "server_error", "details": str(exc)}, status=500)


@scheduling_access_required
def scheduling_dashboard(request):
    """
    Display the therapy scheduling dashboard with draft, failed, and scheduled therapies.
    """
    from .models import TherapyAllocation, Booking, BookingAssignment
    from Patient.models import Therapist, TreatmentRoom, TimeSlot
    from masters.models import SlotMaster
    
    # Get date filter from request
    date_filter = request.GET.get('date')
    if date_filter:
        try:
            filter_date = parse_date(date_filter)
        except:
            filter_date = None
    else:
        filter_date = None
    
    # Fetch therapy allocations based on status
    draft_allocations = TherapyAllocation.objects.filter(status='draft')
    failed_allocations = TherapyAllocation.objects.filter(status='failed')
    scheduled_allocations = TherapyAllocation.objects.filter(status='allocated')
    
    # Apply date filter if provided
    if filter_date:
        draft_allocations = draft_allocations.filter(from_date__lte=filter_date, to_date__gte=filter_date)
        failed_allocations = failed_allocations.filter(from_date__lte=filter_date, to_date__gte=filter_date)
        scheduled_allocations = scheduled_allocations.filter(from_date__lte=filter_date, to_date__gte=filter_date)
    
    # Prepare context data
    context = {
        'draft_allocations': draft_allocations.select_related('patient', 'room', 'timeslot').prefetch_related('bookings__assignments__therapist'),
        'failed_allocations': failed_allocations.select_related('patient', 'room', 'timeslot').prefetch_related('bookings__assignments__therapist'),
        'scheduled_allocations': scheduled_allocations.select_related('patient', 'room', 'timeslot').prefetch_related('bookings__assignments__therapist'),
        'date_filter': date_filter or '',
        'stats': {
            'draft_count': draft_allocations.count(),
            'failed_count': failed_allocations.count(),
            'scheduled_count': scheduled_allocations.count(),
        }
    }
    
    return render(request, 'scheduling.html', context)


@csrf_exempt
@api_access_required
def schedule_therapies_api(request):
    """
    API endpoint to trigger the scheduling algorithm for draft therapies.
    """
    if request.method != 'POST':
        return JsonResponse({'error': 'POST method required'}, status=405)
    
    try:
        data = json.loads(request.body)
        date_filter = data.get('date')
        allocation_ids = data.get('allocation_ids', [])
        
        if not date_filter:
            return JsonResponse({'error': 'Date is required'}, status=400)
        
        # Import the scheduling algorithm
        from allocation_logic import expand_therapies_for_visit
        
        # Get draft allocations to process
        from .models import TherapyAllocation
        
        if allocation_ids:
            # Process specific allocations
            allocations = TherapyAllocation.objects.filter(
                id__in=allocation_ids, 
                status='draft'
            )
            if not allocations.exists():
                return JsonResponse({'error': 'No draft therapies found with the specified IDs'}, status=400)
        else:
            # Process all draft allocations (regardless of date range)
            # This allows scheduling even if no therapies exist for the specific date
            allocations = TherapyAllocation.objects.filter(status='draft')
            
            if not allocations.exists():
                return JsonResponse({
                    'success': True,
                    'message': 'No draft therapies found to schedule. You can create new therapy allocations first.',
                    'results': [],
                    'stats': {
                        'total': 0,
                        'successful': 0,
                        'failed': 0
                    }
                })
        
        results = []
        success_count = 0
        failed_count = 0
        
        # Process each allocation
        for allocation in allocations:
            try:
                # Convert TherapyAllocation to Visit format for the algorithm
                # This is a simplified conversion - you may need to adjust based on your data structure
                visit_id = allocation.id  # Using allocation ID as visit ID for now
                
                # Run the scheduling algorithm
                tasks = expand_therapies_for_visit(visit_id, create_bookings=True)
                
                if isinstance(tasks, dict) and "error" in tasks:
                    # Algorithm returned an error
                    allocation.status = 'failed'
                    allocation.save()
                    results.append({
                        'allocation_id': allocation.id,
                        'status': 'failed',
                        'reason': tasks['error']
                    })
                    failed_count += 1
                else:
                    # Process algorithm results
                    success_tasks = [t for t in tasks if t.get('status') == 'BOOKED']
                    failed_tasks = [t for t in tasks if t.get('status') == 'FAILED']
                    
                    if success_tasks:
                        allocation.status = 'allocated'
                        allocation.save()
                        success_count += 1
                        results.append({
                            'allocation_id': allocation.id,
                            'status': 'success',
                            'tasks': success_tasks
                        })
                    else:
                        allocation.status = 'failed'
                        allocation.save()
                        failed_count += 1
                        results.append({
                            'allocation_id': allocation.id,
                            'status': 'failed',
                            'reason': failed_tasks[0].get('reason', 'Unknown error') if failed_tasks else 'No available slots'
                        })
                        
            except Exception as e:
                allocation.status = 'failed'
                allocation.save()
                results.append({
                    'allocation_id': allocation.id,
                    'status': 'failed',
                    'reason': str(e)
                })
                failed_count += 1
        
        return JsonResponse({
            'success': True,
            'message': f'Processed {len(allocations)} therapies: {success_count} successful, {failed_count} failed',
            'results': results,
            'stats': {
                'total': len(allocations),
                'successful': success_count,
                'failed': failed_count
            }
        })
        
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


@csrf_exempt
@api_access_required
def get_therapy_data_api(request):
    """
    API endpoint to fetch therapy data for the scheduling dashboard.
    """
    if request.method != 'GET':
        return JsonResponse({'error': 'GET method required'}, status=405)
    
    try:
        from .models import TherapyAllocation
        from Patient.models import Therapist, TreatmentRoom, TimeSlot
        
        # Get filters
        date_filter = request.GET.get('date')
        status_filter = request.GET.get('status', 'all')
        
        # Build query
        query = {}
        if date_filter:
            filter_date = parse_date(date_filter)
            if filter_date:
                query['from_date__lte'] = filter_date
                query['to_date__gte'] = filter_date
        
        if status_filter != 'all':
            query['status'] = status_filter
        
        # Fetch allocations
        allocations = TherapyAllocation.objects.filter(**query).select_related(
            'patient', 'room', 'timeslot'
        ).prefetch_related(
            'bookings__assignments__therapist'
        )
        
        # Convert to JSON format
        data = []
        for allocation in allocations:
            # Get assigned therapists
            therapists = []
            for booking in allocation.bookings.all():
                for assignment in booking.assignments.all():
                    therapists.append({
                        'code': assignment.therapist.therapist_code,
                        'name': assignment.therapist.therapist_name,
                        'grade': assignment.therapist.therapist_grade
                    })
            
            data.append({
                'id': allocation.id,
                'patient_name': allocation.patient.pat_name,
                'patient_reg_no': allocation.patient.pat_reg_no,
                'therapy_name': allocation.therapy_name,
                'therapy_code': allocation.therapy_code,
                'from_date': allocation.from_date.isoformat(),
                'to_date': allocation.to_date.isoformat(),
                'status': allocation.status,
                'room_no': allocation.room.room_no if allocation.room else None,
                'timeslot': allocation.timeslot.start_time.strftime('%H:%M') if allocation.timeslot else None,
                'therapists': therapists,
                'created_at': allocation.created_at.isoformat(),
                'allocated_by': allocation.allocated_by.username if allocation.allocated_by else None
            })
        
        return JsonResponse({
            'success': True,
            'data': data,
            'count': len(data)
        })
        
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


@csrf_exempt
@api_access_required
def reschedule_therapy_api(request):
    """
    API endpoint to reschedule a single failed therapy.
    """
    if request.method != 'POST':
        return JsonResponse({'error': 'POST method required'}, status=405)
    
    try:
        data = json.loads(request.body)
        allocation_id = data.get('allocation_id')
        date = data.get('date')
        
        if not allocation_id or not date:
            return JsonResponse({'error': 'allocation_id and date are required'}, status=400)
        
        from .models import TherapyAllocation
        
        try:
            allocation = TherapyAllocation.objects.get(id=allocation_id, status='failed')
            allocation.status = 'draft'
            allocation.save()
            
            return JsonResponse({
                'success': True,
                'message': 'Therapy moved back to draft for rescheduling'
            })
        except TherapyAllocation.DoesNotExist:
            return JsonResponse({'error': 'Therapy allocation not found'}, status=404)
            
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


@csrf_exempt
@api_access_required
def reschedule_all_failed_api(request):
    """
    API endpoint to reschedule all failed therapies for a date.
    """
    if request.method != 'POST':
        return JsonResponse({'error': 'POST method required'}, status=405)
    
    try:
        data = json.loads(request.body)
        date = data.get('date')
        
        if not date:
            return JsonResponse({'error': 'date is required'}, status=400)
        
        from .models import TherapyAllocation
        
        filter_date = parse_date(date)
        if not filter_date:
            return JsonResponse({'error': 'Invalid date format'}, status=400)
        
        # Get all failed allocations (regardless of date range for rescheduling)
        failed_allocations = TherapyAllocation.objects.filter(status='failed')
        
        if not failed_allocations.exists():
            return JsonResponse({
                'success': True,
                'message': 'No failed therapies found to reschedule. You can create new therapy allocations first.'
            })
        
        # Move them back to draft
        updated_count = failed_allocations.update(status='draft')
        
        return JsonResponse({
            'success': True,
            'message': f'{updated_count} failed therapies moved back to draft for rescheduling'
        })
        
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)
