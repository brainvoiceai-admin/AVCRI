from django.shortcuts import render
from django.http import JsonResponse, HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from django.contrib.auth.decorators import login_required
from django.utils import timezone
from django.db import transaction
from django.utils.dateparse import parse_date
from .models import PrescriptionScheduling, PrescriptionChangeLog, PrescriptionItem, PrescriptionDispatch
from .decorators import prescription_scheduling_access_required, prescription_scheduling_api_access_required
import json
from datetime import datetime
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter, landscape
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
import io
import openpyxl

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter, landscape
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
import io
import openpyxl


@login_required
@prescription_scheduling_access_required
def prescription_scheduling_dashboard(request):
    """
    Display the prescription scheduling dashboard with draft, scheduled, and dispatched prescriptions.
    Similar to therapy scheduling dashboard but for prescriptions.
    """
    from .models import PrescriptionAllocation
    from django.utils.dateparse import parse_date
    
    # Get date filter from request
    date_filter = request.GET.get('date')
    if date_filter:
        try:
            filter_date = parse_date(date_filter)
        except:
            filter_date = None
    else:
        filter_date = None
    
    # Use PrescriptionScheduling for per-date filtering (similar to Booking for therapies)
    from .models import PrescriptionScheduling
    
    if filter_date:
        # Get PrescriptionScheduling records for the specific date
        draft_scheduling = PrescriptionScheduling.objects.filter(
            prescription_date=filter_date,
            status='draft'
        ).select_related('patient', 'doctor')
        
        scheduled_scheduling = PrescriptionScheduling.objects.filter(
            prescription_date=filter_date,
            status='scheduled'
        ).select_related('patient', 'doctor')
        
        dispatched_scheduling = PrescriptionScheduling.objects.filter(
            prescription_date=filter_date,
            status='dispatched'
        ).select_related('patient', 'doctor')
        
        context = {
            'draft_allocations': [],  # Not used when date filter is active
            'scheduled_allocations': [],
            'dispatched_allocations': [],
            'draft_scheduling': draft_scheduling,
            'scheduled_scheduling': scheduled_scheduling,
            'dispatched_scheduling': dispatched_scheduling,
            'date_filter': date_filter or '',
            'stats': {
                'draft_count': draft_scheduling.count(),
                'scheduled_count': scheduled_scheduling.count(),
                'dispatched_count': dispatched_scheduling.count(),
            }
        }
    else:
        # If no date filter, show all PrescriptionScheduling by status
        draft_scheduling = PrescriptionScheduling.objects.filter(
            status='draft'
        ).select_related('patient', 'doctor')
        
        scheduled_scheduling = PrescriptionScheduling.objects.filter(
            status='scheduled'
        ).select_related('patient', 'doctor')
        
        dispatched_scheduling = PrescriptionScheduling.objects.filter(
            status='dispatched'
        ).select_related('patient', 'doctor')
        
        context = {
            'draft_allocations': [],  # Legacy - not used
            'scheduled_allocations': [],
            'dispatched_allocations': [],
            'draft_scheduling': draft_scheduling,
            'scheduled_scheduling': scheduled_scheduling,
            'dispatched_scheduling': dispatched_scheduling,
            'date_filter': '',
            'stats': {
                'draft_count': draft_scheduling.count(),
                'scheduled_count': scheduled_scheduling.count(),
                'dispatched_count': dispatched_scheduling.count(),
            }
        }
    
    return render(request, 'dashboards/prescriptions/prescription_scheduling.html', context)

@csrf_exempt
@require_http_methods(["GET"])
@prescription_scheduling_api_access_required
def get_prescription_data_api(request):
    """
    API endpoint to fetch prescription data for the scheduling dashboard.
    Works with PrescriptionAllocation similar to how therapy dashboard works with TherapyAllocation.
    """
    try:
        from .models import PrescriptionAllocation
        
        status = request.GET.get('status', 'draft')
        date = request.GET.get('date')
        
        if not date:
            return JsonResponse({'error': 'Date is required'}, status=400)
        
        filter_date = parse_date(date)
        if not filter_date:
            return JsonResponse({'error': 'Invalid date format'}, status=400)
        
        # Get PrescriptionScheduling records for the specific date (per-date processing)
        prescriptions = PrescriptionScheduling.objects.filter(
            prescription_date=filter_date,
            status=status  # Use status directly (draft, scheduled, dispatched)
        ).select_related('patient', 'doctor')
        
        data = []
        for prescription_scheduling in prescriptions:
            try:
                # Get patient details
                patient = prescription_scheduling.patient
                
                # Handle potential None values
                patient_name = patient.pat_name or 'Unknown'
                
                # Get doctor information from Registration and doctor_master tables
                doctor_name = ''
                doctor_team = ''
                try:
                    from MySql_Data_pull.models import Registration, doctor_master
                    
                    # Extract numeric digits from pat_reg_no (handle string format)
                    reg_no_str = str(patient.pat_reg_no).strip()
                    digits_only = ''.join(ch for ch in reg_no_str if ch.isdigit())
                    
                    # Check if patient is OP (5 digits) - OP patients are not in Registration table
                    is_op = len(digits_only) == 5
                    
                    if not is_op and digits_only:
                        # IP patient - convert to integer for querying Registration table
                        try:
                            reg_no_int = int(digits_only)
                            # Use the therapy_db connection for Registration table
                            registration = Registration.objects.using('therapy_db').filter(
                                pat_reg_no=reg_no_int
                            ).first()
                            
                            if registration:
                                # Get doctor team from Registration table
                                doctor_team = registration.dct_team or ''
                                
                                # Get doctor name from doctor_master table using doctcode
                                if registration.doctcode:
                                    doctor = doctor_master.objects.using('therapy_db').filter(
                                        Doct_Code=registration.doctcode
                                    ).first()
                                    
                                    if doctor:
                                        doctor_name = doctor.Doct_Name or ''
                        except (ValueError, TypeError) as e:
                            print(f"Error converting registration number to integer: {e}")
                except Exception as e:
                    # If there's an error fetching from Registration/doctor_master, show empty
                    print(f"Error fetching doctor info from Registration: {e}")
                    doctor_name = ''
                    doctor_team = ''
                
                # Get room_no - fallback to PatientSnapshot.pat_room_no
                room_no = getattr(patient, 'pat_room_no', None)
                
                # Get ALL prescription allocations for this patient and date
                # Exclude only cancelled prescriptions for this specific date
                allocations = PrescriptionAllocation.objects.filter(
                    patient=patient,
                    from_date__lte=filter_date,
                    to_date__gte=filter_date
                )
                
                # Filter out allocations that are cancelled for this specific date
                active_allocations = []
                for alloc in allocations:
                    # Skip if allocation is cancelled and the filter_date falls within the cancelled date range
                    if alloc.status == 'cancelled' and alloc.cancelled_date_from and alloc.cancelled_date_to:
                        if alloc.cancelled_date_from <= filter_date <= alloc.cancelled_date_to:
                            # This prescription is cancelled for this date, skip it
                            continue
                    active_allocations.append(alloc)
                
                # If no active allocations (all are cancelled for this date), skip this patient entry
                if not active_allocations:
                    continue
                
                # Count items from all active allocations
                prescription_count = 0
                prescription_names = []
                
                for allocation in active_allocations:
                    if allocation.prescription_name:
                        prescription_names.append(allocation.prescription_name)
                    
                    # Normalize items_groups to a list of groups
                    raw_groups = allocation.items_groups
                    groups = []
                    if isinstance(raw_groups, str):
                        try:
                            groups = json.loads(raw_groups)
                        except Exception:
                            groups = []
                    elif isinstance(raw_groups, list):
                        groups = raw_groups
                    elif isinstance(raw_groups, dict):
                        groups = [raw_groups]
                    else:
                        groups = []

                    # Count total items across groups for this allocation
                    for grp in groups:
                        items = grp.get('items', []) if isinstance(grp, dict) else []
                        prescription_count += len(items)
                
                # Use first prescription name or default
                prescription_name = prescription_names[0] if prescription_names else 'Prescription'
                if len(prescription_names) > 1:
                    prescription_name += f' (+{len(prescription_names) - 1} more)'
                
                data.append({
                    'patient_id': patient.id,
                    'scheduling_id': prescription_scheduling.id,
                    'patient_name': patient_name,
                    'patient_id_display': patient.pat_reg_no,
                    'registration_no': patient.pat_reg_no,
                    'room_no': room_no,
                    'doctor_name': doctor_name,
                    'doctor_team': doctor_team,
                    'prescription_count': prescription_count,
                    'status': prescription_scheduling.status,
                    'prescription_name': prescription_name,
                    'prescription_date': prescription_scheduling.prescription_date.isoformat(),
                    'sent_to': prescription_scheduling.sent_to,
                    'dispatched_from': prescription_scheduling.dispatched_from,
                    'dispatched_at': prescription_scheduling.dispatched_at.isoformat() if prescription_scheduling.dispatched_at else None,
                    'created_at': prescription_scheduling.created_at.isoformat(),
                    'updated_at': prescription_scheduling.updated_at.isoformat()
                })
            except Exception as item_error:
                continue
        
        return JsonResponse({
            'success': True,
            'data': data,
            'count': len(data)
        })
        
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)

