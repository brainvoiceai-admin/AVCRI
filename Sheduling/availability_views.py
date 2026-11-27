from django.shortcuts import render
from django.http import JsonResponse
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_http_methods
from django.views.decorators.csrf import csrf_exempt
from django.db.models import Q
from datetime import datetime, date, timedelta
import json

from .models import (
    TherapyAllocation, Booking, BookingItem, BookingAssignment, 
    PatientSnapshot, PrescriptionScheduling, PrescriptionItem
)
from masters.models import SlotMaster, TherapistMaster, TherapistLeaveMaster, EmergencyLeave
from Patient.models import TherapistBooking, RoomBooking
from authentication.models import CustomUser


@login_required
def therapist_availability_dashboard(request):
    """Render the therapist availability dashboard page"""
    return render(request, 'dashboards/therapist/therapist_availability.html')


@login_required
@require_http_methods(["GET"])
def get_available_therapists_api(request):
    """API to get available therapists based on filters"""
    try:
        selected_date = request.GET.get('date')
        time_slot = request.GET.get('time')
        gender = request.GET.get('gender')
        
        if not selected_date:
            return JsonResponse({'error': 'Date parameter is required'}, status=400)
        
        # Parse the date
        try:
            target_date = datetime.strptime(selected_date, '%Y-%m-%d').date()
        except ValueError:
            return JsonResponse({'error': 'Invalid date format'}, status=400)
        
        # Get all active therapists from master table
        # Use select_related to get grade information efficiently
        therapists_query = TherapistMaster.objects.filter(is_active=True).select_related('therapist_grade')
        
        # Primary vs Helping Therapist filtering
        therapist_type = (request.GET.get('therapist_type') or 'primary').strip().lower()
        include_helping = request.GET.get('include_helping') in ['1', 'true', 'True'] or request.GET.get('ignore_leave') in ['1', 'true', 'True'] or request.GET.get('include_all') in ['1', 'true', 'True']
        
        if not include_helping:
            if therapist_type == 'primary':
                therapists_query = therapists_query.filter(is_helping_therapist=False)
            elif therapist_type == 'helping':
                therapists_query = therapists_query.filter(is_helping_therapist=True)
        
        # Filter by gender if specified - use therapist_gender column from TherapistMaster
        if gender and gender != 'all':
            # Normalize gender values for comparison
            gender_lower = gender.lower()
            # Build filter for therapist_gender field (primary source)
            if gender_lower in ['male', 'm']:
                # Match 'Male', 'male', 'M', 'm' in therapist_gender
                therapists_query = therapists_query.filter(
                    Q(therapist_gender__iexact='male') | 
                    Q(therapist_gender__iexact='m') |
                    Q(therapist_gender__istartswith='male')
                )
            elif gender_lower in ['female', 'f']:
                # Match 'Female', 'female', 'F', 'f' in therapist_gender
                therapists_query = therapists_query.filter(
                    Q(therapist_gender__iexact='female') | 
                    Q(therapist_gender__iexact='f') |
                    Q(therapist_gender__istartswith='female')
                )
        
        # Get therapists who are on recurring leave for this date
        # TherapistLeaveMaster model uses leave_day (day of week: 0=Monday, 1=Tuesday, etc.)
        day_of_week = target_date.weekday()  # 0=Monday, 1=Tuesday, ..., 6=Sunday
        recurring_leave_therapist_ids = TherapistLeaveMaster.objects.filter(
            leave_day=day_of_week,
            is_active=True
        ).values_list('therapist_id', flat=True)
        
        # Parse slot if specified
        slot_master = None
        if time_slot:
            try:
                for fmt in ('%H:%M', '%H:%M:%S', '%I:%M %p', '%I:%M%p'):
                    try:
                        time_obj = datetime.strptime(time_slot.strip(), fmt).time()
                        slot_master = SlotMaster.objects.filter(slot_time=time_obj, is_active=True).first()
                        if slot_master:
                            break
                    except Exception:
                        continue
                if not slot_master and str(time_slot).strip().isdigit():
                    slot_master = SlotMaster.objects.filter(slot_number=int(time_slot), is_active=True).first()
            except Exception:
                slot_master = None

        # Check if caller requested to ignore leave (e.g. for therapist preference/exclusion dropdowns)
        ignore_leave = request.GET.get('ignore_leave') in ['1', 'true', 'True'] or request.GET.get('all') in ['1', 'true', 'True']

        if not ignore_leave:
            # Exclude therapists on recurring leave
            available_therapists = therapists_query.exclude(
                pk__in=recurring_leave_therapist_ids
            )
            
            # Emergency leave check: if slot is known, exclude only therapists on leave for that slot
            emergency_leave_qs = EmergencyLeave.objects.filter(
                from_date__lte=target_date,
                to_date__gte=target_date
            )
            if slot_master:
                active_leaves = [el for el in emergency_leave_qs if el.is_slot_on_leave(target_date, slot_master)]
            else:
                active_leaves = list(emergency_leave_qs)

            em_therapist_ids = set(el.therapist_id for el in active_leaves if el.therapist_id)
            em_emp_codes = set(el.employee_code for el in active_leaves if el.employee_code)
            if em_emp_codes:
                em_by_code = set(
                    TherapistMaster.objects.filter(employee_code__in=em_emp_codes).values_list('id', flat=True)
                )
                em_therapist_ids |= em_by_code

            if em_therapist_ids:
                available_therapists = available_therapists.exclude(pk__in=em_therapist_ids)

            # Deputation check: exclude therapists on approved deputation covering target_date
            from masters.models import get_deputed_therapist_ids_for_date
            deputed_ids = get_deputed_therapist_ids_for_date(target_date)
            if deputed_ids:
                available_therapists = available_therapists.exclude(pk__in=deputed_ids)

            # On-call check: exclude on-call therapists who are turned OFF, outside date range, or not available for slot
            from masters.models import get_inactive_on_call_therapist_ids
            inactive_on_call_ids = get_inactive_on_call_therapist_ids(target_date, slot_master)
            if inactive_on_call_ids:
                available_therapists = available_therapists.exclude(pk__in=inactive_on_call_ids)

            # Treatment Omission check: exclude therapists with approved omission for specified treatment
            treatment_param = (
                request.GET.get('treatment') or 
                request.GET.get('therapy') or 
                request.GET.get('therapy_name') or 
                request.GET.get('treatment_name')
            )
            if treatment_param:
                from masters.models import get_omitted_therapist_ids_for_treatment
                omitted_ids = get_omitted_therapist_ids_for_treatment(treatment_param)
                if omitted_ids:
                    available_therapists = available_therapists.exclude(pk__in=omitted_ids)
        else:
            available_therapists = therapists_query
        
        # If time slot is specified, check availability using SlotMaster and TherapistBooking
        if time_slot:
            try:
                if slot_master:
                    # Shift eligibility filter (additive): applies only when shift masters are configured
                    try:
                        from masters.models import ShiftSlotMapping, TherapistShiftMapping

                        shift_filter_enabled = (
                            ShiftSlotMapping.objects.filter(is_active=True).exists()
                            and TherapistShiftMapping.objects.filter(is_active=True).exists()
                        )

                        if shift_filter_enabled:
                            mapped_ids = set(
                                TherapistShiftMapping.objects.filter(is_active=True).values_list(
                                    "therapist_id", flat=True
                                ).distinct()
                            )
                            if mapped_ids:
                                eligible_ids = set(
                                    TherapistShiftMapping.objects.filter(
                                        is_active=True,
                                        shift__shift_slots__slot=slot_master,
                                        shift__shift_slots__is_active=True,
                                    ).values_list("therapist_id", flat=True).distinct()
                                )
                                on_call_ids = set(TherapistMaster.objects.filter(is_on_call=True).values_list("id", flat=True))
                                disallowed_ids = (mapped_ids - eligible_ids) - on_call_ids
                                if disallowed_ids:
                                    available_therapists = available_therapists.exclude(pk__in=disallowed_ids)
                    except Exception:
                        # fail-open: do not block scheduling if shift configuration is incomplete
                        pass

                    # Get therapists who have bookings at this time slot using TherapistBooking
                    booked_therapist_ids = TherapistBooking.objects.filter(
                        date=target_date,
                        time_slot=slot_master,
                        status='BOOKED'
                    ).values_list('therapist_id', flat=True)
                    
                    # Exclude therapists who are already booked
                    available_therapists = available_therapists.exclude(
                        pk__in=booked_therapist_ids
                    )
                else:
                    # If slot master not found, return error
                    return JsonResponse({
                        'error': f'Time slot {time_slot} not found in SlotMaster',
                        'success': False
                    }, status=400)
            except ValueError:
                return JsonResponse({'error': 'Invalid time format'}, status=400)
        
        # Prepare therapist data
        # Ensure we get fresh data by evaluating the queryset
        therapists_list = list(available_therapists)
        therapists_data = []
        for therapist in therapists_list:
            # Get gender - use therapist_gender field directly from TherapistMaster
            # Access the field directly without any fallbacks
            therapist_gender_val = getattr(therapist, 'therapist_gender', None)
            if therapist_gender_val:
                # Strip whitespace and get the value
                therapist_gender_val = str(therapist_gender_val).strip()
            
            # Format gender for display based on therapist_gender field
            gender_display = 'Unknown'
            if therapist_gender_val:
                therapist_gender_lower = therapist_gender_val.lower()
                # Check for male variations
                if therapist_gender_lower in ['male', 'm'] or therapist_gender_lower.startswith('male'):
                    gender_display = 'Male'
                # Check for female variations
                elif therapist_gender_lower in ['female', 'f'] or therapist_gender_lower.startswith('female'):
                    gender_display = 'Female'
                else:
                    # If it's not clearly male or female, use the original value
                    gender_display = therapist_gender_val
            
            # Get grade name directly
            grade_name = None
            if therapist.therapist_grade:
                grade_name = therapist.therapist_grade.name
            
            therapist_data = {
                'id': therapist.pk,
                'name': therapist.therapist_name,
                'code': therapist.therapist_code,
                'employee_code': therapist.employee_code,
                'gender': gender_display,  # This should be 'Male', 'Female', or 'Unknown'
                'grade': grade_name,  # Grade name from TherapistGrade model
                'is_bathing': therapist.is_bathing_therapist,
                'is_helping_therapist': getattr(therapist, 'is_helping_therapist', False),
                'is_on_call': getattr(therapist, 'is_on_call', False),
                'is_active': therapist.is_active,
                'specialization': 'General Therapy'  # Default specialization
            }
            therapists_data.append(therapist_data)
        
        return JsonResponse({
            'success': True,
            'therapists': therapists_data,
            'total_count': len(therapists_data)
        })
        
    except Exception as e:
        print(f"Error in get_available_therapists_api: {e}")
        import traceback
        traceback.print_exc()
        return JsonResponse({'error': str(e)}, status=500)


