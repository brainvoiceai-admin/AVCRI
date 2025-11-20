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
from Patient.models import Therapist, TreatmentRoom, TimeSlot
from authentication.models import CustomUser


@login_required
def therapist_dashboard(request):
    """Render the therapist dashboard page"""
    return render(request, 'dashboards/therapist/therapist_dashboard.html')


@login_required
@require_http_methods(["GET"])
def get_therapist_data_api(request):
    """API to get therapist data and assigned sessions"""
    try:
        # Get the current user (assuming they are a therapist)
        user = request.user
        # Find the therapist record for this user via TherapistProfile
        therapist = None
        try:
            # Check if user has a TherapistProfile
            if hasattr(user, 'therapist_profile'):
                therapist_code = user.therapist_profile.therapist_code
                therapist = Therapist.objects.filter(therapist_code=therapist_code).first()
            
            # If still not found, try matching by name as fallback
            if not therapist:
                therapist = Therapist.objects.filter(
                    Q(therapist_name__icontains=user.get_full_name() or user.username)
                ).first()
            
            if not therapist:
                return JsonResponse({'error': 'Therapist not found. Please contact administrator.'}, status=404)
        except Exception as e:
            print(f"Error finding therapist: {e}")
            import traceback
            traceback.print_exc()
            return JsonResponse({'error': f'Error finding therapist: {str(e)}'}, status=404)
        
        # Get sessions assigned to this therapist
        sessions = []
        try:
            # Get booking assignments for this therapist
            assignments = BookingAssignment.objects.filter(
                therapist=therapist
            ).select_related(
                'booking', 'booking__allocation', 'booking__allocation__patient',
                'booking__timeslot', 'booking__room', 'therapist'
            )
            
            # Pre-fetch TherapistBooking records to get is_bathing flags
            # Use visit (TherapyAllocation) to match TherapistBooking records
            therapist_bookings = {}
            try:
                from Patient.models import TherapistBooking
                from masters.models import TherapistMaster
                # Get all allocations (visits) for these bookings
                allocations = [a.booking.allocation for a in assignments if a.booking.allocation]
                # Get all therapist codes for these assignments
                therapist_codes = [a.therapist.therapist_code for a in assignments]
                # Get all TherapistMaster records
                therapist_masters = {tm.therapist_code: tm for tm in TherapistMaster.objects.filter(
                    therapist_code__in=therapist_codes
                )}
                # Get all TherapistBooking records for these visits and therapists
                if therapist_masters and allocations:
                    tb_list = TherapistBooking.objects.filter(
                        visit__in=allocations,
                        therapist__in=therapist_masters.values(),
                        status='BOOKED'
                    ).select_related('therapist', 'visit')
                    # Create a map: (visit_id, therapist_code) -> is_bathing
                    # ONLY use TherapistBooking.is_bathing field from Patient module
                    for tb in tb_list:
                        if tb.visit and tb.therapist:
                            key = (tb.visit.id, tb.therapist.therapist_code)
                            therapist_bookings[key] = tb.is_bathing  # Direct access to is_bathing field
            except Exception as e:
                print(f"Error pre-fetching TherapistBooking records: {e}")
                import traceback
                traceback.print_exc()
            
            for assignment in assignments:
                booking = assignment.booking
                allocation = booking.allocation
                patient = allocation.patient
                
                # Get time slot and room info
                time_slot = booking.timeslot  # Use timeslot (no underscore)
                room = booking.room
                
                # Get is_bathing flag from TherapistBooking model ONLY (Patient module)
                # Match by visit (TherapyAllocation) and therapist
                is_bathing = False
                if allocation and assignment.therapist:
                    key = (allocation.id, assignment.therapist.therapist_code)
                    is_bathing = therapist_bookings.get(key, False)
                
                # Format therapy name
                therapy_name = allocation.therapy_name
                
                # Get time slot display and value expected by frontend slots
                slot_display = '6:30 AM'
                slot_value = '6-30am'
                if time_slot and hasattr(time_slot, 'slot_time'):
                    slot_display = time_slot.slot_time.strftime('%I:%M %p')
                    # Format like '6-30am', '10-00am', '2-30pm'
                    h_24 = int(time_slot.slot_time.strftime('%H'))
                    m = time_slot.slot_time.strftime('%M')
                    ampm = 'am' if h_24 < 12 else 'pm'
                    h_12 = h_24 % 12
                    if h_12 == 0:
                        h_12 = 12
                    slot_value = f"{h_12}-{m}{ampm}"
                
                # Get room number - check booking.room first, then RoomBooking via visit
                room_no = None
                if room:
                    room_no = room.room_no  # TreatmentRoom uses room_no
                else:
                    # Try to get from RoomBooking
                    try:
                        from Patient.models import RoomBooking
                        room_booking = RoomBooking.objects.filter(visit=booking).first()
                        if room_booking and room_booking.room:
                            room_no = room_booking.room.room_no
                    except Exception as e:
                        print(f"Error getting room from RoomBooking: {e}")
                
                if not room_no:
                    room_no = 'TBD'
                
                # Map booking status to display status
                status_map = {
                    'draft': 'Draft',
                    'scheduled': 'Scheduled',
                    'completed': 'Completed',
                    'failed': 'Failed',
                    'cancelled': 'Cancelled',
                    'in_progress': 'In Progress'
                }
                display_status = status_map.get(booking.status, booking.status.title() if booking.status else 'Unknown')
                
                session_data = {
                    'id': booking.id,
                    'date': booking.date.strftime('%Y-%m-%d') if booking.date else '',
                    'slot': slot_display,
                    'slot_value': slot_value,
                    'patient_name': patient.pat_name if patient else 'Unknown',
                    'patient_id': patient.pat_reg_no if patient else 'Unknown',
                    'therapy': therapy_name,
                    'is_bathing': bool(is_bathing),  # Ensure boolean value for frontend display
                    'room': room_no,
                    'status': display_status,
                    'notes': booking.therapist_note or ''  # Use therapist_note field
                }
                # Debug logging
                if is_bathing:
                    print(f"[DEBUG] Therapist {assignment.therapist.therapist_code} has is_bathing=True for booking {booking.id}, therapy {therapy_name}")
                sessions.append(session_data)
        except Exception as e:
            print(f"Error getting sessions: {e}")
            import traceback
            traceback.print_exc()
            sessions = []
        
        # Prepare therapist info - get from profile if available for more details
        therapist_info = {
            'id': therapist.therapist_code,
            'name': therapist.therapist_name,
            'level': therapist.therapist_grade or 'Therapist',
            'specialization': 'General Therapy'
        }
        
        # Try to get specialization from profile if available
        if hasattr(user, 'therapist_profile'):
            profile = user.therapist_profile
            if profile.specialization:
                therapist_info['specialization'] = profile.specialization
        
        return JsonResponse({
            'success': True,
            'therapist': therapist_info,
            'sessions': sessions
        })
        
    except Exception as e:
        print(f"Error in get_therapist_data_api: {e}")
        return JsonResponse({'error': str(e)}, status=500)


