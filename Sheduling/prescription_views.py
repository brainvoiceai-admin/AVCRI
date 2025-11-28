from django.shortcuts import render
from django.http import JsonResponse
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
    
    return render(request, 'prescription_scheduling.html', context)

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
                doctor_name = prescription_scheduling.doctor.get_full_name() if prescription_scheduling.doctor and hasattr(prescription_scheduling.doctor, 'get_full_name') else (prescription_scheduling.doctor.username if prescription_scheduling.doctor else 'Unknown')
                
                # Get room_no - fallback to PatientSnapshot.pat_room_no
                room_no = getattr(patient, 'pat_room_no', None)
                
                # Get prescription items count from associated PrescriptionAllocation
                allocation = PrescriptionAllocation.objects.filter(
                    patient=patient,
                    from_date__lte=filter_date,
                    to_date__gte=filter_date
                ).first()
                
                if allocation:
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

                    # Count total items across groups
                    prescription_count = 0
                    for grp in groups:
                        items = grp.get('items', []) if isinstance(grp, dict) else []
                        prescription_count += len(items)

                    prescription_name = allocation.prescription_name
                else:
                    prescription_count = 0
                    prescription_name = 'Prescription'
                
                data.append({
                    'patient_id': patient.id,
                    'scheduling_id': prescription_scheduling.id,
                    'patient_name': patient_name,
                    'patient_id_display': patient.pat_reg_no,
                    'registration_no': patient.pat_reg_no,
                    'room_no': room_no,
                    'doctor_name': doctor_name,
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
        
        # Get patient
        try:
            patient = PatientSnapshot.objects.get(pk=patient_id)
        except PatientSnapshot.DoesNotExist:
            return JsonResponse({'error': 'Patient not found'}, status=404)
        
        # Get patient info
        patient_info = {
            'name': patient.pat_name or 'Unknown',
            'registration_no': patient.pat_reg_no,
            'room_no': getattr(patient, 'pat_room_no', None),
            'doctor_name': None  # Will be set from prescription if available
        }
        
        # Get PrescriptionScheduling for the specific date
        prescription_scheduling = PrescriptionScheduling.objects.filter(
            patient_id=patient_id,
            prescription_date=filter_date
        ).select_related('doctor').first()
        
        if prescription_scheduling and prescription_scheduling.doctor:
            patient_info['doctor_name'] = prescription_scheduling.doctor.get_full_name() if hasattr(prescription_scheduling.doctor, 'get_full_name') else (prescription_scheduling.doctor.username if prescription_scheduling.doctor else None)
        
        # ===== PRESCRIPTION ITEMS =====
        prescription_groups = []  # List of groups with items
        
        # Get all PrescriptionAllocation records for this patient that cover the date
        allocations = PrescriptionAllocation.objects.filter(
            patient_id=patient_id,
            from_date__lte=filter_date,
            to_date__gte=filter_date
        ).order_by('from_date', 'id')
        
        prescription_is_cancelled = False
        prescription_status = 'draft'
        
        if allocations:
            all_cancelled = all(a.status == 'cancelled' for a in allocations)
            prescription_is_cancelled = all_cancelled
            non_cancel_statuses = [a.status for a in allocations if a.status != 'cancelled']
            prescription_status = non_cancel_statuses[0] if non_cancel_statuses else 'cancelled'
        
        # Process all allocations and use items_groups exactly as stored
        for allocation in allocations:
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
                    
                    # Add the group exactly as it appears in items_groups
                    prescription_groups.append({
                        'group_id': f"prescription_group_{allocation.id}_{group_idx}",
                        'time': group.get('time', 'M'),
                        'dose': group.get('dosage', ''),
                        'usage': group.get('usage', ''),
                        'usage_array': group.get('usage_array', []),
                        'internal_external': group.get('internal_external', ''),
                        'notes': group.get('uno', ''),
                        'items': group_items,
                        'is_cancelled': allocation.status == 'cancelled',
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
                        'usage': '',
                        'usage_array': [],
                        'internal_external': '',
                        'uno': '',
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
