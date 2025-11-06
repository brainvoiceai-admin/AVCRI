from django.shortcuts import render
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from django.contrib.auth.decorators import login_required
from django.utils import timezone
from django.db import transaction
from django.utils.dateparse import parse_date
from .models import PrescriptionScheduling, PrescriptionChangeLog, PrescriptionItem, PrescriptionDispatch
from .decorators import scheduling_access_required, api_access_required
import json
from datetime import datetime

@login_required
@scheduling_access_required
def procurement_dashboard(request):
    """
    Display the procurement dashboard for prescription preparation and dispatch.
    """
    return render(request, 'procurement_dashboard.html')

@csrf_exempt
@require_http_methods(["GET"])
def get_procurement_prescriptions_api(request):
    """
    API endpoint to fetch prescriptions for procurement departments.
    """
    try:
        date = request.GET.get('date')
        department = request.GET.get('department', 'IP Pharmacy')
        
        if not date:
            return JsonResponse({'error': 'Date is required'}, status=400)
        
        filter_date = parse_date(date)
        if not filter_date:
            return JsonResponse({'error': 'Invalid date format'}, status=400)
        
        # Get prescriptions that were sent to this department
        prescriptions = PrescriptionScheduling.objects.filter(
            prescription_date=filter_date,
            sent_to=department,
            status__in=['scheduled', 'dispatched']
        ).select_related('patient', 'doctor').prefetch_related('items')
        
        data = []
        for prescription in prescriptions:
            # Get prescription count and a small preview of items
            prescription_count = prescription.items.count()
            items_preview = []
            if prescription_count == 0:
                try:
                    from .models import PrescriptionAllocation
                    allocation = PrescriptionAllocation.objects.filter(
                        patient=prescription.patient,
                        from_date__lte=filter_date,
                        to_date__gte=filter_date
                    ).first()
                    if allocation and allocation.items_groups:
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
                        for grp in groups:
                            items = grp.get('items', []) if isinstance(grp, dict) else []
                            for it in items:
                                items_preview.append({
                                    'item_name': it.get('item_name', ''),
                                    'dose': grp.get('dosage', ''),
                                    'quantity': it.get('quantity', ''),
                                    'time': grp.get('time', ''),
                                    'notes': grp.get('uno', '')
                                })
                        prescription_count = len(items_preview)
                except Exception:
                    pass
            else:
                # Build preview from PrescriptionItem rows
                for it in prescription.items.all()[:10]:
                    items_preview.append({
                        'item_name': it.item_name,
                        'dose': it.dose,
                        'quantity': it.quantity,
                        'time': it.time,
                        'notes': it.notes or ''
                    })
            
            # Get patient details
            patient = prescription.patient
            doctor = prescription.doctor
            
            # Handle potential None values
            patient_name = patient.pat_name or 'Unknown'
            doctor_name = doctor.get_full_name() if hasattr(doctor, 'get_full_name') else (doctor.username if doctor else 'Unknown')
            
            data.append({
                'patient_id': patient.id,
                'patient_name': patient_name,
                'patient_id_display': patient.pat_reg_no,
                'registration_no': patient.pat_reg_no,
                'room_no': getattr(patient, 'pat_room_no', None),
                'doctor_name': doctor_name,
                'prescription_count': prescription_count,
                'items_preview': items_preview[:5],
                'status': prescription.status,
                'sent_to': prescription.sent_to,
                'dispatched_from': prescription.dispatched_from,
                'dispatched_at': prescription.dispatched_at.isoformat() if prescription.dispatched_at else None,
                'created_at': prescription.created_at.isoformat(),
                'updated_at': prescription.updated_at.isoformat()
            })
        
        return JsonResponse({
            'success': True,
            'data': data,
            'count': len(data)
        })
        
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)