@login_required
@require_http_methods(["GET"])
def get_therapists_on_leave_api(request):
    """API to get therapists on leave for a specific date (both recurring and emergency leaves)"""
    try:
        selected_date = request.GET.get('date')
        gender = request.GET.get('gender')
        leave_type = (request.GET.get('leave_type') or 'all').strip().lower()
        leave_type = leave_type.replace('-', '_').replace(' ', '_')
        
        if not selected_date:
            return JsonResponse({'error': 'Date parameter is required'}, status=400)
        
        # Parse the date
        try:
            target_date = datetime.strptime(selected_date, '%Y-%m-%d').date()
        except ValueError:
            return JsonResponse({'error': 'Invalid date format'}, status=400)
        
        leave_data = []
        include_week_off = leave_type in ['all', 'week_off', 'weekoff']
        include_leave = leave_type in ['all', 'leave', 'emergency_leave', 'emergency']
        
        # Get therapists on recurring leave for this date
        # TherapistLeaveMaster model uses leave_day (day of week: 0=Monday, 1=Tuesday, etc.)
        if include_week_off:
            day_of_week = target_date.weekday()  # 0=Monday, 1=Tuesday, ..., 6=Sunday
            recurring_leave_query = TherapistLeaveMaster.objects.filter(
                leave_day=day_of_week,
                is_active=True
            )
            
            # Filter by gender if specified - use therapist_gender column from TherapistMaster
            if gender and gender != 'all':
                gender_lower = gender.lower()
                if gender_lower in ['male', 'm']:
                    recurring_leave_query = recurring_leave_query.filter(
                        Q(therapist__therapist_gender__iexact='male') | 
                        Q(therapist__therapist_gender__iexact='m') |
                        Q(therapist__therapist_gender__istartswith='male')
                    )
                elif gender_lower in ['female', 'f']:
                    recurring_leave_query = recurring_leave_query.filter(
                        Q(therapist__therapist_gender__iexact='female') | 
                        Q(therapist__therapist_gender__iexact='f') |
                        Q(therapist__therapist_gender__istartswith='female')
                    )
            
            # Get recurring leave records with therapist details
            recurring_leave_records = recurring_leave_query.select_related('therapist')
            
            # Process recurring leaves
            for leave_record in recurring_leave_records:
                therapist = leave_record.therapist
                # Get gender - use therapist_gender field directly from TherapistMaster
                therapist_gender_val = None
                if therapist.therapist_gender:
                    therapist_gender_val = str(therapist.therapist_gender).strip()
                
                # Format gender for display
                gender_display = 'Unknown'
                if therapist_gender_val:
                    therapist_gender_lower = therapist_gender_val.lower()
                    if therapist_gender_lower in ['male', 'm'] or therapist_gender_lower.startswith('male'):
                        gender_display = 'Male'
                    elif therapist_gender_lower in ['female', 'f'] or therapist_gender_lower.startswith('female'):
                        gender_display = 'Female'
                    else:
                        gender_display = therapist_gender_val
                
                # Get grade name directly
                grade_name = None
                if therapist.therapist_grade:
                    grade_name = therapist.therapist_grade.name
                
                leave_info = {
                    'id': therapist.pk,
                    'name': therapist.therapist_name,
                    'code': therapist.therapist_code,
                    'employee_code': therapist.employee_code,
                    'gender': gender_display,  # This should be 'Male', 'Female', or 'Unknown'
                    'grade': grade_name,  # Grade name from TherapistGrade model
                    'leave_date': target_date.strftime('%Y-%m-%d'),
                    'leave_day': leave_record.leave_day,
                    'leave_day_name': leave_record.leave_day_name,
                    'leave_type': 'Week Off',
                    'from_date': target_date.strftime('%Y-%m-%d'),
                    'to_date': target_date.strftime('%Y-%m-%d'),
                    'reason': '',  # No reason field in current model
                    'is_bathing': therapist.is_bathing_therapist,
                    'is_active': leave_record.is_active
                }
                leave_data.append(leave_info)
        
        # Get therapists on emergency leave for this date
        if include_leave:
            emergency_leave_query = EmergencyLeave.objects.filter(
                from_date__lte=target_date,
                to_date__gte=target_date
            ).select_related('therapist')
            
            # Process emergency leaves
            emergency_therapist_ids = set()
            for em_leave in emergency_leave_query:
                # Get therapist either from FK or by employee_code
                therapist = None
                if em_leave.therapist:
                    therapist = em_leave.therapist
                elif em_leave.employee_code:
                    therapist = TherapistMaster.objects.filter(
                        employee_code=em_leave.employee_code,
                        is_active=True
                    ).first()
                
                if therapist and therapist.pk not in emergency_therapist_ids:
                    emergency_therapist_ids.add(therapist.pk)
                    
                    # Filter by gender if specified - use therapist_gender column
                    if gender and gender != 'all':
                        therapist_gender_val = None
                        if therapist.therapist_gender:
                            therapist_gender_val = therapist.therapist_gender.lower()
                        
                        if not therapist_gender_val:
                            continue  # Skip if therapist_gender is not set
                        
                        gender_lower = gender.lower()
                        # Check if therapist_gender matches the filter
                        if gender_lower in ['male', 'm']:
                            if therapist_gender_val not in ['male', 'm'] and not therapist_gender_val.startswith('male'):
                                continue
                        elif gender_lower in ['female', 'f']:
                            if therapist_gender_val not in ['female', 'f'] and not therapist_gender_val.startswith('female'):
                                continue
                    
                    # Get gender for display - use therapist_gender field directly
                    therapist_gender_val = None
                    if therapist.therapist_gender:
                        therapist_gender_val = str(therapist.therapist_gender).strip()
                    
                    # Format gender for display
                    gender_display = 'Unknown'
                    if therapist_gender_val:
                        therapist_gender_lower = therapist_gender_val.lower()
                        if therapist_gender_lower in ['male', 'm'] or therapist_gender_lower.startswith('male'):
                            gender_display = 'Male'
                        elif therapist_gender_lower in ['female', 'f'] or therapist_gender_lower.startswith('female'):
                            gender_display = 'Female'
                        else:
                            gender_display = therapist_gender_val
                    
                    # Get grade name directly
                    grade_name = None
                    if therapist.therapist_grade:
                        grade_name = therapist.therapist_grade.name
                    
                    leave_info = {
                        'id': therapist.pk,
                        'name': therapist.therapist_name,
                        'code': therapist.therapist_code,
                        'employee_code': therapist.employee_code,
                        'gender': gender_display,  # This should be 'Male', 'Female', or 'Unknown'
                        'grade': grade_name,  # Grade name from TherapistGrade model
                        'leave_date': target_date.strftime('%Y-%m-%d'),
                        'leave_day': None,
                        'leave_day_name': None,
                        'leave_type': 'Emergency Leave',
                        'from_date': em_leave.from_date.strftime('%Y-%m-%d'),
                        'to_date': em_leave.to_date.strftime('%Y-%m-%d'),
                        'reason': em_leave.leave_type or '',  # Show leave_type as reason if available
                        'is_bathing': therapist.is_bathing_therapist,
                        'is_active': True
                    }
                    leave_data.append(leave_info)

        # Get therapists on approved deputation for this date
        from masters.models import TherapistDeputation
        deputed_query = TherapistDeputation.objects.filter(
            status='approved',
            start_date__lte=target_date,
            end_date__gte=target_date
        ).select_related('therapist', 'therapist__therapist_grade', 'assigned_doctor')
        
        for dep in deputed_query:
            therapist = dep.therapist
            if therapist:
                if gender and gender != 'all':
                    t_gen = (therapist.therapist_gender or '').lower()
                    if gender.lower().startswith('m') and not t_gen.startswith('m'):
                        continue
                    if gender.lower().startswith('f') and not t_gen.startswith('f'):
                        continue
                leave_info = {
                    'id': therapist.pk,
                    'name': therapist.therapist_name,
                    'code': therapist.therapist_code,
                    'employee_code': therapist.employee_code,
                    'gender': therapist.therapist_gender or 'Unknown',
                    'grade': therapist.therapist_grade.name if therapist.therapist_grade else 'N/A',
                    'leave_date': target_date.strftime('%Y-%m-%d'),
                    'leave_day': target_date.weekday(),
                    'leave_day_name': target_date.strftime('%A'),
                    'leave_type': 'Deputed',
                    'from_date': dep.start_date.strftime('%Y-%m-%d'),
                    'to_date': dep.end_date.strftime('%Y-%m-%d') if dep.end_date else '',
                    'reason': f"Deputed to {dep.destination} ({dep.duration_days} days). Assigned Doctor: {dep.assigned_doctor_name or 'N/A'}",
                    'is_bathing': therapist.is_bathing_therapist,
                    'is_active': True
                }
                leave_data.append(leave_info)
        
        return JsonResponse({
            'success': True,
            'leaves': leave_data,
            'total_count': len(leave_data)
        })
        
    except Exception as e:
        print(f"Error in get_therapists_on_leave_api: {e}")
        import traceback
        traceback.print_exc()
        return JsonResponse({'error': str(e)}, status=500)


