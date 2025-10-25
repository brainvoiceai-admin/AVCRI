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
    API endpoint to get detailed prescription information for a patient.
    """
    try:
        patient_id = request.GET.get('patient_id')
        date = request.GET.get('date')
        
        if not patient_id or not date:
            return JsonResponse({'error': 'Patient ID and date are required'}, status=400)
        
        filter_date = parse_date(date)
        if not filter_date:
            return JsonResponse({'error': 'Invalid date format'}, status=400)
        
        # Get prescription
        try:
            prescription = PrescriptionScheduling.objects.get(
                patient_id=patient_id,
                prescription_date=filter_date
            )
        except PrescriptionScheduling.DoesNotExist:
            return JsonResponse({'error': 'Prescription not found'}, status=404)
        
        # Get prescription items
        items = prescription.items.all()
        prescription_items = []
        for item in items:
            prescription_items.append({
                'item_name': item.item_name,
                'dose': item.dose,
                'quantity': item.quantity,
                'time': item.time,
                'notes': item.notes
            })
        
        # Get patient info
        patient = prescription.patient
        doctor = prescription.doctor
        
        patient_info = {
            'name': patient.pat_name or 'Unknown',
            'registration_no': patient.pat_reg_no,
            'room_no': getattr(patient, 'pat_room_no', None),
            'doctor_name': doctor.get_full_name() if hasattr(doctor, 'get_full_name') else (doctor.username if doctor else 'Unknown')
        }
        
        return JsonResponse({
            'success': True,
            'patient_info': patient_info,
            'prescription_items': prescription_items
        })
        
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


def get_prescription_details_api(request):
    """API to get detailed prescription items for a patient"""
    try:
        patient_id = request.GET.get('patient_id')
        date = request.GET.get('date')
        
        if not patient_id or not date:
            return JsonResponse({'error': 'patient_id and date are required'}, status=400)
        
        # Get prescription scheduling record
        prescription = PrescriptionScheduling.objects.filter(
            patient_id=patient_id,
            prescription_date=date
        ).first()
        
        if not prescription:
            return JsonResponse({'success': True, 'data': []})
        
        # Get prescription items
        items = PrescriptionItem.objects.filter(prescription_scheduling=prescription)
        
        prescription_items = []
        for item in items:
            prescription_items.append({
                'id': item.id,
                'item_name': item.item_name,
                'dose': item.dose,
                'quantity': item.quantity,
                'time': item.time,
                'notes': item.notes or ''
            })
        
        return JsonResponse({
            'success': True,
            'data': prescription_items
        })
        
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)