@csrf_exempt
@require_http_methods(["POST"])
def mark_as_dispatched_api(request):
    """
    API endpoint to mark a prescription as dispatched.
    """
    try:
        data = json.loads(request.body)
        patient_id = data.get('patient_id')
        date = data.get('date')
        
        
        if not patient_id or not date:
            return JsonResponse({'error': 'Patient ID and date are required'}, status=400)
        
        filter_date = parse_date(date)
        if not filter_date:
            return JsonResponse({'error': 'Invalid date format'}, status=400)
        
        # Find the prescription (check both scheduled and dispatched)
        try:
            prescription = PrescriptionScheduling.objects.get(
                patient_id=patient_id,
                prescription_date=filter_date
            )
            
            # If already dispatched, return success (no need to process again)
            if prescription.status == 'dispatched':
                return JsonResponse({
                    'success': True,
                    'message': 'Prescription already dispatched',
                    'already_dispatched': True
                })
                
        except PrescriptionScheduling.DoesNotExist:
            return JsonResponse({'error': 'Prescription not found'}, status=404)
        
        # Update status to dispatched
        with transaction.atomic():
            prescription.status = 'dispatched'
            prescription.dispatched_at = timezone.now()
            prescription.dispatched_from = prescription.sent_to
            prescription.save()
            
            # Get user for dispatch record (fallback to first superuser if no authenticated user)
            dispatch_user = request.user if request.user.is_authenticated else None
            if not dispatch_user:
                from authentication.models import CustomUser
                dispatch_user = CustomUser.objects.filter(is_superuser=True).first()
            
            # Create dispatch record
            PrescriptionDispatch.objects.create(
                prescription_scheduling=prescription,
                department=prescription.sent_to,
                dispatched_by=dispatch_user,
                notes=f'Dispatched from {prescription.sent_to}'
            )
            
            # Create change log entry
            PrescriptionChangeLog.objects.create(
                patient=prescription.patient,
                prescription_date=filter_date,
                action='status_change',
                changed_by=dispatch_user,
                before_values={'status': 'scheduled'},
                after_values={'status': 'dispatched'},
                description=f'Prescription marked as dispatched from {prescription.sent_to}'
            )
        
        return JsonResponse({
            'success': True,
            'message': 'Prescription marked as dispatched successfully'
        })
        
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)