@login_required
@require_http_methods(["GET"])
def get_time_slots_api(request):
    """API to get available time slots"""
    try:
        # Get time slots from SlotMaster (using slot_time field)
        time_slots = SlotMaster.objects.filter(is_active=True).order_by('slot_time')
        
        slots_data = []
        for slot in time_slots:
            # Format slot_time in 12-hour format for display
            time_12hr = slot.slot_time.strftime('%I:%M %p').lstrip('0')
            slot_name = slot.slot_name or f"Slot {slot.slot_number}"
            slots_data.append({
                'id': slot.pk,
                'start_time': slot.slot_time.strftime('%H:%M'),
                'slot_name': slot_name,
                'display_name': f"{slot_name} ({time_12hr})",
                'time_12hr': time_12hr,
                'slot_number': slot.slot_number
            })
        
        # If no time slots in database, return default hospital slots
        if not slots_data:
            default_slots = [
                {'id': 1, 'start_time': '06:30', 'slot_name': 'Slot 1', 'display_name': 'Slot 1 (6:30 AM)', 'time_12hr': '6:30 AM', 'slot_number': 1},
                {'id': 2, 'start_time': '08:30', 'slot_name': 'Slot 2', 'display_name': 'Slot 2 (8:30 AM)', 'time_12hr': '8:30 AM', 'slot_number': 2},
                {'id': 3, 'start_time': '10:00', 'slot_name': 'Slot 3', 'display_name': 'Slot 3 (10:00 AM)', 'time_12hr': '10:00 AM', 'slot_number': 3},
                {'id': 4, 'start_time': '11:30', 'slot_name': 'Slot 4', 'display_name': 'Slot 4 (11:30 AM)', 'time_12hr': '11:30 AM', 'slot_number': 4},
                {'id': 5, 'start_time': '14:30', 'slot_name': 'Slot 5', 'display_name': 'Slot 5 (2:30 PM)', 'time_12hr': '2:30 PM', 'slot_number': 5},
                {'id': 6, 'start_time': '16:00', 'slot_name': 'Slot 6', 'display_name': 'Slot 6 (4:00 PM)', 'time_12hr': '4:00 PM', 'slot_number': 6},
                {'id': 7, 'start_time': '17:30', 'slot_name': 'Slot 7', 'display_name': 'Slot 7 (5:30 PM)', 'time_12hr': '5:30 PM', 'slot_number': 7},
            ]
            slots_data = default_slots
        
        return JsonResponse({
            'success': True,
            'time_slots': slots_data
        })
        
    except Exception as e:
        print(f"Error in get_time_slots_api: {e}")
        return JsonResponse({'error': str(e), 'success': False}, status=500)


