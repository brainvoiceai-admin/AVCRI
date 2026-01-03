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
from Patient.models import TherapistBooking
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
        
        # Get therapists who are on emergency leave for this date
        # EmergencyLeave covers date ranges (from_date <= target_date <= to_date)
        emergency_leave_qs = EmergencyLeave.objects.filter(
            from_date__lte=target_date,
            to_date__gte=target_date
        )
        # Get therapist IDs from FK relationship
        emergency_leave_therapist_ids = set(
            emergency_leave_qs.exclude(therapist__isnull=True)
            .values_list('therapist_id', flat=True)
        )
        # Also get therapist IDs by matching employee_code
        emergency_leave_employee_codes = set(
            emergency_leave_qs.values_list('employee_code', flat=True)
        )
        emergency_leave_by_emp_code = set(
            TherapistMaster.objects.filter(employee_code__in=emergency_leave_employee_codes)
            .values_list('id', flat=True)
        )
        # Combine both sets
        emergency_leave_therapist_ids = emergency_leave_therapist_ids | emergency_leave_by_emp_code
        
        # Exclude therapists on recurring leave
        available_therapists = therapists_query.exclude(
            pk__in=recurring_leave_therapist_ids
        )
        
        # Exclude therapists on emergency leave
        if emergency_leave_therapist_ids:
            available_therapists = available_therapists.exclude(
                pk__in=emergency_leave_therapist_ids
            )
        
        # If time slot is specified, check availability using SlotMaster and TherapistBooking
        if time_slot:
            # Parse time slot (e.g., "09:00" -> 9:00 AM)
            try:
                time_obj = datetime.strptime(time_slot, '%H:%M').time()
                
                # Find the SlotMaster record matching this time
                slot_master = SlotMaster.objects.filter(
                    slot_time=time_obj,
                    is_active=True
                ).first()
                
                if slot_master:
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
        
        if not selected_date:
            return JsonResponse({'error': 'Date parameter is required'}, status=400)
        
        # Parse the date
        try:
            target_date = datetime.strptime(selected_date, '%Y-%m-%d').date()
        except ValueError:
            return JsonResponse({'error': 'Invalid date format'}, status=400)
        
        leave_data = []
        
        # Get therapists on recurring leave for this date
        # TherapistLeaveMaster model uses leave_day (day of week: 0=Monday, 1=Tuesday, etc.)
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
                'leave_type': 'Week Off',  # Changed from 'Recurring Leave' to 'Week Off'
                'from_date': target_date.strftime('%Y-%m-%d'),
                'to_date': target_date.strftime('%Y-%m-%d'),
                'reason': '',  # No reason field in current model
                'is_bathing': therapist.is_bathing_therapist,
                'is_active': leave_record.is_active
            }
            leave_data.append(leave_info)
        
        # Get therapists on emergency leave for this date
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
                    'leave_type': 'Emergency Leave',  # Always show as 'Emergency Leave'
                    'from_date': em_leave.from_date.strftime('%Y-%m-%d'),
                    'to_date': em_leave.to_date.strftime('%Y-%m-%d'),
                    'reason': em_leave.leave_type or '',  # Show leave_type as reason if available
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
            slots_data.append({
                'id': slot.pk,
                'start_time': slot.slot_time.strftime('%H:%M'),
                'slot_name': slot.slot_name or f"Slot {slot.slot_number}",
                'display_name': time_12hr,
                'slot_number': slot.slot_number
            })
        
        # If no time slots in database, return default ones
        if not slots_data:
            default_slots = [
                {'id': 1, 'start_time': '09:00', 'slot_name': 'Morning Slot', 'display_name': '9:00 AM', 'slot_number': 1},
                {'id': 2, 'start_time': '10:00', 'slot_name': 'Late Morning', 'display_name': '10:00 AM', 'slot_number': 2},
                {'id': 3, 'start_time': '14:00', 'slot_name': 'Afternoon Slot', 'display_name': '2:00 PM', 'slot_number': 3},
                {'id': 4, 'start_time': '15:00', 'slot_name': 'Late Afternoon', 'display_name': '3:00 PM', 'slot_number': 4},
            ]
            slots_data = default_slots
        
        return JsonResponse({
            'success': True,
            'time_slots': slots_data
        })
        
    except Exception as e:
        print(f"Error in get_time_slots_api: {e}")
        return JsonResponse({'error': str(e)}, status=500)