@csrf_exempt
@require_http_methods(["GET"])
@prescription_scheduling_api_access_required
def get_prescription_details_api(request):
    """
    API endpoint to get detailed prescription information for a patient.
    Returns the same format as procurement dashboard - grouped prescription and therapy items.
    """
    try:
        from .models import PrescriptionAllocation, Booking, BookingItem, PatientSnapshot
        
        patient_id = request.GET.get('patient_id')
        date = request.GET.get('date')
        
        if not patient_id or not date:
            return JsonResponse({'error': 'patient_id and date are required'}, status=400)
        
        filter_date = parse_date(date)
        if not filter_date:
            return JsonResponse({'error': 'Invalid date format'}, status=400)
        
        # Get patient - try PatientSnapshot first, then fall back to therapy data
        patient = None
        patient_info = {
            'name': 'Unknown',
            'registration_no': '',
            'room_no': None,
            'age': '',
            'sex': '',
            'doctor_name': None,
            'doctor_team': ''
        }
        
        try:
            patient = PatientSnapshot.objects.get(pk=patient_id)
            patient_info = {
                'name': patient.pat_name or 'Unknown',
                'registration_no': patient.pat_reg_no,
                'room_no': getattr(patient, 'pat_room_no', None),
                'age': getattr(patient, 'pat_age', '') or '',
                'sex': getattr(patient, 'pat_sex', '') or '',
                'doctor_name': None,  # Will be set from Registration->doctor_master
                'doctor_team': ''  # Will be set from Registration
            }
        except PatientSnapshot.DoesNotExist:
            # Patient not in snapshot - try to get from therapy allocations
            from .models import TherapyAllocation
            therapy_alloc = TherapyAllocation.objects.filter(
                patient_id=patient_id
            ).select_related('patient').first()
            
            if therapy_alloc and therapy_alloc.patient:
                patient = therapy_alloc.patient
                patient_info = {
                    'name': patient.pat_name or 'Unknown',
                    'registration_no': patient.pat_reg_no,
                    'room_no': getattr(patient, 'pat_room_no', None),
                    'age': getattr(patient, 'pat_age', '') or '',
                    'sex': getattr(patient, 'pat_sex', '') or '',
                    'doctor_name': None,  # Will be set from Registration->doctor_master
                    'doctor_team': ''  # Will be set from Registration
                }
            else:
                # If still not found, return 404
                return JsonResponse({'error': 'Patient not found'}, status=404)
        
        # Get doctor information from Registration and doctor_master tables
        # First, get doctcode and dct_team from Registration table using pat_reg_no
        try:
            from MySql_Data_pull.models import Registration, doctor_master
            from django.db import connections
            
            # Extract numeric digits from registration_no (handle string format)
            reg_no_str = str(patient_info['registration_no']).strip()
            digits_only = ''.join(ch for ch in reg_no_str if ch.isdigit())
            
            # Check if patient is OP (5 digits) - OP patients are not in Registration table
            is_op = len(digits_only) == 5
            
            if not is_op and digits_only:
                # IP patient - convert to integer for querying Registration table
                try:
                    reg_no_int = int(digits_only)
                    # Use the therapy_db connection for Registration table
                    registration = Registration.objects.using('therapy_db').filter(
                        pat_reg_no=reg_no_int
                    ).first()
                    
                    if registration:
                        # Get doctor team from Registration table
                        patient_info['doctor_team'] = registration.dct_team or ''
                        
                        # Get doctor name from doctor_master table using doctcode
                        if registration.doctcode:
                            doctor = doctor_master.objects.using('therapy_db').filter(
                                Doct_Code=registration.doctcode
                            ).first()
                            
                            if doctor:
                                patient_info['doctor_name'] = doctor.Doct_Name or ''
                            else:
                                patient_info['doctor_name'] = ''
                        else:
                            patient_info['doctor_name'] = ''
                    else:
                        patient_info['doctor_name'] = ''
                        patient_info['doctor_team'] = ''
                except (ValueError, TypeError) as e:
                    print(f"Error converting registration number to integer: {e}")
                    patient_info['doctor_name'] = ''
                    patient_info['doctor_team'] = ''
            else:
                # OP patient - not in Registration table
                patient_info['doctor_name'] = ''
                patient_info['doctor_team'] = ''
        except Exception as e:
            # If there's an error fetching from Registration/doctor_master, show empty
            print(f"Error fetching doctor info from Registration: {e}")
            patient_info['doctor_name'] = ''
            patient_info['doctor_team'] = ''
        
        # Get PrescriptionScheduling for the specific date (for other purposes, not doctor name)
        prescription_scheduling = PrescriptionScheduling.objects.filter(
            patient_id=patient_id,
            prescription_date=filter_date
        ).select_related('doctor').first()
        
        # Don't use PrescriptionScheduling.doctor as fallback - only use doctor from Registration->doctor_master
        
        # ===== PRESCRIPTION ITEMS =====
        prescription_groups = []  # List of groups with items
        
        # Get all PrescriptionAllocation records for this patient that cover the date
        allocations = PrescriptionAllocation.objects.filter(
            patient_id=patient_id,
            from_date__lte=filter_date,
            to_date__gte=filter_date
        ).order_by('from_date', 'id')
        
        # Include all allocations, but we'll mark them as cancelled only if the current date
        # falls within the cancelled date range. This way cancelled entries show as cancelled
        # only for the specific dates they were cancelled, not for all dates.
        active_allocations = []
        for allocation in allocations:
            # Check if this allocation is cancelled for the current date
            is_cancelled_for_this_date = False
            if allocation.status == 'cancelled' and allocation.cancelled_date_from and allocation.cancelled_date_to:
                if allocation.cancelled_date_from <= filter_date <= allocation.cancelled_date_to:
                    is_cancelled_for_this_date = True
            
            # Include the allocation in active_allocations regardless of cancellation status
            # We'll use is_cancelled_for_this_date when setting is_cancelled flag for groups
            active_allocations.append(allocation)
        
        prescription_is_cancelled = False
        prescription_status = 'draft'
        
        if active_allocations:
            # Check if all allocations are cancelled for this specific date
            all_cancelled_for_date = True
            for a in active_allocations:
                is_cancelled_for_date = False
                if a.status == 'cancelled' and a.cancelled_date_from and a.cancelled_date_to:
                    if a.cancelled_date_from <= filter_date <= a.cancelled_date_to:
                        is_cancelled_for_date = True
                if not is_cancelled_for_date:
                    all_cancelled_for_date = False
                    break
            
            prescription_is_cancelled = all_cancelled_for_date
            # Get status from non-cancelled allocations (for this date)
            non_cancel_statuses = []
            for a in active_allocations:
                is_cancelled_for_date = False
                if a.status == 'cancelled' and a.cancelled_date_from and a.cancelled_date_to:
                    if a.cancelled_date_from <= filter_date <= a.cancelled_date_to:
                        is_cancelled_for_date = True
                if not is_cancelled_for_date:
                    non_cancel_statuses.append(a.status)
            prescription_status = non_cancel_statuses[0] if non_cancel_statuses else 'cancelled'
        
        # Process all active allocations and use items_groups exactly as stored
        for allocation in active_allocations:
            if allocation.items_groups:
                raw_groups = allocation.items_groups
                groups = []
                if isinstance(raw_groups, str):
                    try:
                        groups = json.loads(raw_groups)
                    except Exception:
                        groups = []
                elif isinstance(raw_groups, list):
                    groups = raw_groups
                elif isinstance(raw_groups, dict):
                    groups = [raw_groups]
                
                # Use groups exactly as they are in items_groups
                for group_idx, group in enumerate(groups):
                    items = group.get('items', []) if isinstance(group, dict) else []
                    group_items = []
                    
                    # Convert items from items_groups to the format expected by frontend
                    for it in items:
                        if it and (it.get('item_name') or it.get('id')):
                            group_items.append({
                                'id': f'prescription_alloc_{allocation.id}_{it.get("id", "")}',
                                'type': 'prescription',
                                'item_name': it.get('item_name', ''),
                                'dose': group.get('dosage', ''),
                                'quantity': it.get('quantity', ''),
                                'time': group.get('time', ''),
                                'notes': group.get('uno', ''),
                                'status': 'active'
                            })
                    
                    # Fallback: use allocation-level usage/scope if group-level missing
                    alloc_usage = getattr(allocation, 'usage', '')
                    alloc_scope = getattr(allocation, 'scope', '')
                    group_usage = group.get('usage', '') or alloc_usage
                    usage_array = group.get('usage_array', [])
                    internal_external = group.get('internal_external', '') or alloc_scope
                    
                    # Check if this allocation is cancelled for the current date
                    # Only mark as cancelled if the current date falls within the cancelled date range
                    is_cancelled_for_date = False
                    if allocation.status == 'cancelled' and allocation.cancelled_date_from and allocation.cancelled_date_to:
                        if allocation.cancelled_date_from <= filter_date <= allocation.cancelled_date_to:
                            is_cancelled_for_date = True
                    
                    # Add the group exactly as it appears in items_groups (with fallbacks)
                    prescription_groups.append({
                        'group_id': f"prescription_group_{allocation.id}_{group_idx}",
                        'time': group.get('time', 'M'),
                        'dose': group.get('dosage', ''),
                        'usage': group_usage,
                        'usage_array': usage_array,
                        'internal_external': internal_external,
                        'notes': group.get('uno', ''),
                        'oil_class': group.get('oil_class', ''),
                        'ingredients': group.get('ingredients', []),
                        'ingredient_ids': group.get('ingredient_ids', []),
                        'items': group_items,
                        'is_cancelled': is_cancelled_for_date,
                        'is_group': True
                    })
        
        # If no allocations found, check for PrescriptionItem records as fallback
        if not prescription_groups and prescription_scheduling:
            items_qs = PrescriptionItem.objects.filter(prescription_scheduling=prescription_scheduling).all()
            prescription_is_cancelled = prescription_scheduling.status == 'cancelled'
            prescription_status = prescription_scheduling.status
            
            if items_qs.exists():
                for item in items_qs:
                    prescription_groups.append({
                        'group_id': f"prescription_item_{item.id}",
                        'time': item.time or '',
                        'dose': item.dose or '',
                        'usage': getattr(item, 'usage', '') or '',
                        'internal_external': getattr(item, 'internal_external', '') or '',
                        'notes': item.notes or '',
                        'ingredients': [],
                        'ingredient_ids': [],
                        'items': [{
                            'id': f'prescription_{item.id}',
                            'type': 'prescription',
                            'item_name': item.item_name,
                            'dose': item.dose or '',
                            'quantity': item.quantity or '',
                            'time': item.time or '',
                            'usage': getattr(item, 'usage', '') or '',
                            'internal_external': getattr(item, 'internal_external', '') or '',
                            'notes': item.notes or '',
                            'status': getattr(item, 'status', 'active') if hasattr(item, 'status') else 'active'
                        }],
                        'is_group': True
                    })
        
        # Flatten for backward compatibility
        prescription_items = []
        for group in prescription_groups:
            prescription_items.extend(group['items'])
        
        # ===== THERAPY ITEMS (BookingItem) =====
        # Get all bookings for this patient on this date
        bookings = Booking.objects.filter(
            allocation__patient=patient,
            date=filter_date
        ).select_related('allocation').prefetch_related('items').order_by('allocation__therapy_name', 'timeslot')
        
        # Group therapy items by allocation and items_groups structure
        therapy_groups = {}
        
        for booking in bookings:
            if not booking.allocation:
                continue
                
            allocation = booking.allocation
            therapy_name = allocation.therapy_name
            
            # Get items_groups from allocation
            items_groups = allocation.items_groups if isinstance(allocation.items_groups, list) else []
            
            # Get all BookingItems for this booking
            booking_items = booking.items.all()
            
            # If we have items_groups, try to match BookingItems to groups
            if items_groups and booking_items.exists():
                item_map = {item.item_code: item for item in booking_items}
                item_map.update({item.item_name: item for item in booking_items if item.item_name not in item_map})
                
                for group_idx, group in enumerate(items_groups):
                    group_key = (allocation.id, group_idx)
                    dosage = group.get('dosage', '')
                    uno = group.get('uno', '')
                    
                    if group_key not in therapy_groups:
                        therapy_groups[group_key] = {
                            'therapy_name': therapy_name,
                            'therapy_id': allocation.id,
                            'dosage': dosage,
                            'usage': group.get('usage', ''),
                            'usage_array': group.get('usage_array', []),
                            'internal_external': group.get('internal_external', ''),
                            'uno': uno,
                            'oil_class': group.get('oil_class', '') or allocation.oil_class or '',
                            'ingredients': group.get('ingredients', []) or [],
                            'booking_id': booking.id,
                            'booking_status': booking.status,
                            'items': []
                        }
                    
                    # Match items from group to BookingItems
                    group_items = group.get('items', [])
                    for group_item in group_items:
                        item_code = group_item.get('item_code') or group_item.get('id') or ''
                        item_name = group_item.get('item_name') or group_item.get('text') or ''
                        
                        booking_item = None
                        if item_code and item_code in item_map:
                            booking_item = item_map[item_code]
                        elif item_name and item_name in item_map:
                            booking_item = item_map[item_name]
                        else:
                            for bi in booking_items:
                                if bi.item_name == item_name or bi.item_code == item_code:
                                    booking_item = bi
                                    break
                        
                        if booking_item:
                            therapy_groups[group_key]['items'].append({
                                'id': f'therapy_{booking_item.id}',
                                'type': 'therapy',
                                'item_name': booking_item.item_name,
                                'item_code': booking_item.item_code,
                                'dose': booking_item.dosage or dosage,
                                'quantity': '',
                                'time': '',
                                'notes': booking_item.uno or uno,
                                'status': booking_item.status
                            })
                        else:
                            therapy_groups[group_key]['items'].append({
                                'id': f'therapy_missing_{group_idx}_{len(therapy_groups[group_key]["items"])}',
                                'type': 'therapy',
                                'item_name': item_name,
                                'item_code': item_code,
                                'dose': dosage,
                                'quantity': '',
                                'time': '',
                                'notes': uno,
                                'status': 'removed',
                                'is_removed': True
                            })
            else:
                # Fallback: if no items_groups, show items individually grouped by booking
                group_key = (allocation.id, booking.id)
                if group_key not in therapy_groups:
                    therapy_groups[group_key] = {
                        'therapy_name': therapy_name,
                        'therapy_id': allocation.id,
                        'dosage': '',
                        'usage': allocation.usage or '',
                        'usage_array': [],
                        'internal_external': allocation.ext_int or '',
                        'uno': '',
                        'oil_class': allocation.oil_class or '',
                        'ingredients': [],
                        'booking_id': booking.id,
                        'booking_status': booking.status,
                        'items': []
                    }
                
                for item in booking_items:
                    therapy_groups[group_key]['items'].append({
                        'id': f'therapy_{item.id}',
                        'type': 'therapy',
                        'item_name': item.item_name,
                        'item_code': item.item_code,
                        'dose': item.dosage or '',
                        'quantity': '',
                        'time': '',
                        'notes': item.uno or '',
                        'status': item.status
                    })
        
        # Convert grouped structure to flat list for response
        therapy_items = []
        for group_key, group_data in therapy_groups.items():
            booking_is_cancelled = group_data['booking_status'] == 'cancelled'
            
            items_without_cancellation = []
            for item in group_data['items']:
                item_copy = item.copy()
                item_copy.pop('is_cancelled', None)
                items_without_cancellation.append(item_copy)
            
            therapy_items.append({
                'group_id': f"therapy_group_{group_key[0]}_{group_key[1]}",
                'therapy_name': group_data['therapy_name'],
                'therapy_id': group_data['therapy_id'],
                'dosage': group_data['dosage'],
                'usage': group_data.get('usage', ''),
                'usage_array': group_data.get('usage_array', []),
                'internal_external': group_data.get('internal_external', ''),
                'uno': group_data['uno'],
                'oil_class': group_data.get('oil_class', ''),
                'ingredients': group_data.get('ingredients', []),
                'booking_id': group_data['booking_id'],
                'booking_status': group_data['booking_status'],
                'booking_is_cancelled': booking_is_cancelled,
                'items': items_without_cancellation,
                'is_group': True
            })
        
        return JsonResponse({
            'success': True,
            'patient_info': patient_info,
            'prescription_items': prescription_items,  # Flattened for backward compatibility
            'prescription_groups': prescription_groups,  # Grouped prescription items
            'therapy_items': therapy_items,  # Grouped therapy items
            'counts': {
                'total': len(prescription_items) + sum(len(g['items']) for g in therapy_items),
                'prescription': len(prescription_items),
                'prescription_groups': len(prescription_groups),
                'therapy': len(therapy_items)
            }
        })
        
    except Exception as e:
        import traceback
        return JsonResponse({'error': str(e), 'traceback': traceback.format_exc()}, status=500)

