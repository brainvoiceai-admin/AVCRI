# therapies/views.py
import json
import sys
import io
from contextlib import redirect_stdout
from datetime import timedelta, datetime
from django.shortcuts import render
from django.http import JsonResponse, HttpResponseBadRequest, HttpResponse
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

def generate_debug_pdf(debug_output, title="Debug Output", date=None):
    """
    Generate a PDF from debug output text.
    
    Args:
        debug_output: String containing the debug output
        title: Title for the PDF
        date: Date string for the filename
        
    Returns:
        HttpResponse with PDF content
    """
    try:
        from reportlab.lib.pagesizes import letter, A4
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.units import inch
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, PageBreak
        from reportlab.lib.enums import TA_LEFT
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont
        
        # Create a BytesIO buffer to hold PDF data
        buffer = io.BytesIO()
        
        # Create the PDF document
        doc = SimpleDocTemplate(
            buffer,
            pagesize=letter,
            rightMargin=72,
            leftMargin=72,
            topMargin=72,
            bottomMargin=18
        )
        
        # Container for the 'Flowable' objects
        elements = []
        
        # Define styles
        styles = getSampleStyleSheet()
        title_style = ParagraphStyle(
            'CustomTitle',
            parent=styles['Heading1'],
            fontSize=16,
            textColor='#000080',
            spaceAfter=30,
            alignment=TA_LEFT
        )
        heading_style = ParagraphStyle(
            'CustomHeading',
            parent=styles['Heading2'],
            fontSize=12,
            textColor='#000080',
            spaceAfter=12,
            alignment=TA_LEFT
        )
        normal_style = ParagraphStyle(
            'CustomNormal',
            parent=styles['Normal'],
            fontSize=9,
            leading=12,
            alignment=TA_LEFT,
            fontName='Courier'
        )
        
        # Add title
        elements.append(Paragraph(title, title_style))
        if date:
            elements.append(Paragraph(f"Date: {date}", styles['Normal']))
            elements.append(Paragraph(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", styles['Normal']))
        elements.append(Spacer(1, 0.2*inch))
        
        # Split output into lines and add to PDF
        lines = debug_output.split('\n')
        for line in lines:
            # Escape HTML special characters
            escaped_line = line.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Replace multiple spaces with non-breaking spaces for better formatting
            escaped_line = escaped_line.replace('  ', ' &nbsp;')
            elements.append(Paragraph(escaped_line, normal_style))
        
        # Build PDF
        doc.build(elements)
        
        # Get the value of the BytesIO buffer
        pdf = buffer.getvalue()
        buffer.close()
        
        # Create HTTP response with PDF
        response = HttpResponse(pdf, content_type='application/pdf')
        filename = f"{title.replace(' ', '_')}_{date or datetime.now().strftime('%Y%m%d')}_{datetime.now().strftime('%H%M%S')}.pdf"
        response['Content-Disposition'] = f'attachment; filename="{filename}"'
        
        return response
        
    except ImportError:
        # Fallback if reportlab is not installed
        response = HttpResponse(debug_output, content_type='text/plain')
        filename = f"{title.replace(' ', '_')}_{date or datetime.now().strftime('%Y%m%d')}_{datetime.now().strftime('%H%M%S')}.txt"
        response['Content-Disposition'] = f'attachment; filename="{filename}"'
        return response
    except Exception as e:
        # If PDF generation fails, return as text
        error_msg = f"Error generating PDF: {str(e)}\n\nOriginal Output:\n{debug_output}"
        response = HttpResponse(error_msg, content_type='text/plain')
        filename = f"{title.replace(' ', '_')}_{date or datetime.now().strftime('%Y%m%d')}_{datetime.now().strftime('%H%M%S')}.txt"
        response['Content-Disposition'] = f'attachment; filename="{filename}"'
        return response

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

def is_treatment_requiring_senior_tag(therapy_name):
    """
    Check if a treatment requires special senior tag handling.
    Returns True ONLY if the therapy name exactly matches one of the specified treatments.
    """
    if not therapy_name:
        return False
    
    # List of treatments that require senior tag (only one senior, not bathing)
    # ONLY these exact treatments should show the senior tag
    special_treatments = [
        'dhara & abh(3)',
        'dhara& pizhichil (4)',
        'dhara & pizhichil (5)',
        'dhara & pizhichil (6)',
        'dhara & pizhichil (7)',
        'dhara & abyangam ( 3 t)',
        'dhara & sudhikalpana dhara (5t)',
        'dhara ( 2 t)',
        'thakradhara & abhyangam (4)',
        'thakradhara & pizichil(6)',
        'thakradhara ( 2 t)',
        'thakradhara&fbkadee kizhi (5 t)',
        'thakradhara& thakrapizhichil(7)',
    ]
    
    # Normalize therapy name: lowercase, remove extra spaces, keep structure
    therapy_normalized = ' '.join(str(therapy_name).lower().strip().split())
    
    # Check for exact match (case-insensitive, ignoring extra spaces)
    for special_treatment in special_treatments:
        special_normalized = ' '.join(special_treatment.lower().strip().split())
        if therapy_normalized == special_normalized:
            return True
    
    return False

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
                cancel_from_obj = parse_date(cancel_from)
                cancel_to_obj = parse_date(cancel_to)
                
                # Merge with existing cancellations if any
                if allocation.cancelled_date_from and allocation.cancelled_date_to:
                    # Merge cancellation ranges
                    existing_from = allocation.cancelled_date_from
                    existing_to = allocation.cancelled_date_to
                    
                    # Calculate the merged range (union of both ranges)
                    merged_from = min(existing_from, cancel_from_obj)
                    merged_to = max(existing_to, cancel_to_obj)
                    
                    allocation.cancelled_date_from = merged_from
                    allocation.cancelled_date_to = merged_to
                    # Append reason if different
                    if reason and reason != allocation.cancellation_reason:
                        if allocation.cancellation_reason:
                            allocation.cancellation_reason += f" | Additional cancellation: {reason}"
                        else:
                            allocation.cancellation_reason = reason
                else:
                    # First cancellation
                    allocation.cancelled_date_from = cancel_from_obj
                    allocation.cancelled_date_to = cancel_to_obj
                    allocation.cancellation_reason = reason
                
                allocation.status = 'cancelled'
                allocation.cancelled_by = request.user if request.user.is_authenticated else None
                allocation.cancelled_at = timezone.now()
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
            resume_date = payload.get('resume_date')  # Single date to resume
            resume_from = payload.get('resume_from')  # Backward compatibility
            resume_to = payload.get('resume_to')  # Backward compatibility
            
            if not allocation_id:
                return JsonResponse({'error': 'missing_allocation_id'}, status=400)
            
            # Support both single date and date range (for backward compatibility)
            if resume_date:
                resume_from = resume_date
                resume_to = resume_date
            elif not resume_from or not resume_to:
                return JsonResponse({'error': 'missing_fields'}, status=400)
            
            try:
                allocation = TherapyAllocation.objects.get(id=allocation_id)
                
                # If there are no cancelled dates, return error
                if not allocation.cancelled_date_from or not allocation.cancelled_date_to:
                    return JsonResponse({'error': 'no_cancelled_dates_to_resume'}, status=400)
                
                # Validate that the date is within cancelled range
                resume_date_obj = parse_date(resume_from)
                if resume_date_obj < allocation.cancelled_date_from or resume_date_obj > allocation.cancelled_date_to:
                    return JsonResponse({'error': 'resume_date_outside_cancelled_range'}, status=400)
                
                # Update related bookings for the specific date(s)
                resumed_bookings = Booking.objects.filter(
                    allocation=allocation,
                    date__gte=parse_date(resume_from),
                    date__lte=parse_date(resume_to)
                )
                resumed_count = resumed_bookings.count()
                
                # Release previous assignments/resources before re-allocating
                # This ensures clean state for the algorithm
                try:
                    # Use global BookingAssignment variable (defined at top of file)
                    # Don't use local import to avoid UnboundLocalError when checking it earlier
                    if BookingAssignment is not None:
                        BookingAssignment.objects.filter(booking__in=resumed_bookings).update(status='released')
                except Exception:
                    pass
                
                # Clear room assignments, ensure timeslot is set, and set status to draft
                # The algorithm will allocate room and therapists fresh
                # Make sure timeslot is set from allocation (needed for algorithm)
                update_dict = {'status': 'draft', 'room': None}
                if allocation.timeslot:
                    update_dict['timeslot'] = allocation.timeslot
                resumed_bookings.update(**update_dict)
                BookingItem.objects.filter(booking__in=resumed_bookings).update(status='draft')
                
                # Delete any existing TherapistBooking/RoomBooking for these dates
                # DELETE instead of UPDATE to avoid unique constraint issues
                # This ensures they're completely removed and can be re-allocated fresh
                try:
                    from Patient.models import TherapistBooking as TB, RoomBooking as RB
                    day_timeslot = allocation.timeslot
                    if day_timeslot:
                        for d in daterange(parse_date(resume_from), parse_date(resume_to)):
                            # Delete TherapistBooking for this date/timeslot (any status to avoid conflicts)
                            TB.objects.filter(
                                visit=allocation,
                                date=d,
                                time_slot=day_timeslot
                            ).delete()
                            TB.objects.filter(
                                date=d,
                                time_slot=day_timeslot,
                                patient_id=allocation.patient.id,
                                visit__isnull=True
                            ).delete()
                            
                            # Delete RoomBooking for this date/timeslot (any status to avoid conflicts)
                            RB.objects.filter(
                                therapy=allocation,
                                date=d,
                                time_slot=day_timeslot
                            ).delete()
                            for booking in resumed_bookings.filter(date=d):
                                RB.objects.filter(
                                    visit=booking,
                                    date=d,
                                    time_slot=day_timeslot
                                ).delete()
                            RB.objects.filter(
                                date=d,
                                time_slot=day_timeslot,
                                patient_id=allocation.patient.id,
                                therapy__isnull=True,
                                visit__isnull=True
                            ).delete()
                    else:
                        # If no timeslot, delete all for these dates
                        for d in daterange(parse_date(resume_from), parse_date(resume_to)):
                            TB.objects.filter(
                                visit=allocation,
                                date=d
                            ).delete()
                            RB.objects.filter(
                                therapy=allocation,
                                date=d
                            ).delete()
                except Exception as e:
                    print(f"Error deleting TherapistBooking/RoomBooking on resume: {e}")
                    import traceback
                    traceback.print_exc()
                    pass
                
                # re-allocate only for dates where FinalScheduleRun exists
                failed_reasons = []
                any_success = False
                try:
                    from .models import FinalScheduleRun
                    from final_allocation import expand_therapies_for_visit
                    for d in daterange(parse_date(resume_from), parse_date(resume_to)):
                        if FinalScheduleRun.objects.filter(run_date=d).exists():
                            try:
                                # Debug: Check booking state before calling algorithm
                                booking_check = Booking.objects.filter(allocation=allocation, date=d).first()
                                if not booking_check:
                                    failed_reasons.append({'date': d.isoformat(), 'reason': 'no_booking_found'})
                                    continue
                                
                                # Ensure booking has timeslot (required by algorithm)
                                if not booking_check.timeslot and allocation.timeslot:
                                    booking_check.timeslot = allocation.timeslot
                                    booking_check.save(update_fields=['timeslot'])
                                
                                # Double-check: Delete any remaining TherapistBooking/RoomBooking for this allocation
                                # The algorithm checks for patient_already_has_booking, so we need to ensure
                                # no bookings exist for this allocation that could cause conflicts
                                try:
                                    from Patient.models import TherapistBooking as TB, RoomBooking as RB
                                    if booking_check.timeslot:
                                        # Delete TherapistBooking linked to this allocation
                                        TB.objects.filter(
                                            visit=allocation,
                                            date=d,
                                            time_slot=booking_check.timeslot
                                        ).delete()
                                        # Also delete by patient_id if visit FK is not set
                                        TB.objects.filter(
                                            patient_id=allocation.patient.id,
                                            date=d,
                                            time_slot=booking_check.timeslot,
                                            visit__isnull=True
                                        ).delete()
                                        
                                        # Delete RoomBooking linked to this allocation or booking
                                        RB.objects.filter(
                                            therapy=allocation,
                                            date=d,
                                            time_slot=booking_check.timeslot
                                        ).delete()
                                        RB.objects.filter(
                                            visit=booking_check,
                                            date=d,
                                            time_slot=booking_check.timeslot
                                        ).delete()
                                        # Also delete orphaned RoomBooking for this patient
                                        RB.objects.filter(
                                            patient_id=allocation.patient.id,
                                            date=d,
                                            time_slot=booking_check.timeslot,
                                            therapy__isnull=True,
                                            visit__isnull=True
                                        ).delete()
                                        
                                        print(f"Final cleanup: Deleted TherapistBooking/RoomBooking for allocation {allocation.id} on {d}")
                                except Exception as cleanup_e:
                                    print(f"Warning: Error in final cleanup before algorithm: {cleanup_e}")
                                    import traceback
                                    traceback.print_exc()
                                
                                tasks = expand_therapies_for_visit(allocation.id, d.strftime('%Y-%m-%d'), create_bookings=True)
                                print(f"Resume allocation {allocation.id} for date {d}: algorithm returned {tasks}")
                                
                                if isinstance(tasks, list) and any(t.get('status') == 'BOOKED' for t in tasks):
                                    any_success = True
                                    Booking.objects.filter(allocation=allocation, date=d).update(status='scheduled')
                                    BookingItem.objects.filter(booking__allocation=allocation, booking__date=d).update(status='scheduled')
                                else:
                                    reason = None
                                    if isinstance(tasks, list):
                                        fails = [t for t in tasks if t.get('status') == 'FAILED']
                                        reason = fails[0].get('reason') if fails else 'allocation_failed'
                                        print(f"Resume failed for date {d}: {reason}")
                                    elif isinstance(tasks, dict):
                                        reason = tasks.get('error')
                                        print(f"Resume error for date {d}: {reason}")
                                    failed_reasons.append({'date': d.isoformat(), 'reason': reason or 'unknown'})
                            except Exception as _e:
                                print(f"Exception during resume allocation for date {d}: {_e}")
                                import traceback
                                traceback.print_exc()
                                failed_reasons.append({'date': d.isoformat(), 'reason': str(_e)})
                except Exception:
                    pass
                
                # Update cancelled date range based on what was resumed
                if allocation.cancelled_date_from and allocation.cancelled_date_to:
                    resume_from_obj = parse_date(resume_from)
                    resume_to_obj = parse_date(resume_to)
                    
                    # If resuming the entire range, clear cancellation
                    if resume_from_obj == allocation.cancelled_date_from and resume_to_obj == allocation.cancelled_date_to:
                        allocation.cancelled_date_from = None
                        allocation.cancelled_date_to = None
                        allocation.cancellation_reason = ''
                        allocation.status = 'draft'
                    # If resuming from the start, update from_date
                    elif resume_from_obj == allocation.cancelled_date_from:
                        from datetime import timedelta
                        new_from = resume_to_obj + timedelta(days=1)
                        if new_from <= allocation.cancelled_date_to:
                            allocation.cancelled_date_from = new_from
                        else:
                            # All dates resumed
                            allocation.cancelled_date_from = None
                            allocation.cancelled_date_to = None
                            allocation.cancellation_reason = ''
                            allocation.status = 'draft'
                    # If resuming from the end, update to_date
                    elif resume_to_obj == allocation.cancelled_date_to:
                        from datetime import timedelta
                        new_to = resume_from_obj - timedelta(days=1)
                        if new_to >= allocation.cancelled_date_from:
                            allocation.cancelled_date_to = new_to
                        else:
                            # All dates resumed
                            allocation.cancelled_date_from = None
                            allocation.cancelled_date_to = None
                            allocation.cancellation_reason = ''
                            allocation.status = 'draft'
                    # If resuming from the middle, keep the original cancelled range unchanged
                    # Only the specific resumed date's bookings are updated
                    # The cancelled_date_from/to range stays the same so other dates remain in the cancelled range
                    else:
                        # Resuming a date in the middle - don't change the cancelled_date_from/to range
                        # The range stays as-is (e.g., 11th-14th), and only the specific date (13th) is resumed
                        # This allows resuming dates one by one without losing the cancelled range
                        # The UI will check individual booking statuses to determine which dates are actually cancelled
                        pass  # Keep the original cancelled_date_from/to unchanged
                
                allocation.resumed_by = request.user if request.user.is_authenticated else None
                allocation.resumed_at = timezone.now()
                allocation.save()
                
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
                    
                    # Adjust cancelled_date_from and cancelled_date_to to fit within new date range
                    if allocation.cancelled_date_from and allocation.cancelled_date_to:
                        # If cancelled range is completely outside new date range, clear it
                        if allocation.cancelled_date_to < allocation.from_date or allocation.cancelled_date_from > allocation.to_date:
                            allocation.cancelled_date_from = None
                            allocation.cancelled_date_to = None
                            allocation.cancellation_reason = ''
                        else:
                            # Adjust cancelled range to fit within new date range
                            if allocation.cancelled_date_from < allocation.from_date:
                                allocation.cancelled_date_from = allocation.from_date
                            if allocation.cancelled_date_to > allocation.to_date:
                                allocation.cancelled_date_to = allocation.to_date

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
            # Ensure timedelta is available in this scope
            from datetime import timedelta
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
                        # Check if required models are available
                        # Note: Don't check BookingAssignment here to avoid UnboundLocalError
                        # (it may be imported locally later in the function)
                        if TherapyAllocation is None or Booking is None or BookingItem is None:
                            return JsonResponse({'error': 'required models missing (TherapyAllocation/Booking/BookingItem)'}, status=500)

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
                        # Use global BookingAssignment variable (not local import to avoid UnboundLocalError)
                        if BookingAssignment is not None:
                            for t in therapists:
                                try:
                                    a = BookingAssignment.objects.create(booking=b, booking_item=None, therapist=t, role=getattr(t,'therapist_grade',''), assigned_for='booking', status='assigned')
                                    assigns.append(getattr(t,'therapist_code',''))
                                except Exception as assign_e:
                                    print(f"Error creating BookingAssignment: {assign_e}")
                                    assigns.append(getattr(t,'therapist_code',''))
                        else:
                            # If BookingAssignment model not available, just track therapist codes
                            for t in therapists:
                                assigns.append(getattr(t,'therapist_code',''))
                        bookings_created.append({'date': single_date.isoformat(), 'booking_id': b.pk, 'items_count': len(created_items), 'therapists': assigns})
                        date_status_map[single_date.isoformat()] = 'draft'
                        status_counts['draft'] += 1

                    # Check which dates have Final Schedule run - run algorithm for those dates immediately
                    # Other dates will remain in draft and can be scheduled via Final Schedule button in dashboard
                    # IMPORTANT: Use bulk_allocate_for_date to ensure PASS 1 (continuity) and PASS 2 are both executed
                    try:
                        from .models import FinalScheduleRun
                        from final_allocation import bulk_allocate_for_date

                        any_succeeded = False
                        any_failed = False
                        
                        # Group dates by Final Schedule status
                        dates_with_final_schedule = []
                        for d in daterange(fdate, tdate):
                            if FinalScheduleRun.objects.filter(run_date=d).exists():
                                dates_with_final_schedule.append(d)
                        
                        # Process each date that has Final Schedule run
                        # Use bulk_allocate_for_date which includes PASS 1 (continuity) and PASS 2
                        for d in dates_with_final_schedule:
                            try:
                                print(f"[THERAPY ENTRY] Running bulk_allocate_for_date for date {d.isoformat()} to ensure continuity (PASS 1 + PASS 2)")
                                result = bulk_allocate_for_date(d.strftime('%Y-%m-%d'))
                                
                                if result.get('success', False):
                                    # Check if our allocation was processed successfully
                                    # bulk_allocate_for_date processes all draft bookings for the date
                                    # Check the status of bookings for this specific allocation
                                    allocation_bookings = Booking.objects.filter(allocation=alloc, date=d)
                                    
                                    scheduled_count = allocation_bookings.filter(status='scheduled').count()
                                    failed_count = allocation_bookings.filter(status='failed').count()
                                    draft_count = allocation_bookings.filter(status='draft').count()
                                    
                                    if scheduled_count > 0:
                                        any_succeeded = True
                                        # Update booking items status for this date
                                        BookingItem.objects.filter(booking__allocation=alloc, booking__date=d).update(status='scheduled')
                                        status_counts['draft'] -= draft_count
                                        status_counts['allocated'] += scheduled_count
                                        date_status_map[d.isoformat()] = 'allocated'
                                        print(f"[THERAPY ENTRY] ✓ Date {d.isoformat()}: {scheduled_count} booking(s) scheduled with continuity")
                                    elif failed_count > 0:
                                        any_failed = True
                                        BookingItem.objects.filter(booking__allocation=alloc, booking__date=d).update(status='failed')
                                        status_counts['draft'] -= draft_count
                                        status_counts['failed'] += failed_count
                                        date_status_map[d.isoformat()] = 'failed'
                                        print(f"[THERAPY ENTRY] ✗ Date {d.isoformat()}: {failed_count} booking(s) failed")
                                    else:
                                        # Still in draft - might not have been processed
                                        print(f"[THERAPY ENTRY] ? Date {d.isoformat()}: {draft_count} booking(s) still in draft")
                                else:
                                    # bulk_allocate_for_date returned an error
                                    error_msg = result.get('error', 'Unknown error')
                                    print(f"[THERAPY ENTRY] ✗ Error in bulk_allocate_for_date for {d.isoformat()}: {error_msg}")
                                    any_failed = True
                                    allocation_bookings = Booking.objects.filter(allocation=alloc, date=d)
                                    draft_count = allocation_bookings.filter(status='draft').count()
                                    Booking.objects.filter(allocation=alloc, date=d).update(status='failed')
                                    BookingItem.objects.filter(booking__allocation=alloc, booking__date=d).update(status='failed')
                                    status_counts['draft'] -= draft_count
                                    status_counts['failed'] += draft_count
                                    date_status_map[d.isoformat()] = 'failed'
                            except Exception as _e:
                                # Continue to next date on error
                                print(f"[THERAPY ENTRY] ✗ Error processing date {d.isoformat()} for allocation {alloc.id}: {_e}")
                                import traceback
                                print(f"[THERAPY ENTRY] Traceback: {traceback.format_exc()}")
                                any_failed = True
                                Booking.objects.filter(allocation=alloc, date=d).update(status='failed')
                                BookingItem.objects.filter(booking__allocation=alloc, booking__date=d).update(status='failed')
                                status_counts['draft'] -= Booking.objects.filter(allocation=alloc, date=d, status='draft').count()
                                status_counts['failed'] += Booking.objects.filter(allocation=alloc, date=d, status='failed').count()
                                date_status_map[d.isoformat()] = 'failed'

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
        patient_type = (request.GET.get('patient_type') or '').strip().upper()  # Get patient type (IP or OP)
        results = []

        # Add regular therapies from TherapyMaster
        if TherapyMaster is not None:
            qs = TherapyMaster.objects.filter(is_active=True).all()  # Use local master table

            # New requirement:
            # - For OP patients: show only OP treatments
            # - For IP patients: show ALL treatments (IP + OP)
            # - If patient_type is not provided or empty, show all (backward compatibility)
            if patient_type == 'OP':
                qs = qs.filter(patient_type='OP')
            # For IP or unknown, leave qs as all active therapies

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
        # Updated per requirement:
        # - For IP patients (and when patient_type is empty/unknown): include nurse treatments
        # - For OP patients: do NOT include nurse treatments (OP should see only OP treatments)
        if NurseTreatmentMaster is not None and (patient_type in ('', 'IP')):
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
                # Try with select_related first, fallback to regular query if it fails
                try:
                    qs = ItemMaster.objects.filter(is_active=True).select_related('procured_from').all()
                except Exception:
                    # If select_related fails (e.g., field doesn't exist yet), use regular query
                    qs = ItemMaster.objects.filter(is_active=True).all()
                
                if q:
                    qs = qs.filter(Q(item_name__icontains=q) | Q(item_code__icontains=q))
                qs = qs[:50]
                for i in qs:
                    procured_from_name = ''
                    try:
                        if hasattr(i, 'procured_from') and i.procured_from:
                            procured_from_name = i.procured_from.name if hasattr(i.procured_from, 'name') else str(i.procured_from)
                    except Exception:
                        pass
                    
                    results.append({
                        'item_code': getattr(i, 'item_code', ''),
                        'item_name': getattr(i, 'item_name', ''),
                        'item_uom': getattr(i, 'unit_of_measure', '') or '',
                        'procured_from': procured_from_name
                    })
            except Exception as e:
                print(f"Error in search_items (therapy_entry): {e}")
                import traceback
                traceback.print_exc()
                results = []
        else:
            print("ItemMaster model not found - check if masters app is installed")
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
                        # IMPORTANT: For Dhara & Pizichil and all therapies, ensure only ONE therapist is marked as bathing
                        bathing_found = False
                        for tb in tb_list:
                            if tb.therapist:
                                therapist_code = tb.therapist.therapist_code
                                # Only mark as bathing if is_bathing=True AND we haven't already found a bathing therapist
                                if tb.is_bathing and not bathing_found:
                                    therapist_bookings[therapist_code] = True
                                    bathing_found = True
                                else:
                                    # If this therapist has is_bathing=True but we already found one, set it to False
                                    # This ensures only ONE bathing therapist per visit
                                    therapist_bookings[therapist_code] = False
                                # If is_bathing is False, explicitly set it
                                if not tb.is_bathing and therapist_code not in therapist_bookings:
                                    therapist_bookings[therapist_code] = False
                except Exception as e:
                    print(f"Error pre-fetching TherapistBooking records: {e}")
                    import traceback
                    traceback.print_exc()
                
                # Check if this treatment requires special senior tag handling
                requires_senior_tag = False
                if alloc and alloc.therapy_name:
                    requires_senior_tag = is_treatment_requiring_senior_tag(alloc.therapy_name)
                
                # First pass: collect all therapists and identify seniors who are not bathing
                therapist_data_list = []
                senior_non_bathing_therapist_code = None
                
                for a in b.assignments.all():
                    therapist_code = a.therapist.therapist_code
                    therapist_name = getattr(a.therapist, 'therapist_name', '') or therapist_code
                    # Get is_bathing flag from pre-fetched data
                    is_bathing = therapist_bookings.get(therapist_code, False)
                    
                    # Get TherapistMaster to check grade (use TherapistMaster, not Patient.models.Therapist)
                    therapist_master = None
                    try:
                        therapist_master = therapist_masters.get(therapist_code)
                    except (NameError, AttributeError):
                        # therapist_masters not available, fetch it
                        from masters.models import TherapistMaster
                        try:
                            therapist_master = TherapistMaster.objects.get(therapist_code=therapist_code)
                        except TherapistMaster.DoesNotExist:
                            pass
                    
                    # Check if this therapist is senior
                    is_senior_grade = False
                    if therapist_master and therapist_master.therapist_grade:
                        grade_name = getattr(therapist_master.therapist_grade, 'name', '')
                        if grade_name and 'Senior' in grade_name:
                            is_senior_grade = True
                    
                    therapist_data_list.append({
                        'name': therapist_name,
                        'code': therapist_code,
                        'is_bathing': bool(is_bathing),
                        'is_senior_grade': is_senior_grade,
                        'therapist_master': therapist_master
                    })
                    
                    # For special treatments: identify the first senior who is NOT bathing
                    if requires_senior_tag and is_senior_grade and not is_bathing and senior_non_bathing_therapist_code is None:
                        senior_non_bathing_therapist_code = therapist_code
                
                # Second pass: mark only one senior (non-bathing) with senior tag
                for therapist_data in therapist_data_list:
                    is_senior = False
                    if requires_senior_tag:
                        # Only mark the first senior who is not bathing
                        if therapist_data['code'] == senior_non_bathing_therapist_code:
                            is_senior = True
                    
                    therapists.append({
                        'name': therapist_data['name'],
                        'code': therapist_data['code'],
                        'is_bathing': therapist_data['is_bathing'],
                        'is_senior': is_senior
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
                    'status_summary': status_summary,
                    'cancelled_date_from': a.cancelled_date_from.isoformat() if a.cancelled_date_from else None,
                    'cancelled_date_to': a.cancelled_date_to.isoformat() if a.cancelled_date_to else None,
                    'cancellation_reason': getattr(a, 'cancellation_reason', '') or '',
                    'created_at': a.created_at.isoformat() if a.created_at else None,
                    'updated_at': a.updated_at.isoformat() if a.updated_at else None,
                    'resumed_at': a.resumed_at.isoformat() if a.resumed_at else None,
                    'cancelled_at': a.cancelled_at.isoformat() if a.cancelled_at else None
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

    return render(request, 'dashboards/prescriptions/therapy_entry.html', context={'masters': masters_context})


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
            scope = payload.get('scope', '') or ''
            usage = payload.get('usage', '') or ''
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
                    usage=usage,
                    scope=scope,
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
        # NOTE: The resume_prescription handler has been moved to the second POST section (around line 2767)
        # to support single date resume (resume_date) for middle dates
        # This old handler is kept commented out for reference but should not be used
        # if action_post == 'resume_prescription':
        #     ... (old implementation removed - see line 2767 for new implementation)

        # ---------- update prescription ----------
        if action_post == 'update_prescription':
            allocation_id = payload.get('allocation_id')
            prescription_name = payload.get('prescription_name')
            items_groups = payload.get('items_groups', [])
            procured_from = payload.get('procured_from', '')
            scope = payload.get('scope', '')
            usage = payload.get('usage', '')
            notes = payload.get('notes', '')
            
            if not allocation_id:
                return JsonResponse({'error': 'missing_allocation_id'}, status=400)
            
            try:
                allocation = PrescriptionAllocation.objects.get(id=allocation_id)
                old_data = {
                    'prescription_name': allocation.prescription_name,
                    'items_groups': allocation.items_groups,
                    'procured_from': allocation.procured_from,
                    'usage': allocation.usage,
                    'scope': allocation.scope,
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
                if scope is not None:
                    allocation.scope = scope or ''
                if usage is not None:
                    allocation.usage = usage or ''
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
                        'usage': allocation.usage,
                        'scope': allocation.scope,
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
                # Try with select_related first, fallback to regular query if it fails
                try:
                    qs = ItemMaster.objects.filter(is_active=True).select_related('procured_from').all()
                except Exception:
                    # If select_related fails (e.g., field doesn't exist yet), use regular query
                    qs = ItemMaster.objects.filter(is_active=True).all()
                
                if q:
                    qs = qs.filter(Q(item_name__icontains=q) | Q(item_code__icontains=q))
                qs = qs[:50]
                for i in qs:
                    procured_from_name = ''
                    try:
                        if hasattr(i, 'procured_from') and i.procured_from:
                            procured_from_name = i.procured_from.name if hasattr(i.procured_from, 'name') else str(i.procured_from)
                    except Exception:
                        pass
                    
                    results.append({
                        'item_code': getattr(i, 'item_code', ''),
                        'item_name': getattr(i, 'item_name', ''),
                        'item_uom': getattr(i, 'unit_of_measure', '') or '',
                        'procured_from': procured_from_name
                    })
            except Exception as e:
                print(f"Error in search_items: {e}")
                import traceback
                traceback.print_exc()
                # Return empty results on error rather than failing completely
                results = []
        else:
            print("ItemMaster model not found - check if masters app is installed")
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
    return render(request, 'dashboards/prescriptions/prescription_entry.html')


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
            scope = payload.get('scope', '') or ''
            usage = payload.get('usage', '') or ''
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
                
                # Deduplicate items WITHIN each group only
                # Same medicine can exist in different groups
                cleaned_groups = []
                
                for group in items_groups:
                    seen_in_group = set()
                    unique_items = []
                    
                    for item in group.get('items', []):
                        item_code = item.get('item_code')
                        if item_code and item_code in seen_in_group:
                            # Skip duplicate item within THIS group
                            print(f"Backend: Duplicate item removed within group: {item.get('item_name')} ({item_code})")
                            continue
                        if item_code:
                            seen_in_group.add(item_code)
                        unique_items.append(item)
                    
                    # Only add group if it has items after deduplication
                    if unique_items:
                        cleaned_group = {**group, 'items': unique_items}
                        cleaned_groups.append(cleaned_group)
                
                # Use cleaned groups
                items_groups = cleaned_groups
                
                # Create prescription allocation
                from_date_parsed = parse_date(from_date)
                to_date_parsed = parse_date(to_date)
                
                allocation = PrescriptionAllocation.objects.create(
                    patient=ps,
                    prescription_name=prescription_name,
                    items_groups=json.dumps(items_groups),
                    procured_from=procured_from,
                    usage=usage,
                    scope=scope,
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
                cancel_from_obj = parse_date(cancel_from)
                cancel_to_obj = parse_date(cancel_to)
                
                # Merge with existing cancellations if any
                if allocation.cancelled_date_from and allocation.cancelled_date_to:
                    # Merge cancellation ranges
                    existing_from = allocation.cancelled_date_from
                    existing_to = allocation.cancelled_date_to
                    
                    # Calculate the merged range (union of both ranges)
                    merged_from = min(existing_from, cancel_from_obj)
                    merged_to = max(existing_to, cancel_to_obj)
                    
                    allocation.cancelled_date_from = merged_from
                    allocation.cancelled_date_to = merged_to
                    # Append reason if different
                    if reason and reason != allocation.cancellation_reason:
                        if allocation.cancellation_reason:
                            allocation.cancellation_reason += f" | Additional cancellation: {reason}"
                        else:
                            allocation.cancellation_reason = reason
                else:
                    # First cancellation
                    allocation.cancelled_date_from = cancel_from_obj
                    allocation.cancelled_date_to = cancel_to_obj
                    allocation.cancellation_reason = reason
                
                allocation.status = 'cancelled'
                allocation.cancelled_by = request.user if request.user.is_authenticated else None
                allocation.cancelled_at = timezone.now()
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
            resume_date = payload.get('resume_date')  # Single date to resume
            resume_from = payload.get('resume_from')  # Backward compatibility
            resume_to = payload.get('resume_to')  # Backward compatibility
            
            if not allocation_id:
                return JsonResponse({'error': 'missing_allocation_id'}, status=400)
            
            # Support both single date and date range (for backward compatibility)
            if resume_date:
                resume_from = resume_date
                resume_to = resume_date
            elif not resume_from or not resume_to:
                return JsonResponse({'error': 'missing_fields'}, status=400)
            
            try:
                allocation = PrescriptionAllocation.objects.get(id=allocation_id)
                
                # If there are no cancelled dates, return error
                if not allocation.cancelled_date_from or not allocation.cancelled_date_to:
                    return JsonResponse({'error': 'no_cancelled_dates_to_resume'}, status=400)
                
                # Validate that the date is within cancelled range
                resume_date_obj = parse_date(resume_from)
                if resume_date_obj < allocation.cancelled_date_from or resume_date_obj > allocation.cancelled_date_to:
                    return JsonResponse({'error': 'resume_date_outside_cancelled_range'}, status=400)
                
                # Update cancelled date range based on what was resumed
                if allocation.cancelled_date_from and allocation.cancelled_date_to:
                    resume_from_obj = parse_date(resume_from)
                    resume_to_obj = parse_date(resume_to)
                    
                    # If resuming the entire range, clear cancellation
                    if resume_from_obj == allocation.cancelled_date_from and resume_to_obj == allocation.cancelled_date_to:
                        allocation.cancelled_date_from = None
                        allocation.cancelled_date_to = None
                        allocation.cancellation_reason = ''
                        allocation.status = 'draft'
                    # If resuming from the start, update from_date
                    elif resume_from_obj == allocation.cancelled_date_from:
                        from datetime import timedelta
                        new_from = resume_to_obj + timedelta(days=1)
                        if new_from <= allocation.cancelled_date_to:
                            allocation.cancelled_date_from = new_from
                        else:
                            # All dates resumed
                            allocation.cancelled_date_from = None
                            allocation.cancelled_date_to = None
                            allocation.cancellation_reason = ''
                            allocation.status = 'draft'
                    # If resuming from the end, update to_date
                    elif resume_to_obj == allocation.cancelled_date_to:
                        from datetime import timedelta
                        new_to = resume_from_obj - timedelta(days=1)
                        if new_to >= allocation.cancelled_date_from:
                            allocation.cancelled_date_to = new_to
                        else:
                            # All dates resumed
                            allocation.cancelled_date_from = None
                            allocation.cancelled_date_to = None
                            allocation.cancellation_reason = ''
                            allocation.status = 'draft'
                    # If resuming from the middle, we keep the original range
                    # The frontend will handle showing remaining dates
                
                allocation.resumed_by = request.user if request.user.is_authenticated else None
                allocation.resumed_at = timezone.now()
                allocation.save()
                
                # Ensure PrescriptionScheduling record exists for the resumed date and update status to 'draft'
                from .models import PrescriptionScheduling
                resume_date_obj = parse_date(resume_from)
                ps_record, created = PrescriptionScheduling.objects.get_or_create(
                    patient=allocation.patient,
                    prescription_date=resume_date_obj,
                    defaults={
                        'doctor': request.user if request.user.is_authenticated else None,
                        'status': 'draft'
                    }
                )
                # Update status to 'draft' even if record already existed (was cancelled)
                if not created:
                    ps_record.status = 'draft'
                    ps_record.save()
                
                # Create notification - COMMENTED OUT TEMPORARILY DUE TO NETWORK ERRORS
                # create_prescription_notification(allocation, 'prescription_resumed', request.user, {
                #     'resume_date': resume_date or resume_from,
                #     'resume_from': resume_from,
                #     'resume_to': resume_to
                # })
                
                # Log audit
                log_prescription_audit(request.user, 'resume_prescription', 'PrescriptionAllocation', str(allocation.id), {
                    'resume_date': resume_date or resume_from,
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
            scope = payload.get('scope', '')
            usage = payload.get('usage', '')
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
                    'usage': getattr(allocation, 'usage', ''),
                    'scope': getattr(allocation, 'scope', ''),
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
                    # Deduplicate items WITHIN each group only
                    # Same medicine can exist in different groups
                    cleaned_groups = []
                    
                    for group in items_groups:
                        seen_in_group = set()
                        unique_items = []
                        
                        for item in group.get('items', []):
                            item_code = item.get('item_code')
                            if item_code and item_code in seen_in_group:
                                # Skip duplicate item within THIS group
                                print(f"Backend: Duplicate item removed within group: {item.get('item_name')} ({item_code})")
                                continue
                            if item_code:
                                seen_in_group.add(item_code)
                            unique_items.append(item)
                        
                        # Only add group if it has items after deduplication
                        if unique_items:
                            cleaned_group = {**group, 'items': unique_items}
                            cleaned_groups.append(cleaned_group)
                    
                    # Use cleaned groups
                    items_groups = cleaned_groups
                    
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
                # Update scope / usage if provided
                if scope is not None:
                    allocation.scope = scope or ''
                if usage is not None:
                    allocation.usage = usage or ''
                if from_date is not None and from_date != '':
                    allocation.from_date = parse_date(from_date)
                if to_date is not None and to_date != '':
                    allocation.to_date = parse_date(to_date)
                if days is not None and days != '':
                    try:
                        allocation.days = int(days)
                    except (ValueError, TypeError):
                        pass  # Keep existing days if invalid

                allocation.save()

                # Create/update PrescriptionScheduling records for the date range (especially for extended dates)
                from .models import PrescriptionScheduling
                from datetime import timedelta
                
                if allocation.from_date and allocation.to_date:
                    current_date = allocation.from_date
                    while current_date <= allocation.to_date:
                        # Get or create PrescriptionScheduling for this date
                        PrescriptionScheduling.objects.get_or_create(
                            patient=allocation.patient,
                            prescription_date=current_date,
                            defaults={
                                'doctor': request.user if request.user.is_authenticated else None,
                                'status': 'draft'
                            }
                        )
                        current_date += timedelta(days=1)

                # Log audit
                log_prescription_audit(request.user, 'update_prescription', 'PrescriptionAllocation', str(allocation.id), {
                    'old_data': old_data,
                    'new_data': {
                        'prescription_name': allocation.prescription_name,
                        'items_groups': allocation.items_groups,
                        'procured_from': allocation.procured_from,
                        'usage': getattr(allocation, 'usage', ''),
                        'scope': getattr(allocation, 'scope', ''),
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
                # Try with select_related first, fallback to regular query if it fails
                try:
                    qs = ItemMaster.objects.filter(is_active=True).select_related('procured_from').all()
                except Exception:
                    # If select_related fails (e.g., field doesn't exist yet), use regular query
                    qs = ItemMaster.objects.filter(is_active=True).all()
                
                if q:
                    qs = qs.filter(Q(item_name__icontains=q) | Q(item_code__icontains=q))
                qs = qs[:50]
                for i in qs:
                    procured_from_name = ''
                    try:
                        if hasattr(i, 'procured_from') and i.procured_from:
                            procured_from_name = i.procured_from.name if hasattr(i.procured_from, 'name') else str(i.procured_from)
                    except Exception:
                        pass
                    
                    results.append({
                        'item_code': getattr(i, 'item_code', ''),
                        'item_name': getattr(i, 'item_name', ''),
                        'item_uom': getattr(i, 'unit_of_measure', '') or '',
                        'procured_from': procured_from_name
                    })
            except Exception as e:
                print(f"Error in search_items: {e}")
                import traceback
                traceback.print_exc()
                results = []
        else:
            print("ItemMaster model not found - check if masters app is installed")
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
            prescriptions = PrescriptionAllocation.objects.filter(patient=patient).order_by('created_at')
            
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
                    
                    # Count status from PrescriptionScheduling records
                    # This correctly reflects the actual status of each date
                    for ps in scheduling_records:
                        if ps.status in status_counts:
                            status_counts[ps.status] += 1
                    
                    # Don't add allocation status to counts - status_counts should only reflect PrescriptionScheduling records
                    # The allocation status (p.status) is separate and represents the overall allocation state
                    # Individual dates have their own status in PrescriptionScheduling
                
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
                    'usage': getattr(p, 'usage', ''),
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
                    'resumed_at': p.resumed_at.isoformat() if p.resumed_at else None,
                    'created_at': p.created_at.isoformat() if p.created_at else None,
                    'updated_at': p.updated_at.isoformat() if p.updated_at else None
                })
            
            return JsonResponse(results, safe=False)
        except PatientSnapshot.DoesNotExist:
            return JsonResponse({'error': 'patient_not_found'}, status=404)
        except Exception as e:
            return JsonResponse({'error': str(e)}, status=500)
    
    # Default: render the template
    return render(request, 'dashboards/prescriptions/prescription_entry.html')


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
    
    # Get date filter from request; default to today for failed/scheduled,
    # but do NOT default for draft therapies (handled separately below)
    date_filter = request.GET.get('date')
    has_query_date = bool(date_filter)
    if date_filter:
        try:
            filter_date = parse_date(date_filter)
        except Exception:
            filter_date = None
    else:
        # If no date is provided, we still use today's date for failed/scheduled
        # sections, but drafts will remain unfiltered by date.
        filter_date = timezone.localdate()
        date_filter = filter_date.isoformat()
    
    # Fetch bookings based on status for the specific date (if filter provided)
    # This ensures each date is treated separately
    if filter_date:
        # Draft: if user explicitly filtered by date, respect that; otherwise show all drafts
        if has_query_date:
            draft_allocations = TherapyAllocation.objects.filter(
                from_date__lte=filter_date,
                to_date__gte=filter_date,
                bookings__date=filter_date,
                bookings__status='draft'
            ).distinct().select_related('patient', 'room', 'timeslot').prefetch_related('bookings__assignments__therapist')
        else:
            draft_allocations = TherapyAllocation.objects.filter(
                bookings__status='draft'
            ).distinct().select_related('patient', 'room', 'timeslot').prefetch_related('bookings__assignments__therapist')

        # Failed: show allocations that have failed bookings for the effective date (query date or today)
        failed_allocations = TherapyAllocation.objects.filter(
            from_date__lte=filter_date,
            to_date__gte=filter_date,
            bookings__date=filter_date,
            bookings__status='failed'
        ).distinct().select_related('patient', 'room', 'timeslot').prefetch_related('bookings__assignments__therapist')
        
        # Filter out therapies with zero therapist requirements
        from reshedule import therapist_requirements
        failed_allocations = [alloc for alloc in failed_allocations if therapist_requirements(alloc).get("total", 1) > 0]
        
        # Scheduled: show allocations that have scheduled bookings for this date
        scheduled_allocations = TherapyAllocation.objects.filter(
            from_date__lte=filter_date,
            to_date__gte=filter_date,
            bookings__date=filter_date,
            bookings__status='scheduled'
        ).distinct()
        # Note: zero-therapist therapies (non-nurse) will be filtered out later at the
        # booking level so we keep this as a queryset for efficient select_related/prefetch
    else:
        # If no date filter, show allocations based on Booking status (not allocation status)
        # This ensures we check actual booking objects, not the allocation header status
        draft_allocations = TherapyAllocation.objects.filter(
            bookings__status='draft'
        ).distinct().select_related('patient', 'room', 'timeslot').prefetch_related('bookings__assignments__therapist')
        
        failed_allocations = TherapyAllocation.objects.filter(
            bookings__status='failed'
        ).distinct().select_related('patient', 'room', 'timeslot').prefetch_related('bookings__assignments__therapist')
        
        # Filter out therapies with zero therapist requirements
        from reshedule import therapist_requirements
        failed_allocations = [alloc for alloc in failed_allocations if therapist_requirements(alloc).get("total", 1) > 0]
        
        scheduled_allocations = TherapyAllocation.objects.filter(
            bookings__status='scheduled'
        ).distinct()
        # Note: zero-therapist therapies (non-nurse) will be filtered out later at the
        # booking level so we keep this as a queryset for efficient select_related/prefetch
    
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
        # Only apply date-based filtering for drafts when user has explicitly chosen a date
        if has_query_date:
            draft_bookings = Booking.objects.filter(
                date=filter_date,
                status='draft'
            ).select_related('allocation__patient', 'allocation', 'timeslot', 'room').prefetch_related('assignments__therapist')

        # Always date-filter scheduled bookings (defaulting to today when no query date)
        scheduled_bookings = Booking.objects.filter(
            date=filter_date,
            status='scheduled'
        ).select_related('allocation__patient', 'allocation', 'timeslot', 'room').prefetch_related(
            'assignments__therapist',
            'nurse_assignments__nurse',  # Prefetch nurse assignments
            'room_bookings__room'  # Prefetch RoomBooking for room lookup
        )
        
        # Separate therapist and nurse bookings
        # Filter out zero-therapist therapies (not nurse treatments) from scheduled bookings
        # These are treated as prescriptions and only appear in prescription scheduling PDF
        from .nurse_allocation import is_nurse_treatment
        from reshedule import therapist_requirements
        therapist_bookings = []
        nurse_bookings = []
        for booking in scheduled_bookings:
            is_nurse = is_nurse_treatment(booking.allocation.therapy_code, booking.allocation.therapy_name)
            therapy_req = therapist_requirements(booking.allocation)
            
            # Skip zero-therapist therapies (not nurse treatments) - they appear only in prescription PDF
            if not is_nurse and therapy_req.get("total", 1) == 0:
                continue  # Skip from scheduled list
            
            if is_nurse:
                nurse_bookings.append(booking)
            else:
                therapist_bookings.append(booking)
    
    # Separate therapist and nurse bookings for template
    therapist_bookings_list = []
    nurse_bookings_list = []
    if filter_date:
        from .nurse_allocation import is_nurse_treatment
        from reshedule import therapist_requirements
        for booking in scheduled_bookings:
            is_nurse = is_nurse_treatment(booking.allocation.therapy_code, booking.allocation.therapy_name)
            therapy_req = therapist_requirements(booking.allocation)

            # Skip zero-therapist therapies (not nurse treatments) - they appear only in prescription PDF
            if not is_nurse and therapy_req.get("total", 1) == 0:
                continue  # Skip from scheduled list

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
            # For drafts, only use date-based count when user explicitly filtered by date;
            # otherwise show total drafts across all dates.
            'draft_count': draft_bookings.count() if has_query_date and filter_date else draft_allocations.count(),
            'failed_count': len(failed_allocations) if isinstance(failed_allocations, list) else failed_allocations.count(),
            # Scheduled is always date-based (including default "today")
            'scheduled_count': scheduled_bookings.count(),
        }
    }
    
    return render(request, 'dashboards/scheduling/scheduling.html', context)


@scheduling_access_required
def user_therapy_entry_dashboard(request):
    """
    Display therapies entered by the currently logged-in user only.
    Shows draft, scheduled, and failed therapies with same columns as scheduling dashboard.
    Users can only see therapies they entered themselves.
    No user filter - automatically filters by request.user.
    """
    from .models import TherapyAllocation, Booking
    from django.db.models import Q
    
    # Get date filter from request
    date_filter = request.GET.get('date', '')
    
    # Parse date if provided
    filter_date = None
    if date_filter:
        try:
            filter_date = parse_date(date_filter)
        except Exception:
            filter_date = None
    
    # Filter by currently logged-in user only
    current_user = request.user if request.user.is_authenticated else None
    if not current_user:
        # If user is not authenticated, return empty results
        context = {
            'draft_allocations': TherapyAllocation.objects.none(),
            'draft_bookings': [],
            'scheduled_allocations': TherapyAllocation.objects.none(),
            'scheduled_bookings': [],
            'therapist_bookings': [],
            'nurse_bookings': [],
            'failed_allocations': [],
            'failed_bookings': [],
            'date_filter': date_filter,
            'stats': {
                'draft_count': 0,
                'failed_count': 0,
                'scheduled_count': 0,
            },
        }
        return render(request, 'dashboards/user_therapy_entry/user_therapy_entry.html', context)
    
    # Base queryset - filter by current user only
    base_query = TherapyAllocation.objects.filter(allocated_by=current_user)
    
    # Filter by date if provided
    if filter_date:
        base_query = base_query.filter(
            Q(from_date__lte=filter_date) & Q(to_date__gte=filter_date)
        )
    
    # Get draft therapies
    draft_allocations = base_query.filter(
        bookings__status='draft'
    ).distinct().select_related('patient', 'room', 'timeslot', 'allocated_by').prefetch_related('bookings__assignments__therapist')
    
    # Get failed therapies
    failed_allocations = base_query.filter(
        bookings__status='failed'
    ).distinct().select_related('patient', 'room', 'timeslot', 'allocated_by').prefetch_related('bookings__assignments__therapist')
    
    # Filter out therapies with zero therapist requirements
    from reshedule import therapist_requirements
    failed_allocations = [alloc for alloc in failed_allocations if therapist_requirements(alloc).get("total", 1) > 0]
    
    # Get scheduled therapies
    scheduled_allocations = base_query.filter(
        bookings__status='scheduled'
    ).distinct().select_related('patient', 'room', 'timeslot', 'allocated_by').prefetch_related(
        'bookings__assignments__therapist',
        'bookings__timeslot',
        'bookings__room'
    )
    
    # Get bookings - filter by current user only
    booking_query = Booking.objects.filter(allocation__allocated_by=current_user)
    
    # Filter by date if provided
    if filter_date:
        booking_query = booking_query.filter(date=filter_date)
    
    # Get bookings by status
    draft_bookings = booking_query.filter(status='draft').select_related(
        'allocation__patient', 'allocation', 'timeslot', 'room', 'allocation__allocated_by'
    ).prefetch_related('assignments__therapist').order_by('-date', '-created_at')
    
    scheduled_bookings = booking_query.filter(status='scheduled').select_related(
        'allocation__patient', 'allocation', 'timeslot', 'room', 'allocation__allocated_by'
    ).prefetch_related(
        'assignments__therapist',
        'nurse_assignments__nurse',
        'room_bookings__room'
    ).order_by('-date', '-created_at')
    
    failed_bookings = booking_query.filter(status='failed').select_related(
        'allocation__patient', 'allocation', 'timeslot', 'room', 'allocation__allocated_by'
    ).prefetch_related('assignments__therapist').order_by('-date', '-created_at')
    
    # Separate therapist and nurse bookings for scheduled
    from .nurse_allocation import is_nurse_treatment
    therapist_bookings_list = []
    nurse_bookings_list = []
    for booking in scheduled_bookings:
        is_nurse = is_nurse_treatment(booking.allocation.therapy_code, booking.allocation.therapy_name)
        therapy_req = therapist_requirements(booking.allocation)
        
        # Skip zero-therapist therapies (not nurse treatments)
        if not is_nurse and therapy_req.get("total", 1) == 0:
            continue
        
        if is_nurse:
            nurse_bookings_list.append(booking)
        else:
            therapist_bookings_list.append(booking)
    
    # Calculate stats - use bookings for accurate counts
    stats = {
        'draft_count': draft_bookings.count(),
        'failed_count': failed_bookings.count(),
        'scheduled_count': scheduled_bookings.count(),
    }
    
    context = {
        'draft_allocations': draft_allocations,
        'draft_bookings': draft_bookings,
        'scheduled_allocations': scheduled_allocations,
        'scheduled_bookings': scheduled_bookings,
        'therapist_bookings': therapist_bookings_list,
        'nurse_bookings': nurse_bookings_list,
        'failed_allocations': failed_allocations,
        'failed_bookings': failed_bookings,
        'date_filter': date_filter,
        'stats': stats,
        'current_user': current_user,
    }
    
    return render(request, 'dashboards/user_therapy_entry/user_therapy_entry.html', context)


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

    NOTE: This endpoint now returns JSON with summary stats instead of a debug PDF,
    so the frontend can show clear success/failed counts.
    """
    if request.method != 'POST':
        return JsonResponse({'error': 'POST method required'}, status=405)

    # Capture stdout for optional debug logging (not returned to frontend)
    debug_output_buffer = io.StringIO()

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

        # Redirect stdout to capture debug output (for server-side inspection only)
        with redirect_stdout(debug_output_buffer):
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
            print(f"[LEAVE UPDATE] {leave_update_result}")

            # Step 2: Trigger final allocation algorithm
            try:
                # Import final allocation functions
                from final_allocation import bulk_allocate_for_date

                # Run the final allocation algorithm
                allocation_result = bulk_allocate_for_date(date_filter)

                allocation_update_result = {
                    'success': bool(allocation_result.get('success')),
                    'result': allocation_result
                }
            except Exception as e:
                allocation_result = {}
                allocation_update_result = {
                    'success': False,
                    'error': str(e)
                }
            print(f"[ALLOCATION RESULT] {allocation_update_result}")

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
                nurse_allocation_result = {}
                nurse_allocation_update_result = {
                    'success': False,
                    'error': str(e)
                }
            print(f"[NURSE ALLOCATION RESULT] {nurse_allocation_update_result}")

        # Close debug buffer (content is not sent to client)
        debug_output_buffer.close()

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
                        'nurse_allocation': nurse_allocation_update_result,
                    }
                }
            )
        except Exception:
            pass

        # Build summary stats for frontend
        alloc_stats = allocation_result or allocation_update_result.get('result') or {}
        total_processed = alloc_stats.get('total_processed') or alloc_stats.get('total') or 0
        successful = alloc_stats.get('successful') or 0
        failed = alloc_stats.get('failed') if alloc_stats.get('failed') is not None else max(total_processed - successful, 0)

        overall_success = bool(leave_update_result.get('success') and allocation_update_result.get('success'))

        message = f"Final Schedule completed for {date_filter}."
        if total_processed:
            message += f" Processed {total_processed} therapies: {successful} successful, {failed} failed."

        return JsonResponse({
            'success': overall_success,
            'message': message,
            'stats': {
                'total_processed': total_processed,
                'successful': successful,
                'failed': failed,
                'leave': leave_update_result,
                'allocation': alloc_stats,
                'nurse_allocation': nurse_allocation_result,
            }
        })

    except Exception as e:
        # On error, ensure buffer is closed and return JSON error
        try:
            debug_output_buffer.close()
        except Exception:
            pass
        return JsonResponse({
            'success': False,
            'error': str(e),
            'message': 'Final Schedule failed'
        }, status=500)

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
        include_zero_therapist = request.GET.get('include_zero_therapist', 'false').lower() == 'true'  # For prescription PDF
        
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
                
                # Base queryset for this status/date
                base_bookings_qs = Booking.objects.filter(**booking_query).select_related(
                    'allocation__patient', 'allocation', 'timeslot', 'room'
                ).prefetch_related(
                    'assignments__therapist'
                )
                
                # For 'allocated' status (used by prescription scheduling PDF), we also want to
                # include zero‑therapist (non‑nurse) therapies. They are auto-scheduled as 'scheduled'
                # after Final Schedule, but we need to include them in the prescription PDF.
                # Note: base_bookings_qs already includes scheduled bookings, but we need to ensure
                # zero-therapist therapies are NOT filtered out later in the loop.
                if status_filter == 'allocated':
                    # base_bookings_qs already has scheduled bookings, which includes zero-therapist therapies
                    # We just need to make sure they're not filtered out in the conversion loop below
                    bookings = list(base_bookings_qs)
                else:
                    bookings = list(base_bookings_qs)
                
                from .nurse_allocation import is_nurse_treatment
                from reshedule import therapist_requirements
                
                # Convert bookings to JSON format
                for booking in bookings:
                    # Determine if this is a nurse treatment and get therapist requirements
                    # We only want to hide zero-therapist non‑nurse therapies from the
                    # therapy scheduling *lists* (scheduled/failed), but we still need
                    # them for the prescription PDF which uses status=allocated.
                    is_nurse = is_nurse_treatment(booking.allocation.therapy_code, booking.allocation.therapy_name)
                    therapy_req = therapist_requirements(booking.allocation)
                    
                    # Exclude zero-therapist therapies (not nurse treatments) from scheduled/failed views
                    # Keep them for 'allocated' status (used by prescription PDF) and 'draft'/'all'
                    # Note: 'allocated' status is used by prescription PDF which needs zero-therapist therapies
                    # The therapy scheduling dashboard uses 'scheduled' status, not 'allocated'
                    if status_filter in ('scheduled', 'failed'):
                        if not is_nurse and therapy_req.get("total", 1) == 0:
                            continue  # Skip zero-therapist therapies from scheduled/failed lists
                    
                    # For draft/all, include zero-therapist therapies
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
                        # Get all TherapistBooking records for this visit, therapists, date, and time_slot
                        # IMPORTANT: Must filter by date and time_slot to get the correct records for this specific booking
                        if therapist_masters and allocation:
                            tb_list = TherapistBooking.objects.filter(
                                visit=allocation,
                                therapist__in=therapist_masters.values(),
                                date=booking.date,  # Filter by booking date
                                time_slot=booking.timeslot,  # Filter by booking time_slot
                                status='BOOKED'
                            ).select_related('therapist', 'visit', 'time_slot')
                            # Create a map: therapist_code -> is_bathing
                            # ONLY use TherapistBooking.is_bathing field from Patient module
                            # IMPORTANT: For Dhara & Pizichil, ensure only ONE therapist is marked as bathing
                            bathing_found = False
                            for tb in tb_list:
                                if tb.therapist:
                                    therapist_code = tb.therapist.therapist_code
                                    # Only mark as bathing if is_bathing=True AND we haven't already found a bathing therapist
                                    if tb.is_bathing and not bathing_found:
                                        therapist_bookings[therapist_code] = True
                                        bathing_found = True
                                    else:
                                        # If this therapist has is_bathing=True but we already found one, set it to False
                                        # This ensures only ONE bathing therapist per visit
                                        therapist_bookings[therapist_code] = False
                                    # If is_bathing is False, explicitly set it
                                    if not tb.is_bathing:
                                        therapist_bookings[therapist_code] = False
                    except Exception as e:
                        print(f"Error pre-fetching TherapistBooking records: {e}")
                        import traceback
                        traceback.print_exc()
                    
                    # Check if this treatment requires special senior tag handling
                    requires_senior_tag = False
                    if allocation and allocation.therapy_name:
                        requires_senior_tag = is_treatment_requiring_senior_tag(allocation.therapy_name)
                    
                    # First pass: collect all therapists and identify seniors who are not bathing
                    therapist_data_list = []
                    senior_non_bathing_therapist_code = None
                    
                    for assignment in booking.assignments.all():
                        therapist_code = assignment.therapist.therapist_code
                        # Get is_bathing flag from pre-fetched data
                        is_bathing = therapist_bookings.get(therapist_code, False)
                        
                        # Get TherapistMaster to check grade (use TherapistMaster, not Patient.models.Therapist)
                        therapist_master = therapist_masters.get(therapist_code)
                        
                        # Check if this therapist is senior
                        is_senior_grade = False
                        if therapist_master and therapist_master.therapist_grade:
                            grade_name = getattr(therapist_master.therapist_grade, 'name', '')
                            if grade_name and 'Senior' in grade_name:
                                is_senior_grade = True
                        
                        therapist_name = assignment.therapist.therapist_name or therapist_code
                        grade_display = ''
                        if therapist_master and therapist_master.therapist_grade:
                            grade_display = getattr(therapist_master.therapist_grade, 'name', '')
                        
                        therapist_data_list.append({
                            'code': therapist_code,
                            'name': therapist_name,
                            'grade': grade_display,
                            'is_bathing': is_bathing,
                            'is_senior_grade': is_senior_grade
                        })
                        
                        # For special treatments: identify the first senior who is NOT bathing
                        if requires_senior_tag and is_senior_grade and not is_bathing and senior_non_bathing_therapist_code is None:
                            senior_non_bathing_therapist_code = therapist_code
                    
                    # Second pass: mark only one senior (non-bathing) with senior tag
                    for therapist_data in therapist_data_list:
                        is_senior = False
                        if requires_senior_tag:
                            # Only mark the first senior who is not bathing
                            if therapist_data['code'] == senior_non_bathing_therapist_code:
                                is_senior = True
                        
                        therapists.append({
                            'code': therapist_data['code'],
                            'name': therapist_data['name'],
                            'grade': therapist_data['grade'],
                            'is_bathing': therapist_data['is_bathing'],
                            'is_senior': is_senior
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
                    

                    # Determine if rescheduled (booking differs from allocation preferences)
                    is_rescheduled = False
                    if booking.status in ('scheduled', 'allocated', 'completed'):
                        # Check timeslot change
                        if booking.allocation.timeslot_id and booking.timeslot_id and booking.allocation.timeslot_id != booking.timeslot_id:
                            is_rescheduled = True
                        # Check room change
                        elif booking.allocation.room_id and booking.room_id and booking.allocation.room_id != booking.room_id:
                            is_rescheduled = True

                    data.append({
                        'id': booking.allocation.id,
                        'is_rescheduled': is_rescheduled,
                        'patient_id': booking.allocation.patient.id,
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
                        'allocated_by': booking.allocation.allocated_by.username if booking.allocation.allocated_by else None,
                        'usage': booking.allocation.usage or '',
                        'usage_array': booking.allocation.usage_array if hasattr(booking.allocation, 'usage_array') and booking.allocation.usage_array else [],
                        'items_groups': booking.allocation.items_groups if booking.allocation.items_groups else [],
                        'items': booking.allocation.items if hasattr(booking.allocation, 'items') and booking.allocation.items else [],
                        'dosage': booking.allocation.dosage if hasattr(booking.allocation, 'dosage') else '',
                        'uno': booking.allocation.uno if hasattr(booking.allocation, 'uno') else '',
                        'oil_class': booking.allocation.oil_class or ''
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
            from reshedule import therapist_requirements
            
            for allocation in allocations:
                # Skip therapies with zero therapist requirements (only for failed status)
                if status_filter == 'failed' and therapist_requirements(allocation).get("total", 1) == 0:
                    continue
                    # Check if this treatment requires special senior tag handling
                    requires_senior_tag = False
                    if allocation and allocation.therapy_name:
                        requires_senior_tag = is_treatment_requiring_senior_tag(allocation.therapy_name)
                    
                    # Get all therapist codes for this allocation to fetch TherapistMaster records
                    therapist_codes = []
                    for booking in allocation.bookings.all():
                        for assignment in booking.assignments.all():
                            therapist_codes.append(assignment.therapist.therapist_code)
                    
                    # Get all TherapistMaster records for this allocation
                    from masters.models import TherapistMaster
                    from Patient.models import TherapistBooking
                    therapist_masters_dict = {}
                    if therapist_codes:
                        therapist_masters_dict = {tm.therapist_code: tm for tm in TherapistMaster.objects.filter(
                            therapist_code__in=therapist_codes
                        )}
                    
                    # Pre-fetch TherapistBooking records to check bathing status
                    # Group by booking date and time_slot to get correct is_bathing flags per booking
                    therapist_bookings_dict = {}
                    if allocation and therapist_masters_dict:
                        # Get all bookings for this allocation to process each separately
                        for booking in allocation.bookings.all():
                            booking_date = booking.date
                            booking_timeslot = booking.timeslot
                            if not booking_date or not booking_timeslot:
                                continue
                            # Get TherapistBooking records for this specific booking (date + time_slot)
                            tb_list = TherapistBooking.objects.filter(
                                visit=allocation,
                                therapist__in=therapist_masters_dict.values(),
                                date=booking_date,  # Filter by booking date
                                time_slot=booking_timeslot,  # Filter by booking time_slot
                                status='BOOKED'
                            ).select_related('therapist', 'time_slot')
                            # Create a map: (therapist_code, booking_date, booking_timeslot) -> is_bathing
                            # This ensures we get the correct is_bathing flag for each booking
                            for tb in tb_list:
                                if tb.therapist:
                                    therapist_code = tb.therapist.therapist_code
                                    # Use a composite key to handle multiple bookings for same therapist
                                    key = (therapist_code, booking_date, booking_timeslot.id if booking_timeslot else None)
                                    therapist_bookings_dict[key] = tb.is_bathing
                    
                    # First pass: collect all therapists and identify seniors who are not bathing
                    therapist_data_list = []
                    senior_non_bathing_therapist_code = None
                    
                    for booking in allocation.bookings.all():
                        booking_date = booking.date
                        booking_timeslot = booking.timeslot
                        for assignment in booking.assignments.all():
                            therapist_code = assignment.therapist.therapist_code
                            # Get TherapistMaster to check grade (use TherapistMaster, not Patient.models.Therapist)
                            therapist_master = therapist_masters_dict.get(therapist_code)
                            
                            # Get is_bathing flag using composite key (therapist_code, date, time_slot)
                            key = (therapist_code, booking_date, booking_timeslot.id if booking_timeslot else None)
                            is_bathing = therapist_bookings_dict.get(key, False)
                            
                            # Check if this therapist is senior
                            is_senior_grade = False
                            if therapist_master and therapist_master.therapist_grade:
                                grade_name = getattr(therapist_master.therapist_grade, 'name', '')
                                if grade_name and 'Senior' in grade_name:
                                    is_senior_grade = True
                            
                            grade_display = ''
                            if therapist_master and therapist_master.therapist_grade:
                                grade_display = getattr(therapist_master.therapist_grade, 'name', '')
                            
                            therapist_data_list.append({
                                'code': therapist_code,
                                'name': assignment.therapist.therapist_name or therapist_code,
                                'grade': grade_display,
                                'is_bathing': is_bathing,
                                'is_senior_grade': is_senior_grade
                            })
                            
                            # For special treatments: identify the first senior who is NOT bathing
                            if requires_senior_tag and is_senior_grade and not is_bathing and senior_non_bathing_therapist_code is None:
                                senior_non_bathing_therapist_code = therapist_code
                    
                    # Second pass: mark only one senior (non-bathing) with senior tag
                    therapists = []
                    for therapist_data in therapist_data_list:
                        is_senior = False
                        if requires_senior_tag:
                            # Only mark the first senior who is not bathing
                            if therapist_data['code'] == senior_non_bathing_therapist_code:
                                is_senior = True
                        
                        therapists.append({
                            'code': therapist_data['code'],
                            'name': therapist_data['name'],
                            'grade': therapist_data['grade'],
                            'is_senior': is_senior
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
                        'patient_id': allocation.patient.id,
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
                        'allocated_by': allocation.allocated_by.username if allocation.allocated_by else None,
                        'usage': allocation.usage or '',
                        'usage_array': allocation.usage_array if hasattr(allocation, 'usage_array') and allocation.usage_array else [],
                        'items_groups': allocation.items_groups if allocation.items_groups else [],
                        'items': allocation.items if hasattr(allocation, 'items') and allocation.items else [],
                        'dosage': allocation.dosage if hasattr(allocation, 'dosage') else '',
                        'uno': allocation.uno if hasattr(allocation, 'uno') else '',
                        'oil_class': allocation.oil_class or ''
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
            # Get allocation - don't require status='failed' since failed is determined by booking status
            allocation = TherapyAllocation.objects.get(id=allocation_id)
            
            # Parse date
            target_date = parse_date(date)
            if not target_date:
                return JsonResponse({'error': 'Invalid date format. Use YYYY-MM-DD.'}, status=400)
            
            # Check if there's a failed booking for this date
            booking = Booking.objects.filter(allocation=allocation, date=target_date).first()
            if not booking:
                # Create booking if it doesn't exist (for rescheduling)
                booking = Booking.objects.create(
                    allocation=allocation,
                    date=target_date,
                    timeslot=allocation.timeslot,
                    room=allocation.room,
                    status='draft'
                )
            elif booking.status != 'failed':
                # If booking exists but is not failed, we can still reschedule it
                # This allows rescheduling draft or other status bookings
                pass
            
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
            return JsonResponse({'error': 'Therapy allocation not found'}, status=404)
            
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
    Captures all debug output and returns as PDF download.
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

        print(f"[RESCHEDULE ALL FAILED] Found {failed_allocations.count()} failed allocations for date {date}")

        if not failed_allocations.exists():
            return JsonResponse({
                'success': True,
                'message': f'No failed therapies found for {date} to reschedule.',
                'results': [],
                'stats': {
                    'total': 0,
                    'successful': 0,
                    'failed': 0,
                }
            })

        results = []
        success_count = 0
        failed_count = 0

        # Process each failed allocation
        for idx, allocation in enumerate(failed_allocations, 1):
            try:
                print(f"\n[RESCHEDULE {idx}/{failed_allocations.count()}] Processing allocation ID: {allocation.id}, Therapy: {allocation.therapy_name}")

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
                    print(f"  Created new booking for allocation {allocation.id}")

                # Call rescheduling algorithm
                print(f"  Calling allocate_therapy_for_visit for allocation {allocation.id}...")
                tasks = allocate_therapy_for_visit(
                    allocation.id,
                    date,
                    create_bookings=True
                )

                if isinstance(tasks, dict) and "error" in tasks:
                    # Algorithm returned an error
                    allocation.status = 'failed'
                    allocation.save(update_fields=['status'])
                    print(f"  ERROR: {tasks['error']}")
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

                    print(f"  Results: {len(success_tasks)} successful, {len(failed_tasks)} failed")

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
                        print(f"  FAILED: {reason}")
                        results.append({
                            'allocation_id': allocation.id,
                            'status': 'failed',
                            'reason': reason
                        })

            except Exception as e:
                print(f"  EXCEPTION: {str(e)}")
                allocation.status = 'failed'
                allocation.save(update_fields=['status'])
                results.append({
                    'allocation_id': allocation.id,
                    'status': 'failed',
                    'reason': str(e)
                })
                failed_count += 1

        total = failed_allocations.count()
        return JsonResponse({
            'success': True,
            'message': f'Reschedule All Failed completed for {date}. Total: {total}, successfully rescheduled: {success_count}, failed: {failed_count}.',
            'results': results,
            'stats': {
                'total': total,
                'successful': success_count,
                'failed': failed_count,
            }
        })

    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'error': 'Invalid JSON in request body'}, status=400)
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


# ============================================================================
# STANDALONE BULK EXCEL UPLOAD/DOWNLOAD FOR TESTING ALLOCATION ALGORITHM
# ============================================================================
# This is a completely separate page for testing purposes only.
# It does NOT interfere with any existing therapy entry or scheduling logic.
# ============================================================================

def therapy_bulk_excel(request):
    """
    Standalone page for bulk Excel upload/download to test allocation algorithm.
    
    - GET + ?action=download&date=YYYY-MM-DD: Download Excel with therapy data for that date
    - POST + action=upload: Upload Excel file to create TherapyAllocation + Booking records for testing
    
    This is completely isolated from existing therapy_entry and scheduling logic.
    """
    import io
    import pandas as pd
    from django.shortcuts import redirect
    from django.contrib import messages
    from django.http import HttpResponse
    from Sheduling.models import TherapyAllocation, Booking, PatientSnapshot
    from masters.models import SlotMaster, TherapyMaster
    
    action = (request.GET.get('action') or request.POST.get('action') or '').strip().lower()
    
    # ---- DOWNLOAD: GET with ?action=download&date=YYYY-MM-DD ----
    if request.method == 'GET' and action == 'download':
        date_str = (request.GET.get('date') or '').strip()
        target_date = parse_date(date_str) if date_str else None
        if not target_date:
            messages.error(request, "Please provide a valid date (YYYY-MM-DD).")
            return redirect('therapy_bulk_excel')
        
        # Get all bookings for that date
        bookings = (
            Booking.objects
            .select_related('allocation', 'allocation__patient', 'timeslot', 'room')
            .filter(date=target_date)
            .order_by('timeslot__slot_number', 'allocation__patient__pat_reg_no')
        )
        
        rows = []
        for b in bookings:
            alloc = b.allocation
            patient = getattr(alloc, 'patient', None)
            timeslot = b.timeslot
            required_roles = getattr(alloc, 'required_therapist_roles', []) or []
            
            rows.append({
                "patient_reg_no": getattr(patient, 'pat_reg_no', '') if patient else '',
                "patient_name": getattr(patient, 'pat_name', '') if patient else '',
                "therapy_code": alloc.therapy_code if alloc else '',
                "therapy_name": alloc.therapy_name if alloc else '',
                # Use slot_number as the portable code for import/export
                "timeslot_code": str(getattr(timeslot, 'slot_number', '')) if timeslot else '',
                "timeslot_label": str(timeslot) if timeslot else '',
                "date": b.date.isoformat(),
                "required_therapist_roles_json": json.dumps(required_roles, ensure_ascii=False),
                "ext_int": alloc.ext_int if alloc else '',
                "notes": alloc.notes if alloc else '',
            })
        
        # If no data, create template with headers only
        if not rows:
            rows.append({
                "patient_reg_no": "",
                "patient_name": "",
                "therapy_code": "",
                "therapy_name": "",
                "timeslot_code": "",
                "timeslot_label": "",
                "date": target_date.isoformat(),
                "required_therapist_roles_json": "[]",
                "ext_int": "",
                "notes": "",
            })
        
        # Create Excel file
        df = pd.DataFrame(rows)
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df.to_excel(writer, index=False, sheet_name='Therapies')
        output.seek(0)
        
        filename = f"therapy_data_{target_date.isoformat()}.xlsx"
        response = HttpResponse(
            output.read(),
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        response['Content-Disposition'] = f'attachment; filename="{filename}"'
        return response
    
    # ---- UPLOAD: POST with Excel file ----
    if request.method == 'POST' and action == 'upload':
        date_str = (request.POST.get('target_date') or '').strip()
        target_date = parse_date(date_str) if date_str else None
        file = request.FILES.get('excel_file')
        
        if not target_date:
            messages.error(request, "Please provide a valid target date (YYYY-MM-DD).")
            return redirect('therapy_bulk_excel')
        if not file:
            messages.error(request, "Please choose an Excel (.xlsx) file to upload.")
            return redirect('therapy_bulk_excel')
        
        # Read Excel
        try:
            df = pd.read_excel(file)
        except Exception as e:
            messages.error(request, f"Error reading Excel file: {e}")
            return redirect('therapy_bulk_excel')
        
        # Normalize column names (case-insensitive)
        df_columns = {str(c).strip().lower(): c for c in df.columns}
        required_cols = ["patient_reg_no", "therapy_code", "therapy_name", "timeslot_code"]
        missing = [c for c in required_cols if c not in df_columns]
        if missing:
            messages.error(
                request,
                f"Missing required columns in Excel: {', '.join(missing)}. "
                "Please download a sample file and use the same headers."
            )
            return redirect('therapy_bulk_excel')
        
        created_alloc = 0
        created_bookings = 0
        skipped_rows = 0
        errors = []
        
        with transaction.atomic():
            # Delete existing draft bookings for target date (clean slate for testing)
            Booking.objects.filter(date=target_date, status='draft').delete()
            
            for idx, row in df.iterrows():
                try:
                    pat_reg_no = str(row[df_columns["patient_reg_no"]]).strip()
                    therapy_code = str(row[df_columns["therapy_code"]]).strip()
                    therapy_name = str(row[df_columns["therapy_name"]]).strip()
                    timeslot_code = str(row[df_columns["timeslot_code"]]).strip()
                    
                    # Skip empty rows
                    if not pat_reg_no or (not therapy_code and not therapy_name) or not timeslot_code:
                        skipped_rows += 1
                        continue
                    
                    # Use per-row date if provided, else use target_date
                    row_date = target_date
                    if "date" in df_columns:
                        try:
                            cell = row[df_columns["date"]]
                            if pd.notna(cell):
                                if isinstance(cell, str):
                                    d = parse_date(cell)
                                else:
                                    d = cell.date() if hasattr(cell, "date") else cell
                                if d:
                                    row_date = d
                        except Exception:
                            pass
                    
                    # Find patient
                    patient = PatientSnapshot.objects.filter(pat_reg_no=pat_reg_no).first()
                    if not patient:
                        errors.append(f"Row {idx+2}: Patient '{pat_reg_no}' not found; skipped.")
                        skipped_rows += 1
                        continue
                    
                    # Find timeslot
                    # We use SlotMaster.slot_number as the code in Excel; fall back to slot_name if needed
                    slot = None
                    if timeslot_code.isdigit():
                        try:
                            slot = SlotMaster.objects.filter(slot_number=int(timeslot_code)).first()
                        except Exception:
                            slot = None
                    if not slot:
                        slot = SlotMaster.objects.filter(slot_name__iexact=timeslot_code).first()
                    if not slot:
                        errors.append(f"Row {idx+2}: Timeslot '{timeslot_code}' not found; skipped.")
                        skipped_rows += 1
                        continue
                    
                    # Find therapy master
                    therapy_master = None
                    if therapy_code:
                        therapy_master = TherapyMaster.objects.filter(therapy_code__iexact=therapy_code).first()
                    if not therapy_master and therapy_name:
                        therapy_master = TherapyMaster.objects.filter(therapy_name__iexact=therapy_name).first()
                    
                    # Parse required_therapist_roles JSON
                    required_roles = []
                    if "required_therapist_roles_json" in df_columns:
                        raw = row[df_columns["required_therapist_roles_json"]]
                        if pd.notna(raw):
                            try:
                                required_roles = json.loads(str(raw))
                            except Exception:
                                pass
                    
                    # Create TherapyAllocation
                    alloc = TherapyAllocation.objects.create(
                        patient=patient,
                        therapy_code=therapy_master.therapy_code if therapy_master else therapy_code,
                        therapy_name=therapy_master.therapy_name if therapy_master else therapy_name,
                        ext_int=getattr(therapy_master, 'ext_int', '') if therapy_master else (str(row.get(df_columns.get("ext_int", ""), "")) if "ext_int" in df_columns else ''),
                        timeslot=slot,
                        room=None,
                        items_groups=[],
                        oil_class=getattr(therapy_master, 'oil_class', '') if therapy_master else '',
                        usage=getattr(therapy_master, 'usage', '') if therapy_master else '',
                        procured_from='',
                        from_date=row_date,
                        to_date=row_date,
                        days=1,
                        required_therapist_roles=required_roles,
                        allocated_by=request.user if request.user.is_authenticated else None,
                        locked=False,
                        notes=str(row.get(df_columns.get("notes", ""), "")) if "notes" in df_columns else '',
                        status='draft',
                    )
                    created_alloc += 1
                    
                    # Create Booking
                    Booking.objects.create(
                        allocation=alloc,
                        date=row_date,
                        timeslot=slot,
                        room=None,
                        status='draft',
                        therapist_note='',
                    )
                    created_bookings += 1
                    
                except Exception as e:
                    errors.append(f"Row {idx+2}: {str(e)}")
                    skipped_rows += 1
        
        # Show results
        msg = f"Import completed. Created {created_alloc} allocations and {created_bookings} bookings for date {target_date.isoformat()}."
        if skipped_rows:
            msg += f" Skipped {skipped_rows} rows."
        messages.success(request, msg)
        if errors:
            for e in errors[:10]:
                messages.warning(request, e)
            if len(errors) > 10:
                messages.warning(request, f"...and {len(errors)-10} more errors (see server logs).")
        
        return redirect('therapy_bulk_excel')
    
    # Default: render the page
    return render(request, "dashboards/scheduling/therapy_bulk_excel.html")