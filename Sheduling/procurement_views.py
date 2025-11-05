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
        prescription_items = []
        prescription = PrescriptionScheduling.objects.filter(
            patient_id=patient_id,
            prescription_date=filter_date
        ).select_related('doctor').first()
        
        if prescription:
            # Set doctor name from prescription
            if prescription.doctor:
                patient_info['doctor_name'] = prescription.doctor.get_full_name() if hasattr(prescription.doctor, 'get_full_name') else (prescription.doctor.username if prescription.doctor else None)
            
            # Primary: items entered as PrescriptionItem
            items_qs = PrescriptionItem.objects.filter(prescription_scheduling=prescription)
            for item in items_qs:
                prescription_items.append({
                    'id': f'prescription_{item.id}',
                    'type': 'prescription',
                    'item_name': item.item_name,
                    'dose': item.dose or '',
                    'quantity': item.quantity or '',
                    'time': item.time or '',
                    'notes': item.notes or ''
                })
            
            # Fallback: derive from PrescriptionAllocation.items_groups when no rows exist
            if not prescription_items:
                allocation = PrescriptionAllocation.objects.filter(
                    patient_id=patient_id,
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
                    
                    for group in groups:
                        items = group.get('items', []) if isinstance(group, dict) else []
                        for it in items:
                            prescription_items.append({
                                'id': f'prescription_alloc_{it.get("id", "")}',
                                'type': 'prescription',
                                'item_name': it.get('item_name', ''),
                                'dose': group.get('dosage', ''),
                                'quantity': it.get('quantity', ''),
                                'time': group.get('time', ''),
                                'notes': group.get('uno', '')
                            })
        
        # ===== THERAPY ITEMS (BookingItem) =====
        # Get all bookings for this patient on this date
        therapy_items = []
        # Booking status can be: draft, scheduled, partially_cancelled, cancelled, completed
        # Include all non-cancelled bookings (draft, scheduled, completed) to show items
        bookings = Booking.objects.filter(
            allocation__patient=patient,
            date=filter_date
        ).exclude(status='cancelled').select_related('allocation').prefetch_related('items')
        
        for booking in bookings:
            # BookingItem status can be: scheduled, cancelled, completed
            # Include all non-cancelled items
            for item in booking.items.exclude(status='cancelled'):
                therapy_items.append({
                    'id': f'therapy_{item.id}',
                    'type': 'therapy',
                    'therapy_name': booking.allocation.therapy_name if booking.allocation else '',
                    'item_name': item.item_name,
                    'item_code': item.item_code,
                    'dose': item.dosage or '',
                    'quantity': '',  # BookingItem doesn't have quantity field
                    'time': '',  # BookingItem doesn't have time field
                    'notes': item.uno or ''
                })
        
        # Combine all items (prescription first, then therapy)
        all_items = prescription_items + therapy_items
        
        return JsonResponse({
            'success': True,
            'patient_info': patient_info,
            'items': all_items,
            'prescription_items': prescription_items,
            'therapy_items': therapy_items,
            'counts': {
                'total': len(all_items),
                'prescription': len(prescription_items),
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
            
            for key in all_keys:
                before_val = before_values.get(key, 'N/A')
                after_val = after_values.get(key, 'N/A')
                
                if before_val != after_val:
                    changes.append({
                        'field': key.replace('_', ' ').title(),
                        'before': before_val,
                        'after': after_val
                    })
            
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
