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
def get_prescription_details_api(request):
    """
    API endpoint to get detailed prescription information for a patient.
    Works with PrescriptionAllocation.
    """
    try:
        from .models import PrescriptionAllocation
        
        patient_id = request.GET.get('patient_id')
        date = request.GET.get('date')
        
        if not patient_id or not date:
            return JsonResponse({'error': 'patient_id and date are required'}, status=400)
        
        filter_date = parse_date(date)
        if not filter_date:
            return JsonResponse({'error': 'Invalid date format'}, status=400)
        
        # Get PrescriptionScheduling for the specific date
        prescription_scheduling = PrescriptionScheduling.objects.filter(
            patient_id=patient_id,
            prescription_date=filter_date
        ).select_related('patient', 'doctor').first()
        
        if not prescription_scheduling:
            return JsonResponse({'error': 'Prescription not found'}, status=404)
        
        # Get patient info - fallback to PatientSnapshot.pat_room_no
        room_no = getattr(prescription_scheduling.patient, 'pat_room_no', None)
        doctor_name = prescription_scheduling.doctor.get_full_name() if prescription_scheduling.doctor and hasattr(prescription_scheduling.doctor, 'get_full_name') else (prescription_scheduling.doctor.username if prescription_scheduling.doctor else 'Unknown')
        
        patient_info = {
            'name': prescription_scheduling.patient.pat_name,
            'registration_no': prescription_scheduling.patient.pat_reg_no,
            'room_no': room_no,
            'doctor_name': doctor_name
        }
        
        # Get prescription items from associated PrescriptionAllocation
        allocation = PrescriptionAllocation.objects.filter(
            patient_id=patient_id,
            from_date__lte=filter_date,
            to_date__gte=filter_date
        ).first()
        
        prescription_items = []
        if allocation:
            items_groups = allocation.items_groups if isinstance(allocation.items_groups, list) else []
            for group in items_groups:
                for item in group.get('items', []):
                    prescription_items.append({
                        'name': item.get('item_name', ''),
                        'dose': group.get('dosage', ''),
                        'quantity': '',  # Not stored in items_groups format
                        'time': group.get('time', ''),
                        'notes': group.get('uno', '')
                    })
        
        return JsonResponse({
            'success': True,
            'patient_info': patient_info,
            'prescription_items': prescription_items
        })
        
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)

@csrf_exempt
@require_http_methods(["POST"])
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