# ============================================
# TREATMENT ROOM AVAILABILITY VIEWS
# ============================================

def _resolve_slot_master(time_slot_param):
    """
    Robustly resolves a SlotMaster instance from various possible representations:
    - SlotMaster PK / ID (int or numeric string)
    - slot_number (e.g. 1, 2, 3...)
    - 24-hr time ('06:30', '06:30:00')
    - 12-hr time ('6:30 AM', '06:30 PM')
    - slot_name ('Slot 1', 'Vamanam Slot...')
    Returns (slot_master, error_message). If time_slot_param is empty or 'all', returns (None, None).
    """
    if not time_slot_param or str(time_slot_param).strip().lower() in ['', 'all', 'none', 'null']:
        return None, None
        
    time_str = str(time_slot_param).strip()
    
    # Check if numeric (PK or slot_number)
    if time_str.isdigit():
        val = int(time_str)
        sm = SlotMaster.objects.filter(pk=val).first()
        if sm:
            return sm, None
        sm = SlotMaster.objects.filter(slot_number=val).first()
        if sm:
            return sm, None

    # Try parsing time formats
    for fmt in ('%H:%M', '%H:%M:%S', '%I:%M %p', '%I:%M%p'):
        try:
            t = datetime.strptime(time_str, fmt).time()
            sm = SlotMaster.objects.filter(slot_time=t).first()
            if not sm:
                sm = SlotMaster.objects.filter(
                    slot_time__hour=t.hour,
                    slot_time__minute=t.minute
                ).first()
            if sm:
                return sm, None
        except ValueError:
            continue

    # Try matching by slot name
    sm = SlotMaster.objects.filter(slot_name__iexact=time_str).first()
    if not sm:
        sm = SlotMaster.objects.filter(slot_name__icontains=time_str).first()
    if sm:
        return sm, None

    return None, f"Time slot '{time_slot_param}' not found in SlotMaster"