@csrf_exempt
@require_http_methods(["POST"])
@prescription_scheduling_api_access_required
def send_final_prescription_api(request):
    """
    API endpoint to send final prescriptions to procurement departments.
    Works with PrescriptionAllocation - updates status from draft to active.
    """
    try:
        from .models import PrescriptionAllocation
        
        data = json.loads(request.body)
        date = data.get('date')
        
        if not date:
            return JsonResponse({'error': 'Date is required'}, status=400)
        
        filter_date = parse_date(date)
        if not filter_date:
            return JsonResponse({'error': 'Invalid date format'}, status=400)
        
        # Get all draft PrescriptionScheduling records for the specific date (per-date processing)
        draft_prescriptions = PrescriptionScheduling.objects.filter(
            prescription_date=filter_date,
            status='draft'
        ).select_related('patient')
        
        if not draft_prescriptions.exists():
            return JsonResponse({'error': 'No draft prescriptions found for the selected date'}, status=400)
        
        with transaction.atomic():
            updated_count = 0
            sent_to_departments = []
            
            for prescription_scheduling in draft_prescriptions:
                # Get the associated PrescriptionAllocation to determine department
                # Find allocation that covers this date
                allocation = PrescriptionAllocation.objects.filter(
                    patient=prescription_scheduling.patient,
                    from_date__lte=filter_date,
                    to_date__gte=filter_date
                ).first()
                
                if allocation:
                    # Determine which department to send to based on patient type or prescription content
                    department = determine_procurement_department_from_allocation(allocation)
                    
                    # Update PrescriptionScheduling status to scheduled (only for this specific date)
                    prescription_scheduling.status = 'scheduled'
                    prescription_scheduling.sent_to = department
                    prescription_scheduling.save()
                    
                    # Log the change
                    PrescriptionChangeLog.objects.create(
                        patient=prescription_scheduling.patient,
                        prescription_date=filter_date,
                        action='status_change',
                        changed_by=request.user,
                        before_values={'status': 'draft'},
                        after_values={'status': 'scheduled', 'sent_to': department},
                        description=f'Prescription sent to {department} for date {filter_date}'
                    )
                    
                    updated_count += 1
                    if department not in sent_to_departments:
                        sent_to_departments.append(department)
        
        return JsonResponse({
            'success': True,
            'message': f'Successfully sent {updated_count} prescriptions to {", ".join(sent_to_departments)}',
            'updated_count': updated_count,
            'departments': sent_to_departments
        })
        
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)

