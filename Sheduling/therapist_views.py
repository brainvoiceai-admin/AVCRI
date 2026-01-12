from django.shortcuts import render
from django.http import JsonResponse
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_http_methods
from django.views.decorators.csrf import csrf_exempt
from django.db.models import Q
from django.utils import timezone
from datetime import datetime, date, timedelta
from collections import defaultdict
import json
import logging

logger = logging.getLogger(__name__)

from .models import (
    TherapyAllocation, Booking, BookingItem, BookingAssignment, 
    PatientSnapshot, PrescriptionScheduling, PrescriptionItem
)
from Patient.models import Therapist, TreatmentRoom, TimeSlot, TherapyDetails
from authentication.models import CustomUser
from authentication.decorators import super_admin_required
from masters.models import TherapyMaster, TherapistMaster


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


@super_admin_required
def therapist_difficulty_dashboard(request):
    """
    Render dashboard for super admins to view therapist workload split by therapy difficulty.
    """
    date_param = request.GET.get('date')
    if date_param:
        try:
            parsed_date = datetime.strptime(date_param, '%Y-%m-%d').date()
            default_date = parsed_date.isoformat()
        except ValueError:
            default_date = timezone.localdate().isoformat()
    else:
        default_date = timezone.localdate().isoformat()
    
    context = {
        'default_date': default_date,
    }
    return render(request, 'dashboards/superadmin/therapist_difficulty_dashboard.html', context)