def _get_unified_occupied_rooms(target_date, slot_master=None, floor=None):
    """
    Consolidates room occupancy from both Sheduling.Booking and Patient.RoomBooking.
    Ensures cancelled/failed bookings and cancelled allocations are excluded.
    Returns a unified list of occupied room dictionaries.
    """
    from Patient.models import RoomBooking
    from Sheduling.models import Booking, PatientSnapshot
    from django.db.models import Q

    # 1. Query Sheduling.Booking (active, scheduled therapies)
    b_qs = Booking.objects.filter(
        date=target_date,
        room__isnull=False
    ).exclude(
        status__in=['cancelled', 'failed', 'draft']
    ).exclude(
        allocation__status__in=['cancelled', 'failed']
    ).select_related(
        'room', 'timeslot', 'allocation', 'allocation__patient'
    ).prefetch_related(
        'assignments__therapist', 'nurse_assignments__nurse'
    )
    if slot_master:
        b_qs = b_qs.filter(timeslot=slot_master)
    if floor and floor != 'all':
        b_qs = b_qs.filter(room__floor=floor)

    # 2. Query Patient.RoomBooking (booked treatment room slots)
    # Crucial: exclude rows where visit, allocation, or therapy was cancelled!
    rb_qs = RoomBooking.objects.filter(
        date=target_date,
        status='BOOKED'
    ).exclude(
        Q(visit__status__in=['cancelled', 'failed', 'draft']) |
        Q(visit__allocation__status__in=['cancelled', 'failed']) |
        Q(therapy__status__in=['cancelled', 'failed'])
    ).select_related(
        'room', 'time_slot', 'visit', 'visit__allocation', 'visit__allocation__patient',
        'therapy', 'therapy__patient'
    ).prefetch_related(
        'visit__assignments__therapist', 'visit__nurse_assignments__nurse'
    )
    if slot_master:
        rb_qs = rb_qs.filter(time_slot=slot_master)
    if floor and floor != 'all':
        rb_qs = rb_qs.filter(room__floor=floor)

    occupied_map = {}

    def _format_slot(slot_obj):
        if not slot_obj:
            return 'N/A'
        try:
            t_str = slot_obj.slot_time.strftime('%I:%M %p').lstrip('0')
            s_name = slot_obj.slot_name or f"Slot {slot_obj.slot_number}"
            return f"{s_name} ({t_str})"
        except Exception:
            return str(slot_obj)

    # Process RoomBookings
    for rb in rb_qs:
        room = rb.room
        if not room:
            continue
        slot = rb.time_slot
        slot_key = slot.id if slot else 0
        key = (room.room_no, slot_key)

        patient_name = 'N/A'
        patient_reg_no = 'N/A'
        patient_id = rb.patient_id

        # Patient lookup
        p = None
        if rb.visit and rb.visit.allocation and rb.visit.allocation.patient:
            p = rb.visit.allocation.patient
        elif rb.therapy and rb.therapy.patient:
            p = rb.therapy.patient
        elif rb.patient_id:
            p = PatientSnapshot.objects.filter(pk=rb.patient_id).first() or \
                PatientSnapshot.objects.filter(pat_reg_no=str(rb.patient_id)).first()

        if p:
            patient_name = p.pat_name
            patient_reg_no = p.pat_reg_no
            patient_id = p.id

        therapy_name = rb.therapy_name or (rb.therapy.therapy_name if rb.therapy else 'N/A')
        if rb.visit and (not therapy_name or therapy_name == 'N/A'):
            therapy_name = rb.visit.snapshot_therapy_name or (rb.visit.allocation.therapy_name if rb.visit.allocation else 'N/A')

        therapists = []
        if rb.visit:
            for a in rb.visit.assignments.all():
                if a.therapist:
                    therapists.append(a.therapist.therapist_name or a.therapist.therapist_code)
            for na in rb.visit.nurse_assignments.all():
                if na.nurse:
                    therapists.append(na.nurse.nurse_name or na.nurse.nurse_code)

        occupied_map[key] = {
            'room_no': room.room_no,
            'tr_code': room.tr_code or 'N/A',
            'floor': room.floor or 'N/A',
            'therapy_name': therapy_name,
            'patient_name': patient_name,
            'patient_reg_no': patient_reg_no,
            'patient_id': patient_id,
            'therapists': ', '.join(therapists) if therapists else 'N/A',
            'status': rb.status,
            'date': rb.date.strftime('%Y-%m-%d'),
            'time_slot': _format_slot(slot),
            'time_slot_id': slot_key,
            'slot_number': getattr(slot, 'slot_number', 99) if slot else 99
        }

    # Process Bookings (fills any bookings missing from RoomBooking and enriches therapist info)
    for b in b_qs:
        room = b.room
        if not room:
            continue
        slot = b.timeslot
        slot_key = slot.id if slot else 0
        key = (room.room_no, slot_key)

        therapists = []
        for a in b.assignments.all():
            if a.therapist:
                therapists.append(a.therapist.therapist_name or a.therapist.therapist_code)
        for na in b.nurse_assignments.all():
            if na.nurse:
                therapists.append(na.nurse.nurse_name or na.nurse.nurse_code)

        if key in occupied_map:
            if therapists and occupied_map[key]['therapists'] == 'N/A':
                occupied_map[key]['therapists'] = ', '.join(therapists)
            continue

        patient_name = 'N/A'
        patient_reg_no = 'N/A'
        patient_id = None
        if b.allocation and b.allocation.patient:
            patient_name = b.allocation.patient.pat_name
            patient_reg_no = b.allocation.patient.pat_reg_no
            patient_id = b.allocation.patient.id

        therapy_name = b.snapshot_therapy_name or (b.allocation.therapy_name if b.allocation else 'N/A')

        occupied_map[key] = {
            'room_no': room.room_no,
            'tr_code': room.tr_code or 'N/A',
            'floor': room.floor or 'N/A',
            'therapy_name': therapy_name,
            'patient_name': patient_name,
            'patient_reg_no': patient_reg_no,
            'patient_id': patient_id,
            'therapists': ', '.join(therapists) if therapists else 'N/A',
            'status': 'BOOKED',
            'date': b.date.strftime('%Y-%m-%d'),
            'time_slot': _format_slot(slot),
            'time_slot_id': slot_key,
            'slot_number': getattr(slot, 'slot_number', 99) if slot else 99
        }

    # Sort occupied rooms: floor, room_no, slot_number
    result = list(occupied_map.values())
    result.sort(key=lambda x: (str(x.get('floor', '')), str(x.get('room_no', '')), x.get('slot_number', 99)))
    return result


