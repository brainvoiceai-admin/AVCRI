from django.shortcuts import render
from django.http import JsonResponse
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_http_methods
from django.db.models import Q
from datetime import datetime
import json

from masters.models import SlotMaster
from Patient.models import TreatmentRoom, RoomBooking

@login_required
def room_availability_dashboard(request):
    """Render the treatment room availability dashboard page"""
    return render(request, 'dashboards/scheduling/room_availability.html')

@login_required
@require_http_methods(["GET"])
def get_available_rooms_api(request):
    """API to get available treatment rooms based on filters"""
    try:
        selected_date = request.GET.get('date')
        time_slot = request.GET.get('time')
        floor = request.GET.get('floor')
        
        if not selected_date:
            return JsonResponse({'error': 'Date parameter is required'}, status=400)
        
        # Parse the date
        try:
            target_date = datetime.strptime(selected_date, '%Y-%m-%d').date()
        except ValueError:
            return JsonResponse({'error': 'Invalid date format'}, status=400)
        
        # Get all active treatment rooms
        rooms_query = TreatmentRoom.objects.filter(is_active=True)
        
        # Filter by floor if specified
        if floor and floor != 'all':
            rooms_query = rooms_query.filter(floor__iexact=floor)
        
        # If time slot is specified, check availability
        if time_slot:
            try:
                time_obj = datetime.strptime(time_slot, '%H:%M').time()
                
                # Find the SlotMaster record matching this time
                slot_master = SlotMaster.objects.filter(
                    slot_time=time_obj,
                    is_active=True
                ).first()
                
                if slot_master:
                    # Get rooms that have bookings at this time slot
                    booked_room_ids = RoomBooking.objects.filter(
                        date=target_date,
                        time_slot=slot_master,
                        status='BOOKED'
                    ).values_list('room_id', flat=True)
                    
                    # Exclude rooms which are already booked
                    rooms_query = rooms_query.exclude(
                        room_no__in=booked_room_ids
                    )
                else:
                    return JsonResponse({
                        'error': f'Time slot {time_slot} not found',
                        'success': False
                    }, status=400)
            except ValueError:
                return JsonResponse({'error': 'Invalid time format'}, status=400)
        
        # Prepare room data
        rooms_list = list(rooms_query)
        rooms_data = []
        for room in rooms_list:
            rooms_data.append({
                'room_no': room.room_no,
                'floor': room.floor or 'N/A',
                'description': room.description or '',
                'tr_code': room.tr_code or '',
                'is_active': room.is_active
            })
            
        return JsonResponse({
            'success': True,
            'rooms': rooms_data,
            'total_count': len(rooms_data)
        })
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return JsonResponse({'error': str(e)}, status=500)

@login_required
@require_http_methods(["GET"])
def get_booked_rooms_api(request):
    """API to get rooms that are booked for a specific date"""
    try:
        selected_date = request.GET.get('date')
        floor = request.GET.get('floor')
        
        if not selected_date:
            return JsonResponse({'error': 'Date parameter is required'}, status=400)
        
        # Parse the date
        try:
            target_date = datetime.strptime(selected_date, '%Y-%m-%d').date()
        except ValueError:
            return JsonResponse({'error': 'Invalid date format'}, status=400)
        
        # Get all bookings for the date
        bookings_query = RoomBooking.objects.filter(
            date=target_date,
            status='BOOKED'
        ).select_related('room', 'time_slot')
        
        if floor and floor != 'all':
            bookings_query = bookings_query.filter(room__floor__iexact=floor)
            
        from Sheduling.models import PatientSnapshot
        
        bookings_data = []
        for booking in bookings_query:
            # Try to get patient name via relationships first
            patient_name = 'Unknown Patient'
            if booking.therapy and booking.therapy.patient:
                patient_name = booking.therapy.patient.pat_name
            elif booking.visit and booking.visit.allocation and booking.visit.allocation.patient:
                patient_name = booking.visit.allocation.patient.pat_name
            elif booking.patient_id:
                # Fallback to direct lookup if reg_no is stored in patient_id
                # Search by pat_reg_no as string
                patient = PatientSnapshot.objects.filter(pat_reg_no=str(booking.patient_id)).first()
                if patient:
                    patient_name = patient.pat_name
                else:
                    # Try raw lookup if it might be an ID
                    patient = PatientSnapshot.objects.filter(id=booking.patient_id).first()
                    if patient:
                        patient_name = patient.pat_name
                    else:
                        patient_name = f"Patient {booking.patient_id}"
            
            bookings_data.append({
                'room_no': booking.room.room_no,
                'floor': booking.room.floor or 'N/A',
                'time_slot': booking.time_slot.slot_time.strftime('%I:%M %p'),
                'therapy_name': booking.therapy_name or 'N/A',
                'patient_id': booking.patient_id or 'N/A',
                'patient_name': patient_name
            })
            
        return JsonResponse({
            'success': True,
            'bookings': bookings_data,
            'total_count': len(bookings_data)
        })
        
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)

@login_required
@require_http_methods(["GET"])
def get_floors_api(request):
    """API to get unique floors for filtering"""
    try:
        floors = TreatmentRoom.objects.filter(is_active=True).values_list('floor', flat=True).distinct()
        # Filter out None and empty strings
        floors_list = [f for f in floors if f]
        return JsonResponse({
            'success': True,
            'floors': sorted(floors_list)
        })
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)