@csrf_exempt
@require_http_methods(["GET"])
@prescription_scheduling_api_access_required
def get_change_log_api(request):
    """
    API endpoint to get change log for a patient's prescription.
    """
    try:
        patient_id = request.GET.get('patient_id')
        date = request.GET.get('date')
        
        if not patient_id or not date:
            return JsonResponse({'error': 'patient_id and date are required'}, status=400)
        
        filter_date = parse_date(date)
        if not filter_date:
            return JsonResponse({'error': 'Invalid date format'}, status=400)
        
        # Get change log entries
        change_logs = PrescriptionChangeLog.objects.filter(
            patient_id=patient_id,
            prescription_date=filter_date
        ).select_related('changed_by').order_by('-timestamp')
        
        change_log_data = []
        for log in change_logs:
            change_log_data.append({
                'action': log.get_action_display(),
                'patient_name': log.patient.pat_name,
                'date': log.prescription_date.isoformat(),
                'changed_by': log.changed_by.get_full_name() or log.changed_by.username,
                'timestamp': log.timestamp.isoformat(),
                'before_values': log.before_values,
                'after_values': log.after_values,
                'description': log.description
            })
        
        return JsonResponse({
            'success': True,
            'change_log': change_log_data
        })
        
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)

@csrf_exempt
@require_http_methods(["POST"])
@prescription_scheduling_api_access_required
def update_prescription_status_api(request):
    """
    API endpoint to update prescription status (called from procurement dashboards).
    Works with PrescriptionAllocation.
    """
    try:
        from .models import PrescriptionAllocation
        
        data = json.loads(request.body)
        patient_id = data.get('patient_id')
        date = data.get('date')
        new_status = data.get('status')
        department = data.get('department')
        
        if not all([patient_id, date, new_status]):
            return JsonResponse({'error': 'patient_id, date, and status are required'}, status=400)
        
        filter_date = parse_date(date)
        if not filter_date:
            return JsonResponse({'error': 'Invalid date format'}, status=400)
        
        # Get PrescriptionScheduling for the specific date (per-date processing)
        prescription_scheduling = PrescriptionScheduling.objects.filter(
            patient_id=patient_id,
            prescription_date=filter_date
        ).first()
        
        if not prescription_scheduling:
            return JsonResponse({'error': 'Prescription not found'}, status=404)
        
        old_status = prescription_scheduling.status
        
        with transaction.atomic():
            # Update PrescriptionScheduling status (only for this specific date)
            prescription_scheduling.status = new_status
            if new_status == 'dispatched':
                prescription_scheduling.dispatched_from = department
                prescription_scheduling.dispatched_at = timezone.now()
            prescription_scheduling.save()
            
            # Log the change
            PrescriptionChangeLog.objects.create(
                patient=prescription_scheduling.patient,
                prescription_date=filter_date,
                action='status_change',
                changed_by=request.user,
                before_values={'status': old_status},
                after_values={'status': new_status, 'dispatched_from': department},
                description=f'Status changed from {old_status} to {new_status} by {department} for date {filter_date}'
            )
        
        return JsonResponse({
            'success': True,
            'message': f'Prescription status updated to {new_status}'
        })
        
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)

def determine_procurement_department(prescription):
    """
    Determine which procurement department should handle the prescription.
    This is a simple implementation - you can make it more sophisticated.
    """
    # Check if patient is IP (inpatient)
    if hasattr(prescription.patient, 'room_no') and prescription.patient.room_no:
        return 'IP Pharmacy'
    
    # Check prescription items for kashaya/ayurvedic medicines
    for item in prescription.items.all():
        if any(keyword in item.item_name.lower() for keyword in ['kashaya', 'kashayam', 'taila', 'oil']):
            return 'Kashaya Room'
    
    # Default to IP Pharmacy
    return 'IP Pharmacy'

