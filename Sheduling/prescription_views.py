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
    Display the prescription scheduling dashboard.
    """
    return render(request, 'prescription_scheduling.html')

@csrf_exempt
@require_http_methods(["GET"])
def get_prescription_data_api(request):
    """
    API endpoint to fetch prescription data for the scheduling dashboard.
    """
    try:
        status = request.GET.get('status', 'draft')
        date = request.GET.get('date')
        
        if not date:
            return JsonResponse({'error': 'Date is required'}, status=400)
        
        filter_date = parse_date(date)
        if not filter_date:
            return JsonResponse({'error': 'Invalid date format'}, status=400)
        
        # Get prescription scheduling data
        prescriptions = PrescriptionScheduling.objects.filter(
            prescription_date=filter_date,
            status=status
        ).select_related('patient', 'doctor').prefetch_related('items')
        
        data = []
        for prescription in prescriptions:
            try:
                # Get prescription count
                prescription_count = prescription.items.count()
                
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
                    'status': prescription.status,
                    'sent_to': prescription.sent_to,
                    'dispatched_from': prescription.dispatched_from,
                    'dispatched_at': prescription.dispatched_at.isoformat() if prescription.dispatched_at else None,
                    'created_at': prescription.created_at.isoformat(),
                    'updated_at': prescription.updated_at.isoformat()
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
    """
    try:
        patient_id = request.GET.get('patient_id')
        date = request.GET.get('date')
        
        if not patient_id or not date:
            return JsonResponse({'error': 'patient_id and date are required'}, status=400)
        
        filter_date = parse_date(date)
        if not filter_date:
            return JsonResponse({'error': 'Invalid date format'}, status=400)
        
        # Get prescription scheduling
        prescription = PrescriptionScheduling.objects.filter(
            patient_id=patient_id,
            prescription_date=filter_date
        ).select_related('patient', 'doctor').prefetch_related('items').first()
        
        if not prescription:
            return JsonResponse({'error': 'Prescription not found'}, status=404)
        
        # Get patient info
        patient_info = {
            'name': prescription.patient.pat_name,
            'registration_no': prescription.patient.pat_reg_no,
            'room_no': getattr(prescription.patient, 'room_no', None),
            'doctor_name': prescription.doctor.get_full_name() or prescription.doctor.username
        }
        
        # Get prescription items
        prescription_items = []
        for item in prescription.items.all():
            prescription_items.append({
                'name': item.item_name,
                'dose': item.dose,
                'quantity': item.quantity,
                'time': item.time,
                'notes': item.notes or ''
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
    """
    try:
        data = json.loads(request.body)
        date = data.get('date')
        
        if not date:
            return JsonResponse({'error': 'Date is required'}, status=400)
        
        filter_date = parse_date(date)
        if not filter_date:
            return JsonResponse({'error': 'Invalid date format'}, status=400)
        
        # Get all draft prescriptions for the date
        draft_prescriptions = PrescriptionScheduling.objects.filter(
            prescription_date=filter_date,
            status='draft'
        )
        
        if not draft_prescriptions.exists():
            return JsonResponse({'error': 'No draft prescriptions found for the selected date'}, status=400)
        
        with transaction.atomic():
            updated_count = 0
            sent_to_departments = []
            
            for prescription in draft_prescriptions:
                # Determine which department to send to based on patient type or prescription content
                department = determine_procurement_department(prescription)
                
                # Update status to scheduled
                prescription.status = 'scheduled'
                prescription.sent_to = department
                prescription.save()
                
                # Create dispatch record
                PrescriptionDispatch.objects.create(
                    prescription_scheduling=prescription,
                    department=department,
                    dispatched_by=request.user,
                    notes=f'Automatically dispatched to {department}'
                )
                
                # Log the change
                PrescriptionChangeLog.objects.create(
                    patient=prescription.patient,
                    prescription_date=prescription.prescription_date,
                    action='status_change',
                    changed_by=request.user,
                    before_values={'status': 'draft'},
                    after_values={'status': 'scheduled', 'sent_to': department},
                    description=f'Prescription sent to {department}'
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
    """
    try:
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
        
        # Get prescription
        prescription = PrescriptionScheduling.objects.filter(
            patient_id=patient_id,
            prescription_date=filter_date
        ).first()
        
        if not prescription:
            return JsonResponse({'error': 'Prescription not found'}, status=404)
        
        old_status = prescription.status
        
        with transaction.atomic():
            # Update status
            prescription.status = new_status
            if new_status == 'dispatched':
                prescription.dispatched_from = department
                prescription.dispatched_at = timezone.now()
            prescription.save()
            
            # Log the change
            PrescriptionChangeLog.objects.create(
                patient=prescription.patient,
                prescription_date=prescription.prescription_date,
                action='status_change',
                changed_by=request.user,
                before_values={'status': old_status},
                after_values={'status': new_status, 'dispatched_from': department},
                description=f'Status changed from {old_status} to {new_status} by {department}'
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