@super_admin_required
@require_http_methods(["GET"])
def get_therapist_difficulty_data(request):
    """
    Return therapist vs difficulty counts for a selected date.
    Supports optional gender filter.
    """
    date_str = request.GET.get('date')
    if date_str:
        try:
            target_date = datetime.strptime(date_str, '%Y-%m-%d').date()
        except ValueError:
            return JsonResponse({'success': False, 'error': 'Invalid date format. Use YYYY-MM-DD.'}, status=400)
    else:
        target_date = timezone.localdate()
        date_str = target_date.isoformat()
    
    gender_filter = request.GET.get('gender', '').strip().lower()
    patient_gender_filter = request.GET.get('patient_gender', '').strip().lower()
    grade_filter = request.GET.get('grade', '').strip()
    grade_filter_lower = grade_filter.lower()
    
    assignments = (
        BookingAssignment.objects
        .filter(
            booking__date=target_date,
            status='assigned',
            booking__status__in=['draft', 'scheduled', 'in_progress']
        )
        .select_related('therapist', 'booking__allocation')
    )
    
    therapy_codes = {
        assignment.booking.allocation.therapy_code
        for assignment in assignments
        if assignment.booking and assignment.booking.allocation
    }
    
    therapy_categories = {}
    if therapy_codes:
        for tm in TherapyMaster.objects.filter(therapy_code__in=therapy_codes):
            category = (tm.therapy_category or tm.therapy_group or 'Uncategorized').strip() or 'Uncategorized'
            therapy_categories[tm.therapy_code] = category
        missing_codes = therapy_codes - set(therapy_categories.keys())
        if missing_codes:
            for legacy in TherapyDetails.objects.filter(therapy_code__in=missing_codes):
                category = (legacy.therapy_category or legacy.therapy_group or 'Uncategorized').strip() or 'Uncategorized'
                therapy_categories[legacy.therapy_code] = category
    
    # Get therapist codes from assignments to fetch gender info
    therapist_codes_from_assignments = {
        assignment.therapist.therapist_code
        for assignment in assignments
        if assignment.therapist
    }
    
    # Fetch TherapistMaster records to get gender information
    from masters.models import TherapistMaster
    therapist_masters = {}
    if therapist_codes_from_assignments:
        for tm in TherapistMaster.objects.filter(therapist_code__in=therapist_codes_from_assignments):
            therapist_masters[tm.therapist_code] = {
                'gender': (tm.therapist_gender or 'Male').strip(),
                'grade': tm.therapist_grade.name if tm.therapist_grade else ''
            }
    
    therapist_map = defaultdict(lambda: {
        'name': '',
        'grade': '',
        'gender': '',
        'counts': defaultdict(int),
        'total': 0
    })
    difficulties = set()
    total_assignments = 0
    
    for assignment in assignments:
        therapist = assignment.therapist
        booking = assignment.booking
        if not therapist or not booking or not booking.allocation:
            continue
        
        # Get gender from TherapistMaster
        therapist_code = therapist.therapist_code
        therapist_info = therapist_masters.get(therapist_code, {})
        therapist_gender = (therapist_info.get('gender', 'Male') or '').strip().lower()
        therapist_grade_name = (therapist_info.get('grade') or '').strip()
        
        # Apply gender filter if specified
        if gender_filter and therapist_gender != gender_filter:
            continue
        # Apply grade filter if specified (exact, case-insensitive match)
        if grade_filter:
            if not therapist_grade_name:
                continue
            if therapist_grade_name.lower() != grade_filter_lower:
                continue
        
        difficulty = therapy_categories.get(booking.allocation.therapy_code, 'Uncategorized')
        difficulty = difficulty.strip() or 'Uncategorized'
        difficulty = difficulty.title()
        
        data = therapist_map[therapist_code]
        if not data['name']:
            data['name'] = therapist.therapist_name
            data['grade'] = therapist_grade_name or getattr(therapist, 'therapist_grade', '')
            data['gender'] = therapist_info.get('gender', 'Male')
        data['counts'][difficulty] += 1
        data['total'] += 1
        total_assignments += 1
        difficulties.add(difficulty)
    
    preferred_order = ['Critical', 'Hard', 'Medium', 'Easy', 'Simple']
    order_map = {name: idx for idx, name in enumerate(preferred_order)}
    difficulties_list = sorted(
        difficulties,
        key=lambda name: (0, order_map[name]) if name in order_map else (1, name.lower())
    )
    
    therapists_payload = []
    for code, data in therapist_map.items():
        row_counts = {diff: data['counts'].get(diff, 0) for diff in difficulties_list}
        therapists_payload.append({
            'therapist_code': code,
            'therapist_name': data['name'],
            'therapist_grade': data['grade'],
            'therapist_gender': data['gender'],
            'total': data['total'],
            'counts': row_counts
        })
    
    therapists_payload.sort(key=lambda item: item['total'], reverse=True)
    
    difficulty_totals = {
        diff: sum(row['counts'].get(diff, 0) for row in therapists_payload)
        for diff in difficulties_list
    }

    # Aggregate by therapist grade for charts (grade vs difficulty)
    grade_summary = defaultdict(lambda: {diff: 0 for diff in difficulties_list})
    for row in therapists_payload:
        grade = (row.get('therapist_grade') or '').strip() or 'Unknown'
        for diff in difficulties_list:
            grade_summary[grade][diff] = grade_summary[grade].get(diff, 0) + row['counts'].get(diff, 0)
    
    # NEW: Calculate scheduled treatments by difficulty and therapist requirements
    treatment_scheduling_data = {
        'treatment_counts': {'Easy': 0, 'Medium': 0, 'Hard': 0, 'Uncategorized': 0},
        'therapist_requirements': {
            'Easy': {'super_senior': 0, 'senior': 0, 'junior': 0, 'trainee': 0},
            'Medium': {'super_senior': 0, 'senior': 0, 'junior': 0, 'trainee': 0},
            'Hard': {'super_senior': 0, 'senior': 0, 'junior': 0, 'trainee': 0},
            'Uncategorized': {'super_senior': 0, 'senior': 0, 'junior': 0, 'trainee': 0}
        }
    }
    
    try:
        # Get all scheduled bookings for the date
        scheduled_bookings = Booking.objects.filter(
            date=target_date,
            status__in=['scheduled', 'draft']  # Include both scheduled and draft bookings
        ).select_related('allocation')

        # Optional: filter by patient gender at the Booking/TherapyAllocation level
        if patient_gender_filter in ('male', 'female'):
            gender_prefix = 'M' if patient_gender_filter == 'male' else 'F'
            scheduled_bookings = scheduled_bookings.filter(
                allocation__patient__pat_sex__istartswith=gender_prefix
            )
        
        # Get unique therapy allocations to avoid double counting
        seen_allocations = set()
        for booking in scheduled_bookings:
            if not booking.allocation:
                continue
            
            # Use allocation + date as unique key (same therapy for same patient on same date = 1 treatment)
            allocation_key = (booking.allocation.pk, booking.date)
            if allocation_key in seen_allocations:
                continue
            seen_allocations.add(allocation_key)
            
            # Get therapy code from allocation
            therapy_code = getattr(booking.allocation, 'therapy_code', None)
            if not therapy_code:
                continue
            
            # Get TherapyMaster to get category and requirements
            try:
                therapy_master = TherapyMaster.objects.filter(therapy_code=therapy_code).first()
                if not therapy_master:
                    continue
                
                # Get category
                category = (therapy_master.therapy_category or therapy_master.therapy_group or 'Uncategorized').strip() or 'Uncategorized'
                category = category.title()
                
                # Normalize to Easy/Medium/Hard/Uncategorized
                if category not in ['Easy', 'Medium', 'Hard']:
                    category = 'Uncategorized'
                
                # Count treatment
                treatment_scheduling_data['treatment_counts'][category] = treatment_scheduling_data['treatment_counts'].get(category, 0) + 1
                
                # Sum therapist requirements
                req = treatment_scheduling_data['therapist_requirements'][category]
                req['super_senior'] += int(getattr(therapy_master, 'no_of_super_senior_therapist', 0) or 0)
                req['senior'] += int(getattr(therapy_master, 'no_of_senior_therapist', 0) or 0)
                req['junior'] += int(getattr(therapy_master, 'no_of_junior_therapist', 0) or 0)
                req['trainee'] += int(getattr(therapy_master, 'no_of_trainee_therapist', 0) or 0)
                
            except Exception as e:
                logger.debug(f"Error processing therapy {therapy_code}: {e}")
                continue
    except Exception as e:
        logger.debug(f"Error calculating treatment scheduling data: {e}")
    
    summary = {
        'total_assignments': total_assignments,
        'therapist_count': len(therapists_payload),
        'difficulty_totals': difficulty_totals,
        'grade_summary': grade_summary,
        'treatment_scheduling': treatment_scheduling_data
    }
    
    return JsonResponse({
        'success': True,
        'date': target_date.isoformat(),
        'therapists': therapists_payload,
        'difficulties': difficulties_list,
        'summary': summary
    })