def determine_procurement_department_from_allocation(allocation):
    """
    Determine which procurement department should handle the prescription allocation.
    Works with PrescriptionAllocation instead of PrescriptionScheduling.
    """
    # Check if patient is IP (inpatient) - check pat_room_no
    if hasattr(allocation.patient, 'pat_room_no') and allocation.patient.pat_room_no:
        return 'IP Pharmacy'
    
    # Check prescription items_groups for kashaya/ayurvedic medicines
    items_groups = allocation.items_groups if isinstance(allocation.items_groups, list) else []
    for group in items_groups:
        for item in group.get('items', []):
            item_name = item.get('item_name', '').lower()
            if any(keyword in item_name for keyword in ['kashaya', 'kashayam', 'taila', 'oil']):
                return 'Kashaya Room'
    
    # Default to IP Pharmacy
    return 'IP Pharmacy'

def log_prescription_change(patient, prescription_date, action, changed_by, before_values=None, after_values=None, description=None):
    """
    Helper function to log prescription changes.
    """
    PrescriptionChangeLog.objects.create(
        patient=patient,
        prescription_date=prescription_date,
        action=action,
        changed_by=changed_by,
        before_values=before_values,
        after_values=after_values,
        description=description
    )

@csrf_exempt
@require_http_methods(["GET"])
@prescription_scheduling_access_required
def get_previous_prescriptions_api(request):
    """
    API to fetch previous prescription history for a patient.
    Now uses 'iptherapy_db' and '[dbo].[Prescription]' table which contains the full history (1.8M+ rows).
    """
    try:
        from MySql_Data_pull.models import ItemMaster
        from django.db import connections
        
        patient_id = request.GET.get('patient_id')
        reg_no_param = request.GET.get('registration_no')
        
        debug_info = {}
        
        if not patient_id and not reg_no_param:
            return JsonResponse({'error': 'Patient ID or Registration Number required'}, status=400)
        
        # Determine registration number
        reg_no = None
        if reg_no_param:
            reg_no = reg_no_param
        elif patient_id:
            try:
                from .models import PatientSnapshot
                patient = PatientSnapshot.objects.get(pk=patient_id)
                reg_no = patient.pat_reg_no
            except Exception:
                pass
        
        if not reg_no:
            return JsonResponse({'error': 'Could not determine registration number'}, status=400)
            
        # Clean reg_no
        try:
            reg_no_int = int(''.join(filter(str.isdigit, str(reg_no))))
        except ValueError:
            return JsonResponse({'error': 'Invalid registration number format'}, status=400)
            
        debug_info['queried_reg_no'] = reg_no_int
        
        # FETCH PRESCRIPTIONS FROM IPTHERAPY_DB
        history_rows = []
        # UPDATED: Use iptherapy_db where the real data resides
        with connections['iptherapy_db'].cursor() as cursor:
            # Query the correct table: [dbo].[Prescription]
            # Columns: Rdate, Pat_Reg_No, Pres_Item_Code, etc.
            # Using SELECT * for simplicity to catch all potential columns, then processing in Python
            # Try iptherapy_db first as it typically has more historical data
            query = """
                SELECT *
                FROM [dbo].[Prescription] 
                WHERE Pat_Reg_No = %s 
                ORDER BY Rdate DESC
            """
            # Fallback to Prescribtion table if Prescription fails (some databases use different spelling)
            fallback_query = """
                SELECT *
                FROM [dbo].[Prescribtion] 
                WHERE Pat_Reg_No = %s 
                ORDER BY Rdate DESC
            """
            debug_info['query'] = query
            try:
                cursor.execute(query, [reg_no_int])
            except:
                debug_info['primary_query_failed'] = True
                cursor.execute(fallback_query, [reg_no_int])

            if cursor.description:
                columns = [col[0] for col in cursor.description]
                col_map = {col.lower(): index for index, col in enumerate(columns)}
                raw_rows = cursor.fetchall()
            else:
                raw_rows = []
                col_map = {}

            history_rows = []
            for row in raw_rows:
                row_dict = {}
                # Map known columns
                ctx_idx = col_map.get('rdate')
                if ctx_idx is not None: row_dict['Pres_Date'] = row[ctx_idx]
                
                ctx_idx = col_map.get('pres_item_code')
                if ctx_idx is not None: row_dict['Pres_Item_Code'] = row[ctx_idx]
                
                ctx_idx = col_map.get('pres_item_dosage')
                if ctx_idx is not None: row_dict['Pres_Item_Dosage'] = row[ctx_idx]
                
                ctx_idx = col_map.get('pres_item_uom')
                if ctx_idx is not None: row_dict['Pres_Item_Uom'] = row[ctx_idx]
                
                ctx_idx = col_map.get('pres_item_usage')
                if ctx_idx is not None: row_dict['Pres_Item_Usage'] = row[ctx_idx]
                
                ctx_idx = col_map.get('pres_item_seq')
                if ctx_idx is not None: row_dict['Pres_Item_Seq'] = row[ctx_idx]
                
                ctx_idx = col_map.get('pres_item_seq1')
                if ctx_idx is not None: row_dict['Pres_Item_Seq1'] = row[ctx_idx]
                
                ctx_idx = col_map.get('ingred')
                if ctx_idx is not None: row_dict['Ingred'] = row[ctx_idx]
                
                ctx_idx = col_map.get('pres_days') or col_map.get('pres_item_days') or col_map.get('pres_time_period')
                if ctx_idx is not None: row_dict['Pres_Days'] = row[ctx_idx]
                
                ctx_idx = col_map.get('pres_doc_code') or col_map.get('pres_doct_code')
                if ctx_idx is not None: 
                    val = row[ctx_idx]
                    row_dict['Pres_Doct_Code'] = str(val).strip() if (val is not None and str(val).strip() != '0') else ''

                ctx_idx = col_map.get('pres_int_ext')
                if ctx_idx is not None: row_dict['Pres_Int_Ext'] = row[ctx_idx]

                ctx_idx = col_map.get('pres_from')
                if ctx_idx is not None: row_dict['Pres_From'] = row[ctx_idx]
                
                ctx_idx = col_map.get('pres_to')
                if ctx_idx is not None: row_dict['Pres_To'] = row[ctx_idx]
                
                ctx_idx = col_map.get('doa')
                if ctx_idx is not None: row_dict['DOA'] = row[ctx_idx]

                history_rows.append(row_dict)

        # Requirement: Show only the latest PAST admission (exclude current)
        latest_past_doa_val = None
        if history_rows:
            # unique_doas sorted descending: [Current, Last Past, Before That, ...]
            unique_doas = sorted(list(set(r.get('DOA') for r in history_rows if r.get('DOA'))), reverse=True)
            
            if len(unique_doas) > 1:
                # Latest past admission is index 1
                latest_past_doa_val = unique_doas[1]
                history_rows = [r for r in history_rows if r.get('DOA') == latest_past_doa_val]
            else:
                # Only current admission or no DOA found
                history_rows = []
        
        # If no history left after filtering current admission
        if not history_rows:
            return JsonResponse({'success': True, 'data': [], 'count': 0, 'debug': debug_info})
            
        # Get all item codes
        item_codes = set()
        for row in history_rows:
            val = row.get('Pres_Item_Code')
            if val:
                item_codes.add(str(val))
                
        # Fetch Item Master details from IPTHERAPY_DB
        item_map = {}
        if item_codes:
                with connections['iptherapy_db'].cursor() as cursor:
                    try:
                        codes_list = list(item_codes)
                        placeholders = ', '.join(['%s'] * len(codes_list))
                        query = f"SELECT item_code, item_name FROM [dbo].[item_Master] WHERE item_code IN ({placeholders})"
                        
                        cursor.execute(query, codes_list)
                        for row in cursor.fetchall():
                            item_map[str(row[0]).strip()] = row[1]
                    except Exception as e:
                        debug_info['item_fetch_error'] = str(e)

        # Get all doctor codes from the history rows
        doctor_codes = set()
        for row in history_rows:
            val = row.get('Pres_Doct_Code')
            if val:
                doctor_codes.add(str(val))

        # PATIENT LEVEL DOCTOR FALLBACK (from Registration table)
        patient_doctor_name = None
        try:
            with connections['therapy_db'].cursor() as cursor:
                 reg_digits = ''.join(c for c in str(reg_no) if c.isdigit())
                 cursor.execute("SELECT doctcode FROM [dbo].[Registration] WHERE pat_reg_no = %s", [reg_digits])
                 reg_row = cursor.fetchone()
                 if reg_row and reg_row[0]:
                     d_code_f = str(reg_row[0]).strip()
                     found_f = False
                     for db_name in ['therapy_db', 'iptherapy_db']:
                         if found_f: break
                         with connections[db_name].cursor() as cursor2:
                             for table_name in ['[dbo].[Doctor_Master_New]', '[dbo].[doctor_master]']:
                                 try:
                                     cursor2.execute(f"SELECT Doct_Name FROM {table_name} WHERE Doct_Code = %s", [d_code_f])
                                     res = cursor2.fetchone()
                                     if res:
                                         patient_doctor_name = res[0]
                                         found_f = True; break
                                     if d_code_f.isdigit():
                                         cursor2.execute(f"SELECT Doct_Name FROM {table_name} WHERE Doct_Code = %s", [d_code_f.zfill(4)])
                                         res = cursor2.fetchone()
                                         if res:
                                             patient_doctor_name = res[0]
                                             found_f = True; break
                                 except: continue
        except Exception as e:
            debug_info['patient_doctor_fallback_error'] = str(e)

        doctor_map = {}
        if doctor_codes:
            # Try therapy_db first, then iptherapy_db as fallback
            for db_name in ['therapy_db', 'iptherapy_db']:
                # Even if we found some, keep looking if some remain missing? 
                # Let's just try to fill the map as much as possible.
                with connections[db_name].cursor() as cursor:
                    try:
                        doc_list = list(doctor_codes)
                        placeholders = ', '.join(['%s'] * len(doc_list))
                        for table_name in ['[dbo].[Doctor_Master_New]', '[dbo].[doctor_master]']:
                            try:
                                query = f"SELECT Doct_Code, Doct_Name FROM {table_name} WHERE Doct_Code IN ({placeholders})"
                                cursor.execute(query, doc_list)
                                for r in cursor.fetchall():
                                    doctor_map[str(r[0]).strip()] = r[1]
                                    # Also store without padding if it was padded
                                    if str(r[0]).strip().startswith('0'):
                                        doctor_map[str(r[0]).strip().lstrip('0')] = r[1]
                                
                                # Check if any missing and try padding
                                remaining = [c for c in doc_list if str(c).strip() not in doctor_map]
                                for c in remaining:
                                    if c.isdigit():
                                        cursor.execute(f"SELECT Doct_Name FROM {table_name} WHERE Doct_Code = %s", [c.zfill(4)])
                                        res = cursor.fetchone()
                                        if res:
                                            doctor_map[str(c).strip()] = res[0]
                            except:
                                continue
                    except Exception as e:
                        debug_info[f'doctor_fetch_error_{db_name}'] = str(e)
                
        # Group by Date, then by Prescription Seq (Prescription Number)
        grouped_history = {}
        
        for row in history_rows:
            rdate = row.get('Pres_Date')
            if not rdate:
                continue
            
            # handle datetime object
            if hasattr(rdate, 'strftime'):
                date_str = rdate.strftime('%Y-%m-%d')
            else:
                date_str = str(rdate).split(' ')[0]
            
            if date_str not in grouped_history:
                grouped_history[date_str] = {
                    'date': date_str,
                    'prescriptions': {} # pres_item_seq -> { seq, doctor, items: [] }
                }
            
            seq_val = row.get('Pres_Item_Seq')
            seq = int(seq_val) if (seq_val is not None and str(seq_val).isdigit()) else 0
            if seq not in grouped_history[date_str]['prescriptions']:
                d_code = row.get('Pres_Doct_Code', '')
                d_name = doctor_map.get(d_code)
                if not d_name and d_code:
                    d_name = f"Dr. {d_code}"
                
                # Use patient-level fallback if still missing
                if not d_name or d_name == "N/A":
                    d_name = patient_doctor_name or "N/A"
                
                grouped_history[date_str]['prescriptions'][seq] = {
                    'seq': seq,
                    'doctor_code': d_code,
                    'doctor_name': d_name,
                    'items': []
                }
            
            item_code_str = str(row.get('Pres_Item_Code', '')).strip()
            item_name = item_map.get(item_code_str, f"Item {item_code_str}")
            
            grouped_history[date_str]['prescriptions'][seq]['items'].append({
                'item_name': item_name,
                'dosage': row.get('Pres_Item_Dosage') or '',
                'uom': row.get('Pres_Item_Uom') or '',
                'usage': row.get('Pres_Item_Usage') or '',
                'seq1': int(row.get('Pres_Item_Seq1', 0) or 0),
                'ingred': row.get('Ingred') or '',
                'duration': row.get('Pres_Days') or '', 
                'int_ext': row.get('Pres_Int_Ext') or '',
                'start_date': row.get('Pres_From'),
                'end_date': row.get('Pres_To')
            })
            
        # Convert to list and sort ASCENDING by date
        history_list = []
        # ASCENDING ORDER for dates
        for date_str in sorted(grouped_history.keys()):
            date_data = grouped_history[date_str]
            
            # Convert prescriptions dict to list and sort ASCENDING by seq
            pres_list = list(date_data['prescriptions'].values())
            pres_list.sort(key=lambda x: x['seq'])
            
            history_list.append({
                'date': date_str,
                'prescriptions': pres_list
            })
        
        # Format DOA for display
        doa_display = ""
        if latest_past_doa_val:
            if hasattr(latest_past_doa_val, 'strftime'):
                doa_display = latest_past_doa_val.strftime('%d/%m/%Y')
            else:
                doa_display = str(latest_past_doa_val).split(' ')[0]
        
        return JsonResponse({
            'success': True,
            'data': history_list,
            'previous_doa': doa_display,
            'doctor_name': patient_doctor_name or "N/A",
            'count': len(history_list),
            'debug': debug_info
        })
        
    except Exception as e:
        import traceback
        error_details = traceback.format_exc()
        # Return 500 with JSON to help debug
        return JsonResponse({
            'success': False,
            'error': str(e),
            'traceback': error_details,
            'debug_info': debug_info
        }, status=500)


