from django.shortcuts import render
from django.http import JsonResponse
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_http_methods
from django.views.decorators.csrf import csrf_exempt
from django.db.models import Q
from datetime import datetime, date
import json

from .patient_decorators import patient_dashboard_access_required, patient_data_access_required

from .models import (
    TherapyAllocation, Booking, BookingItem, BookingAssignment, 
    PatientSnapshot, PrescriptionScheduling, PrescriptionItem
)
from Patient.models import Therapist, TreatmentRoom, TimeSlot
from authentication.models import CustomUser


@login_required
@patient_dashboard_access_required
def patient_dashboard(request):
    """Render the patient dashboard page"""
    return render(request, 'patient_dashboard.html')


@login_required
@patient_data_access_required
@require_http_methods(["GET"])
def get_patient_data_api(request):
    """API to get patient data, sessions, and prescriptions for the logged-in patient"""
    try:
        # Get the current user (assuming they are a patient)
        user = request.user
        
        # Find the patient snapshot for this user via PatientProfile
        patient = None
        try:
            # Check if user has a PatientProfile
            if hasattr(user, 'patient_profile'):
                patient_reg_no = user.patient_profile.patient_reg_no
                # Find patient by pat_reg_no
                patient = PatientSnapshot.objects.filter(
                    pat_reg_no=patient_reg_no
                ).first()
            
            # If still not found, try matching by name as fallback
            if not patient:
                patient = PatientSnapshot.objects.filter(
                    Q(pat_name__icontains=user.get_full_name() or user.username)
                ).first()
            
            if not patient:
                return JsonResponse({'error': 'Patient not found. Please contact administrator.'}, status=404)
        except Exception as e:
            print(f"Error finding patient: {e}")
            return JsonResponse({'error': f'Error finding patient: {str(e)}'}, status=404)
        
        # Get therapy sessions for this patient
        sessions = []
        try:
            # Get therapy allocations for this patient
            allocations = TherapyAllocation.objects.filter(patient=patient).select_related('patient')
            
            for allocation in allocations:
                # Get booking details - use date field, not booking_date
                bookings = Booking.objects.filter(allocation=allocation).select_related(
                    'timeslot', 'room', 'allocation'
                ).prefetch_related('assignments__therapist')
                
                for booking in bookings:
                    # Get assigned therapists
                    assignments = BookingAssignment.objects.filter(booking=booking).select_related('therapist')
                    therapists = [assignment.therapist.therapist_name for assignment in assignments]
                    
                    # Get time slot - use timeslot (no underscore) based on model
                    time_slot = booking.timeslot
                    slot_hour = time_slot.start_time.hour if time_slot and hasattr(time_slot, 'start_time') else 9
                    
                    # Get room - check booking.room first, then RoomBooking via visit
                    room_no = None
                    if booking.room:
                        room_no = booking.room.room_no  # TreatmentRoom uses room_no
                    else:
                        # Try to get from RoomBooking
                        try:
                            from Patient.models import RoomBooking
                            room_booking = RoomBooking.objects.filter(visit=booking).first()
                            if room_booking and room_booking.room:
                                room_no = room_booking.room.room_no
                        except Exception as e:
                            print(f"Error getting room from RoomBooking: {e}")
                    
                    # If still no room, check patient snapshot
                    if not room_no:
                        room_no = patient.pat_room_no or 'TBD'
                    
                    # Map booking status to display status
                    status_map = {
                        'draft': 'Draft',
                        'scheduled': 'Scheduled',
                        'completed': 'Completed',
                        'failed': 'Failed',
                        'cancelled': 'Cancelled'
                    }
                    display_status = status_map.get(booking.status, booking.status.title() if booking.status else 'Unknown')
                    
                    session_data = {
                        'id': booking.id,
                        'date': booking.date.strftime('%Y-%m-%d') if booking.date else '',
                        'slot': slot_hour,
                        'therapy': allocation.therapy_name,
                        'room_id': room_no,
                        'therapists': therapists,
                        'status': display_status,
                        'remarks': booking.therapist_note or ''
                    }
                    sessions.append(session_data)
        except Exception as e:
            print(f"Error getting sessions: {e}")
            import traceback
            traceback.print_exc()
            sessions = []
        
        # Get prescriptions for this patient
        prescriptions = []
        try:
            prescription_schedules = PrescriptionScheduling.objects.filter(
                patient=patient
            ).select_related('patient', 'doctor').prefetch_related('items')
            
            for schedule in prescription_schedules:
                # Try to get items from PrescriptionItem first (if they exist)
                items = schedule.items.all()
                
                if items.exists():
                    # Use PrescriptionItem records
                    for item in items:
                        prescription_data = {
                            'id': item.id,
                            'date': schedule.prescription_date.strftime('%Y-%m-%d') if schedule.prescription_date else '',
                            'item_name': item.item_name or '',
                            'dose': item.dose or '',
                            'quantity': item.quantity or '',
                            'time': item.time or '',
                            'notes': item.notes or ''
                        }
                        prescriptions.append(prescription_data)
                else:
                    # Fallback: Try to get items from PrescriptionAllocation by matching date range
                    try:
                        from .models import PrescriptionAllocation
                        allocation = PrescriptionAllocation.objects.filter(
                            patient=patient,
                            from_date__lte=schedule.prescription_date,
                            to_date__gte=schedule.prescription_date
                        ).first()
                        
                        if allocation and allocation.items_groups:
                            import json
                            items_data = json.loads(allocation.items_groups) if isinstance(allocation.items_groups, str) else allocation.items_groups
                            for item_group in items_data:
                                if isinstance(item_group, dict) and 'items' in item_group:
                                    for item in item_group['items']:
                                        prescription_data = {
                                            'id': item.get('id', schedule.id),
                                            'date': schedule.prescription_date.strftime('%Y-%m-%d') if schedule.prescription_date else '',
                                            'item_name': item.get('item_name', ''),
                                            'dose': item.get('dose', ''),
                                            'quantity': item.get('quantity', ''),
                                            'time': item.get('time', ''),
                                            'notes': item.get('notes', '')
                                        }
                                        prescriptions.append(prescription_data)
                    except Exception as e:
                        print(f"Error processing prescription schedule {schedule.id}: {e}")
                        continue
        except Exception as e:
            print(f"Error getting prescriptions: {e}")
            import traceback
            traceback.print_exc()
            prescriptions = []
        
        # Prepare patient info
        patient_info = {
            'id': patient.pat_reg_no,
            'name': patient.pat_name,
            'age': patient.pat_age,
            'sex': patient.pat_sex,
            'room': patient.pat_room_no
        }
        
        return JsonResponse({
            'success': True,
            'patient': patient_info,
            'sessions': sessions,
            'prescriptions': prescriptions
        })
        
    except Exception as e:
        print(f"Error in get_patient_data_api: {e}")
        return JsonResponse({'error': str(e)}, status=500)


