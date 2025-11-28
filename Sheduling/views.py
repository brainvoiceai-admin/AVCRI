# therapies/views.py
import json
from datetime import timedelta, datetime
from django.shortcuts import render
from django.http import JsonResponse, HttpResponseBadRequest
from django.apps import apps
from django.db.models import Q
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from django.utils.dateparse import parse_date
from django.utils import timezone
from django.db import transaction, IntegrityError
from authentication.models import AuditLog as AuthAuditLog
from .decorators import scheduling_access_required, scheduling_admin_required, therapist_access_required, api_access_required
from masters.models import get_staying_room_display_number

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
        if therapy_allocation and AuditLog is not None:
            try:
                AuditLog.objects.create(
                    user=user,
                    action=action,
                    obj_type='TherapyAllocation',
                    obj_id=str(therapy_allocation.id),
                    data=audit_data
                )
            except Exception as audit_e:
                print(f"AuditLog creation error: {audit_e}")
            
            # Create therapy notification - COMMENTED OUT DUE TO WEBSOCKET ERRORS
            # create_therapy_notification(therapy_allocation, action, user, additional_data)
            
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
        
        # Send notification to target roles - COMMENTED OUT DUE TO WEBSOCKET ERRORS
        # notification.send_to_roles(target_roles)
        
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
NurseTreatmentMaster = get_model_safe('masters', 'NurseTreatmentMaster')

