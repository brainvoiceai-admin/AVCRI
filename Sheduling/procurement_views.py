from django.shortcuts import render
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from django.contrib.auth.decorators import login_required
from django.utils import timezone
from django.db import transaction
from django.utils.dateparse import parse_date
from django.db.models import Q
from .models import PrescriptionScheduling, PrescriptionChangeLog, PrescriptionItem, PrescriptionDispatch
from .decorators import procurement_access_required, procurement_api_access_required
import json
from datetime import datetime, timedelta

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
                sent_to_list = [s.strip().lower() for s in (pres.sent_to or '').split(',')]
                sent_to_matches = user_dept_normalized in sent_to_list
                procured_from_matches = pres.patient_id in matching_patient_ids_from_allocations
                
                # Include prescription if either sent_to or procured_from matches
                if sent_to_matches or procured_from_matches:
                    matching_prescriptions.append(pres)
            
            # Convert back to queryset
            prescription_ids = [p.id for p in matching_prescriptions]
            prescriptions = PrescriptionScheduling.objects.filter(
                id__in=prescription_ids
            ).select_related('patient', 'doctor').prefetch_related('items')
        # --- NEW: Bulk Filter Inactive Patients ---
        prescriptions_list = list(prescriptions)
        if prescriptions_list:
            try:
                from MySql_Data_pull.models import Registration
                ip_reg_ints = []
                for p in prescriptions_list:
                    reg_str = str(p.patient.pat_reg_no).strip()
                    digits = ''.join(ch for ch in reg_str if ch.isdigit())
                    if len(digits) > 5:
                        try: ip_reg_ints.append(int(digits))
                        except: pass
                
                if ip_reg_ints:
                    active_regs = set(Registration.objects.using('therapy_db').filter(
                        pat_reg_no__in=ip_reg_ints,
                        pat_status='Y'
                    ).values_list('pat_reg_no', flat=True))
                    
                    # Re-filter prescriptions list
                    filtered_prescriptions = []
                    for p in prescriptions_list:
                        reg_str = str(p.patient.pat_reg_no).strip()
                        digits = ''.join(ch for ch in reg_str if ch.isdigit())
                        if len(digits) == 5:
                            filtered_prescriptions.append(p)
                        elif digits and int(digits) in active_regs:
                            filtered_prescriptions.append(p)
                            
                    prescriptions_list = filtered_prescriptions
            except Exception as e:
                print(f"Error filtering inactive patients in Procurement API: {e}")
        
        data = []
        for prescription in prescriptions_list:
            # 1. Start with PrescriptionItem count (New system / Individually added items)
            # These are the ones shown in the "Scheduled Prescription" tab
            items_preview = []
            items_qs = prescription.items.all()
            for it in items_qs:
                if len(items_preview) < 10:
                    items_preview.append({
                        'item_name': it.item_name,
                        'dose': it.dose,
                        'quantity': it.quantity,
                        'time': it.time,
                        'notes': it.notes or ''
                    })
            prescription_count = items_qs.count()

            # 2. Add PrescriptionAllocation items (Kashayams / Treatments)
            try:
                from .models import PrescriptionAllocation
                # Get allocations for this patient/date
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
                
                # Helper to reconstruct historic items_groups reliably
                def get_effective_items_groups(alloc, target_date):
                    logs = PrescriptionChangeLog.objects.filter(
                        Q(after_values__allocation_id=alloc.id) |
                        Q(before_values__allocation_id=alloc.id)
                    ).order_by('-timestamp')
                    
                    date_logs = {}
                    for log in logs:
                        if log.prescription_date not in date_logs:
                            date_logs[log.prescription_date] = log
                    
                    running_items = alloc.items_groups
                    temp_date = alloc.to_date
                    while temp_date >= target_date:
                        log = date_logs.get(temp_date)
                        if temp_date == target_date:
                            return log.after_values.get('items_groups', running_items) if log else running_items
                        if log:
                            running_items = log.before_values.get('items_groups', running_items)
                        temp_date -= timedelta(days=1)
                    return running_items

                alloc_items_count = 0
                for allocation in relevant_allocations:
                    # Skip cancelled treatments for this day
                    if allocation.status == 'cancelled' and allocation.cancelled_date_from and allocation.cancelled_date_to:
                        if allocation.cancelled_date_from <= filter_date <= allocation.cancelled_date_to:
                            continue

                    raw_groups = get_effective_items_groups(allocation, filter_date)
                    if raw_groups:
                        groups = json.loads(raw_groups) if isinstance(raw_groups, str) else (raw_groups if isinstance(raw_groups, list) else [raw_groups])
                        for grp in groups:
                            items = grp.get('items', []) if isinstance(grp, dict) else []
                            for it in items:
                                if not it: continue
                                alloc_items_count += 1
                                if len(items_preview) < 10:
                                    items_preview.append({
                                        'item_name': it.get('item_name', ''),
                                        'dose': grp.get('dosage', ''),
                                        'quantity': it.get('quantity', ''),
                                        'time': grp.get('time', ''),
                                        'notes': grp.get('uno', '')
                                    })
                prescription_count += alloc_items_count
            except Exception as e:
                print(f"Error merging allocation items in Procurement Index API: {e}")
            
            # Get patient details
            patient = prescription.patient
            doctor = prescription.doctor
            
            # Handle potential None values
            patient_name = patient.pat_name or 'Unknown'
            doctor_name = doctor.get_full_name() if hasattr(doctor, 'get_full_name') else (doctor.username if doctor else 'Unknown')
            
            # Get prepared count (how many individual dispatches already exist)
            prepared_count = PrescriptionDispatch.objects.filter(
                prescription_scheduling=prescription,
                prescription_allocation__isnull=False
            ).count()

            # Skip patients with no active/scheduled items for this date
            if prescription_count == 0:
                continue

            data.append({
                'patient_id': patient.id,
                'patient_name': patient_name,
                'patient_id_display': patient.pat_reg_no,
                'registration_no': patient.pat_reg_no,
                'room_no': getattr(patient, 'pat_room_no', None),
                'doctor_name': doctor_name,
                'prescription_count': prescription_count,
                'prepared_count': prepared_count,
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
        allocation_id = data.get('allocation_id') # New: individual medicine dispatch
        
        if not patient_id or not date:
            return JsonResponse({'error': 'Patient ID and date are required'}, status=400)
        
        filter_date = parse_date(date)
        if not filter_date:
            return JsonResponse({'error': 'Invalid date format'}, status=400)
        
        from .models import PrescriptionAllocation
        
        # Find the scheduling record
        try:
            scheduling = PrescriptionScheduling.objects.get(
                patient_id=patient_id,
                prescription_date=filter_date
            )
        except PrescriptionScheduling.DoesNotExist:
            return JsonResponse({'error': 'Scheduling record not found'}, status=404)
        
        with transaction.atomic():
            dispatch_user = request.user if request.user.is_authenticated else None
            if not dispatch_user:
                from authentication.models import CustomUser
                dispatch_user = CustomUser.objects.filter(is_superuser=True).first()

            if allocation_id:
                # Mark individual allocation as dispatched
                try:
                    target_alloc = PrescriptionAllocation.objects.get(id=allocation_id, patient_id=patient_id)
                except PrescriptionAllocation.DoesNotExist:
                    return JsonResponse({'error': 'Allocation not found'}, status=404)
                
                # Check if already dispatched for this specific allocation
                if PrescriptionDispatch.objects.filter(
                    prescription_scheduling=scheduling,
                    prescription_allocation=target_alloc
                ).exists():
                    return JsonResponse({'success': True, 'message': 'Medicine already dispatched'})

                # Create dispatch record for this specific allocation
                PrescriptionDispatch.objects.create(
                    prescription_scheduling=scheduling,
                    prescription_allocation=target_alloc,
                    department=target_alloc.procured_from or scheduling.sent_to,
                    dispatched_by=dispatch_user,
                    notes=f"Single medicine '{target_alloc.prescription_name}' dispatched"
                )
                
                # Check if ALL other active medicines are now dispatched
                all_allocs = PrescriptionAllocation.objects.filter(
                    patient_id=patient_id,
                    from_date__lte=filter_date,
                    to_date__gte=filter_date
                ).exclude(status='cancelled', cancelled_date_from__lte=filter_date, cancelled_date_to__gte=filter_date)
                
                dispatched_alloc_ids = PrescriptionDispatch.objects.filter(
                    prescription_scheduling=scheduling,
                    prescription_allocation__isnull=False
                ).values_list('prescription_allocation_id', flat=True)
                
                all_dispatched = True
                for a in all_allocs:
                    if a.id not in dispatched_alloc_ids:
                        all_dispatched = False
                        break
                
                if all_dispatched:
                    scheduling.status = 'dispatched'
                    scheduling.dispatched_at = timezone.now()
                    scheduling.save()
                    
                message = f"Medicine '{target_alloc.prescription_name}' marked as dispatched"
            else:
                # Mark everything as dispatched (Mark All as Prepared)
                scheduling.status = 'dispatched'
                scheduling.dispatched_at = timezone.now()
                scheduling.dispatched_from = scheduling.sent_to
                scheduling.save()
                
                # Get all active allocations for today to mark them individually
                active_allocs = PrescriptionAllocation.objects.filter(
                    patient_id=patient_id,
                    from_date__lte=filter_date,
                    to_date__gte=filter_date
                ).exclude(status='cancelled', cancelled_date_from__lte=filter_date, cancelled_date_to__gte=filter_date)

                for alloc in active_allocs:
                    PrescriptionDispatch.objects.get_or_create(
                        prescription_scheduling=scheduling,
                        prescription_allocation=alloc,
                        defaults={
                            'department': alloc.procured_from or scheduling.sent_to,
                            'dispatched_by': dispatch_user,
                            'notes': f'Bulk dispatch from {scheduling.sent_to}'
                        }
                    )
                
                # Also create a general dispatch record for the schedule itself (legacy compatibility)
                PrescriptionDispatch.objects.get_or_create(
                    prescription_scheduling=scheduling,
                    prescription_allocation=None,
                    defaults={
                        'department': scheduling.sent_to,
                        'dispatched_by': dispatch_user,
                        'notes': f'Bulk dispatch from {scheduling.sent_to}'
                    }
                )
                
                message = 'All medicines marked as dispatched'

            # Log change
            PrescriptionChangeLog.objects.create(
                patient=scheduling.patient,
                prescription_date=filter_date,
                action='status_change',
                changed_by=dispatch_user,
                after_values={'status': 'dispatched', 'allocation_id': allocation_id},
                description=message
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
    API endpoint to fetch all medicines (PrescriptionAllocation - Kashayams/Oils AND 
    PrescriptionItem - Manually added medicines) for a patient and date,
    including their grouped items.
    """
    try:
        from .models import PrescriptionAllocation, Booking, BookingItem, PatientSnapshot, PrescriptionScheduling, PrescriptionItem, PrescriptionDispatch, PrescriptionChangeLog
        
        patient_id = request.GET.get('patient_id')
        date = request.GET.get('date')
        
        if not patient_id or not date:
            return JsonResponse({'error': 'patient_id and date are required'}, status=400)
        
        filter_date = parse_date(date)
        if not filter_date:
            return JsonResponse({'error': 'Invalid date format'}, status=400)
        
        # Get patient model
        try:
            patient = PatientSnapshot.objects.get(id=patient_id)
        except PatientSnapshot.DoesNotExist:
            return JsonResponse({'error': 'Patient not found'}, status=404)
        
        patient_info = {
            'id': patient.id,
            'name': patient.pat_name,
            'registration_no': patient.pat_reg_no,
            'room_no': getattr(patient, 'pat_room_no', None),
            'doctor_name': None
        }

        # ===== DEPARTMENT FILTERING =====
        user_department = None
        if request.user.role != 'super_admin':
            if hasattr(request.user, 'staff_profile'):
                user_department = request.user.staff_profile.department
            elif request.user.role == 'ip_pharmacy_staff':
                return JsonResponse({'error': 'User department not configured.'}, status=400)
            else:
                user_department = request.GET.get('department', 'IP Pharmacy')
        
        user_dept_normalized = user_department.strip().lower() if user_department else ''
        
        # Helper for reconstructing historic items_groups
        def get_effective_items_groups(alloc, target_date):
            logs = PrescriptionChangeLog.objects.filter(
                Q(after_values__allocation_id=alloc.id) |
                Q(before_values__allocation_id=alloc.id)
            ).order_by('-timestamp')
            
            date_logs = {}
            for log in logs:
                if log.prescription_date not in date_logs:
                    date_logs[log.prescription_date] = log
            
            running_items = alloc.items_groups
            temp_date = alloc.to_date
            while temp_date >= target_date:
                log = date_logs.get(temp_date)
                if temp_date == target_date:
                    return log.after_values.get('items_groups', running_items) if log else running_items
                if log:
                    running_items = log.before_values.get('items_groups', running_items)
                temp_date -= timedelta(days=1)
            return running_items

        # Fetch ALL prescriptions for metadata
        all_prescriptions = PrescriptionScheduling.objects.filter(
            patient_id=patient_id,
            prescription_date=filter_date
        ).select_related('doctor')
        
        valid_pres_depts = set()
        representative_prescription = None
        for ps in all_prescriptions:
            depts = [s.strip().lower() for s in (ps.sent_to or '').split(',')]
            for d in depts: 
                if d: valid_pres_depts.add(d)
            if not representative_prescription or user_dept_normalized in depts:
                representative_prescription = ps

        if representative_prescription and representative_prescription.doctor:
            patient_info['doctor_name'] = representative_prescription.doctor.get_full_name() or representative_prescription.doctor.username

        # Fetch allocations (Kashayams / Ointments / etc.)
        allocations = PrescriptionAllocation.objects.filter(
            patient_id=patient_id,
            from_date__lte=filter_date,
            to_date__gte=filter_date
        ).order_by('from_date', 'id')

        prescription_groups = []
        sent_to_matches = user_dept_normalized in valid_pres_depts

        for allocation in allocations:
            # 1. Department Filtering
            procured_from = (allocation.procured_from or '').strip().lower()
            if user_department:
                if procured_from:
                    if procured_from != user_dept_normalized: continue
                elif not sent_to_matches and valid_pres_depts:
                    # Only skip if we have other prescriptions but none match our dept
                    continue

            # 2. Pull effective items
            raw_groups = get_effective_items_groups(allocation, filter_date)
            if raw_groups:
                groups = json.loads(raw_groups) if isinstance(raw_groups, str) else (raw_groups if isinstance(raw_groups, list) else [raw_groups])
                for group_idx, group in enumerate(groups):
                    items = group.get('items', []) if isinstance(group, dict) else []
                    group_items = []
                    for it in items:
                        if it and (it.get('item_name') or it.get('id')):
                            group_items.append({
                                'id': f'prescription_alloc_{allocation.id}_{it.get("id", it.get("item_code", "it"))}',
                                'type': 'prescription',
                                'item_name': it.get('item_name', ''),
                                'dose': group.get('dosage', ''),
                                'quantity': it.get('quantity', ''),
                                'time': group.get('time', ''),
                                'notes': group.get('uno', ''),
                                'status': 'active'
                            })
                    
                    is_dispatched = PrescriptionDispatch.objects.filter(
                        prescription_scheduling=representative_prescription,
                        prescription_allocation=allocation
                    ).exists() if representative_prescription else False

                    prescription_groups.append({
                        'group_id': f"prescription_group_{allocation.id}_{group_idx}",
                        'allocation_id': allocation.id,
                        'time': group.get('time', 'M'),
                        'dose': group.get('dosage', ''),
                        'usage': group.get('usage', '') or getattr(allocation, 'usage', ''),
                        'usage_array': group.get('usage_array', []),
                        'internal_external': group.get('internal_external', '') or getattr(allocation, 'scope', ''),
                        'notes': group.get('uno', ''),
                        'oil_class': group.get('oil_class', ''),
                        'ingredients': group.get('ingredients', []),
                        'items': group_items,
                        'is_dispatched': is_dispatched,
                        'is_group': True
                    })

        # Fetch individually added PrescriptionItems
        if representative_prescription:
            items_qs = PrescriptionItem.objects.filter(prescription_scheduling=representative_prescription).all()
            for item in items_qs:
                prescription_groups.append({
                    'group_id': f"prescription_item_{item.id}",
                    'time': item.time or '',
                    'dose': item.dose or '',
                    'usage': getattr(item, 'usage', ''),
                    'internal_external': getattr(item, 'internal_external', ''),
                    'notes': item.notes or '',
                    'items': [{
                        'id': f'prescription_{item.id}',
                        'type': 'prescription',
                        'item_name': item.item_name,
                        'dose': item.dose or '',
                        'quantity': item.quantity or '',
                        'time': item.time or '',
                        'usage': getattr(item, 'usage', ''),
                        'notes': item.notes or '',
                        'status': 'active'
                    }],
                    'is_group': True,
                    'is_dispatched': representative_prescription.status == 'dispatched'
                })

        # Therapy Items (BookingItem)
        bookings = Booking.objects.filter(
            allocation__patient=patient,
            date=filter_date
        ).select_related('allocation').prefetch_related('items').order_by('allocation__therapy_name', 'timeslot')
        
        therapy_items = []
        therapy_groups = {}
        for booking in bookings:
            if not booking.allocation: continue
            alloc = booking.allocation
            items_groups = alloc.items_groups if isinstance(alloc.items_groups, list) else []
            booking_items = booking.items.all()
            item_map = {item.item_code: item for item in booking_items}
            item_map.update({item.item_name: item for item in booking_items})

            if items_groups:
                for idx, grp in enumerate(items_groups):
                    key = (alloc.id, idx)
                    if key not in therapy_groups:
                        therapy_groups[key] = {
                            'therapy_name': alloc.therapy_name,
                            'dosage': grp.get('dosage', ''),
                            'uno': grp.get('uno', ''),
                            'booking_status': booking.status,
                            'items': []
                        }
                    for i in grp.get('items', []):
                        name = i.get('item_name') or i.get('text') or ''
                        code = i.get('item_code') or i.get('id') or ''
                        bi = item_map.get(code) or item_map.get(name)
                        if bi:
                            therapy_groups[key]['items'].append({
                                'id': f'therapy_{bi.id}',
                                'type': 'therapy',
                                'item_name': bi.item_name,
                                'status': bi.status
                            })
                        else:
                            # Fallback to items info in grp even if BookingItem isn't in DB yet
                            therapy_groups[key]['items'].append({
                                'id': f'therapy_missing_{idx}_{len(therapy_groups[key]["items"])}',
                                'type': 'therapy',
                                'item_name': name,
                                'status': 'draft'
                            })
            else:
                for bi in booking_items:
                    therapy_items.append({
                        'group_id': f'therapy_indiv_{bi.id}',
                        'therapy_name': alloc.therapy_name,
                        'booking_status': booking.status,
                        'items': [{'item_name': bi.item_name, 'status': bi.status, 'type': 'therapy', 'id': bi.id}],
                        'is_group': True
                    })

        for key, gdata in therapy_groups.items():
            therapy_items.append({
                'group_id': f"therapy_group_{key[0]}_{key[1]}",
                'therapy_name': gdata['therapy_name'],
                'dosage': gdata['dosage'],
                'uno': gdata['uno'],
                'booking_status': gdata['booking_status'],
                'booking_is_cancelled': gdata['booking_status'] == 'cancelled',
                'items': gdata['items'],
                'is_group': True
            })

        # Combine items for backward matching
        all_items_flat = []
        for g in prescription_groups:
            all_items_flat.extend(g.get('items', []))

        return JsonResponse({
            'success': True,
            'patient_info': patient_info,
            'items': all_items_flat,
            'prescription_groups': prescription_groups,
            'prescription_items': all_items_flat,
            'therapy_items': therapy_items,
            'counts': {
                'total': len(all_items_flat) + sum(len(g['items']) for g in therapy_items),
                'prescription': len(all_items_flat),
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