@csrf_exempt
@require_http_methods(["GET"])
@prescription_scheduling_access_required
def download_prescription_history_api(request):
    """
    API to download previous prescription history as PDF or Excel.
    Now uses 'iptherapy_db' and '[dbo].[Prescription]' table which contains the full history (1.8M+ rows).
    """
    try:
        from MySql_Data_pull.models import ItemMaster, Registration
        from django.db import connections
        
        patient_id = request.GET.get('patient_id')
        reg_no_param = request.GET.get('registration_no')
        download_format = request.GET.get('format', 'pdf').lower()
        
        # Determine registration number
        reg_no = None
        patient_name = "Unknown"
        
        if reg_no_param:
            reg_no = reg_no_param
        elif patient_id:
            try:
                from .models import PatientSnapshot
                patient = PatientSnapshot.objects.get(pk=patient_id)
                reg_no = patient.pat_reg_no
                patient_name = patient.pat_name
            except Exception:
                pass
        
        if not reg_no:
            return HttpResponse("Could not determine registration number", status=400)

        # Clean reg_no
        try:
            reg_no_int = int(''.join(filter(str.isdigit, str(reg_no))))
        except ValueError:
            return HttpResponse("Invalid registration number format", status=400)

        # Get patient name if only reg_no provided
        if patient_name == "Unknown":
             try:
                # Still checking therapy_db for registration name as it's the master
                reg_pat = Registration.objects.using('therapy_db').filter(pat_reg_no=reg_no_int).first()
                if reg_pat:
                    patient_name = reg_pat.pat_name
             except:
                 pass
            
        # Fetch prescriptions using raw cursor from IPTHERAPY_DB
        history_rows = []
        with connections['iptherapy_db'].cursor() as cursor:
            # Query the correct table: [dbo].[Prescription]
            query = """
                SELECT *
                FROM [dbo].[Prescription] 
                WHERE Pat_Reg_No = %s 
                ORDER BY Rdate DESC
            """
            fallback_query = """
                SELECT *
                FROM [dbo].[Prescribtion] 
                WHERE Pat_Reg_No = %s 
                ORDER BY Rdate DESC
            """
            try:
                cursor.execute(query, [reg_no_int])
            except:
                cursor.execute(fallback_query, [reg_no_int])
            
            if cursor.description:
                columns = [col[0] for col in cursor.description]
                col_map = {col.lower(): index for index, col in enumerate(columns)}
                raw_rows = cursor.fetchall()
            else:
                raw_rows = []
                col_map = {}
                
            # Process rows to normalize
            for row in raw_rows:
                def get_col(name):
                    idx = col_map.get(name.lower())
                    if idx is not None:
                        return row[idx]
                    return None
                    
                # Map dynamic columns to standard keys
                date_val = get_col('rdate')
                item_code = get_col('pres_item_code')
                
                # Format date
                date_str = ""
                if hasattr(date_val, 'strftime'):
                    date_str = date_val.strftime('%Y-%m-%d')
                elif date_val:
                    date_str = str(date_val).split(' ')[0]
                    
                val = get_col('pres_doc_code') or get_col('pres_doct_code')
                doc_code = str(val).strip() if (val is not None and str(val).strip() != '0') else ''
                
                history_rows.append({
                    'Pres_Date': date_str,
                    'Pres_Item_Code': item_code,
                    'Pres_Item_Dosage': get_col('pres_item_dosage'),
                    'Pres_Item_Uom': get_col('pres_item_uom'),
                    'Pres_Item_Usage': get_col('pres_item_usage'),
                    'Pres_Item_Seq': get_col('pres_item_seq'),
                    'Pres_Item_Seq1': get_col('pres_item_seq1'),
                    'Ingred': get_col('ingred'),
                    'Pres_Days': get_col('pres_days') or get_col('pres_item_days') or get_col('pres_time_period'),
                    'Pres_Docs_Code': doc_code,
                    'Pres_Int_Ext': get_col('pres_int_ext'),
                    'Pres_From': get_col('pres_from'),
                    'Pres_To': get_col('pres_to'),
                    'Exp_DOD': get_col('exp_dod'),
                    'DOA': get_col('doa')
                })
        
        # Requirement: Show only the latest PAST admission
        latest_past_doa_val = None
        if history_rows:
            unique_doas = sorted(list(set(r.get('DOA') for r in history_rows if r.get('DOA'))), reverse=True)
            if len(unique_doas) > 1:
                latest_past_doa_val = unique_doas[1]
                history_rows = [r for r in history_rows if r.get('DOA') == latest_past_doa_val]
            else:
                history_rows = []
        
        # Format DOA for display
        doa_display = ""
        if latest_past_doa_val:
            if hasattr(latest_past_doa_val, 'strftime'):
                doa_display = latest_past_doa_val.strftime('%d/%m/%Y')
            else:
                doa_display = str(latest_past_doa_val).split(' ')[0]
        
        item_codes = set()
        for row in history_rows:
            if row.get('Pres_Item_Code'):
                item_codes.add(str(row['Pres_Item_Code']))
                
        item_map = {}
        if item_codes:
            with connections['iptherapy_db'].cursor() as cursor:
                 try:
                    codes_list = list(item_codes)
                    placeholders = ', '.join(['%s'] * len(codes_list))
                    query = f"SELECT item_code, item_name FROM [dbo].[item_Master] WHERE item_code IN ({placeholders})"
                    cursor.execute(query, codes_list)
                    for row in cursor.fetchall():
                        item_map[str(row[0]).strip()] = row[1]
                 except:
                     pass
                
        # Get doctor names
        doctor_codes = set()
        for row in history_rows:
            if row.get('Pres_Docs_Code'):
                doctor_codes.add(str(row['Pres_Docs_Code']))
        
        # PATIENT LEVEL DOCTOR FALLBACK
        patient_doctor_name = None
        try:
             with connections['therapy_db'].cursor() as cursor:
                 reg_digits = ''.join(c for c in str(reg_no) if c.isdigit())
                 cursor.execute("SELECT doctcode FROM [dbo].[Registration] WHERE pat_reg_no = %s", [reg_digits])
                 reg_row = cursor.fetchone()
                 if reg_row and reg_row[0]:
                     d_code_f = str(reg_row[0]).strip()
                     found_f = False
                     for db_name in ['therapy_db', 'iptherapy_db']:
                         if found_f: break
                         with connections[db_name].cursor() as cursor2:
                             for table_name in ['[dbo].[Doctor_Master_New]', '[dbo].[doctor_master]']:
                                 try:
                                     cursor2.execute(f"SELECT Doct_Name FROM {table_name} WHERE Doct_Code = %s", [d_code_f])
                                     res = cursor2.fetchone()
                                     if res:
                                         patient_doctor_name = res[0]
                                         found_f = True; break
                                     if d_code_f.isdigit():
                                         cursor2.execute(f"SELECT Doct_Name FROM {table_name} WHERE Doct_Code = %s", [d_code_f.zfill(4)])
                                         res = cursor2.fetchone()
                                         if res:
                                             patient_doctor_name = res[0]
                                             found_f = True; break
                                 except: continue
        except: pass

        # Get doctor names with fallback
        doctor_map = {}
        if doctor_codes:
            for db_name in ['therapy_db', 'iptherapy_db']:
                with connections[db_name].cursor() as cursor:
                    try:
                        doc_list = list(doctor_codes)
                        placeholders = ', '.join(['%s'] * len(doc_list))
                        for table_name in ['[dbo].[Doctor_Master_New]', '[dbo].[doctor_master]']:
                            try:
                                query = f"SELECT Doct_Code, Doct_Name FROM {table_name} WHERE Doct_Code IN ({placeholders})"
                                cursor.execute(query, doc_list)
                                for r in cursor.fetchall():
                                    doctor_map[str(r[0]).strip()] = r[1]
                                    if str(r[0]).strip().startswith('0'):
                                        doctor_map[str(r[0]).strip().lstrip('0')] = r[1]
                                
                                remaining = [c for c in doc_list if str(c).strip() not in doctor_map]
                                for c in remaining:
                                    if c.isdigit():
                                        cursor.execute(f"SELECT Doct_Name FROM {table_name} WHERE Doct_Code = %s", [c.zfill(4)])
                                        res = cursor.fetchone()
                                        if res:
                                            doctor_map[str(c).strip()] = res[0]
                            except: continue
                    except: pass
        grouped_history = {}
        for row in history_rows:
            date_str = row['Pres_Date']
            if not date_str:
                continue

            if date_str not in grouped_history:
                grouped_history[date_str] = {
                    'date': date_str,
                    'prescriptions': {} # seq -> { seq, items }
                }
            
            seq_val = row.get('Pres_Item_Seq')
            seq = int(seq_val) if (seq_val is not None and str(seq_val).isdigit()) else 0
            if seq not in grouped_history[date_str]['prescriptions']:
                d_code = str(row.get('Pres_Doct_Code', '')).strip()
                # If Pres_Docs_Code is empty, try fallback to the record level code (mapped earlier)
                if not d_code or d_code == '':
                    d_code = str(row.get('Pres_Doct_Code', '')).strip()
                
                d_name = doctor_map.get(d_code) or (f"Dr. {d_code}" if d_code else None)
                if not d_name or d_name == "N/A":
                    d_name = patient_doctor_name or "N/A"
                
                grouped_history[date_str]['prescriptions'][seq] = {
                    'seq': seq,
                    'doctor_code': d_code,
                    'doctor_name': d_name,
                    'items': []
                }
            
            item_code_str = str(row.get('Pres_Item_Code', '')).strip()
            item_name = item_map.get(item_code_str, f"Item {item_code_str}")
            
            grouped_history[date_str]['prescriptions'][seq]['items'].append({
                'item_name': item_name,
                'dosage': row.get('Pres_Item_Dosage') or '',
                'uom': row.get('Pres_Item_Uom') or '',
                'usage': row.get('Pres_Item_Usage') or '',
                'seq1': int(row.get('Pres_Item_Seq1', 0) or 0),
                'ingred': row.get('Ingred') or '',
                'duration': row.get('Pres_Days') or '', 
                'int_ext': row.get('Pres_Int_Ext') or '',
                'start_date': row.get('Pres_From'),
                'end_date': row.get('Pres_To')
            })
            
        # Convert to list and sort ASCENDING
        history_list = []
        for date_str in sorted(grouped_history.keys()):
            date_data = grouped_history[date_str]
            pres_list = list(date_data['prescriptions'].values())
            pres_list.sort(key=lambda x: x['seq'])
            history_list.append({
                'date': date_str,
                'prescriptions': pres_list
            })
        
        if download_format == 'excel':
            import openpyxl
            wb = openpyxl.Workbook()
            ws = wb.active
            ws.title = "Prescription History"
            
            ws.append(["Patient Name:", patient_name])
            ws.append(["Previous Admission (DOA):", str(doa_display)])
            ws.append(["Doctor In-Charge:", str(patient_doctor_name or "N/A")])
            ws.append([])
            
            headers = ["Date", "Medicine", "Usage", "Ext/Int"]
            ws.append(headers)
            
            for entry in history_list:
                date_val = entry['date']
                for pres in entry['prescriptions']:
                    items = pres['items']
                    if not items: continue
                    
                    # Group items by seq1
                    seq1_map = {}
                    for it in items:
                        s1 = it.get('seq1', 0)
                        if s1 not in seq1_map: seq1_map[s1] = []
                        seq1_map[s1].append(it)
                    
                    sorted_s1_list = sorted(seq1_map.keys())
                    
                    group_texts = []
                    for s1 in sorted_s1_list:
                        g_items = seq1_map[s1]
                        names = " + ".join([it['item_name'] for it in g_items])
                        first_it = g_items[0]
                        dosage = str(first_it.get('dosage') or '').strip()
                        uom = str(first_it.get('uom') or '').strip()
                        
                        g_str = f"[{names}]"
                        if dosage: g_str += f" {dosage}"
                        if uom: g_str += f" {uom}"
                        group_texts.append(g_str)
                    
                    combined_med = " + ".join(group_texts)
                    first_it = items[0]
                    ws.append([
                        date_val,
                        combined_med,
                        first_it.get('usage') or "-",
                        first_it.get('int_ext') or "-"
                    ])
                    
            for col in ws.columns:
                max_length = 0
                column = col[0].column_letter
                for cell in col:
                    try:
                         if len(str(cell.value)) > max_length: max_length = len(str(cell.value))
                    except: pass
                ws.column_dimensions[column].width = (max_length + 2)
                
            response = HttpResponse(content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
            response['Content-Disposition'] = f'attachment; filename="prescription_history_{reg_no}.xlsx"'
            wb.save(response)
            return response
            
        else:
            from reportlab.lib import colors
            from reportlab.lib.pagesizes import letter
            from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
            from reportlab.lib.styles import getSampleStyleSheet
            from reportlab.lib.units import inch
            import io
            
            buffer = io.BytesIO()
            doc = SimpleDocTemplate(buffer, pagesize=letter)
            elements = []
            styles = getSampleStyleSheet()
            
            title_style = styles['Heading1']
            title_style.alignment = 1 
            elements.append(Paragraph("Prescription History", title_style))
            elements.append(Spacer(1, 12))
            
            elements.append(Paragraph(f"<b>Patient Name:</b> {patient_name}", styles['Normal']))
            elements.append(Paragraph(f"<b>Registration No:</b> {reg_no}", styles['Normal']))
            if doa_display:
                elements.append(Paragraph(f"<b>Previous DOA:</b> {doa_display}", styles['Normal']))
            if patient_doctor_name:
                elements.append(Paragraph(f"<b>Doctor In-Charge:</b> {patient_doctor_name}", styles['Normal']))
            elements.append(Spacer(1, 15))
            
            if not history_list:
                 elements.append(Paragraph("No history found.", styles['Normal']))
            else:

                for entry in history_list:
                    # Move date label ABOVE each section
                    elements.append(Paragraph(f"<b>Date: {entry['date']}</b>", styles['Normal']))
                    elements.append(Spacer(1, 10))
                    
                    table_data = [["Medicine", "Usage", "Ext/Int"]]
                    
                    for pres in entry['prescriptions']:
                        items = pres['items']
                        if not items: continue

                        # Group by seq1
                        seq1_map = {}
                        for it in items:
                            s1 = it.get('seq1', 0)
                            if s1 not in seq1_map: seq1_map[s1] = []
                            seq1_map[s1].append(it)
                        
                        sorted_s1_list = sorted(seq1_map.keys())
                        
                        med_group_paras = []
                        for s1 in sorted_s1_list:
                            g_items = seq1_map[s1]
                            names = " + ".join([it['item_name'] for it in g_items])
                            
                            first_it = g_items[0]
                            dosage = str(first_it.get('dosage') or '').strip()
                            uom = str(first_it.get('uom') or '').strip()
                            
                            m_text = f"<b>[{names}]</b>"
                            if dosage: m_text += f" {dosage}"
                            if uom: m_text += f" {uom}"
                            
                            # Add ingredients if exists
                            all_ingreds = [it.get('ingred') for it in g_items if it.get('ingred') and it.get('ingred').strip() not in ['', '-']]
                            if all_ingreds:
                                m_text += f" <font size=8 color=grey>({', '.join(list(dict.fromkeys(all_ingreds)))})</font>"
                            
                            med_group_paras.append(m_text)
                        
                        # Use styles['Normal'] and adjust font size for table cells
                        cell_style = styles['Normal']
                        cell_style.fontSize = 8
                        cell_style.leading = 10
                        
                        med_names_para = Paragraph(" + ".join(med_group_paras), cell_style)
                        
                        # Usage & Ext/Int from first in group
                        first_it = items[0]
                        usage_text = first_it.get('usage') or "-"
                        ext_int_text = first_it.get('int_ext') or "-"
                        
                        # Wrap usage in Paragraph to prevent overlapping
                        usage_para = Paragraph(usage_text, cell_style)
                        ext_int_para = Paragraph(ext_int_text, cell_style)

                        table_data.append([
                            med_names_para,
                            usage_para,
                            ext_int_para
                        ])
                    
                    if len(table_data) > 1:
                        # Slightly adjusted widths for better distribution
                        # Total width: 4.5 + 1.2 + 0.8 = 6.5 inch (fits well on letter with 1 inch margins)
                        t = Table(table_data, colWidths=[4.5*inch, 1.2*inch, 0.8*inch])
                        t.setStyle(TableStyle([
                            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#f0f9f1')),
                            ('TEXTCOLOR', (0, 0), (-1, 0), colors.black),
                            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
                            ('ALIGN', (1, 0), (-1, -1), 'LEFT'),  # Centered usage often causes issues with wrapping
                            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                            ('BOTTOMPADDING', (0, 0), (-1, 0), 8),
                            ('TOPPADDING', (1, 0), (-1, -1), 10),
                            ('BOTTOMPADDING', (1, 0), (-1, -1), 10),
                            ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
                            ('FONTSIZE', (0, 0), (-1, -1), 8),
                            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                            ('LEFTPADDING', (0, 0), (-1, -1), 8),
                            ('RIGHTPADDING', (0, 0), (-1, -1), 8),
                        ]))
                        elements.append(t)
                        elements.append(Spacer(1, 20))
            
            doc.build(elements)
            pdf = buffer.getvalue()
            buffer.close()
            
            response = HttpResponse(content_type='application/pdf')
            response['Content-Disposition'] = f'attachment; filename="prescription_history_{reg_no}.pdf"'
            response.write(pdf)
            return response
            
    except Exception as e:
        import traceback
        traceback.print_exc()
        return HttpResponse(f"Error generating download: {str(e)}", status=500)