# Masters
Procured = get_model_safe('masters', 'Procured')
OilClass = get_model_safe('masters', 'OilClass')
UsageType = get_model_safe('masters', 'UsageType')
PrescriptionTime = get_model_safe('masters', 'PrescriptionTime')
PrescriptionScope = get_model_safe('masters', 'PrescriptionScope')
IngredientMaster = get_model_safe('masters', 'IngredientMaster')

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
                # Release therapist assignments and free Patient booking resources
                try:
                    # mark assignments as released
                    BookingAssignment.objects.filter(booking__in=cancelled_bookings).update(status='released')
                except Exception:
                    pass
                try:
                    # also free underlying Patient TherapistBooking/RoomBooking
                    from Patient.models import TherapistBooking as TB, RoomBooking as RB
                    TB.objects.filter(date__gte=parse_date(cancel_from), date__lte=parse_date(cancel_to), patient_id=allocation.patient.id).update(status='CANCELLED')
                    RB.objects.filter(date__gte=parse_date(cancel_from), date__lte=parse_date(cancel_to), patient_id=allocation.patient.id).update(status='CANCELLED')
                except Exception:
                    pass
                
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
                # default set to draft; will selectively schedule if final run exists
                resumed_bookings.update(status='draft')
                
                # re-allocate only for dates where FinalScheduleRun exists
                failed_reasons = []
                any_success = False
                try:
                    from .models import FinalScheduleRun
                    from final_allocation import expand_therapies_for_visit
                    for d in daterange(parse_date(resume_from), parse_date(resume_to)):
                        if FinalScheduleRun.objects.filter(run_date=d).exists():
                            try:
                                tasks = expand_therapies_for_visit(allocation.id, d.strftime('%Y-%m-%d'), create_bookings=True)
                                if isinstance(tasks, list) and any(t.get('status') == 'BOOKED' for t in tasks):
                                    any_success = True
                                    Booking.objects.filter(allocation=allocation, date=d).update(status='scheduled')
                                    BookingItem.objects.filter(booking__allocation=allocation, booking__date=d).update(status='scheduled')
                                else:
                                    reason = None
                                    if isinstance(tasks, list):
                                        fails = [t for t in tasks if t.get('status') == 'FAILED']
                                        reason = fails[0].get('reason') if fails else 'allocation_failed'
                                    elif isinstance(tasks, dict):
                                        reason = tasks.get('error')
                                    failed_reasons.append({'date': d.isoformat(), 'reason': reason or 'unknown'})
                            except Exception as _e:
                                failed_reasons.append({'date': d.isoformat(), 'reason': str(_e)})
                except Exception:
                    pass
                
                # set overall status after resume
                if any_success:
                    allocation.status = 'allocated'
                elif failed_reasons:
                    allocation.status = 'failed'
                else:
                    allocation.status = 'draft'
                allocation.save(update_fields=['status'])
                
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

                # capture old state
                old_name = allocation.therapy_name
                old_slot_id = getattr(allocation.timeslot, 'id', None)
                old_from_date = allocation.from_date
                old_to_date = allocation.to_date

                # optional timeslot update ("HH:MM" or slot_number)
                new_timeslot = None
                ts_val = payload.get('timeslot') or payload.get('slot')
                if ts_val:
                    try:
                        parts = str(ts_val).split(':')
                        if len(parts) == 2:
                            hh = int(parts[0]); mm = int(parts[1])
                            from_time = datetime.strptime(f"{hh:02d}:{mm:02d}", "%H:%M").time()
                            if SlotMaster is not None:
                                new_timeslot = SlotMaster.objects.filter(slot_time=from_time, is_active=True).first()
                        else:
                            if SlotMaster is not None:
                                new_timeslot = SlotMaster.objects.filter(slot_number=int(ts_val), is_active=True).first()
                    except Exception:
                        new_timeslot = None

                # Update therapy details
                therapy_name_changed = False
                if 'therapy_name' in payload:
                    new_name = payload['therapy_name']
                    if allocation.therapy_name != new_name:
                        therapy_name_changed = True
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
                if new_timeslot is not None:
                    allocation.timeslot = new_timeslot
                
                # Check if therapy code changed (might indicate nurse treatment change)
                if 'therapy_code' in payload:
                    allocation.therapy_code = payload['therapy_code']
                    therapy_name_changed = True  # Assume change if code changed

                # Handle date range changes (not just extensions)
                new_from_date = parse_date(payload.get('from_date') or '') if payload.get('from_date') else None
                new_to_date = parse_date(payload.get('to_date') or '') if payload.get('to_date') else None
                dates_changed = False
                
                if new_from_date and new_from_date != allocation.from_date:
                    allocation.from_date = new_from_date
                    dates_changed = True
                
                if new_to_date:
                    if new_to_date != allocation.to_date:
                        dates_changed = True
                    allocation.to_date = new_to_date
                    allocation.days = (allocation.to_date - allocation.from_date).days + 1

                # Delete bookings outside the new date range if dates changed
                if dates_changed:
                    # Get bookings that will be deleted
                    bookings_to_delete = Booking.objects.filter(
                        allocation=allocation
                    ).exclude(
                        date__gte=allocation.from_date,
                        date__lte=allocation.to_date
                    )
                    
                    # Cancel associated TherapistBooking and RoomBooking before deleting
                    if bookings_to_delete.exists():
                        try:
                            from Patient.models import TherapistBooking as TB, RoomBooking as RB
                            deleted_dates = list(bookings_to_delete.values_list('date', flat=True).distinct())
                            deleted_booking_ids = list(bookings_to_delete.values_list('id', flat=True))
                            
                            # Cancel TherapistBooking for deleted dates
                            TB.objects.filter(
                                visit=allocation,
                                date__in=deleted_dates,
                                status__in=['BOOKED','scheduled']
                            ).update(status='CANCELLED')
                            TB.objects.filter(
                                date__in=deleted_dates,
                                patient_id=allocation.patient.id,
                                status__in=['BOOKED','scheduled'],
                                visit__isnull=True
                            ).update(status='CANCELLED')
                            
                            # Cancel RoomBooking for deleted dates
                            RB.objects.filter(
                                therapy=allocation,
                                date__in=deleted_dates,
                                status__in=['BOOKED','scheduled']
                            ).update(status='CANCELLED')
                            RB.objects.filter(
                                visit_id__in=deleted_booking_ids,
                                status__in=['BOOKED','scheduled']
                            ).update(status='CANCELLED')
                            RB.objects.filter(
                                date__in=deleted_dates,
                                patient_id=allocation.patient.id,
                                status__in=['BOOKED','scheduled'],
                                therapy__isnull=True,
                                visit__isnull=True
                            ).update(status='CANCELLED')
                        except Exception as e:
                            print(f"Error canceling bookings for deleted dates: {e}")
                            pass
                    
                    # Now delete the bookings
                    bookings_to_delete.delete()

                allocation.save()

                # dynamic re-scheduling if name/slot changed for FinalScheduleRun dates
                try:
                    from .models import FinalScheduleRun
                    from final_allocation import expand_therapies_for_visit
                except Exception:
                    FinalScheduleRun = None
                    expand_therapies_for_visit = None

                name_changed = ('therapy_name' in payload) and (allocation.therapy_name != old_name)
                slot_changed = (new_timeslot is not None) and (getattr(new_timeslot, 'id', None) != old_slot_id)

                failed_reasons = []
                any_success = False
                date_change_success = False
                date_change_failed_reasons = []

                # Process re-allocation for dates where name/slot changed
                if (name_changed or slot_changed) and FinalScheduleRun and expand_therapies_for_visit:
                    # Process ALL dates in the NEW date range (not just old range)
                    for d in daterange(allocation.from_date, allocation.to_date):
                        # If final schedule not run for this date: keep draft and skip immediate allocation
                        if not FinalScheduleRun.objects.filter(run_date=d).exists():
                            try:
                                day_bookings = Booking.objects.filter(allocation=allocation, date=d)
                                # release therapist assignments for those bookings
                                BookingAssignment.objects.filter(booking__in=day_bookings).update(status='released')
                                # cancel external TherapistBooking/RoomBooking to free them up
                                from Patient.models import TherapistBooking as TB, RoomBooking as RB
                                day_timeslot = allocation.timeslot
                                if day_timeslot:
                                    # Cancel TherapistBooking
                                    TB.objects.filter(
                                        visit=allocation,
                                        date=d,
                                        time_slot=day_timeslot,
                                        status__in=['BOOKED','scheduled']
                                    ).update(status='CANCELLED')
                                    TB.objects.filter(
                                        date=d,
                                        time_slot=day_timeslot,
                                        patient_id=allocation.patient.id,
                                        status__in=['BOOKED','scheduled'],
                                        visit__isnull=True
                                    ).update(status='CANCELLED')
                                    # Cancel RoomBooking
                                    RB.objects.filter(
                                        therapy=allocation,
                                        date=d,
                                        time_slot=day_timeslot,
                                        status__in=['BOOKED','scheduled']
                                    ).update(status='CANCELLED')
                                    for booking in day_bookings:
                                        RB.objects.filter(
                                            visit=booking,
                                            date=d,
                                            time_slot=day_timeslot,
                                            status__in=['BOOKED','scheduled']
                                        ).update(status='CANCELLED')
                                    RB.objects.filter(
                                        date=d,
                                        time_slot=day_timeslot,
                                        patient_id=allocation.patient.id,
                                        status__in=['BOOKED','scheduled'],
                                        therapy__isnull=True,
                                        visit__isnull=True
                                    ).update(status='CANCELLED')
                                else:
                                    TB.objects.filter(visit=allocation, date=d, status__in=['BOOKED','scheduled']).update(status='CANCELLED')
                                    RB.objects.filter(therapy=allocation, date=d, status__in=['BOOKED','scheduled']).update(status='CANCELLED')
                                # put bookings back to draft, clear room and update to new timeslot
                                day_bookings.update(status='draft', timeslot=allocation.timeslot, room=None)
                                BookingItem.objects.filter(booking__in=day_bookings).update(status='draft')
                            except Exception as e:
                                print(f"Error updating draft bookings for date {d}: {e}")
                                pass
                            continue

                        # Release previous assignments/resources for this date and create fresh bookings
                        try:
                            day_bookings = Booking.objects.filter(allocation=allocation, date=d)
                            # release therapist assignments for those bookings
                            BookingAssignment.objects.filter(booking__in=day_bookings).update(status='released')
                            # cancel external TherapistBooking/RoomBooking
                            from Patient.models import TherapistBooking as TB, RoomBooking as RB
                            # Get the timeslot for this date
                            day_timeslot = allocation.timeslot
                            if day_timeslot:
                                # Cancel TherapistBooking: filter by visit (TherapyAllocation FK) or patient_id + date + timeslot
                                TB.objects.filter(
                                    visit=allocation,
                                    date=d,
                                    time_slot=day_timeslot,
                                    status__in=['BOOKED','scheduled']
                                ).update(status='CANCELLED')
                                # Also cancel by patient_id if visit FK is not set
                                TB.objects.filter(
                                    date=d,
                                    time_slot=day_timeslot,
                                    patient_id=allocation.patient.id,
                                    status__in=['BOOKED','scheduled'],
                                    visit__isnull=True
                                ).update(status='CANCELLED')
                                
                                # Cancel RoomBooking: filter by therapy (TherapyAllocation FK) or visit (Booking FK) or patient_id
                                # First via therapy FK
                                RB.objects.filter(
                                    therapy=allocation,
                                    date=d,
                                    time_slot=day_timeslot,
                                    status__in=['BOOKED','scheduled']
                                ).update(status='CANCELLED')
                                # Then via visit FK (Booking)
                                for booking in day_bookings:
                                    RB.objects.filter(
                                        visit=booking,
                                        date=d,
                                        time_slot=day_timeslot,
                                        status__in=['BOOKED','scheduled']
                                    ).update(status='CANCELLED')
                                # Also cancel by patient_id if neither FK is set
                                RB.objects.filter(
                                    date=d,
                                    time_slot=day_timeslot,
                                    patient_id=allocation.patient.id,
                                    status__in=['BOOKED','scheduled'],
                                    therapy__isnull=True,
                                    visit__isnull=True
                                ).update(status='CANCELLED')
                            else:
                                # If no timeslot, cancel all for this date and allocation
                                TB.objects.filter(
                                    visit=allocation,
                                    date=d,
                                    status__in=['BOOKED','scheduled']
                                ).update(status='CANCELLED')
                                RB.objects.filter(
                                    therapy=allocation,
                                    date=d,
                                    status__in=['BOOKED','scheduled']
                                ).update(status='CANCELLED')
                            
                            # Delete ALL old bookings for this date (they're for the old therapy)
                            # Ensure we delete all to avoid duplicates
                            booking_ids_to_delete = list(day_bookings.values_list('id', flat=True))
                            day_bookings.delete()
                            
                            # Double-check: Ensure no bookings exist for this date (safety check)
                            remaining_bookings = Booking.objects.filter(allocation=allocation, date=d)
                            if remaining_bookings.exists():
                                print(f"Warning: Found {remaining_bookings.count()} remaining bookings for date {d}, deleting...")
                                remaining_bookings.delete()
                            
                            # Create new booking with updated therapy details (only one per date)
                            new_booking = Booking.objects.create(
                                allocation=allocation,
                                date=d,
                                timeslot=allocation.timeslot,
                                room=None,
                                status='draft'
                            )
                            
                            # Create BookingItems from updated allocation.items_groups
                            items_groups = allocation.items_groups or []
                            for grp in items_groups:
                                grp_dosage = grp.get('dosage', '')
                                grp_uno = grp.get('uno', '')
                                for it in grp.get('items', []):
                                    BookingItem.objects.create(
                                        booking=new_booking,
                                        item_code=it.get('item_code') or it.get('id') or it.get('item_name', ''),
                                        item_name=it.get('item_name') or it.get('text') or '',
                                        dosage=it.get('dosage') or grp_dosage or '',
                                        uno=it.get('uno') or grp_uno or '',
                                        status='draft'
                                    )
                        except Exception as e:
                            print(f"Error releasing resources and creating new bookings for date {d}: {e}")
                            import traceback
                            traceback.print_exc()
                            pass

                        # Attempt re-allocation for this date with fresh bookings
                        try:
                            print(f"Running algorithm for allocation {allocation.id}, date {d} (name/slot changed, FinalScheduleRun exists)")
                            tasks = expand_therapies_for_visit(allocation.id, d.strftime('%Y-%m-%d'), create_bookings=True)
                            print(f"Algorithm returned: {tasks}")
                            # Only consider successful if ALL tasks are BOOKED (no FAILED tasks)
                            if isinstance(tasks, list):
                                booked_tasks = [t for t in tasks if t.get('status') == 'BOOKED']
                                failed_tasks = [t for t in tasks if t.get('status') == 'FAILED']
                                if booked_tasks and not failed_tasks:
                                    any_success = True
                                    Booking.objects.filter(allocation=allocation, date=d).update(status='scheduled')
                                    BookingItem.objects.filter(booking__allocation=allocation, booking__date=d).update(status='scheduled')
                                elif failed_tasks:
                                    # If any failed, mark as failed
                                    reason = failed_tasks[0].get('reason', 'unknown')
                                    print(f"Allocation had failures for date {d}: {reason}")
                                    Booking.objects.filter(allocation=allocation, date=d).update(status='failed')
                                    BookingItem.objects.filter(booking__allocation=allocation, booking__date=d).update(status='failed')
                            else:
                                reason = None
                                if isinstance(tasks, list):
                                    fails = [t for t in tasks if t.get('status') == 'FAILED']
                                    reason = fails[0].get('reason') if fails else 'allocation_failed'
                                elif isinstance(tasks, dict):
                                    reason = tasks.get('error')
                                failed_reasons.append({'date': d.isoformat(), 'reason': reason or 'unknown'})
                        except Exception as _e:
                            failed_reasons.append({'date': d.isoformat(), 'reason': str(_e)})

                    if any_success:
                        allocation.status = 'allocated'
                    elif failed_reasons:
                        allocation.status = 'failed'
                    allocation.save(update_fields=['status'])

                # Create draft bookings for any dates in the new range that don't have bookings
                if dates_changed or (name_changed or slot_changed):
                    for d in daterange(allocation.from_date, allocation.to_date):
                        if not Booking.objects.filter(allocation=allocation, date=d).exists():
                            booking = Booking.objects.create(
                                allocation=allocation, 
                                date=d, 
                                timeslot=allocation.timeslot, 
                                room=None, 
                                status='draft'
                            )
                            # Create BookingItems from allocation.items_groups
                            items_groups = allocation.items_groups or []
                            for grp in items_groups:
                                grp_dosage = grp.get('dosage', '')
                                grp_uno = grp.get('uno', '')
                                for it in grp.get('items', []):
                                    BookingItem.objects.create(
                                        booking=booking,
                                        item_code=it.get('item_code') or it.get('id') or it.get('item_name', ''),
                                        item_name=it.get('item_name') or it.get('text') or '',
                                        dosage=it.get('dosage') or grp_dosage or '',
                                        uno=it.get('uno') or grp_uno or '',
                                        status='draft'
                                    )
                
                # Auto-schedule new dates if FinalScheduleRun exists for them (even if name/slot didn't change)
                if dates_changed and FinalScheduleRun and expand_therapies_for_visit:
                    for d in daterange(allocation.from_date, allocation.to_date):
                        # Check if Final Schedule has already run for this date
                        if FinalScheduleRun.objects.filter(run_date=d).exists():
                            # Check if booking exists (create if it doesn't)
                            booking = Booking.objects.filter(allocation=allocation, date=d).first()
                            if not booking:
                                # Create booking if it doesn't exist
                                booking = Booking.objects.create(
                                    allocation=allocation,
                                    date=d,
                                    timeslot=allocation.timeslot,
                                    room=None,
                                    status='draft'
                                )
                                # Create BookingItems from allocation.items_groups
                                items_groups = allocation.items_groups or []
                                for grp in items_groups:
                                    grp_dosage = grp.get('dosage', '')
                                    grp_uno = grp.get('uno', '')
                                    for it in grp.get('items', []):
                                        BookingItem.objects.create(
                                            booking=booking,
                                            item_code=it.get('item_code') or it.get('id') or it.get('item_name', ''),
                                            item_name=it.get('item_name') or it.get('text') or '',
                                            dosage=it.get('dosage') or grp_dosage or '',
                                            uno=it.get('uno') or grp_uno or '',
                                            status='draft'
                                        )
                            
                            # Since we're updating the therapy, delete old booking and create fresh one
                            # Save booking details before deletion
                            old_booking_timeslot = booking.timeslot
                            old_booking_id = booking.id
                            
                            # Release assignments and cancel external bookings
                            BookingAssignment.objects.filter(booking=booking).update(status='released')
                            from Patient.models import TherapistBooking as TB, RoomBooking as RB
                            if old_booking_timeslot:
                                TB.objects.filter(
                                    visit=allocation,
                                    date=d,
                                    time_slot=old_booking_timeslot,
                                    status__in=['BOOKED','scheduled']
                                ).update(status='CANCELLED')
                                RB.objects.filter(
                                    therapy=allocation,
                                    date=d,
                                    time_slot=old_booking_timeslot,
                                    status__in=['BOOKED','scheduled']
                                ).update(status='CANCELLED')
                                RB.objects.filter(
                                    visit_id=old_booking_id,
                                    date=d,
                                    time_slot=old_booking_timeslot,
                                    status__in=['BOOKED','scheduled']
                                ).update(status='CANCELLED')
                            
                            # Delete ALL old bookings for this date (safety: delete all, not just one)
                            Booking.objects.filter(allocation=allocation, date=d).delete()
                            
                            # Double-check: Ensure no bookings exist for this date
                            remaining_bookings = Booking.objects.filter(allocation=allocation, date=d)
                            if remaining_bookings.exists():
                                print(f"Warning: Found {remaining_bookings.count()} remaining bookings for date {d}, deleting...")
                                remaining_bookings.delete()
                            
                            # Create fresh booking with updated therapy details (only one per date)
                            new_booking = Booking.objects.create(
                                allocation=allocation,
                                date=d,
                                timeslot=allocation.timeslot,
                                room=None,
                                status='draft'
                            )
                            
                            # Create BookingItems from updated allocation.items_groups
                            items_groups = allocation.items_groups or []
                            for grp in items_groups:
                                grp_dosage = grp.get('dosage', '')
                                grp_uno = grp.get('uno', '')
                                for it in grp.get('items', []):
                                    BookingItem.objects.create(
                                        booking=new_booking,
                                        item_code=it.get('item_code') or it.get('id') or it.get('item_name', ''),
                                        item_name=it.get('item_name') or it.get('text') or '',
                                        dosage=it.get('dosage') or grp_dosage or '',
                                        uno=it.get('uno') or grp_uno or '',
                                        status='draft'
                                    )
                            
                            # Now run algorithm with the fresh booking
                            try:
                                print(f"Running algorithm for allocation {allocation.id}, date {d} (FinalScheduleRun exists)")
                                # Run algorithm for this date
                                tasks = expand_therapies_for_visit(allocation.id, d.strftime('%Y-%m-%d'), create_bookings=True)
                                print(f"Algorithm returned: {tasks}")
                                # Only consider successful if ALL tasks are BOOKED (no FAILED tasks)
                                if isinstance(tasks, list):
                                    booked_tasks = [t for t in tasks if t.get('status') == 'BOOKED']
                                    failed_tasks = [t for t in tasks if t.get('status') == 'FAILED']
                                    if booked_tasks and not failed_tasks:
                                        date_change_success = True
                                        Booking.objects.filter(allocation=allocation, date=d).update(status='scheduled')
                                        BookingItem.objects.filter(booking__allocation=allocation, booking__date=d).update(status='scheduled')
                                        
                                        # Allocate nurses for nurse treatments
                                        try:
                                            from .nurse_allocation import reallocate_nurses_for_booking
                                            bookings = Booking.objects.filter(allocation=allocation, date=d, status='scheduled')
                                            for booking in bookings:
                                                reallocate_nurses_for_booking(booking)
                                        except Exception as nurse_e:
                                            print(f"Error allocating nurses for booking on date {d}: {nurse_e}")
                                        
                                        print(f"Successfully allocated for date {d}")
                                    else:
                                        reason = None
                                        if failed_tasks:
                                            reason = failed_tasks[0].get('reason', 'unknown')
                                        elif not booked_tasks:
                                            reason = 'allocation_failed'
                                        print(f"Allocation failed for date {d}: {reason}")
                                        date_change_failed_reasons.append({'date': d.isoformat(), 'reason': reason or 'unknown'})
                                        Booking.objects.filter(allocation=allocation, date=d).update(status='failed')
                                        BookingItem.objects.filter(booking__allocation=allocation, booking__date=d).update(status='failed')
                                elif isinstance(tasks, dict):
                                    reason = tasks.get('error', 'unknown')
                                    print(f"Allocation failed for date {d}: {reason}")
                                    date_change_failed_reasons.append({'date': d.isoformat(), 'reason': reason})
                                    Booking.objects.filter(allocation=allocation, date=d).update(status='failed')
                                    BookingItem.objects.filter(booking__allocation=allocation, booking__date=d).update(status='failed')
                            except Exception as _e:
                                print(f"Exception running algorithm for date {d}: {_e}")
                                import traceback
                                traceback.print_exc()
                                date_change_failed_reasons.append({'date': d.isoformat(), 'reason': str(_e)})
                                Booking.objects.filter(allocation=allocation, date=d).update(status='failed')
                    
                    # Update allocation status if any dates were processed
                    if date_change_success or date_change_failed_reasons:
                        if date_change_success:
                            allocation.status = 'allocated'
                        elif date_change_failed_reasons and not date_change_success:
                            allocation.status = 'failed'
                        allocation.save(update_fields=['status'])
                
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
                
                resp = {'status': 'ok', 'message': 'Therapy updated successfully'}
                if failed_reasons:
                    resp.update({'failed': failed_reasons})
                return JsonResponse(resp)
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
            try:
                # required fields (items_groups is optional - can be empty array)
                required = ['patient_reg_no', 'therapy_code', 'therapy_name', 'from_date', 'to_date']
                missing = [k for k in required if not payload.get(k)]
                if missing:
                    return JsonResponse({'error': 'missing_fields', 'missing': missing}, status=400)
                
                # items_groups is optional - default to empty array if not provided
                items_groups = payload.get('items_groups', [])
                if not isinstance(items_groups, list):
                    return JsonResponse({'error': 'items_groups must be a list'}, status=400)

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
                                timeslot_obj = SlotMaster.objects.filter(slot_time=from_time, is_active=True).first()
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
                raw_room_no = payload.get('patient_room_no') or ''
                resolved_room_no = get_staying_room_display_number(raw_room_no) or ''
                ps_defaults = {
                    'pat_name': payload.get('patient_name') or '',
                    'pat_age': payload.get('patient_age') or '',
                    'pat_sex': payload.get('patient_sex') or '',
                    'pat_room_no': resolved_room_no,
                    'pat_ref_id': payload.get('pat_ref_id') or payload.get('pat_ref_id') or ''
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
                if ps_defaults['pat_room_no'] and getattr(ps, 'pat_room_no', '') != ps_defaults['pat_room_no']:
                    ps.pat_room_no = ps_defaults['pat_room_no']; changed = True
                if ps_defaults['pat_ref_id'] and getattr(ps, 'pat_ref_id', '') != ps_defaults['pat_ref_id']:
                    ps.pat_ref_id = ps_defaults['pat_ref_id']; changed = True
                if changed:
                    ps.save(update_fields=['pat_name', 'pat_age', 'pat_sex', 'pat_room_no', 'pat_ref_id', 'updated_at'])

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
                        items_groups=items_groups,
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
                    # Track status counts for response
                    status_counts = {
                        'allocated': 0,
                        'failed': 0,
                        'draft': 0,
                        'cancelled': 0
                    }
                    date_status_map = {}  # Maps date to status for detailed breakdown
                    
                    for i in range((tdate - fdate).days + 1):
                        single_date = fdate + timedelta(days=i)
                        # Initially set all as draft
                        booking_status = 'draft'
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
                        date_status_map[single_date.isoformat()] = 'draft'
                        status_counts['draft'] += 1

                    # Check which dates have Final Schedule run - run algorithm for those dates immediately
                    # Other dates will remain in draft and can be scheduled via Final Schedule button in dashboard
                    try:
                        from .models import FinalScheduleRun
                        from final_allocation import expand_therapies_for_visit

                        any_succeeded = False
                        any_failed = False
                        
                        # Process each date in the range
                        for d in daterange(fdate, tdate):
                            # Check if Final Schedule has been run for this date
                            # If yes, run the algorithm immediately for this date
                            final_schedule_run = FinalScheduleRun.objects.filter(run_date=d).exists()
                            
                            # If Final Schedule run exists, run algorithm immediately
                            if final_schedule_run:
                                try:
                                    tasks = expand_therapies_for_visit(
                                        alloc.id,
                                        d.strftime('%Y-%m-%d'),
                                        create_bookings=True
                                    )
                                    if isinstance(tasks, list):
                                        booked_tasks = [t for t in tasks if t.get('status') == 'BOOKED']
                                        failed_tasks = [t for t in tasks if t.get('status') == 'FAILED']
                                        
                                        if booked_tasks:
                                            any_succeeded = True
                                            # Update booking status for this date
                                            Booking.objects.filter(allocation=alloc, date=d).update(status='scheduled')
                                            # Update booking items status for this date
                                            BookingItem.objects.filter(booking__allocation=alloc, booking__date=d).update(status='scheduled')
                                            status_counts['draft'] -= 1
                                            status_counts['allocated'] += 1
                                            date_status_map[d.isoformat()] = 'allocated'
                                        elif failed_tasks:
                                            any_failed = True
                                            Booking.objects.filter(allocation=alloc, date=d).update(status='failed')
                                            BookingItem.objects.filter(booking__allocation=alloc, booking__date=d).update(status='failed')
                                            status_counts['draft'] -= 1
                                            status_counts['failed'] += 1
                                            date_status_map[d.isoformat()] = 'failed'
                                    elif isinstance(tasks, dict) and 'error' in tasks:
                                        # Algorithm returned an error
                                        any_failed = True
                                        Booking.objects.filter(allocation=alloc, date=d).update(status='failed')
                                        BookingItem.objects.filter(booking__allocation=alloc, booking__date=d).update(status='failed')
                                        status_counts['draft'] -= 1
                                        status_counts['failed'] += 1
                                        date_status_map[d.isoformat()] = 'failed'
                                except Exception as _e:
                                    # Continue to next date on error
                                    print(f"Error processing date {d.isoformat()} for allocation {alloc.id}: {_e}")
                                    pass

                        # Update overall allocation status based on results
                        if any_succeeded:
                            alloc.status = 'allocated'
                            alloc.save(update_fields=['status'])
                        elif any_failed and not any_succeeded:
                            alloc.status = 'failed'
                            alloc.save(update_fields=['status'])
                        else:
                            alloc.status = 'draft'
                            alloc.save(update_fields=['status'])
                    except Exception as e:
                        # Keep as draft if auto-scheduling fails
                        alloc.status = 'draft'
                        alloc.save(update_fields=['status'])
                        print(f"Automatic scheduling check failed for allocation {alloc.id}: {e}")

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

                    # COMMENTED OUT DUE TO WEBSOCKET ERRORS
                    # try:
                    #     if NotificationQueue is not None and (payload.get('procured') or payload.get('procured_from')):
                    #         # queue a procurement notification aggregated for the allocation
                    #         NotificationQueue.objects.create(target_type='procurement', target_identifier=payload.get('procured') or payload.get('procured_from'), channel='internal', payload={'allocation_id': alloc.pk}, status='queued')
                    # except Exception:
                    #     pass

                    # Build status summary for response
                    status_summary = {}
                    if status_counts['allocated'] > 0:
                        status_summary['allocated'] = status_counts['allocated']
                    if status_counts['failed'] > 0:
                        status_summary['failed'] = status_counts['failed']
                    if status_counts['cancelled'] > 0:
                        status_summary['cancelled'] = status_counts['cancelled']
                    if status_counts['draft'] > 0:
                        status_summary['draft'] = status_counts['draft']
                    
                    return JsonResponse({
                        'status': 'ok', 
                        'allocation_id': alloc.pk, 
                        'bookings_created': len(bookings_created),
                        'status_counts': status_counts,
                        'status_summary': status_summary,
                        'date_status_map': date_status_map,
                        'overall_status': alloc.status
                    }, status=201)
                except IntegrityError as e:
                    return JsonResponse({'error': 'conflict', 'details': str(e)}, status=409)
            except Exception as e:
                import traceback
                error_trace = traceback.format_exc()
                print(f"Error in allocate action: {e}")
                print(error_trace)
                return JsonResponse({'error': str(e), 'type': type(e).__name__}, status=500)

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


    # search therapies (includes both TherapyMaster and NurseTreatmentMaster)
    if action == 'search_therapies':
        q = (request.GET.get('q') or '').strip()
        results = []
        
        # Add regular therapies from TherapyMaster
        if TherapyMaster is not None:
            qs = TherapyMaster.objects.filter(is_active=True).all()  # Use local master table
            if q:
                qs = qs.filter(Q(therapy_name__icontains=q) | Q(therapy_code__icontains=q))
            qs = qs[:50]
            for t in qs:
                results.append({
                    'therapy_code': getattr(t, 'therapy_code', ''),
                    'therapy_name': getattr(t, 'therapy_name', ''),
                    'therapy_category': getattr(t, 'therapy_category', '') or ''
                })
        
        # Add nurse treatments from NurseTreatmentMaster
        if NurseTreatmentMaster is not None:
            qs = NurseTreatmentMaster.objects.filter(is_active=True).all()
            if q:
                qs = qs.filter(Q(name__icontains=q) | Q(treatment_code__icontains=q))
            qs = qs[:50]
            for nt in qs:
                results.append({
                    'therapy_code': getattr(nt, 'treatment_code', ''),
                    'therapy_name': getattr(nt, 'name', ''),
                    'therapy_category': 'Nurse Treatment'  # Mark as nurse treatment
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
                    start = getattr(s, 'slot_time', '')
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
        
        # Calculate status counts
        status_counts = {
            'allocated': 0,
            'failed': 0,
            'draft': 0,
            'cancelled': 0,
            'scheduled': 0
        }
        
        out = {
            'allocation_id': alloc.pk,
            'therapy_name': alloc.therapy_name,
            'from_date': alloc.from_date.isoformat(),
            'to_date': alloc.to_date.isoformat(),
            'overall_status': alloc.status,
            'bookings': [],
            'status_counts': status_counts,
            'date_status_map': {}
        }
        
        # iterate booking objects if present (field names may vary; using related_name 'bookings' expected)
        for b in alloc.bookings.all().order_by('date'):
            booking_status = getattr(b, 'status', 'draft')
            
            # Count statuses (map 'scheduled' to 'allocated' for consistency)
            if booking_status == 'scheduled':
                # Count as both 'allocated' (for display) and 'scheduled' (for detailed counts)
                status_counts['allocated'] += 1
                status_counts['scheduled'] += 1
            elif booking_status in status_counts:
                status_counts[booking_status] += 1
            
            items = []
            try:
                for it in b.items.all():
                    items.append({'id': it.pk, 'item_code': it.item_code, 'item_name': it.item_name, 'status': it.status})
            except Exception:
                items = []
            therapists = []
            try:
                # Pre-fetch all TherapistBooking records to avoid N+1 queries
                # Use visit (TherapyAllocation) to match TherapistBooking records
                therapist_bookings = {}
                try:
                    from Patient.models import TherapistBooking
                    from masters.models import TherapistMaster
                    # Get allocation (visit) for this booking
                    allocation = b.allocation
                    # Get all therapist codes for this booking
                    therapist_codes = [a.therapist.therapist_code for a in b.assignments.all()]
                    # Get all TherapistMaster records
                    therapist_masters = {tm.therapist_code: tm for tm in TherapistMaster.objects.filter(
                        therapist_code__in=therapist_codes
                    )}
                    # Get all TherapistBooking records for this visit and therapists
                    if therapist_masters and allocation:
                        tb_list = TherapistBooking.objects.filter(
                            visit=allocation,
                            therapist__in=therapist_masters.values(),
                            status='BOOKED'
                        ).select_related('therapist', 'visit')
                        # Create a map: therapist_code -> is_bathing
                        # ONLY use TherapistBooking.is_bathing field from Patient module
                        for tb in tb_list:
                            if tb.therapist:
                                therapist_bookings[tb.therapist.therapist_code] = tb.is_bathing  # Direct access to is_bathing field
                except Exception as e:
                    print(f"Error pre-fetching TherapistBooking records: {e}")
                    import traceback
                    traceback.print_exc()
                
                for a in b.assignments.all():
                    therapist_name = getattr(a.therapist, 'therapist_name', '') or getattr(a.therapist, 'therapist_code', '') or getattr(a.therapist, 'id', '')
                    # Get is_bathing flag from pre-fetched data
                    is_bathing = therapist_bookings.get(a.therapist.therapist_code, False)
                    
                    therapists.append({
                        'name': therapist_name,
                        'code': getattr(a.therapist, 'therapist_code', None),
                        'is_bathing': bool(is_bathing)
                    })
            except Exception:
                therapists = []
            
            # Get nurses for this booking
            nurses = []
            try:
                for na in b.nurse_assignments.filter(status='assigned'):
                    nurse_name = getattr(na.nurse, 'nurse_name', '') or getattr(na.nurse, 'nurse_code', '') or ''
                    if nurse_name:
                        nurses.append(nurse_name)
            except Exception:
                nurses = []
            
            slot_s = ''
            try:
                slot_s = b.timeslot.slot_time.strftime('%H:%M') if getattr(b, 'timeslot', None) and getattr(b.timeslot, 'slot_time', None) else ''
            except Exception:
                slot_s = ''
            
            # Get patient room number (staying room) - mapped from StayingRoom
            patient_room_no = None
            if alloc.patient.pat_room_no:
                # Use the global import from line 15
                patient_room_no = get_staying_room_display_number(alloc.patient.pat_room_no)
            
            # Check if this is a nurse treatment
            from .nurse_allocation import is_nurse_treatment
            is_nurse_treatment_flag = is_nurse_treatment(alloc.therapy_code, alloc.therapy_name) is not None
            
            # Map scheduled to allocated for display consistency
            display_status = 'allocated' if booking_status == 'scheduled' else booking_status
            out['date_status_map'][b.date.isoformat()] = display_status
            
            out['bookings'].append({
                'booking_id': b.pk,
                'date': b.date.isoformat(),
                'slot': slot_s,
                'room': getattr(b.room, 'room_no', None),
                'patient_room_no': patient_room_no,
                'therapists': therapists,
                'nurses': nurses,
                'is_nurse_treatment': is_nurse_treatment_flag,
                'status': booking_status,
                'display_status': display_status,
                'items': items
            })
        
        # Add is_nurse_treatment flag to the main response
        out['is_nurse_treatment'] = is_nurse_treatment_flag
        
        # Build status summary (only include non-zero counts)
        # Note: 'scheduled' bookings are counted in both 'allocated' and 'scheduled' in status_counts.
        # For summary, we use 'allocated' count (which includes scheduled bookings) to avoid double-counting.
        status_summary = {}
        # Use 'allocated' count which already includes all scheduled bookings
        if status_counts['allocated'] > 0:
            status_summary['allocated'] = status_counts['allocated']
        if status_counts['failed'] > 0:
            status_summary['failed'] = status_counts['failed']
        if status_counts['cancelled'] > 0:
            status_summary['cancelled'] = status_counts['cancelled']
        if status_counts['draft'] > 0:
            status_summary['draft'] = status_counts['draft']
        
        out['status_summary'] = status_summary
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
                # Calculate status counts from bookings
                status_counts = {
                    'allocated': 0,
                    'scheduled': 0,
                    'failed': 0,
                    'draft': 0,
                    'cancelled': 0
                }
                for b in a.bookings.all():
                    booking_status = getattr(b, 'status', 'draft')
                    if booking_status == 'scheduled':
                        status_counts['allocated'] += 1
                        status_counts['scheduled'] += 1
                    elif booking_status in status_counts:
                        status_counts[booking_status] += 1
                
                # Build status summary (only include non-zero counts)
                # Note: 'scheduled' bookings are counted in both 'allocated' and 'scheduled' in status_counts.
                # For summary, we use 'allocated' count (which includes scheduled bookings) to avoid double-counting.
                status_summary = {}
                # Use 'allocated' count which already includes all scheduled bookings
                if status_counts['allocated'] > 0:
                    status_summary['allocated'] = status_counts['allocated']
                if status_counts['failed'] > 0:
                    status_summary['failed'] = status_counts['failed']
                if status_counts['cancelled'] > 0:
                    status_summary['cancelled'] = status_counts['cancelled']
                if status_counts['draft'] > 0:
                    status_summary['draft'] = status_counts['draft']
                
                # Get slot time in HH:MM format
                slot_value = ''
                if a.timeslot and hasattr(a.timeslot, 'slot_time'):
                    slot_value = a.timeslot.slot_time.strftime('%H:%M')
                
                out.append({
                    'allocation_id': a.pk,
                    'therapy_code': a.therapy_code,
                    'therapy_name': a.therapy_name,
                    'ext_int': a.ext_int,
                    'slot': slot_value,
                    'oil_class': a.oil_class,
                    'usage': a.usage,
                    'procured': a.procured_from,
                    'from_date': a.from_date.isoformat(),
                    'to_date': a.to_date.isoformat(),
                    'days': a.days,
                    'items_groups': a.items_groups or [],
                    'status': a.status,
                    'status_counts': status_counts,
                    'status_summary': status_summary
                })
            return JsonResponse(out, safe=False)

        # fallback if you still have any other model (PatientTherapy)
        if PatientTherapy is not None:
            out = []
            try:
                qs = PatientTherapy.objects.filter(patient__pat_reg_no=reg)[:200]
                for pt in qs:
                    # Get slot value - handle both slot_time and start_time for backward compatibility
                    slot_val = ''
                    if hasattr(pt, 'slot') and pt.slot:
                        if hasattr(pt.slot, 'slot_time'):
                            slot_val = pt.slot.slot_time.strftime('%H:%M') if pt.slot.slot_time else ''
                        elif hasattr(pt.slot, 'start_time'):
                            slot_val = pt.slot.start_time.strftime('%H:%M') if pt.slot.start_time else ''
                        else:
                            slot_val = str(getattr(pt, 'slot', ''))
                    
                    out.append({
                        'therapy_code': getattr(pt, 'therapy_code', getattr(pt, 'therapy_id', '')),
                        'therapy_name': getattr(pt, 'therapy_name', '') or str(getattr(pt, 'therapy', '')),
                        'ext_int': getattr(pt, 'ext_int', ''),
                        'slot': slot_val,
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
                raw_room_no = payload.get('patient_room_no', '')
                resolved_room_no = get_staying_room_display_number(raw_room_no) if raw_room_no else ''
                ps, created = PatientSnapshot.objects.get_or_create(
                    pat_reg_no=str(patient_reg_no),
                    defaults={
                        'pat_name': payload.get('patient_name', ''),
                        'pat_age': payload.get('patient_age', ''),
                        'pat_sex': payload.get('patient_sex', ''),
                        'pat_room_no': resolved_room_no,
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
                if resolved_room_no and ps.pat_room_no != resolved_room_no:
                    ps.pat_room_no = resolved_room_no; changed = True
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
                
                # Create PrescriptionScheduling records for each date in the range (similar to Booking for therapies)
                from .models import PrescriptionScheduling
                from datetime import timedelta
                
                current_date = from_date
                while current_date <= to_date:
                    # Get or create PrescriptionScheduling for this date
                    PrescriptionScheduling.objects.get_or_create(
                        patient=ps,
                        prescription_date=current_date,
                        defaults={
                            'doctor': request.user if request.user.is_authenticated else None,
                            'status': 'draft'
                        }
                    )
                    current_date += timedelta(days=1)
                
                # Create notification - COMMENTED OUT TEMPORARILY DUE TO NETWORK ERRORS
                # create_prescription_notification(allocation, 'prescription_allocated', request.user, {
                #     'bookings_created': (to_date - from_date).days + 1
                # })
                
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
                
                # Create notification - COMMENTED OUT TEMPORARILY DUE TO NETWORK ERRORS
                # create_prescription_notification(allocation, 'prescription_cancelled', request.user, {
                #     'cancel_from': cancel_from,
                #     'cancel_to': cancel_to,
                #     'reason': reason
                # })
                
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
                
                # Create notification - COMMENTED OUT TEMPORARILY DUE TO NETWORK ERRORS
                # create_prescription_notification(allocation, 'prescription_resumed', request.user, {
                #     'resume_from': resume_from,
                #     'resume_to': resume_to
                # })
                
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
                items_changed = False
                if prescription_name:
                    allocation.prescription_name = prescription_name
                if items_groups:
                    # Compare old and new items_groups to detect changes
                    old_items_groups = old_data.get('items_groups', [])
                    import json
                    # Normalize for comparison
                    old_normalized = json.dumps(old_items_groups, sort_keys=True) if old_items_groups else ''
                    new_normalized = json.dumps(items_groups, sort_keys=True) if items_groups else ''
                    if old_normalized != new_normalized:
                        items_changed = True
                    allocation.items_groups = items_groups
                if procured_from is not None:
                    allocation.procured_from = procured_from
                if notes is not None:
                    allocation.notes = notes
                
                allocation.save()
                
                # Create notification - COMMENTED OUT TEMPORARILY DUE TO NETWORK ERRORS
                # create_prescription_notification(allocation, 'prescription_updated', request.user, {
                #     'changes': 'Prescription details updated'
                # })
                
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
                
                # Create PrescriptionChangeLog entry for item updates
                if items_changed:
                    from .models import PrescriptionChangeLog
                    from django.utils import timezone as tz
                    from datetime import timedelta
                    
                    # Get all dates in the allocation range
                    date_range = []
                    current_date = allocation.from_date
                    while current_date <= allocation.to_date:
                        date_range.append(current_date)
                        current_date += timedelta(days=1)
                    
                    # Create change log entries for each date in the range
                    for date in date_range:
                        PrescriptionChangeLog.objects.create(
                            patient=allocation.patient,
                            prescription_date=date,
                            action='update',
                            changed_by=request.user if request.user.is_authenticated else None,
                            before_values={'items_groups': old_data.get('items_groups', [])},
                            after_values={'items_groups': items_groups},
                            description=f'Prescription items updated for {allocation.prescription_name}'
                        )
                
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
                    for p in Procured.objects.filter(is_active=True).order_by('name')[:200]:
                        results.append({'name': getattr(p, 'name', '')})
                except Exception:
                    pass
        elif master_type == 'oil':
            if OilClass is not None:
                try:
                    for o in OilClass.objects.filter(is_active=True).order_by('name')[:200]:
                        results.append({'name': getattr(o, 'name', '')})
                except Exception:
                    pass
        elif master_type == 'usage':
            if UsageType is not None:
                try:    
                    for u in UsageType.objects.filter(is_active=True).order_by('name')[:200]:
                        results.append({'name': getattr(u, 'name', '')})
                except Exception:
                    pass
        elif master_type in ('prescriptiontime', 'ptime'):
            if PrescriptionTime is not None:
                try:
                    for t in PrescriptionTime.objects.filter(is_active=True).order_by('name')[:200]:
                        results.append({'name': getattr(t, 'name', '')})
                except Exception:
                    pass
        elif master_type in ('prescriptionscope', 'scope'):
            if PrescriptionScope is not None:
                try:
                    for s in PrescriptionScope.objects.filter(is_active=True).order_by('name')[:200]:
                        results.append({'name': getattr(s, 'name', '')})
                except Exception:
                    pass
        elif master_type == 'ingredient':
            if IngredientMaster is not None:
                try:
                    for ing in IngredientMaster.objects.filter(is_active=True).order_by('ingredient_name')[:200]:
                        results.append({
                            'id': ing.id,
                            'ingredient_name': getattr(ing, 'ingredient_name', ''),
                            'ingredient_code': getattr(ing, 'ingredient_code', '')
                        })
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
        
        # Send notification to target roles - COMMENTED OUT DUE TO WEBSOCKET ERRORS
        # notification.send_to_roles(target_roles)
        
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
                raw_room_no = payload.get('patient_room_no', '')
                resolved_room_no = get_staying_room_display_number(raw_room_no) if raw_room_no else ''
                ps, created = PatientSnapshot.objects.get_or_create(
                    pat_reg_no=str(patient_reg_no),
                    defaults={
                        'pat_name': payload.get('patient_name', ''),
                        'pat_age': payload.get('patient_age', ''),
                        'pat_sex': payload.get('patient_sex', ''),
                        'pat_room_no': resolved_room_no,
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
                if resolved_room_no and ps.pat_room_no != resolved_room_no:
                    ps.pat_room_no = resolved_room_no; changed = True
                if payload.get('patient_ref_id') and ps.pat_ref_id != payload.get('patient_ref_id'):
                    ps.pat_ref_id = payload.get('patient_ref_id'); changed = True
                if changed: ps.save()
                
                # Create prescription allocation
                from_date_parsed = parse_date(from_date)
                to_date_parsed = parse_date(to_date)
                
                allocation = PrescriptionAllocation.objects.create(
                    patient=ps,
                    prescription_name=prescription_name,
                    items_groups=json.dumps(items_groups),
                    procured_from=procured_from,
                    from_date=from_date_parsed,
                    to_date=to_date_parsed,
                    days=days,
                    allocated_by=request.user if request.user.is_authenticated else None,
                    status='draft'  # Default status
                )
                
                # Create PrescriptionScheduling records for each date in the range (similar to Booking for therapies)
                from .models import PrescriptionScheduling
                from datetime import timedelta
                
                current_date = from_date_parsed
                while current_date <= to_date_parsed:
                    # Get or create PrescriptionScheduling for this date
                    PrescriptionScheduling.objects.get_or_create(
                        patient=ps,
                        prescription_date=current_date,
                        defaults={
                            'doctor': request.user if request.user.is_authenticated else None,
                            'status': 'draft'
                        }
                    )
                    current_date += timedelta(days=1)
                
                # Update patient snapshot
                ps.prescription_count = PrescriptionAllocation.objects.filter(patient=ps).count()
                ps.last_prescription_date = allocation.from_date
                ps.save()
                
                # Create notification - COMMENTED OUT DUE TO WEBSOCKET ERRORS
                # create_prescription_notification(allocation, 'prescription_allocated', request.user)
                
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
                
                # Create notification - COMMENTED OUT DUE TO WEBSOCKET ERRORS
                # create_prescription_notification(allocation, 'prescription_cancelled', request.user, {
                #     'cancel_from': cancel_from,
                #     'cancel_to': cancel_to,
                #     'reason': reason
                # })
                
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
                
                # Create notification - COMMENTED OUT TEMPORARILY DUE TO NETWORK ERRORS
                # create_prescription_notification(allocation, 'prescription_resumed', request.user, {
                #     'resume_from': resume_from,
                #     'resume_to': resume_to
                # })
                
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

                # Capture old state for change log
                old_data = {
                    'prescription_name': allocation.prescription_name,
                    'items_groups': allocation.items_groups,
                    'procured_from': allocation.procured_from,
                    'from_date': allocation.from_date.isoformat() if allocation.from_date else None,
                    'to_date': allocation.to_date.isoformat() if allocation.to_date else None,
                    'days': allocation.days,
                    'notes': allocation.notes
                }

                # Normalize existing items_groups to list for comparison
                import json as _json
                old_items_groups = allocation.items_groups
                if isinstance(old_items_groups, str):
                    try:
                        old_items_groups = _json.loads(old_items_groups) if old_items_groups else []
                    except Exception:
                        old_items_groups = []

                # Update fields
                items_changed = False
                if prescription_name:
                    allocation.prescription_name = prescription_name
                if items_groups is not None and items_groups != []:
                    # Compare old and new groups (normalize for comparison)
                    try:
                        old_norm = _json.dumps(old_items_groups, sort_keys=True) if old_items_groups else ''
                        new_norm = _json.dumps(items_groups, sort_keys=True) if items_groups else ''
                        items_changed = (old_norm != new_norm)
                    except Exception:
                        items_changed = True
                    allocation.items_groups = items_groups  # store as JSON (list), not string
                if procured_from:
                    allocation.procured_from = procured_from
                if from_date:
                    allocation.from_date = parse_date(from_date)
                if to_date:
                    allocation.to_date = parse_date(to_date)
                if days:
                    allocation.days = days

                allocation.save()

                # Log audit
                log_prescription_audit(request.user, 'update_prescription', 'PrescriptionAllocation', str(allocation.id), {
                    'old_data': old_data,
                    'new_data': {
                        'prescription_name': allocation.prescription_name,
                        'items_groups': allocation.items_groups,
                        'procured_from': allocation.procured_from,
                        'from_date': allocation.from_date.isoformat() if allocation.from_date else None,
                        'to_date': allocation.to_date.isoformat() if allocation.to_date else None,
                        'days': allocation.days,
                        'notes': allocation.notes
                    }
                })

                # Create PrescriptionChangeLog entry for item updates (cover each date in range)
                if items_changed:
                    from .models import PrescriptionChangeLog
                    from datetime import timedelta

                    # Build date range
                    date_range = []
                    current_date = allocation.from_date
                    while current_date and allocation.to_date and current_date <= allocation.to_date:
                        date_range.append(current_date)
                        current_date += timedelta(days=1)
                    if not date_range and allocation.from_date:
                        date_range = [allocation.from_date]

                    for d in date_range:
                        PrescriptionChangeLog.objects.create(
                            patient=allocation.patient,
                            prescription_date=d,
                            action='update',
                            changed_by=request.user if request.user.is_authenticated else None,
                            before_values={'items_groups': old_items_groups},
                            after_values={'items_groups': allocation.items_groups},
                            description=f'Prescription items updated for {allocation.prescription_name}'
                        )

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
        elif master_type in ('usage', 'usagetype'):
            if UsageType is not None:
                try:
                    for u in UsageType.objects.filter(is_active=True).order_by('name')[:200]:
                        results.append({'name': getattr(u, 'name', '')})
                except Exception:
                    pass
        elif master_type in ('prescriptionusage', 'prescription_usage'):
            PrescriptionUsage = get_model_safe('masters', 'PrescriptionUsage')
            if PrescriptionUsage is not None:
                try:
                    for u in PrescriptionUsage.objects.filter(is_active=True).order_by('name')[:200]:
                        results.append({'name': getattr(u, 'name', '')})
                except Exception:
                    pass
        elif master_type in ('prescriptiontime', 'ptime'):
            if PrescriptionTime is not None:
                try:
                    for t in PrescriptionTime.objects.filter(is_active=True)[:20]:
                        results.append({'name': getattr(t, 'name', '')})
                except Exception:
                    pass
        elif master_type in ('prescriptionscope', 'scope'):
            if PrescriptionScope is not None:
                try:
                    for s in PrescriptionScope.objects.filter(is_active=True)[:20]:
                        results.append({'name': getattr(s, 'name', '')})
                except Exception:
                    pass
        elif master_type == 'ingredient':
            if IngredientMaster is not None:
                try:
                    for ing in IngredientMaster.objects.filter(is_active=True).order_by('ingredient_name')[:200]:
                        results.append({
                            'id': ing.id,
                            'ingredient_name': getattr(ing, 'ingredient_name', ''),
                            'ingredient_code': getattr(ing, 'ingredient_code', '')
                        })
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
            
            # Import PrescriptionScheduling to calculate status counts
            from .models import PrescriptionScheduling
            
            results = []
            for p in prescriptions:
                # Calculate status counts from PrescriptionScheduling for dates within this allocation's range
                status_counts = {
                    'draft': 0,
                    'scheduled': 0,
                    'dispatched': 0,
                    'active': 0,
                    'cancelled': 0,
                    'failed': 0
                }
                
                if p.from_date and p.to_date:
                    # Get PrescriptionScheduling records for this patient within the allocation date range
                    from datetime import timedelta
                    scheduling_records = PrescriptionScheduling.objects.filter(
                        patient=patient,
                        prescription_date__gte=p.from_date,
                        prescription_date__lte=p.to_date
                    )
                    
                    for ps in scheduling_records:
                        if ps.status in status_counts:
                            status_counts[ps.status] += 1
                    
                    # Also count the allocation status itself
                    if p.status in ['active', 'cancelled', 'failed']:
                        status_counts[p.status] += 1
                
                # Build status summary (only include non-zero counts)
                status_summary = {}
                if status_counts['draft'] > 0:
                    status_summary['draft'] = status_counts['draft']
                if status_counts['active'] > 0:
                    status_summary['active'] = status_counts['active']
                if status_counts['scheduled'] > 0:
                    status_summary['scheduled'] = status_counts['scheduled']
                if status_counts['dispatched'] > 0:
                    status_summary['dispatched'] = status_counts['dispatched']
                if status_counts['failed'] > 0:
                    status_summary['failed'] = status_counts['failed']
                if status_counts['cancelled'] > 0:
                    status_summary['cancelled'] = status_counts['cancelled']
                
                results.append({
                    'id': p.id,
                    'allocation_id': p.id,
                    'prescription_name': p.prescription_name,
                    'items_groups': p.items_groups if isinstance(p.items_groups, (list, dict)) else (json.loads(p.items_groups) if p.items_groups else []),
                    'procured_from': p.procured_from,
                    'scope': getattr(p, 'scope', ''),
                    'from_date': p.from_date.isoformat() if p.from_date else None,
                    'to_date': p.to_date.isoformat() if p.to_date else None,
                    'days': p.days,
                    'status': p.status,
                    'status_counts': status_counts,
                    'status_summary': status_summary,
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
        
        # Send notification to target roles - COMMENTED OUT DUE TO WEBSOCKET ERRORS
        # notification.send_to_roles(target_roles)
        
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
    # items_groups is optional - can be empty array
    required = ["patient_reg_no", "therapy_code", "therapy_name", "from_date", "to_date"]
    missing = [k for k in required if k not in payload]
    if missing:
        return JsonResponse({"error": "Missing required fields", "missing": missing}, status=400)
    
    # parse dates
    from_date = parse_date(payload["from_date"])
    to_date = parse_date(payload["to_date"])
    if not from_date or not to_date or from_date > to_date:
        return JsonResponse({"error": "Invalid from_date / to_date"}, status=400)

    # Check if this is a nurse treatment early
    from .nurse_allocation import is_nurse_treatment
    nurse_treatment = is_nurse_treatment(payload.get("therapy_code"), payload.get("therapy_name"))
    
    # timeslot: accept either slot_number (int) or "HH:MM" string
    # For nurse treatments, timeslot is optional (they work entire day)
    timeslot = None
    if not nurse_treatment:  # Only require timeslot for regular therapies
        if payload.get("timeslot_slot_number") is not None:
            try:
                timeslot = SlotMaster.objects.get(slot_number=int(payload["timeslot_slot_number"]), is_active=True)  # Use local master table
            except SlotMaster.DoesNotExist:
                return JsonResponse({"error": "Slot with that slot_number not found"}, status=400)
        elif payload.get("timeslot"):
            t = parse_time_hhmm(payload["timeslot"])
            if not t:
                return JsonResponse({"error": "Invalid timeslot format, expected HH:MM"}, status=400)
            timeslot = SlotMaster.objects.filter(slot_time=t, is_active=True).first()  # Use local master table
            if not timeslot:
                # Optionally create a timeslot if you want; for safety we require an existing one:
                return JsonResponse({"error": "TimeSlot with that slot_time not found"}, status=400)
    else:
        # For nurse treatments, timeslot is optional - use if provided, but not required
        if payload.get("timeslot_slot_number") is not None:
            try:
                timeslot = SlotMaster.objects.get(slot_number=int(payload["timeslot_slot_number"]), is_active=True)
            except SlotMaster.DoesNotExist:
                timeslot = None  # Don't fail, just set to None
        elif payload.get("timeslot"):
            t = parse_time_hhmm(payload["timeslot"])
            if t:
                timeslot = SlotMaster.objects.filter(slot_time=t, is_active=True).first()

    # room (optional for both regular and nurse treatments)
    room = None
    room_no = payload.get("room_no")  # optional string
    if room_no:
        room = TreatmentRoom.objects.filter(room_no=room_no).first()
        if not room:
            return JsonResponse({"error": f"TreatmentRoom {room_no} not found"}, status=400)

    # therapists: optional list of therapist_codes that should be assigned for every date
    # Skip therapist allocation for nurse treatments (already checked above)
    therapist_codes = payload.get("therapists") or []
    therapists = []
    if not nurse_treatment and therapist_codes:  # Only check therapists for non-nurse treatments
        therapists_qs = Therapist.objects.filter(therapist_code__in=therapist_codes)
        found_codes = set(t.therapist_code for t in therapists_qs)
        missing_ts = [c for c in therapist_codes if c not in found_codes]
        if missing_ts:
            return JsonResponse({"error": "Some therapists not found", "missing_therapists": missing_ts}, status=400)
        therapists = list(therapists_qs)

    # items_groups expected as list of groups (can be empty):
    # [{ "items":[{"item_code":"KAS","item_name":"Kashayam"}, ...], "dosage":"10 ml", "uno":"1" }, ...]
    # items_groups is optional - can be empty array (already set above)
    if not isinstance(items_groups, list):
        return JsonResponse({"error": "items_groups must be a list"}, status=400)

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

            # Auto-schedule for any dates within the range that already had Final Schedule run
            try:
                from .models import FinalScheduleRun
                from final_allocation import expand_therapies_for_visit
                from .nurse_allocation import allocate_nurses_for_booking

                any_succeeded = False
                for d in daterange(from_date, to_date):
                    if FinalScheduleRun.objects.filter(run_date=d).exists():
                        try:
                            tasks = expand_therapies_for_visit(
                                allocation.id,
                                d.strftime('%Y-%m-%d'),
                                create_bookings=True
                            )
                            if isinstance(tasks, list) and any(t.get('status') == 'BOOKED' for t in tasks):
                                any_succeeded = True
                                
                                # Allocate nurses for nurse treatments on this date
                                from .models import Booking
                                bookings = Booking.objects.filter(
                                    allocation=allocation,
                                    date=d,
                                    status__in=['scheduled', 'draft']
                                )
                                for booking in bookings:
                                    try:
                                        allocate_nurses_for_booking(booking)
                                    except Exception as nurse_e:
                                        print(f"Error allocating nurses for booking {booking.id}: {nurse_e}")
                        except Exception as _e:
                            # continue to next date
                            pass

                allocation.status = 'allocated' if any_succeeded else 'draft'
                allocation.save(update_fields=['status'])
            except Exception as e:
                allocation.status = 'draft'
                allocation.save(update_fields=['status'])
                print(f"Automatic scheduling check failed for allocation {allocation.id}: {e}")

            # nurse_treatment already checked above
            
            created_bookings = []
            notifications_to_enqueue = []

            # iterate dates and create Booking, BookingItem, BookingAssignment
            for d in daterange(from_date, to_date):
                # For nurse treatments, status starts as 'scheduled' (no therapist allocation needed)
                # For regular therapies, status starts as 'draft' (will be scheduled by final schedule)
                initial_status = "scheduled" if nurse_treatment else "draft"
                
                # create booking (UniqueConstraint on room/date/timeslot will guard)
                booking = Booking.objects.create(
                    allocation=allocation,
                    date=d,
                    timeslot=timeslot,
                    room=room,
                    status=initial_status
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

                # For nurse treatments, allocate nurses instead of therapists
                if nurse_treatment:
                    try:
                        from .nurse_allocation import allocate_nurses_for_booking
                        nurse_assignments = allocate_nurses_for_booking(booking)
                        nurse_codes = [na.nurse.nurse_code for na in nurse_assignments] if nurse_assignments else []
                    except Exception as nurse_e:
                        print(f"Error allocating nurses for booking {booking.id}: {nurse_e}")
                        nurse_codes = []
                    
                    created_bookings.append({
                        "date": d.isoformat(),
                        "booking_id": booking.pk,
                        "items_count": len(created_items),
                        "therapists": [],  # No therapists for nurse treatments
                        "nurses": nurse_codes,  # Include nurses
                        "room_no": room.room_no if room else None
                    })
                else:
                    # assign therapists (same therapists assigned to each date) - only for regular therapies
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

            # create notification rows - COMMENTED OUT DUE TO WEBSOCKET ERRORS
            # for n in notifications_to_enqueue:
            #     NotificationQueue.objects.create(
            #         target_type=n["target_type"],
            #         target_identifier=n.get("target_identifier",""),
            #         channel=n.get("channel","webhook"),
            #         payload=n["payload"],
            #         status="queued"
            #     )

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
    
    # Fetch bookings based on status for the specific date (if filter provided)
    # This ensures each date is treated separately
    if filter_date:
        # Draft: show allocations that have draft bookings for this specific date (regardless of overall allocation status)
        draft_allocations = TherapyAllocation.objects.filter(
            from_date__lte=filter_date,
            to_date__gte=filter_date,
            bookings__date=filter_date,
            bookings__status='draft'
        ).distinct().select_related('patient', 'room', 'timeslot').prefetch_related('bookings__assignments__therapist')
        
        # Failed: show allocations that have failed bookings for this date
        failed_allocations = TherapyAllocation.objects.filter(
            from_date__lte=filter_date,
            to_date__gte=filter_date,
            bookings__date=filter_date,
            bookings__status='failed'
        ).distinct().select_related('patient', 'room', 'timeslot').prefetch_related('bookings__assignments__therapist')
        
        # Scheduled: show allocations that have scheduled bookings for this date
        scheduled_allocations = TherapyAllocation.objects.filter(
            from_date__lte=filter_date,
            to_date__gte=filter_date,
            bookings__date=filter_date,
            bookings__status='scheduled'
        ).distinct()
    else:
        # If no date filter, show allocations based on Booking status (not allocation status)
        # This ensures we check actual booking objects, not the allocation header status
        draft_allocations = TherapyAllocation.objects.filter(
            bookings__status='draft'
        ).distinct().select_related('patient', 'room', 'timeslot').prefetch_related('bookings__assignments__therapist')
        
        failed_allocations = TherapyAllocation.objects.filter(
            bookings__status='failed'
        ).distinct().select_related('patient', 'room', 'timeslot').prefetch_related('bookings__assignments__therapist')
        
        scheduled_allocations = TherapyAllocation.objects.filter(
            bookings__status='scheduled'
        ).distinct()
    
    # Prepare context data with proper prefetching for RoomBooking
    scheduled_allocations_with_bookings = scheduled_allocations.select_related('patient', 'room', 'timeslot').prefetch_related(
        'bookings__assignments__therapist',
        'bookings__timeslot',
        'bookings__room'
    )
    
    # Get draft and scheduled bookings for the filter date to pass to template (per-date display)
    draft_bookings = []
    scheduled_bookings = []
    if filter_date:
        draft_bookings = Booking.objects.filter(
            date=filter_date,
            status='draft'
        ).select_related('allocation__patient', 'allocation', 'timeslot', 'room').prefetch_related('assignments__therapist')
        
        scheduled_bookings = Booking.objects.filter(
            date=filter_date,
            status='scheduled'
        ).select_related('allocation__patient', 'allocation', 'timeslot', 'room').prefetch_related(
            'assignments__therapist',
            'assignments__therapist__therapist_code',
            'nurse_assignments__nurse',  # Prefetch nurse assignments
            'room_bookings__room'  # Prefetch RoomBooking for room lookup
        )
        
        # Separate therapist and nurse bookings
        from .nurse_allocation import is_nurse_treatment
        therapist_bookings = []
        nurse_bookings = []
        for booking in scheduled_bookings:
            is_nurse = is_nurse_treatment(booking.allocation.therapy_code, booking.allocation.therapy_name)
            if is_nurse:
                nurse_bookings.append(booking)
            else:
                therapist_bookings.append(booking)
    
    # Separate therapist and nurse bookings for template
    therapist_bookings_list = []
    nurse_bookings_list = []
    if filter_date:
        from .nurse_allocation import is_nurse_treatment
        for booking in scheduled_bookings:
            is_nurse = is_nurse_treatment(booking.allocation.therapy_code, booking.allocation.therapy_name)
            if is_nurse:
                nurse_bookings_list.append(booking)
            else:
                therapist_bookings_list.append(booking)
    else:
        # When no date filter, separate from scheduled_allocations
        from .nurse_allocation import is_nurse_treatment
        for allocation in scheduled_allocations_with_bookings:
            is_nurse = is_nurse_treatment(allocation.therapy_code, allocation.therapy_name)
            for booking in allocation.bookings.filter(status='scheduled'):
                if is_nurse:
                    nurse_bookings_list.append(booking)
                else:
                    therapist_bookings_list.append(booking)
    
    context = {
        'draft_allocations': draft_allocations,
        'draft_bookings': draft_bookings,  # Pass bookings separately for per-date display
        'scheduled_allocations': scheduled_allocations_with_bookings,
        'scheduled_bookings': scheduled_bookings,  # Pass scheduled bookings per date
        'therapist_bookings': therapist_bookings_list,  # Separate therapist bookings
        'nurse_bookings': nurse_bookings_list,  # Separate nurse bookings
        'failed_allocations': failed_allocations,
        'date_filter': date_filter or '',
        'stats': {
            'draft_count': draft_bookings.count() if filter_date else draft_allocations.count(),
            'failed_count': failed_allocations.count(),
            'scheduled_count': scheduled_bookings.count() if filter_date else scheduled_allocations.count(),
        }
    }
    
    return render(request, 'scheduling.html', context)


@require_http_methods(["GET"])
def final_schedule_status_api(request):
    """Return whether Final Schedule has been run for a given date.
    Query param: ?date=YYYY-MM-DD
    """
    date_str = request.GET.get('date')
    if not date_str:
        return JsonResponse({'error': 'date required'}, status=400)
    try:
        from datetime import datetime
        target_date = datetime.strptime(date_str, '%Y-%m-%d').date()
    except ValueError:
        return JsonResponse({'error': 'invalid date'}, status=400)

    from .models import FinalScheduleRun
    already = FinalScheduleRun.objects.filter(run_date=target_date).exists()
    run = FinalScheduleRun.objects.filter(run_date=target_date).first()
    return JsonResponse({
        'date': date_str,
        'already_run': bool(already),
        'status': getattr(run, 'status', None),
        'ran_at': getattr(run, 'ran_at', None),
    })

@csrf_exempt
@api_access_required
def final_schedule_api(request):
    """
    Final Schedule API endpoint that:
    1. Updates emergency leave data via api.py
    2. Triggers final allocation algorithm via final_allocation.py
    """
    if request.method != 'POST':
        return JsonResponse({'error': 'POST method required'}, status=405)
    
    try:
        data = json.loads(request.body)
        date_filter = data.get('date')
        
        if not date_filter:
            return JsonResponse({'error': 'Date is required'}, status=400)
        
        # Check if Final Schedule has already been run for this date
        from .models import FinalScheduleRun
        from datetime import datetime
        
        try:
            target_date = datetime.strptime(date_filter, '%Y-%m-%d').date()
            
            # Check marker table
            if FinalScheduleRun.objects.filter(run_date=target_date).exists():
                return JsonResponse({
                    'error': 'Final Schedule has already been run for this date. New therapies will be automatically scheduled when added.',
                    'already_run': True,
                    'date': date_filter
                }, status=400)
        except ValueError:
            return JsonResponse({'error': 'Invalid date format'}, status=400)
        
        # Step 1: Update emergency leave data via api.py
        try:
            import api
            api.enable_django_for_scheduling()
            
            # Update emergency leave for the selected date
            employees_on_leave = api.get_employees_on_leave_and_save(
                target_date=date_filter, 
                save_to_db=True
            )
            
            leave_update_result = {
                'success': True,
                'employees_on_leave': employees_on_leave,
                'count': len(employees_on_leave)
            }
        except Exception as e:
            leave_update_result = {
                'success': False,
                'error': str(e)
            }
        print(leave_update_result)
        # Step 2: Trigger final allocation algorithm
        try:
            # Import final allocation functions
            from final_allocation import bulk_allocate_for_date
            
            # Run the final allocation algorithm
            allocation_result = bulk_allocate_for_date(date_filter)
            
            allocation_update_result = {
                'success': True,
                'result': allocation_result
            }
        except Exception as e:
            allocation_update_result = {
                'success': False,
                'error': str(e)
            }
        
        # Step 3: Allocate nurses for nurse treatments
        try:
            from .nurse_allocation import allocate_nurses_for_date
            
            # Allocate nurses for all nurse treatments on this date
            nurse_allocation_result = allocate_nurses_for_date(date_filter)
            
            nurse_allocation_update_result = {
                'success': True,
                'result': nurse_allocation_result
            }
        except Exception as e:
            nurse_allocation_update_result = {
                'success': False,
                'error': str(e)
            }
        
        # Persist run marker when complete (store status and stats)
        try:
            from .models import FinalScheduleRun
            run_status = 'success' if (leave_update_result.get('success') and allocation_update_result.get('success')) else 'failed'
            FinalScheduleRun.objects.update_or_create(
                run_date=target_date,
                defaults={
                    'status': run_status,
                    'ran_by': request.user if getattr(request, 'user', None) and request.user.is_authenticated else None,
                    'message': (allocation_update_result.get('error') or leave_update_result.get('error') or '')[:1000],
                    'stats': {
                        'leave': leave_update_result,
                        'allocation': allocation_update_result,
                    }
                }
            )
        except Exception:
            pass

        # Return combined results
        return JsonResponse({
            'success': True,
            'message': 'Final schedule completed',
            'date': date_filter,
            'leave_update': leave_update_result,
            'allocation_update': allocation_update_result,
            'overall_success': leave_update_result['success'] and allocation_update_result['success']
        })
        print(allocation_update_result)
        
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)

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
    Returns bookings per date when date filter is provided, otherwise allocations.
    """
    if request.method != 'GET':
        return JsonResponse({'error': 'GET method required'}, status=405)
    
    try:
        from .models import TherapyAllocation, Booking
        from Patient.models import Therapist, TreatmentRoom, TimeSlot
        
        # Get filters
        date_filter = request.GET.get('date')
        status_filter = request.GET.get('status', 'all')
        patient_name_filter = (request.GET.get('patient_name') or request.GET.get('patient') or '').strip()
        
        data = []
        
        # If date filter is provided, return bookings for that date (per-date processing)
        if date_filter:
            filter_date = parse_date(date_filter)
            if filter_date:
                # Filter bookings by date and status
                booking_query = {'date': filter_date}
                
                if status_filter == 'draft':
                    booking_query['status'] = 'draft'
                elif status_filter == 'allocated' or status_filter == 'scheduled':
                    booking_query['status'] = 'scheduled'
                elif status_filter == 'failed':
                    booking_query['status'] = 'failed'
                # If status_filter is 'all', we'll get all statuses
                
                if patient_name_filter:
                    booking_query['allocation__patient__pat_name__icontains'] = patient_name_filter
                
                bookings = Booking.objects.filter(**booking_query).select_related(
                    'allocation__patient', 'allocation', 'timeslot', 'room'
                ).prefetch_related(
                    'assignments__therapist'
                )
                
                from .nurse_allocation import is_nurse_treatment
                
                # Convert bookings to JSON format
                for booking in bookings:
                    # Get assigned therapists for this booking
                    therapists = []
                    # Pre-fetch all TherapistBooking records for this booking to avoid N+1 queries
                    # Use visit (TherapyAllocation) to match TherapistBooking records
                    therapist_bookings = {}
                    try:
                        from Patient.models import TherapistBooking
                        from masters.models import TherapistMaster
                        # Get allocation (visit) for this booking
                        allocation = booking.allocation
                        # Get all therapist codes for this booking
                        therapist_codes = [a.therapist.therapist_code for a in booking.assignments.all()]
                        # Get all TherapistMaster records
                        therapist_masters = {tm.therapist_code: tm for tm in TherapistMaster.objects.filter(
                            therapist_code__in=therapist_codes
                        )}
                        # Get all TherapistBooking records for this visit and therapists
                        if therapist_masters and allocation:
                            tb_list = TherapistBooking.objects.filter(
                                visit=allocation,
                                therapist__in=therapist_masters.values(),
                                status='BOOKED'
                            ).select_related('therapist', 'visit')
                            # Create a map: therapist_code -> is_bathing
                            # ONLY use TherapistBooking.is_bathing field from Patient module
                            for tb in tb_list:
                                if tb.therapist:
                                    therapist_bookings[tb.therapist.therapist_code] = tb.is_bathing  # Direct access to is_bathing field
                    except Exception as e:
                        print(f"Error pre-fetching TherapistBooking records: {e}")
                        import traceback
                        traceback.print_exc()
                    
                    for assignment in booking.assignments.all():
                        # Get is_bathing flag from pre-fetched data
                        is_bathing = therapist_bookings.get(assignment.therapist.therapist_code, False)
                        
                        therapist_name = assignment.therapist.therapist_name or assignment.therapist.therapist_code
                        therapists.append({
                            'code': assignment.therapist.therapist_code,
                            'name': therapist_name,
                            'grade': getattr(assignment.therapist.therapist_grade, 'name', '') if assignment.therapist.therapist_grade else '',
                            'is_bathing': is_bathing
                        })
                    
                    # Get assigned nurses for this booking
                    nurses = []
                    for nurse_assignment in booking.nurse_assignments.filter(status='assigned'):
                        nurses.append({
                            'code': nurse_assignment.nurse.nurse_code,
                            'name': nurse_assignment.nurse.nurse_name or nurse_assignment.nurse.nurse_code
                        })
                    
                    # Get room from booking, RoomBooking, allocation, or PatientSnapshot
                    room_no = None
                    if booking.room:
                        room_no = booking.room.room_no
                    elif booking.allocation.room:
                        # Use allocation's preferred room if booking doesn't have one
                        room_no = booking.allocation.room.room_no
                    else:
                        # Try to get from RoomBooking - first try via visit field, then by matching date/slot/patient
                        try:
                            from Patient.models import RoomBooking
                            # Try via visit field (if RoomBooking is linked to Booking)
                            rb = booking.room_bookings.filter(
                                date=booking.date,
                                time_slot=booking.timeslot,
                                status='BOOKED'
                            ).first()
                            
                            # If not found, try by patient_id, date, and time_slot
                            if not rb:
                                rb = RoomBooking.objects.filter(
                                    date=booking.date,
                                    time_slot=booking.timeslot,
                                    patient_id=booking.allocation.patient.id,
                                    status='BOOKED'
                                ).first()
                            
                            if rb:
                                room_no = rb.room.room_no
                        except Exception as e:
                            print(f"Error getting room from RoomBooking: {e}")
                            pass
                    
                    # Fallback to PatientSnapshot pat_room_no if still no room found
                    if not room_no and booking.allocation.patient.pat_room_no:
                        room_no = booking.allocation.patient.pat_room_no
                    
                    # Get patient room number (staying room) - mapped from StayingRoom
                    patient_room_no = None
                    if booking.allocation.patient.pat_room_no:
                        # Use the global import from line 15
                        patient_room_no = get_staying_room_display_number(booking.allocation.patient.pat_room_no)
                    
                    try:
                        is_nurse_treatment_flag = is_nurse_treatment(booking.allocation.therapy_code, booking.allocation.therapy_name) is not None
                    except Exception:
                        is_nurse_treatment_flag = False
                    
                    data.append({
                        'id': booking.allocation.id,
                        'booking_id': booking.id,
                        'patient_name': booking.allocation.patient.pat_name,
                        'patient_reg_no': booking.allocation.patient.pat_reg_no,
                        'therapy_name': booking.allocation.therapy_name,
                        'therapy_code': booking.allocation.therapy_code,
                        'date': booking.date.isoformat(),
                        'from_date': booking.allocation.from_date.isoformat(),
                        'to_date': booking.allocation.to_date.isoformat(),
                        'status': booking.status,
                        'booking_status': booking.status,
                        'room_no': room_no,
                        'patient_room_no': patient_room_no,
                        'timeslot': booking.timeslot.slot_time.strftime('%H:%M') if booking.timeslot else None,
                        'therapists': therapists,
                        'nurses': nurses,
                        'is_nurse_treatment': is_nurse_treatment_flag,
                        'created_at': booking.allocation.created_at.isoformat(),
                        'allocated_by': booking.allocation.allocated_by.username if booking.allocation.allocated_by else None
                    })
        else:
            # No date filter - return allocations based on Booking status (not allocation status)
            # This ensures we check actual booking objects, matching the dashboard behavior
            query = {}
            if status_filter == 'draft':
                # Get allocations that have draft bookings
                allocations = TherapyAllocation.objects.filter(
                    bookings__status='draft'
                ).distinct()
            elif status_filter == 'allocated' or status_filter == 'scheduled':
                # Get allocations that have scheduled bookings
                allocations = TherapyAllocation.objects.filter(
                    bookings__status='scheduled'
                ).distinct()
            elif status_filter == 'failed':
                # Get allocations that have failed bookings
                allocations = TherapyAllocation.objects.filter(
                    bookings__status='failed'
                ).distinct()
            else:
                # All statuses - return all allocations
                allocations = TherapyAllocation.objects.all()
            
            # Apply select/prefetch optimizations
            allocations = allocations.select_related(
                'patient', 'room', 'timeslot'
            ).prefetch_related(
                'bookings__assignments__therapist'
            )
            
            if patient_name_filter:
                allocations = allocations.filter(patient__pat_name__icontains=patient_name_filter)
            
            # Convert to JSON format
            from .nurse_allocation import is_nurse_treatment
            
            for allocation in allocations:
                    # Get assigned therapists from all bookings
                    therapists = []
                    for booking in allocation.bookings.all():
                        for assignment in booking.assignments.all():
                            therapists.append({
                                'code': assignment.therapist.therapist_code,
                                'name': assignment.therapist.therapist_name or assignment.therapist.therapist_code,
                                'grade': getattr(assignment.therapist.therapist_grade, 'name', '') if assignment.therapist.therapist_grade else ''
                            })
                    
                    # Get assigned nurses from all bookings
                    nurses = []
                    for booking in allocation.bookings.all():
                        for nurse_assignment in booking.nurse_assignments.filter(status='assigned'):
                            nurses.append({
                                'code': nurse_assignment.nurse.nurse_code,
                                'name': nurse_assignment.nurse.nurse_name or nurse_assignment.nurse.nurse_code
                            })
                    
                    # Check if this is a nurse treatment
                    try:
                        is_nurse_treatment_flag = is_nurse_treatment(allocation.therapy_code, allocation.therapy_name) is not None
                    except Exception:
                        is_nurse_treatment_flag = False
                    
                    # Get patient room number (staying room) - mapped from StayingRoom
                    patient_room_no = None
                    if allocation.patient.pat_room_no:
                        # Use the global import from line 15
                        patient_room_no = get_staying_room_display_number(allocation.patient.pat_room_no)
                    
                    data.append({
                        'id': allocation.id,
                        'patient_name': allocation.patient.pat_name,
                        'patient_reg_no': allocation.patient.pat_reg_no,
                        'therapy_name': allocation.therapy_name,
                        'therapy_code': allocation.therapy_code,
                        'from_date': allocation.from_date.isoformat(),
                        'to_date': allocation.to_date.isoformat(),
                        'status': allocation.status,  # Keep allocation status but filter was based on booking
                        'room_no': allocation.room.room_no if allocation.room else None,
                        'patient_room_no': patient_room_no,
                        'timeslot': allocation.timeslot.slot_time.strftime('%H:%M') if allocation.timeslot else None,
                        'therapists': therapists,
                        'nurses': nurses,
                        'is_nurse_treatment': is_nurse_treatment_flag,
                        'created_at': allocation.created_at.isoformat(),
                        'allocated_by': allocation.allocated_by.username if allocation.allocated_by else None
                    })
        
        return JsonResponse({
            'success': True,
            'data': data,
            'count': len(data)
        })
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return JsonResponse({'error': str(e)}, status=500)


@csrf_exempt
@api_access_required
def reschedule_therapy_api(request):
    """
    API endpoint to reschedule a single failed therapy using the rescheduling algorithm.
    """
    if request.method != 'POST':
        return JsonResponse({'error': 'POST method required'}, status=405)
    
    try:
        data = json.loads(request.body)
        allocation_id = data.get('allocation_id')
        date = data.get('date')
        
        if not allocation_id or not date:
            return JsonResponse({'error': 'allocation_id and date are required'}, status=400)
        
        from .models import TherapyAllocation, Booking
        from reshedule import allocate_therapy_for_visit
        
        try:
            allocation = TherapyAllocation.objects.get(id=allocation_id, status='failed')
            
            # Parse date
            target_date = parse_date(date)
            if not target_date:
                return JsonResponse({'error': 'Invalid date format. Use YYYY-MM-DD.'}, status=400)
            
            # Ensure booking exists for this date
            booking = Booking.objects.filter(allocation=allocation, date=target_date).first()
            if not booking:
                # Create booking if it doesn't exist
                booking = Booking.objects.create(
                    allocation=allocation,
                    date=target_date,
                    timeslot=allocation.timeslot,
                    room=allocation.room,
                    status='draft'
                )
            
            # Call rescheduling algorithm
            try:
                tasks = allocate_therapy_for_visit(
                    allocation.id,
                    date,
                    create_bookings=True
                )
                
                if isinstance(tasks, dict) and "error" in tasks:
                    # Algorithm returned an error
                    return JsonResponse({
                        'success': False,
                        'error': tasks['error']
                    }, status=400)
                
                # Process results
                if isinstance(tasks, list):
                    success_tasks = [t for t in tasks if t.get('status') == 'BOOKED']
                    failed_tasks = [t for t in tasks if t.get('status') == 'FAILED']
                    
                    if success_tasks:
                        allocation.status = 'allocated'
                        allocation.save(update_fields=['status'])
                        return JsonResponse({
                            'success': True,
                                        'message': 'Therapy successfully rescheduled',
                                        'tasks': success_tasks,
                                        'failed_tasks': failed_tasks
                                    })
                    else:
                        # All tasks failed
                        allocation.status = 'failed'
                        allocation.save(update_fields=['status'])
                        reason = failed_tasks[0].get('reason', 'Unknown error') if failed_tasks else 'No available slots'
                        return JsonResponse({
                            'success': False,
                            'error': f'Rescheduling failed: {reason}',
                            'tasks': failed_tasks
                        })
                else:
                    return JsonResponse({
                        'success': False,
                        'error': 'Unexpected response from scheduling algorithm'
                    }, status=500)
                    
            except Exception as e:
                allocation.status = 'failed'
                allocation.save(update_fields=['status'])
                return JsonResponse({
                    'success': False,
                    'error': f'Error during rescheduling: {str(e)}'
                }, status=500)
                
        except TherapyAllocation.DoesNotExist:
            return JsonResponse({'error': 'Therapy allocation not found or not in failed status'}, status=404)
            
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


@csrf_exempt
@api_access_required
def reschedule_all_failed_api(request):
    """
    API endpoint to reschedule all failed therapies for a specific date using the rescheduling algorithm.
    Filters failed schedules day-wise and reschedules each one.
    """
    if request.method != 'POST':
        return JsonResponse({'error': 'POST method required'}, status=405)
    
    try:
        data = json.loads(request.body)
        date = data.get('date')
        
        if not date:
            return JsonResponse({'error': 'date is required'}, status=400)
        
        from .models import TherapyAllocation, Booking
        from reshedule import allocate_therapy_for_visit
        
        filter_date = parse_date(date)
        if not filter_date:
            return JsonResponse({'error': 'Invalid date format. Use YYYY-MM-DD.'}, status=400)
        
        # Get allocations that have failed bookings on the target date (day-wise filter)
        failed_allocations = (
            TherapyAllocation.objects
            .filter(
                from_date__lte=filter_date,
                to_date__gte=filter_date,
                bookings__date=filter_date,
                bookings__status='failed'
            )
            .distinct()
        )
        
        if not failed_allocations.exists():
            return JsonResponse({
                'success': True,
                'message': f'No failed therapies found for {date} to reschedule.',
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
        
        # Process each failed allocation
        for allocation in failed_allocations:
            try:
                # Ensure booking exists for this date
                booking = Booking.objects.filter(allocation=allocation, date=filter_date).first()
                if not booking:
                    # Create booking if it doesn't exist
                    booking = Booking.objects.create(
                        allocation=allocation,
                        date=filter_date,
                        timeslot=allocation.timeslot,
                        room=allocation.room,
                        status='draft'
                    )
                
                # Call rescheduling algorithm
                tasks = allocate_therapy_for_visit(
                    allocation.id,
                    date,
                    create_bookings=True
                )
                
                if isinstance(tasks, dict) and "error" in tasks:
                    # Algorithm returned an error
                    allocation.status = 'failed'
                    allocation.save(update_fields=['status'])
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
                        allocation.save(update_fields=['status'])
                        # Ensure bookings for this date are marked scheduled
                        try:
                            Booking.objects.filter(allocation=allocation, date=filter_date).update(status='scheduled')
                        except Exception:
                            pass
                        success_count += 1
                        results.append({
                            'allocation_id': allocation.id,
                            'status': 'success',
                            'tasks': success_tasks
                        })
                    else:
                        allocation.status = 'failed'
                        allocation.save(update_fields=['status'])
                        failed_count += 1
                        reason = failed_tasks[0].get('reason', 'Unknown error') if failed_tasks else 'No available slots'
                        results.append({
                            'allocation_id': allocation.id,
                            'status': 'failed',
                            'reason': reason
                        })
                        
            except Exception as e:
                allocation.status = 'failed'
                allocation.save(update_fields=['status'])
                results.append({
                    'allocation_id': allocation.id,
                    'status': 'failed',
                    'reason': str(e)
                })
                failed_count += 1
        
        return JsonResponse({
            'success': True,
            'message': f'Rescheduled {len(failed_allocations)} failed therapies for {date}: {success_count} successful, {failed_count} failed',
            'results': results,
            'stats': {
                'total': len(failed_allocations),
                'successful': success_count,
                'failed': failed_count
            }
        })
        
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)