@login_required
@require_http_methods(["GET"])
def get_therapist_sessions_by_date_api(request):
    """API to get therapist sessions for a specific date"""
    try:
        selected_date = request.GET.get('date')
        if not selected_date:
            return JsonResponse({'error': 'Date parameter is required'}, status=400)
        
        # Parse the date
        try:
            target_date = datetime.strptime(selected_date, '%Y-%m-%d').date()
        except ValueError:
            return JsonResponse({'error': 'Invalid date format'}, status=400)
        
        # Get the current user's therapist record
        user = request.user
        therapist = None
        
        # Check if user has a TherapistProfile
        if hasattr(user, 'therapist_profile'):
            therapist_code = user.therapist_profile.therapist_code
            therapist = Therapist.objects.filter(therapist_code=therapist_code).first()
        
        # If still not found, try matching by name as fallback
        if not therapist:
            therapist = Therapist.objects.filter(
                Q(therapist_name__icontains=user.get_full_name() or user.username)
            ).first()
        
        if not therapist:
            return JsonResponse({'error': 'Therapist not found. Please contact administrator.'}, status=404)
        
        # Get sessions for the selected date
        sessions = []
        try:
            assignments = BookingAssignment.objects.filter(
                therapist=therapist,
                booking__date=target_date
            ).select_related(
                'booking', 'booking__allocation', 'booking__allocation__patient',
                'booking__timeslot', 'booking__room', 'therapist'
            )
            
            # Pre-fetch TherapistBooking records to get is_bathing flags
            # Use visit (TherapyAllocation) to match TherapistBooking records
            therapist_bookings = {}
            try:
                from Patient.models import TherapistBooking
                from masters.models import TherapistMaster
                # Get all allocations (visits) for these bookings
                allocations = [a.booking.allocation for a in assignments if a.booking.allocation]
                # Get all therapist codes for these assignments
                therapist_codes = [a.therapist.therapist_code for a in assignments]
                # Get all TherapistMaster records
                therapist_masters = {tm.therapist_code: tm for tm in TherapistMaster.objects.filter(
                    therapist_code__in=therapist_codes
                )}
                # Get all TherapistBooking records for these visits and therapists
                if therapist_masters and allocations:
                    tb_list = TherapistBooking.objects.filter(
                        visit__in=allocations,
                        therapist__in=therapist_masters.values(),
                        status='BOOKED'
                    ).select_related('therapist', 'visit')
                    # Create a map: (visit_id, therapist_code) -> is_bathing
                    # ONLY use TherapistBooking.is_bathing field from Patient module
                    for tb in tb_list:
                        if tb.visit and tb.therapist:
                            key = (tb.visit.id, tb.therapist.therapist_code)
                            therapist_bookings[key] = tb.is_bathing  # Direct access to is_bathing field
            except Exception as e:
                print(f"Error pre-fetching TherapistBooking records: {e}")
                import traceback
                traceback.print_exc()
            
            for assignment in assignments:
                booking = assignment.booking
                allocation = booking.allocation
                patient = allocation.patient
                
                # Get is_bathing flag from pre-fetched data using visit (TherapyAllocation)
                is_bathing = False
                if allocation and assignment.therapist:
                    key = (allocation.id, assignment.therapist.therapist_code)
                    is_bathing = therapist_bookings.get(key, False)
                
                # Format therapy name
                therapy_name = allocation.therapy_name
                
                # Get time slot display
                time_slot = booking.timeslot
                slot_display = '6:30 AM'
                slot_value = '6-30am'
                if time_slot and hasattr(time_slot, 'slot_time'):
                    slot_display = time_slot.slot_time.strftime('%I:%M %p')
                    h_24 = int(time_slot.slot_time.strftime('%H'))
                    m = time_slot.slot_time.strftime('%M')
                    ampm = 'am' if h_24 < 12 else 'pm'
                    h_12 = h_24 % 12
                    if h_12 == 0:
                        h_12 = 12
                    slot_value = f"{h_12}-{m}{ampm}"
                
                # Get room number
                room_no = None
                if booking.room:
                    room_no = booking.room.room_number if hasattr(booking.room, 'room_number') else (booking.room.room_no if hasattr(booking.room, 'room_no') else 'TBD')
                else:
                    # Try to get from RoomBooking
                    try:
                        from Patient.models import RoomBooking
                        room_booking = RoomBooking.objects.filter(visit=booking).first()
                        if room_booking and room_booking.room:
                            room_no = room_booking.room.room_number if hasattr(room_booking.room, 'room_number') else (room_booking.room.room_no if hasattr(room_booking.room, 'room_no') else 'TBD')
                    except Exception as e:
                        print(f"Error getting room from RoomBooking: {e}")
                
                if not room_no:
                    room_no = 'TBD'
                
                # Map booking status to display status
                status_map = {
                    'draft': 'Draft',
                    'scheduled': 'Scheduled',
                    'completed': 'Completed',
                    'failed': 'Failed',
                    'cancelled': 'Cancelled',
                    'in_progress': 'In Progress'
                }
                display_status = status_map.get(booking.status, booking.status.title() if booking.status else 'Unknown')
                
                session_data = {
                    'id': booking.id,
                    'slot': slot_display,
                    'slot_value': slot_value,
                    'patient_name': patient.pat_name if patient else 'Unknown',
                    'patient_id': patient.pat_reg_no if patient else 'Unknown',
                    'therapy': therapy_name,
                    'is_bathing': bool(is_bathing),  # Ensure boolean value for frontend display
                    'room': room_no,
                    'status': display_status,
                    'notes': booking.therapist_note or ''
                }
                # Debug logging
                if is_bathing:
                    print(f"[DEBUG] Therapist {assignment.therapist.therapist_code} has is_bathing=True for booking {booking.id}, therapy {therapy_name}")
                sessions.append(session_data)
        except Exception as e:
            print(f"Error getting sessions for date {selected_date}: {e}")
            import traceback
            traceback.print_exc()
            sessions = []
        
        return JsonResponse({
            'success': True,
            'sessions': sessions
        })
        
    except Exception as e:
        print(f"Error in get_therapist_sessions_by_date_api: {e}")
        return JsonResponse({'error': str(e)}, status=500)