@login_required
def room_availability_dashboard(request):
    """Render the treatment room availability dashboard page"""
    from Patient.models import TreatmentRoom
    # Get distinct floors for filter
    floors = TreatmentRoom.objects.filter(is_active=True).exclude(floor__isnull=True).exclude(floor='').values_list('floor', flat=True).distinct().order_by('floor')
    return render(request, 'dashboards/room/room_availability.html', {'floors': floors})


@login_required
@require_http_methods(["GET"])
def get_available_rooms_api(request):
    """API to get available treatment rooms based on filters"""
    try:
        from Patient.models import TreatmentRoom
        
        selected_date = request.GET.get('date')
        time_slot = request.GET.get('time')
        floor = request.GET.get('floor')
        
        if not selected_date:
            return JsonResponse({'error': 'Date parameter is required', 'success': False}, status=400)
        
        # Parse the date
        try:
            target_date = datetime.strptime(selected_date, '%Y-%m-%d').date()
        except ValueError:
            return JsonResponse({'error': 'Invalid date format (expected YYYY-MM-DD)', 'success': False}, status=400)
        
        # Resolve time slot
        slot_master, err = _resolve_slot_master(time_slot)
        if err:
            return JsonResponse({'error': err, 'success': False}, status=400)
        
        # Get all active treatment rooms
        rooms_query = TreatmentRoom.objects.filter(is_active=True)
        
        # Filter by floor if specified
        if floor and floor != 'all':
            rooms_query = rooms_query.filter(floor=floor)
            
        # Get occupied rooms
        occupied_data = _get_unified_occupied_rooms(target_date, slot_master=slot_master, floor=floor)
        occupied_room_nos = {item['room_no'] for item in occupied_data}
        
        # Available rooms are active rooms excluding those occupied
        available_rooms_qs = rooms_query.exclude(room_no__in=occupied_room_nos).order_by('floor', 'room_no')
        
        rooms_data = []
        for room in available_rooms_qs:
            rooms_data.append({
                'room_no': room.room_no,
                'tr_code': room.tr_code or 'N/A',
                'floor': room.floor or 'N/A',
                'description': room.description or '',
                'is_steam_room': getattr(room, 'is_steam_room', False),
                'is_vamanam_room': getattr(room, 'is_vamanam_room', False),
                'is_wheelchair_accessible': getattr(room, 'is_wheelchair_accessible', False),
                'is_active': room.is_active
            })
            
        return JsonResponse({
            'success': True,
            'rooms': rooms_data,
            'total_count': len(rooms_data),
            'date': target_date.strftime('%Y-%m-%d'),
            'time_slot': slot_master.slot_name if slot_master else 'All Slots'
        })
        
    except Exception as e:
        print(f"Error in get_available_rooms_api: {e}")
        import traceback
        traceback.print_exc()
        return JsonResponse({'error': str(e), 'success': False}, status=500)