@csrf_exempt
@require_http_methods(["GET"])
def get_prescription_details_api(request):
    """
    API endpoint to get detailed prescription AND therapy items for a patient (procurement dashboard).
    This includes both prescription items and therapy-related items (BookingItem).
    """
    try:
        from .models import PrescriptionAllocation, Booking, BookingItem, PatientSnapshot
        
        patient_id = request.GET.get('patient_id')
        date = request.GET.get('date')
        
        if not patient_id or not date:
            return JsonResponse({'error': 'patient_id and date are required'}, status=400)
        
        # Parse date
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
        
        # Get prescription for doctor name
        prescription = PrescriptionScheduling.objects.filter(
            patient_id=patient_id,
            prescription_date=filter_date
        ).select_related('doctor').first()
        
        if prescription and prescription.doctor:
            patient_info['doctor_name'] = prescription.doctor.get_full_name() if hasattr(prescription.doctor, 'get_full_name') else (prescription.doctor.username if prescription.doctor else None)
        
        # Process all allocations and use items_groups exactly as stored
        for allocation in allocations:
            # Check if allocation is cancelled
            if allocation.status == 'cancelled':
                prescription_is_cancelled = True
            if not prescription_status or prescription_status == 'draft':
                prescription_status = allocation.status
            
            # Use the original items_groups structure from allocation - exactly as stored
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
                
                # Use groups exactly as they are in items_groups - no matching with PrescriptionItem
                for group_idx, group in enumerate(groups):
                    items = group.get('items', []) if isinstance(group, dict) else []
                    group_items = []
                    
                    # Convert items from items_groups to the format expected by frontend
                    for it in items:
                        # Only add non-empty items
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
                        'notes': group.get('uno', ''),
                        'items': group_items,
                        'is_group': True
                    })
        
        # If no allocations found, check for PrescriptionItem records as fallback
        if not prescription_groups and prescription:
            items_qs = PrescriptionItem.objects.filter(prescription_scheduling=prescription).all()
            prescription_is_cancelled = prescription.status == 'cancelled'
            prescription_status = prescription.status
            
            if items_qs.exists():
                for item in items_qs:
                    # Create one group per prescription item
                    prescription_groups.append({
                        'group_id': f"prescription_item_{item.id}",
                        'time': item.time or '',
                        'dose': item.dose or '',
                        'notes': item.notes or '',
                        'items': [{
                            'id': f'prescription_{item.id}',
                            'type': 'prescription',
                            'item_name': item.item_name,
                            'dose': item.dose or '',
                            'quantity': item.quantity or '',
                            'time': item.time or '',
                            'notes': item.notes or '',
                            'status': getattr(item, 'status', 'active') if hasattr(item, 'status') else 'active'
                        }],
                        'is_group': True
                    })
        
        # Flatten for backward compatibility (but prefer groups)
        prescription_items = []
        for group in prescription_groups:
            # Add prescription status to first item of first group
            if prescription_items == [] and group['items']:
                group['items'][0]['prescription_status'] = prescription_status
                group['items'][0]['prescription_is_cancelled'] = prescription_is_cancelled
            prescription_items.extend(group['items'])
        
        # ===== THERAPY ITEMS (BookingItem) =====
        # Get all bookings for this patient on this date
        # Include ALL bookings (including cancelled) to show all items
        bookings = Booking.objects.filter(
            allocation__patient=patient,
            date=filter_date
        ).select_related('allocation').prefetch_related('items').order_by('allocation__therapy_name', 'timeslot')
        
        # Group therapy items by allocation and items_groups structure
        therapy_groups = {}  # Key: (allocation_id, group_index), Value: {therapy_name, dosage, items: []}
        
        for booking in bookings:
            if not booking.allocation:
                continue
                
            allocation = booking.allocation
            therapy_name = allocation.therapy_name
            
            # Get items_groups from allocation to understand the grouping structure
            items_groups = allocation.items_groups if isinstance(allocation.items_groups, list) else []
            
            # Get all BookingItems for this booking (including cancelled ones)
            booking_items = booking.items.all()
            
            # If we have items_groups, try to match BookingItems to groups
            if items_groups and booking_items.exists():
                # Create a map of item_code/item_name to BookingItem for quick lookup
                item_map = {item.item_code: item for item in booking_items}
                item_map.update({item.item_name: item for item in booking_items if item.item_name not in item_map})
                
                # Group items according to items_groups structure
                for group_idx, group in enumerate(items_groups):
                    group_key = (allocation.id, group_idx)
                    dosage = group.get('dosage', '')
                    uno = group.get('uno', '')
                    
                    if group_key not in therapy_groups:
                        therapy_groups[group_key] = {
                            'therapy_name': therapy_name,
                            'therapy_id': allocation.id,
                            'dosage': dosage,
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
                        
                        # Find matching BookingItem
                        booking_item = None
                        if item_code and item_code in item_map:
                            booking_item = item_map[item_code]
                        elif item_name and item_name in item_map:
                            booking_item = item_map[item_name]
                        else:
                            # Try to find by name match
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
                                # Note: is_cancelled removed - cancellation is at booking level, not item level
                            })
                        else:
                            # Item in group but not found in BookingItems (might be removed)
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
                                'is_cancelled': False,
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
                        # Note: is_cancelled removed - cancellation is at booking level, not item level
                    })
        
        # Convert grouped structure to flat list for response (but keep grouping info)
        therapy_items = []
        for group_key, group_data in therapy_groups.items():
            # Check if the entire booking/therapy is cancelled
            booking_is_cancelled = group_data['booking_status'] == 'cancelled'
            
            # Remove individual item cancellation status - cancellation is at booking level
            items_without_cancellation = []
            for item in group_data['items']:
                item_copy = item.copy()
                item_copy.pop('is_cancelled', None)  # Remove item-level cancellation
                items_without_cancellation.append(item_copy)
            
            therapy_items.append({
                'group_id': f"therapy_group_{group_key[0]}_{group_key[1]}",
                'therapy_name': group_data['therapy_name'],
                'therapy_id': group_data['therapy_id'],
                'dosage': group_data['dosage'],
                'uno': group_data['uno'],
                'booking_id': group_data['booking_id'],
                'booking_status': group_data['booking_status'],
                'booking_is_cancelled': booking_is_cancelled,
                'items': items_without_cancellation,
                'is_group': True
            })
        
        # Combine all items (prescription first, then therapy)
        all_items = prescription_items + therapy_items
        
        return JsonResponse({
            'success': True,
            'patient_info': patient_info,
            'items': prescription_items,  # Prescription items for backward compatibility
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
@require_http_methods(["GET"])
def get_prescription_change_log_api(request):
    """
    API endpoint to get change log for a patient's prescription.
    Shows what changed from what (before_values vs after_values).
    """
    try:
        patient_id = request.GET.get('patient_id')
        date = request.GET.get('date')
        
        if not patient_id or not date:
            return JsonResponse({'error': 'patient_id and date are required'}, status=400)
        
        filter_date = parse_date(date)
        if not filter_date:
            return JsonResponse({'error': 'Invalid date format'}, status=400)
        
        # Get all change logs for this patient and date
        change_logs = PrescriptionChangeLog.objects.filter(
            patient_id=patient_id,
            prescription_date=filter_date
        ).select_related('changed_by').order_by('-timestamp')
        
        logs_data = []
        for log in change_logs:
            # Format before_values and after_values for display
            before_values = log.before_values or {}
            after_values = log.after_values or {}

            # Build change description
            changes = []
            all_keys = set(list(before_values.keys()) + list(after_values.keys()))

            def _safe_list(val):
                if isinstance(val, list):
                    return val
                return []

            def _group_diff(before_groups, after_groups):
                diffs = []
                bg = _safe_list(before_groups)
                ag = _safe_list(after_groups)
                max_len = max(len(bg), len(ag))
                for idx in range(max_len):
                    b = bg[idx] if idx < len(bg) else {}
                    a = ag[idx] if idx < len(ag) else {}
                    # Only compare dict-like groups
                    b = b if isinstance(b, dict) else {}
                    a = a if isinstance(a, dict) else {}
                    group_changes = []
                    for f in ['dosage', 'usage', 'time', 'uno']:
                        if (b.get(f) or '') != (a.get(f) or ''):
                            group_changes.append({
                                'field': f,
                                'before': b.get(f) or '',
                                'after': a.get(f) or ''
                            })
                    # Compare item names
                    b_items = [it.get('item_name','') for it in (b.get('items') or []) if isinstance(it, dict)]
                    a_items = [it.get('item_name','') for it in (a.get('items') or []) if isinstance(it, dict)]
                    if b_items != a_items:
                        group_changes.append({
                            'field': 'items',
                            'before': b_items,
                            'after': a_items
                        })
                    if group_changes:
                        diffs.append({
                            'group_index': idx,
                            'changes': group_changes
                        })
                return diffs

            for key in all_keys:
                before_val = before_values.get(key, 'N/A')
                after_val = after_values.get(key, 'N/A')

                if before_val != after_val:
                    entry = {
                        'field': key.replace('_', ' ').title(),
                        'before': before_val,
                        'after': after_val
                    }
                    # Add granular diff for items_groups
                    if key == 'items_groups':
                        entry['items_groups_changes'] = _group_diff(before_val, after_val)
                    changes.append(entry)

            logs_data.append({
                'id': log.id,
                'action': log.action,
                'action_display': dict(log.ACTION_CHOICES).get(log.action, log.action),
                'changed_by': log.changed_by.get_full_name() if log.changed_by and hasattr(log.changed_by, 'get_full_name') else (log.changed_by.username if log.changed_by else 'Unknown'),
                'timestamp': log.timestamp.isoformat(),
                'description': log.description or '',
                'before_values': before_values,
                'after_values': after_values,
                'changes': changes  # Formatted list of what changed
            })
        
        return JsonResponse({
            'success': True,
            'data': logs_data,
            'count': len(logs_data)
        })
    
    except Exception as e:
        import traceback
        return JsonResponse({'error': str(e), 'traceback': traceback.format_exc()}, status=500)
