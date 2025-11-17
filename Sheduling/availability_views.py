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
from masters.models import SlotMaster, TherapistMaster, TherapistLeaveMaster
from authentication.models import CustomUser


@login_required
def therapist_availability_dashboard(request):
    """Render the therapist availability dashboard page"""
    return render(request, 'therapist_availability.html')


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
        
        # Get all therapists from master table
        therapists_query = TherapistMaster.objects.filter(is_active=True)
        
        # Filter by gender if specified
        if gender and gender != 'all':
            therapists_query = therapists_query.filter(user__gender=gender)
        
        # Get therapists who are on leave for this date
        # TherapistLeaveMaster model uses leave_day (day of week: 0=Monday, 1=Tuesday, etc.)
        day_of_week = target_date.weekday()  # 0=Monday, 1=Tuesday, ..., 6=Sunday
        leave_therapist_ids = TherapistLeaveMaster.objects.filter(
            leave_day=day_of_week,
            is_active=True
        ).values_list('therapist_id', flat=True)
        
        # Exclude therapists on leave
        available_therapists = therapists_query.exclude(
            pk__in=leave_therapist_ids
        )
        
        # If time slot is specified, check availability
        if time_slot:
            # Parse time slot (e.g., "09:00" -> 9:00 AM)
            try:
                time_obj = datetime.strptime(time_slot, '%H:%M').time()
                
                # Get therapists who have bookings at this time
                booked_therapist_ids = BookingAssignment.objects.filter(
                    booking__date=target_date,
                    booking__timeslot__start_time=time_obj
                ).values_list('therapist_id', flat=True)
                
                # Exclude therapists who are already booked
                available_therapists = available_therapists.exclude(
                    pk__in=booked_therapist_ids
                )
            except ValueError:
                return JsonResponse({'error': 'Invalid time format'}, status=400)
        
        # Prepare therapist data
        therapists_data = []
        for therapist in available_therapists:
            # Get gender from user model if available
            gender = 'unknown'
            if therapist.user:
                gender = therapist.user.gender
            elif hasattr(therapist, 'therapist_profile') and therapist.therapist_profile:
                gender = getattr(therapist.therapist_profile, 'gender', 'unknown')
            
            therapist_data = {
                'id': therapist.pk,
                'name': therapist.therapist_name,
                'code': therapist.therapist_code,
                'employee_code': therapist.employee_code,
                'gender': gender,
                'grade': therapist.therapist_grade,
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
        return JsonResponse({'error': str(e)}, status=500)


@login_required
@require_http_methods(["GET"])
def get_therapists_on_leave_api(request):
    """API to get therapists on leave for a specific date"""
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
        
        # Get therapists on leave for this date
        # TherapistLeaveMaster model uses leave_day (day of week: 0=Monday, 1=Tuesday, etc.)
        day_of_week = target_date.weekday()  # 0=Monday, 1=Tuesday, ..., 6=Sunday
        leave_query = TherapistLeaveMaster.objects.filter(
            leave_day=day_of_week,
            is_active=True
        )
        
        # Filter by gender if specified
        if gender and gender != 'all':
            leave_query = leave_query.filter(therapist__user__gender=gender)
        
        # Get leave records with therapist details
        leave_records = leave_query.select_related('therapist')
        
        # Prepare leave data
        leave_data = []
        for leave_record in leave_records:
            therapist = leave_record.therapist
            # Get gender from user model if available
            gender = 'unknown'
            if therapist.user:
                gender = therapist.user.gender
            elif hasattr(therapist, 'therapist_profile') and therapist.therapist_profile:
                gender = getattr(therapist.therapist_profile, 'gender', 'unknown')
            
            leave_info = {
                'id': therapist.pk,
                'name': therapist.therapist_name,
                'code': therapist.therapist_code,
                'employee_code': therapist.employee_code,
                'gender': gender,
                'grade': therapist.therapist_grade,
                'leave_date': target_date.strftime('%Y-%m-%d'),
                'leave_day': leave_record.leave_day,
                'leave_day_name': leave_record.leave_day_name,
                'leave_type': 'Leave',  # Default leave type
                'reason': '',  # No reason field in current model
                'is_bathing': therapist.is_bathing_therapist,
                'is_active': leave_record.is_active
            }
            leave_data.append(leave_info)
        
        return JsonResponse({
            'success': True,
            'leaves': leave_data,
            'total_count': len(leave_data)
        })
        
    except Exception as e:
        print(f"Error in get_therapists_on_leave_api: {e}")
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