@login_required
@patient_data_access_required
@require_http_methods(["GET"])
def get_patient_prescriptions_api(request):
    """API to get prescriptions for a specific date"""
    try:
        selected_date = request.GET.get('date')
        if not selected_date:
            return JsonResponse({'error': 'Date parameter is required'}, status=400)
        
        # Parse the date
        try:
            target_date = datetime.strptime(selected_date, '%Y-%m-%d').date()
        except ValueError:
            return JsonResponse({'error': 'Invalid date format'}, status=400)
        
        # Get the current user's patient record
        user = request.user
        patient = None
        
        # Check if user has a PatientProfile
        if hasattr(user, 'patient_profile'):
            patient_reg_no = user.patient_profile.patient_reg_no
            # Find patient by pat_reg_no
            patient = PatientSnapshot.objects.filter(
                pat_reg_no=patient_reg_no
            ).first()
        
        # If still not found, try matching by name as fallback
        if not patient:
            patient = PatientSnapshot.objects.filter(
                Q(pat_name__icontains=user.get_full_name() or user.username)
            ).first()
        
        if not patient:
            return JsonResponse({'error': 'Patient not found. Please contact administrator.'}, status=404)
        
        # Get prescriptions for the selected date
        prescriptions = []
        try:
            prescription_schedules = PrescriptionScheduling.objects.filter(
                patient=patient,
                prescription_date=target_date
            ).select_related('patient', 'doctor').prefetch_related('items')
            
            for schedule in prescription_schedules:
                # Try to get items from PrescriptionItem first (if they exist)
                items = schedule.items.all()
                
                if items.exists():
                    # Use PrescriptionItem records
                    for item in items:
                        prescription_data = {
                            'id': item.id,
                            'item_name': item.item_name or '',
                            'dose': item.dose or '',
                            'quantity': item.quantity or '',
                            'time': item.time or '',
                            'notes': item.notes or ''
                        }
                        prescriptions.append(prescription_data)
                else:
                    # Fallback: Try to get items from PrescriptionAllocation by matching date range
                    try:
                        from .models import PrescriptionAllocation
                        allocation = PrescriptionAllocation.objects.filter(
                            patient=patient,
                            from_date__lte=target_date,
                            to_date__gte=target_date
                        ).first()
                        
                        if allocation and allocation.items_groups:
                            import json
                            items_data = json.loads(allocation.items_groups) if isinstance(allocation.items_groups, str) else allocation.items_groups
                            for item_group in items_data:
                                if isinstance(item_group, dict) and 'items' in item_group:
                                    for item in item_group['items']:
                                        prescription_data = {
                                            'id': item.get('id', schedule.id),
                                            'item_name': item.get('item_name', ''),
                                            'dose': item.get('dose', ''),
                                            'quantity': item.get('quantity', ''),
                                            'time': item.get('time', ''),
                                            'notes': item.get('notes', '')
                                        }
                                        prescriptions.append(prescription_data)
                    except Exception as e:
                        print(f"Error processing prescription schedule {schedule.id}: {e}")
                        continue
        except Exception as e:
            print(f"Error getting prescriptions for date {selected_date}: {e}")
            import traceback
            traceback.print_exc()
            prescriptions = []
        
        return JsonResponse({
            'success': True,
            'prescriptions': prescriptions
        })
        
    except Exception as e:
        print(f"Error in get_patient_prescriptions_api: {e}")
        return JsonResponse({'error': str(e)}, status=500)
