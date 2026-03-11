from django.shortcuts import render
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from django.contrib.auth.decorators import login_required
from django.utils import timezone
from django.db import transaction
from django.utils.dateparse import parse_date
from .models import PrescriptionScheduling, PrescriptionChangeLog, PrescriptionItem, PrescriptionDispatch
from .decorators import procurement_access_required, procurement_api_access_required
import json
from datetime import datetime

@login_required
@procurement_access_required
def procurement_dashboard(request):
    """
    Display the procurement dashboard for prescription preparation and dispatch.
    """
    return render(request, 'dashboards/procurement/procurement_dashboard.html')

@csrf_exempt
@require_http_methods(["GET"])
@procurement_api_access_required
def get_procurement_prescriptions_api(request):
    """
    API endpoint to fetch prescriptions for procurement departments.
    """
    try:
        date = request.GET.get('date')
        
        if not date:
            return JsonResponse({'error': 'Date is required'}, status=400)
        
        filter_date = parse_date(date)
        if not filter_date:
            return JsonResponse({'error': 'Invalid date format'}, status=400)
        
        # For super_admin: show all prescriptions (no department filter)
        # For IP Pharmacy Staff: show only their department's prescriptions
        user_department = None
        if request.user.role == 'super_admin':
            # Super admin sees all prescriptions
            prescriptions = PrescriptionScheduling.objects.filter(
                prescription_date=filter_date,
                status__in=['scheduled', 'dispatched']
            ).select_related('patient', 'doctor').prefetch_related('items')
        else:
            # Get department from logged-in user's StaffProfile
            if hasattr(request.user, 'staff_profile'):
                user_department = request.user.staff_profile.department
            elif request.user.role == 'ip_pharmacy_staff':
                # Fallback: if user doesn't have StaffProfile, return error
                return JsonResponse({'error': 'User department not configured. Please contact administrator.'}, status=400)
            else:
                # For admin/scheduling_staff, allow department parameter or default to IP Pharmacy
                user_department = request.GET.get('department', 'IP Pharmacy')
            
            # Get prescriptions that match this department (check both sent_to and procured_from)
            # Case-insensitive matching
            user_dept_normalized = user_department.strip().lower() if user_department else ''
            
            # Get all prescriptions for the date
            all_prescriptions = PrescriptionScheduling.objects.filter(
                prescription_date=filter_date,
                status__in=['scheduled', 'dispatched']
            ).select_related('patient', 'doctor').prefetch_related('items')
            
            # Also get all allocations for this date to check procured_from
            from .models import PrescriptionAllocation
            all_allocations = PrescriptionAllocation.objects.filter(
                from_date__lte=filter_date,
                to_date__gte=filter_date
            ).select_related('patient')
            
            # Build a set of patient IDs that have allocations with procured_from matching user's department
            matching_patient_ids_from_allocations = set()
            for alloc in all_allocations:
                procured_from = alloc.procured_from.strip().lower() if alloc.procured_from else ''
                if procured_from == user_dept_normalized:
                    matching_patient_ids_from_allocations.add(alloc.patient_id)
            
            # Filter prescriptions: include if EITHER sent_to matches OR patient has allocation with procured_from matching
            matching_prescriptions = []
            for pres in all_prescriptions:
                sent_to_matches = pres.sent_to and pres.sent_to.strip().lower() == user_dept_normalized
                procured_from_matches = pres.patient_id in matching_patient_ids_from_allocations
                
                # Include prescription if either sent_to or procured_from matches
                if sent_to_matches or procured_from_matches:
                    matching_prescriptions.append(pres)
            
            # Convert back to queryset
            prescription_ids = [p.id for p in matching_prescriptions]
            prescriptions = PrescriptionScheduling.objects.filter(
                id__in=prescription_ids
            ).select_related('patient', 'doctor').prefetch_related('items')
        
        data = []
        for prescription in prescriptions:
            # Get prescription count and a small preview of items
            prescription_count = prescription.items.count()
            items_preview = []
            if prescription_count == 0:
                try:
                    from .models import PrescriptionAllocation
                    # Get allocation for this patient/date
                    allocation_query = PrescriptionAllocation.objects.filter(
                        patient=prescription.patient,
                        from_date__lte=filter_date,
                        to_date__gte=filter_date
                    )
                    
                    relevant_allocations = []
                    if request.user.role != 'super_admin' and user_department:
                        user_dept_normalized = user_department.strip().lower()
                        for alloc in allocation_query:
                            procured_from = alloc.procured_from.strip().lower() if alloc.procured_from else ''
                            if procured_from == user_dept_normalized or not procured_from:
                                relevant_allocations.append(alloc)
                    else:
                        relevant_allocations = list(allocation_query)
                    
                    # Helper to reconstruct historic items_groups
                    def get_effective_items_groups(alloc, target_date):
                        from .models import PrescriptionChangeLog
                        logs_for_date = PrescriptionChangeLog.objects.filter(
                            patient_id=alloc.patient_id,
                            prescription_date=target_date,
                            action='update',
                            after_values__allocation_id=alloc.id
                        ).order_by('-timestamp').first()
                        
                        if logs_for_date and logs_for_date.after_values:
                            return logs_for_date.after_values.get('items_groups')
                        
                        return alloc.items_groups

                    # Process ALL relevant allocations
                    for allocation in relevant_allocations:
                        raw_groups = get_effective_items_groups(allocation, filter_date)

                        if raw_groups:
                            groups = []
                            if isinstance(raw_groups, str):
                                try: groups = json.loads(raw_groups)
                                except: groups = []
                            elif isinstance(raw_groups, list): groups = raw_groups
                            elif isinstance(raw_groups, dict): groups = [raw_groups]
                            
                            for grp in groups:
                                items = grp.get('items', []) if isinstance(grp, dict) else []
                                for it in items:
                                    if not it: continue
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
@procurement_api_access_required
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
@procurement_api_access_required
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
        
        from MySql_Data_pull.models import Registration, doctor_master, Treatment
        
        # Get patient info
        patient_info = {
            'name': patient.pat_name or 'Unknown',
            'registration_no': patient.pat_reg_no,
            'room_no': getattr(patient, 'pat_room_no', None),
            'doctor_name': None,
            'doctor_team': '',
            'doa': ''
        }
        
        # Fetch additional patient info from Registration and Treatment tables
        try:
            reg_no = patient.pat_reg_no
            reg_no_str = str(reg_no)
            digits_only = ''.join(c for c in reg_no_str if c.isdigit())
            
            if digits_only:
                reg_no_int = int(digits_only)
                registration = Registration.objects.using('therapy_db').filter(
                    pat_reg_no=reg_no_int
                ).first()
                
                if registration:
                    patient_info['doctor_team'] = registration.dct_team or ''
                    
                    # Fetch DOA
                    treatment = Treatment.objects.using('iptherapy_db').filter(
                        Pat_Reg_No=digits_only
                    ).order_by('-DOA').first()
                    
                    # Try with leading zeros fallback
                    if not treatment:
                        for pad in [4, 5, 6]:
                            treatment = Treatment.objects.using('iptherapy_db').filter(
                                Pat_Reg_No=digits_only.zfill(pad)
                            ).order_by('-DOA').first()
                            if treatment: break
                            
                    if treatment and treatment.DOA:
                        if hasattr(treatment.DOA, 'strftime'):
                            patient_info['doa'] = treatment.DOA.strftime('%d/%m/%Y')
                        else:
                            patient_info['doa'] = str(treatment.DOA).split(' ')[0]
                    elif registration.pat_reg_date:
                        if hasattr(registration.pat_reg_date, 'strftime'):
                            patient_info['doa'] = registration.pat_reg_date.strftime('%d/%m/%Y')
                        else:
                            patient_info['doa'] = str(registration.pat_reg_date).split(' ')[0]
                            
                    # Fetch doctor name
                    if registration.doctcode:
                        doctor = doctor_master.objects.using('therapy_db').filter(
                            Doct_Code=registration.doctcode
                        ).first()
                        if not doctor:
                            doctor = doctor_master.objects.using('therapy_db').filter(
                                Doct_Code=str(registration.doctcode).zfill(4)
                            ).first()
                        
                        if doctor:
                            patient_info['doctor_name'] = doctor.Doct_Name or ''
        except Exception as e:
            print(f"Error fetching additional patient info in procurement API: {e}")
        
        # ===== DEPARTMENT FILTERING =====
        # For super_admin: show all prescriptions (no department filter)
        # For IP Pharmacy Staff: show only their department's prescriptions
        user_department = None
        if request.user.role != 'super_admin':
            # Get department from logged-in user's StaffProfile
            if hasattr(request.user, 'staff_profile'):
                user_department = request.user.staff_profile.department
            elif request.user.role == 'ip_pharmacy_staff':
                # Fallback: if user doesn't have StaffProfile, return error
                return JsonResponse({'error': 'User department not configured. Please contact administrator.'}, status=400)
            else:
                # For admin/scheduling_staff, allow department parameter or default to IP Pharmacy
                user_department = request.GET.get('department', 'IP Pharmacy')
        
        # Get prescription for doctor name and department filtering
        prescription_query = PrescriptionScheduling.objects.filter(
            patient_id=patient_id,
            prescription_date=filter_date
        )
        
        # Filter by department if not super_admin (case-insensitive)
        if user_department:
            user_dept_normalized = user_department.strip().lower() if user_department else ''
            # Get all prescriptions and filter case-insensitively
            all_prescriptions = prescription_query.all()
            matching_prescriptions = []
            for ps in all_prescriptions:
                if ps.sent_to and ps.sent_to.strip().lower() == user_dept_normalized:
                    matching_prescriptions.append(ps)
            
            if matching_prescriptions:
                prescription_query = PrescriptionScheduling.objects.filter(
                    id__in=[p.id for p in matching_prescriptions]
                )
            else:
                prescription_query = PrescriptionScheduling.objects.none()
        
        prescription = prescription_query.select_related('doctor').first()
        # Don't return early if no prescription - we might still have allocations with procured_from matching
        # Only return early if we have no prescription AND no allocations will match
        
        # ===== PRESCRIPTION ITEMS =====
        prescription_groups = []  # List of groups with items
        
        # Get all PrescriptionAllocation records for this patient that cover the date
        allocations = PrescriptionAllocation.objects.filter(
            patient_id=patient_id,
            from_date__lte=filter_date,
            to_date__gte=filter_date
        ).order_by('from_date', 'id')
        
        # Filter allocations based on department: check both sent_to and procured_from
        if user_department:
            # Normalize user department for case-insensitive comparison
            user_dept_normalized = user_department.strip().lower() if user_department else ''
            
            # Get all PrescriptionScheduling records for this patient/date that match user's department
            # Use case-insensitive comparison with __iexact
            valid_prescriptions = PrescriptionScheduling.objects.filter(
                patient_id=patient_id,
                prescription_date=filter_date
            )
            
            # Filter by sent_to case-insensitively
            valid_prescriptions_list = []
            for ps in valid_prescriptions:
                if ps.sent_to and ps.sent_to.strip().lower() == user_dept_normalized:
                    valid_prescriptions_list.append(ps)
            
            sent_to_matches = len(valid_prescriptions_list) > 0
            
            # Filter allocations based on:
            # Priority: If procured_from is set, it MUST match user's department
            # If procured_from is NOT set/empty, then check sent_to
            filtered_allocations = []
            for allocation in allocations:
                procured_from = allocation.procured_from.strip() if allocation.procured_from else ''
                has_procured_from = bool(procured_from)
                procured_from_normalized = procured_from.lower() if procured_from else ''
                procured_from_matches = procured_from_normalized == user_dept_normalized
                
                # Include allocation if:
                # - procured_from is set AND matches user's department (case-insensitive), OR
                # - procured_from is NOT set/empty AND sent_to matches user's department
                # This ensures that:
                # - If procured_from is set to "Kashaya Room" and user is "IP Pharmacy", exclude it
                # - If procured_from is empty and sent_to is "IP Pharmacy", show it for IP Pharmacy users
                # - If procured_from is set to "IP Pharmacy", show it for IP Pharmacy users
                if (has_procured_from and procured_from_matches) or (not has_procured_from and sent_to_matches):
                    filtered_allocations.append(allocation)
            
            # Convert to queryset by filtering by IDs
            if filtered_allocations:
                allocation_ids = [a.id for a in filtered_allocations]
                allocations = allocations.filter(id__in=allocation_ids)
            else:
                allocations = allocations.none()  # Return empty queryset
        
        prescription_is_cancelled = False
        prescription_status = 'draft'
        
        if prescription and prescription.doctor:
            patient_info['doctor_name'] = prescription.doctor.get_full_name() if hasattr(prescription.doctor, 'get_full_name') else (prescription.doctor.username if prescription.doctor else None)
        
        # Determine overall cancellation only if all allocations are cancelled
        if allocations:
            all_cancelled = all(a.status == 'cancelled' for a in allocations)
            prescription_is_cancelled = all_cancelled
            # Set a representative status (prefer non-cancelled if any)
            non_cancel_statuses = [a.status for a in allocations if a.status != 'cancelled']
            prescription_status = non_cancel_statuses[0] if non_cancel_statuses else 'cancelled'
        
        # Process all allocations and use items_groups
        for allocation in allocations:
            # Check if this allocation is cancelled for the current date
            # An allocation is cancelled for a date only if:
            # 1. The allocation status is 'cancelled', AND
            # 2. The date falls within the cancelled_date_from and cancelled_date_to range
            is_cancelled_for_this_date = False
            if allocation.status == 'cancelled' and allocation.cancelled_date_from and allocation.cancelled_date_to:
                if allocation.cancelled_date_from <= filter_date <= allocation.cancelled_date_to:
                    is_cancelled_for_this_date = True
            
            # Helper to reconstruct historic items_groups
            def get_effective_items_groups(alloc, target_date):
                from .models import PrescriptionChangeLog
                logs_for_date = PrescriptionChangeLog.objects.filter(
                    patient_id=alloc.patient_id,
                    prescription_date=target_date,
                    action='update',
                    after_values__allocation_id=alloc.id
                ).order_by('-timestamp').first()
                if logs_for_date and logs_for_date.after_values:
                    return logs_for_date.after_values.get('items_groups')
                
                return alloc.items_groups

            raw_groups = get_effective_items_groups(allocation, filter_date)
            if raw_groups:
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
                    
                    # Fallback: use allocation-level usage/scope if group-level missing
                    alloc_usage = getattr(allocation, 'usage', '')
                    alloc_scope = getattr(allocation, 'scope', '')
                    group_usage = group.get('usage', '') or alloc_usage
                    usage_array = group.get('usage_array', [])
                    internal_external = group.get('internal_external', '') or alloc_scope
                    
                    # Add the group exactly as it appears in items_groups (with fallbacks)
                    # Use is_cancelled_for_this_date instead of just checking allocation.status
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
                        'is_cancelled': is_cancelled_for_this_date,  # Use date-specific cancellation check
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
@procurement_api_access_required
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
        
        # Get user's department for filtering change logs
        user_department = None
        if request.user.role != 'super_admin':
            # Get department from logged-in user's StaffProfile
            if hasattr(request.user, 'staff_profile'):
                user_department = request.user.staff_profile.department
            elif request.user.role == 'ip_pharmacy_staff':
                # Fallback: if user doesn't have StaffProfile, return error
                return JsonResponse({'error': 'User department not configured. Please contact administrator.'}, status=400)
            else:
                # For admin/scheduling_staff, allow department parameter or default to IP Pharmacy
                user_department = request.GET.get('department', 'IP Pharmacy')
        
        # Get all change logs for this patient and date
        change_logs = PrescriptionChangeLog.objects.filter(
            patient_id=patient_id,
            prescription_date=filter_date
        ).select_related('changed_by').order_by('-timestamp')
        
        # Filter change logs by department if not super_admin
        if user_department:
            user_dept_normalized = user_department.strip().lower() if user_department else ''
            
            # Get allocations for this patient/date to check procured_from
            from .models import PrescriptionAllocation
            allocations = PrescriptionAllocation.objects.filter(
                patient_id=patient_id,
                from_date__lte=filter_date,
                to_date__gte=filter_date
            )
            
            # Get prescription scheduling records to check sent_to
            from .models import PrescriptionScheduling
            prescriptions = PrescriptionScheduling.objects.filter(
                patient_id=patient_id,
                prescription_date=filter_date
            )
            
            # Filter change logs to only show those relevant to user's department
            # A change log is relevant if:
            # 1. It mentions the user's department in sent_to or dispatched_from fields, OR
            # 2. It's an item update and there's an allocation with procured_from matching user's department, OR
            # 3. It's a status change and there's a prescription with sent_to matching user's department
            
            filtered_logs = []
            for log in change_logs:
                before_values = log.before_values or {}
                after_values = log.after_values or {}
                description = (log.description or '').lower()
                
                # Check if change log mentions user's department in after_values or before_values
                sent_to_after = (after_values.get('sent_to') or '').strip().lower()
                sent_to_before = (before_values.get('sent_to') or '').strip().lower()
                dispatched_from_after = (after_values.get('dispatched_from') or '').strip().lower()
                dispatched_from_before = (before_values.get('dispatched_from') or '').strip().lower()
                
                # Check if department is mentioned in the change log values
                mentions_department = (
                    sent_to_after == user_dept_normalized or
                    sent_to_before == user_dept_normalized or
                    dispatched_from_after == user_dept_normalized or
                    dispatched_from_before == user_dept_normalized or
                    user_department.lower() in description
                )
                
                # For item updates (which don't have department in values), check allocations
                # Item updates change items_groups, so we need to match the change log's items_groups
                # with allocations that have procured_from matching user's department
                if not mentions_department and log.action == 'update':
                    # Get the items_groups from the change log
                    log_after_groups = after_values.get('items_groups', [])
                    log_before_groups = before_values.get('items_groups', [])
                    
                    # Check if any allocation with procured_from matching has items_groups that match
                    # the change log (either before or after values)
                    for alloc in allocations:
                        procured_from = (alloc.procured_from or '').strip().lower()
                        if procured_from == user_dept_normalized:
                            alloc_items_groups = alloc.items_groups or []
                            
                            # Normalize for comparison
                            try:
                                # Compare: if after_values matches current allocation, it's this allocation's update
                                # OR if before_values matches current, it might be a previous state
                                alloc_str = json.dumps(alloc_items_groups, sort_keys=True) if alloc_items_groups else ''
                                after_str = json.dumps(log_after_groups, sort_keys=True) if log_after_groups else ''
                                before_str = json.dumps(log_before_groups, sort_keys=True) if log_before_groups else ''
                                
                                # Match if after_values matches current (most recent update) OR
                                # if before_values matches current (this was the state before another update)
                                if alloc_str == after_str or alloc_str == before_str:
                                    mentions_department = True
                                    break
                            except:
                                # If JSON comparison fails, do a simple equality check
                                if alloc_items_groups == log_after_groups or alloc_items_groups == log_before_groups:
                                    mentions_department = True
                                    break
                
                # For status changes, check prescriptions
                if not mentions_department and log.action == 'status_change':
                    # Check if any prescription for this patient/date has sent_to matching
                    for pres in prescriptions:
                        sent_to = (pres.sent_to or '').strip().lower()
                        if sent_to == user_dept_normalized:
                            mentions_department = True
                            break
                
                # Include log if it mentions the department
                if mentions_department:
                    filtered_logs.append(log)
            
            # Replace queryset with filtered list
            if filtered_logs:
                log_ids = [log.id for log in filtered_logs]
                change_logs = PrescriptionChangeLog.objects.filter(id__in=log_ids).select_related('changed_by').order_by('-timestamp')
            else:
                change_logs = change_logs.none()
        
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