@login_required
@require_http_methods(["GET"])
def get_occupied_rooms_api(request):
    """API to get occupied treatment rooms for a specific date and time"""
    try:
        selected_date = request.GET.get('date')
        time_slot = request.GET.get('time')
        floor = request.GET.get('floor')
        
        if not selected_date:
            return JsonResponse({'error': 'Date parameter is required', 'success': False}, status=400)
        
        # Parse the date
        try:
            target_date = datetime.strptime(selected_date, '%Y-%m-%d').date()
        except ValueError:
            return JsonResponse({'error': 'Invalid date format (expected YYYY-MM-DD)', 'success': False}, status=400)
        
        # Resolve time slot
        slot_master, err = _resolve_slot_master(time_slot)
        if err:
            return JsonResponse({'error': err, 'success': False}, status=400)
            
        occupied_data = _get_unified_occupied_rooms(target_date, slot_master=slot_master, floor=floor)
        
        return JsonResponse({
            'success': True,
            'occupied_rooms': occupied_data,
            'total_count': len(occupied_data),
            'date': target_date.strftime('%Y-%m-%d'),
            'time_slot': slot_master.slot_name if slot_master else 'All Slots'
        })
        
    except Exception as e:
        print(f"Error in get_occupied_rooms_api: {e}")
        import traceback
        traceback.print_exc()
        return JsonResponse({'error': str(e), 'success': False}, status=500)

