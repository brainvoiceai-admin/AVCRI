from django.http import HttpResponse
from django.shortcuts import render
from django.shortcuts import render, redirect
from django.contrib.auth import authenticate, login as auth_login
from django.contrib import messages
from django.contrib.auth.models import User

def home(request):
    return render(request,'home.html')





from django.shortcuts import render, redirect, get_object_or_404
from django.http import JsonResponse
from django.db.models import Q
from datetime import date
from MySql_Data_pull.models import Registration, OPMaster, store_Therapy, store_TherapyItem, store_Prescription, store_PrescriptionItem, ItemMaster, Visit, doctor_master, Treatment
from masters.models import UnitNo, get_staying_room_display_number
import json
from .models import Repeated_Visitors, PatientHistory
from datetime import date, datetime
from final_allocation import expand_therapies_for_visit

# Step 1: Patient Lookup
# Removed patient_lookup_view - template deleted (not in navigation)
# def patient_lookup_view(request):
#     ...


def search_patients_api(request):
    query = request.GET.get('q', '')
    if not query or len(query) < 3:
        return JsonResponse([], safe=False)
    
    try:
        patients = []
        
        # Search in IP patients (Registration table)
        try:
            ip_patients = Registration.objects.using('therapy_db').filter(
                Q(pat_status='Y') & (
                    Q(pat_reg_no__icontains=query) | 
                    Q(pat_name__icontains=query)
                )
            ).values('pat_reg_no', 'pat_name')[:10]
            
            for patient in ip_patients:
                patients.append({
                    'pat_reg_no': str(patient['pat_reg_no']),
                    'pat_name': patient['pat_name'] or 'Unknown',
                    'patient_type': 'IP'
                })
        except Exception as e:
            print(f"Error searching IP patients: {e}")
        
        # Search in OP patients (OPMaster table)
        try:
            op_patients = OPMaster.objects.using('hospital_db').filter(
                Q(NPat_Reg_No__icontains=query) | Q(NPat_Name__icontains=query)
            ).values('NPat_Reg_No', 'NPat_Name')[:10]
            print(op_patients)
            for patient in op_patients:
                pat_reg_no_str = str(patient['NPat_Reg_No'])
                # OP patients should be shown without Treatment active/inactive filtering.
                patients.append({
                    'pat_reg_no': pat_reg_no_str,
                    'pat_name': patient['NPat_Name'] or 'Unknown',
                    'patient_type': 'OP'
                })
        except Exception as e:
            print(f"Error searching OP patients: {e}")
        
        # Remove duplicates based on registration number
        seen_reg_nos = set()
        unique_patients = []
        for patient in patients:
            if patient['pat_reg_no'] not in seen_reg_nos:
                seen_reg_nos.add(patient['pat_reg_no'])
                unique_patients.append(patient)
        return JsonResponse(unique_patients[:10], safe=False)
    except Exception as e:
        print(f"Error in search_patients_api: {e}")
        return JsonResponse({'error': 'Database connection error'}, status=500)

# In yourappname/views.py

def get_patient_details_api(request):
    pat_reg_no = request.GET.get('pat_reg_no')
    if not pat_reg_no:
        return JsonResponse({'error': 'Registration number is required'}, status=400)
    
    patient_details = None
    print(pat_reg_no)
    # Try to find in IP patients first
    try:
        patient = Registration.objects.using('therapy_db').get(pat_reg_no=pat_reg_no)
        
        # Handle VIP status lookup
        try:
            reg_no_int = int(pat_reg_no)
            vip_status = "Yes" if Repeated_Visitors.objects.filter(register_number=reg_no_int, is_vip=1).exists() else "No"
            repeated_status = "Yes" if Repeated_Visitors.objects.filter(register_number=reg_no_int, total_visits__gt=2).exists() else "No"
        except (ValueError, TypeError):
            vip_status = "No"
            repeated_status = "No"
        
        display_room_no = get_staying_room_display_number(patient.pat_room_no)
        # Get doctor name from doctor_master table using doctcode
        doctor_name = ''
        if patient.doctcode:
            try:
                doctor = doctor_master.objects.using('therapy_db').filter(
                    Doct_Code=patient.doctcode
                ).first()
                if doctor:
                    doctor_name = doctor.Doct_Name or ''
            except Exception as e:
                print(f"Error fetching doctor name for IP: {e}")
                
        patient_details = {
            'pat_reg_no': patient.pat_reg_no,
            'pat_name': patient.pat_name or 'Unknown',
            'pat_age': patient.pat_age or 'Unknown',
            'pat_sex': patient.pat_sex or 'Unknown',
            'vip_status': vip_status,
            'pat_op_reg_no': patient.pat_op_reg_no or '',
            'pat_room_no': display_room_no or '',
            'pat_ref_id': patient.pat_ref_id or '',
            'repeated_status': repeated_status,
            'patient_type': 'IP',
            'doctor_name': doctor_name,
            'doctor_team': patient.dct_team or '',
            'doa': ''
        }
        
        # Fetch DOA for IP - use .values() to avoid utcoffset crash on other DateTimeFields
        try:
            reg_no_str = str(pat_reg_no)
            doa_row = Treatment.objects.using('iptherapy_db').filter(
                Pat_Reg_No=reg_no_str
            ).exclude(DOA__isnull=True).order_by('-DOA').values('DOA').first()
            if not doa_row:
                for pad in [4, 5, 6]:
                    doa_row = Treatment.objects.using('iptherapy_db').filter(
                        Pat_Reg_No=reg_no_str.zfill(pad)
                    ).exclude(DOA__isnull=True).order_by('-DOA').values('DOA').first()
                    if doa_row: break
            
            if doa_row and doa_row['DOA']:
                doa_val = doa_row['DOA']
                patient_details['doa'] = doa_val.strftime('%d/%m/%Y') if hasattr(doa_val, 'strftime') else str(doa_val).split(' ')[0]
            elif patient.pat_reg_date:
                patient_details['doa'] = patient.pat_reg_date.strftime('%d/%m/%Y') if hasattr(patient.pat_reg_date, 'strftime') else str(patient.pat_reg_date).split(' ')[0]
        except Exception as e:
            print(f"Error fetching DOA for IP: {e}")
            import traceback
            traceback.print_exc()
    except Registration.DoesNotExist:
        pass
    except Exception as e:
        print(f"Error searching IP patients: {e}")
    
    # If not found in IP patients, try OP patients
    if not patient_details:
        try:
            op_patient = OPMaster.objects.using('hospital_db').filter(NPat_Reg_No=pat_reg_no).first()
            if op_patient:
                # Handle VIP status lookup for OP patients
                try:
                    reg_no_int = int(pat_reg_no)
                    vip_status = "Yes" if Repeated_Visitors.objects.filter(register_number=reg_no_int, is_vip=1).exists() else "No"
                    repeated_status = "Yes" if Repeated_Visitors.objects.filter(register_number=reg_no_int, total_visits__gt=2).exists() else "No"
                except (ValueError, TypeError):
                    vip_status = "No"
                    repeated_status = "No"
                
                # Fetch room number and age from Treatment model for OP patients
                op_room_no = ''
                op_age = 'Unknown'
                try:
                    # Use .values() to avoid utcoffset crash on DateTimeFields
                    pat_reg_no_str = str(pat_reg_no)
                    treatment_info = Treatment.objects.using('iptherapy_db').filter(
                        Pat_Reg_No=pat_reg_no_str
                    ).values('Pat_Room_No', 'Pat_Age').first()
                    
                    if treatment_info:
                        if treatment_info.get('Pat_Room_No'):
                            op_room_no = str(treatment_info['Pat_Room_No']).strip()
                            print(f"[DEBUG] OP patient {pat_reg_no} room number from Treatment: {op_room_no}")
                        if treatment_info.get('Pat_Age'):
                            op_age = str(treatment_info['Pat_Age']).strip()
                            print(f"[DEBUG] OP patient {pat_reg_no} age from Treatment: {op_age}")
                    else:
                        print(f"[DEBUG] No Treatment record found for OP patient {pat_reg_no}")
                except Exception as e:
                    print(f"Error fetching OP patient details from Treatment model: {e}")
                    import traceback
                    traceback.print_exc()
                
                # Fetch DOA and Doctor for OP from Treatment table - use .values() to avoid utcoffset crash
                op_doa = ''
                op_team = ''
                op_doctor_name = ''
                try:
                    reg_no_str = str(pat_reg_no)
                    treatment_row = Treatment.objects.using('iptherapy_db').filter(
                        Pat_Reg_No=reg_no_str
                    ).exclude(DOA__isnull=True).order_by('-DOA').values('DOA', 'Treat_Doc_Code').first()
                    
                    if not treatment_row:
                        # Try padded versions
                        for pad in [4, 5, 6]:
                            treatment_row = Treatment.objects.using('iptherapy_db').filter(
                                Pat_Reg_No=reg_no_str.zfill(pad)
                            ).exclude(DOA__isnull=True).order_by('-DOA').values('DOA', 'Treat_Doc_Code').first()
                            if treatment_row: break
                    
                    if treatment_row:
                        if treatment_row.get('DOA'):
                            doa_val = treatment_row['DOA']
                            op_doa = doa_val.strftime('%d/%m/%Y') if hasattr(doa_val, 'strftime') else str(doa_val).split(' ')[0]
                        if treatment_row.get('Treat_Doc_Code'):
                            # Fetch doctor name for OP using Treat_Doc_Code
                            try:
                                doctor = doctor_master.objects.using('therapy_db').filter(
                                    Doct_Code=treatment_row['Treat_Doc_Code']
                                ).first()
                                if doctor:
                                    op_doctor_name = doctor.Doct_Name or ''
                            except Exception as e:
                                print(f"Error fetching doctor name for OP: {e}")
                except Exception as e:
                    print(f"Error fetching treatment details for OP: {e}")
                    import traceback
                    traceback.print_exc()
                
                patient_details = {
                    'pat_reg_no': op_patient.NPat_Reg_No,
                    'pat_name': op_patient.NPat_Name or 'Unknown',
                    'pat_age': op_age,  # Fetch from Treatment model
                    'pat_sex': op_patient.NPat_Sex or 'Unknown',
                    'vip_status': vip_status,
                    'pat_op_reg_no': '',  # OP patients don't have OP reg no
                    'pat_room_no': op_room_no,  # Fetch from Treatment model
                    'pat_ref_id': '',  # OP patients don't have ref ID
                    'repeated_status': repeated_status,
                    'patient_type': 'OP',
                    'doctor_name': op_doctor_name,
                    'doctor_team': op_team,
                    'doa': op_doa
                }
        except Exception as e:
            print(f"Error searching OP patients: {e}")
    
    if patient_details:
        return JsonResponse(patient_details)
    else:
        return JsonResponse({'error': 'Patient with this registration number does not exist.'}, status=404)
    

# -----------------------
# Patient history API (PatientHistory model)
# -----------------------
def patient_history_api(request):
    """
    Return all treatment history rows from PatientHistory for a given patient reg no.
    Query param: ?pat_reg_no=XXXXX
    """
    pat_reg_no = request.GET.get('pat_reg_no')
    if not pat_reg_no:
        return JsonResponse({'error': 'Registration number is required'}, status=400)

    try:
        qs = PatientHistory.objects.filter(preg_no=str(pat_reg_no)).order_by('-date', '-id')
        history = []
        for row in qs:
            history.append({
                "id": row.id,
                "preg_no": row.preg_no,
                "pat_name": row.pat_name or "",
                "date": row.date.isoformat() if row.date else None,
                "treatment": row.treatment or "",
                "therapist_name": row.therapist_name or "",
                "therapist_code": row.therapist_code or "",
                "room_no": row.room_no or "",
                "t_room": row.t_room or "",
            })
        return JsonResponse({"history": history})
    except Exception as e:
        print(f"[ERROR] patient_history_api failed for {pat_reg_no}: {e}")
        import traceback
        traceback.print_exc()
        return JsonResponse({'error': 'Error fetching patient history.'}, status=500)

# Step 2: Therapy Entry
import json
from datetime import datetime
from django.shortcuts import get_object_or_404, redirect, render
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods

# import your models
from masters.models import SlotMaster  # Use SlotMaster instead of TimeSlot


@require_http_methods(["GET", "POST"])
def therapy_entry_view(request):
    patient_reg_no = request.session.get('patient_reg_no')
    if not patient_reg_no:
        return redirect('patient:patient_lookup')

    patient = get_object_or_404(Registration.objects.using('therapy_db'), pat_reg_no=patient_reg_no)
    all_therapy_items = ItemMaster.objects.using('therapy_db').all()

    if request.method == 'POST':
        try:
            incoming = json.loads(request.body.decode('utf-8'))
        except json.JSONDecodeError:
            return JsonResponse({'status': 'error', 'message': 'Invalid JSON data.'}, status=400)

        therapy_data = incoming.get('therapy_data', [])
        sanitized = []
        warnings = []

        for idx, row in enumerate(therapy_data):
            # read fields safely
            therapy_name = row.get('therapy_name') or row.get('therapy_code') or ''
            ext_int = row.get('ext_int') or ''
            from_date_raw = row.get('from_date')
            to_date_raw = row.get('to_date')
            days = row.get('days')
            slot_value = row.get('slot')  # expected "HH:MM" string (or empty)

            # normalize dates (store ISO or None)
            from_date_iso = None
            to_date_iso = None
            try:
                if from_date_raw:
                    d = datetime.strptime(from_date_raw, "%Y-%m-%d").date()
                    from_date_iso = d.isoformat()
                if to_date_raw:
                    d2 = datetime.strptime(to_date_raw, "%Y-%m-%d").date()
                    to_date_iso = d2.isoformat()
            except Exception as e:
                warnings.append(f"Row {idx+1}: invalid from/to date format ({e}).")

            # resolve timeslot if provided
            time_slot_id = None
            time_slot_found = None
            if slot_value:
                try:
                    parsed_time = datetime.strptime(slot_value.strip(), "%H:%M").time()
                    # try to find SlotMaster row with matching slot_time
                    time_slot_found = SlotMaster.objects.filter(slot_time=parsed_time, is_active=True).first()
                    if time_slot_found:
                        time_slot_id = getattr(time_slot_found, 'slot_number', None) or getattr(time_slot_found, 'pk', None)
                    else:
                        warnings.append(f"Row {idx+1}: slot '{slot_value}' not found in SlotMaster table.")
                except Exception:
                    warnings.append(f"Row {idx+1}: slot '{slot_value}' has invalid format; expected HH:MM.")

            # keep items as-is (you may want deeper validation later)
            items = row.get('items', [])

            sanitized_row = {
                'therapy_name': therapy_name,
                'ext_int': ext_int,
                'from_date': from_date_iso,
                'to_date': to_date_iso,
                'days': days,
                'slot_value': slot_value or '',
                'time_slot_id': time_slot_id,   # can be None if unresolved
                'items': items
            }
            sanitized.append(sanitized_row)

        # Save sanitized structure to session
        request.session['therapy_rows_data'] = sanitized
        request.session.modified = True

        response = {'status': 'success', 'rows_saved': len(sanitized)}
        if warnings:
            response['warnings'] = warnings

        return JsonResponse(response, status=200)

    # GET - render page
    context = {
        'patient': patient,
        'all_therapy_items': all_therapy_items,
    }
    return render(request, 'dashboards/prescriptions/therapy_entry.html', context)


from .models import TherapyDetails
from masters.models import TherapyMaster

def search_therapies_api(request):
    query = request.GET.get('q', '')
    patient_type = (request.GET.get('patient_type') or '').strip().upper()  # Get patient type (IP or OP)
    
    # Use TherapyMaster if available, otherwise fall back to TherapyDetails
    try:
        if TherapyMaster is not None:
            qs = TherapyMaster.objects.filter(is_active=True)
            
            # Filter by patient type based on requirements:
            # - For IP patients: Show only IP treatments
            # - For OP patients: Show both OP and IP treatments
            if patient_type == 'IP':
                # IP patients: Only IP treatments
                qs = qs.filter(patient_type='IP')
            elif patient_type == 'OP':
                # OP patients: Both OP and IP treatments
                qs = qs.filter(Q(patient_type='OP') | Q(patient_type='IP'))
            # If patient_type is not provided or empty, show all (backward compatibility)
            
            if query:
                qs = qs.filter(Q(therapy_name__icontains=query) | Q(therapy_code__icontains=query))
            
            therapies = qs.values('therapy_code', 'therapy_name')[:10]
            return JsonResponse(list(therapies), safe=False)
    except Exception as e:
        print(f"Error using TherapyMaster: {e}")
    
    # Fallback to TherapyDetails if TherapyMaster fails
    if query:
        therapies = TherapyDetails.objects.filter(
            therapy_name__icontains=query
        ).values('therapy_code', 'therapy_name')[:10]
        return JsonResponse(list(therapies), safe=False)
    return JsonResponse([], safe=False)

# The updated prescription_entry_view
# In yourappname/views.py

DB_ALIAS = 'therapy_db'  # change if your write DB alias is different


def parse_date_safe(d):
    if not d:
        return None
    if isinstance(d, str):
        try:
            return datetime.strptime(d, '%Y-%m-%d').date()
        except Exception:
            return None
    return d


def prescription_entry_view(request):
    # Redirect to the new comprehensive prescription entry
    return redirect('prescription_entry')


# views.py (where your review_view lives)
from datetime import datetime
from django.shortcuts import get_object_or_404, redirect, render
from django.conf import settings

DB_ALIAS = getattr(settings, 'DB_ALIAS', 'therapy_db')  # if you use a constant, keep that

# Removed review_view - template deleted (not in navigation)
# def review_view(request):
#     ...


DEFAULT_DB = 'default'
def parse_date_safe(s):
    """Use your existing parse helper or a simple safe wrapper."""
    if not s:
        return None
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except Exception:
        return None

def submit_all_data(request):
    patient_reg_no = request.session.get('patient_reg_no')
    if not patient_reg_no:
        return redirect('patient:patient_lookup')

    # load patient from the external DB alias you already use
    patient = get_object_or_404(Registration.objects.using(DB_ALIAS), pat_reg_no=patient_reg_no)

    from_date_str = request.session.get('from_date')
    to_date_str = request.session.get('to_date')
    record = Repeated_Visitors.objects.using(DEFAULT_DB).filter(register_number=patient_reg_no).first()
    repeated_status = "Yes" if record and getattr(record, 'total_visits', 0) > 2 else "No"

    from_date = parse_date_safe(from_date_str)
    to_date = parse_date_safe(to_date_str)

    therapy_rows_data = request.session.get('therapy_rows_data', []) or []
    prescription_rows_data = request.session.get('prescription_rows_data', []) or []

    # Atomic writes on therapy DB
    with transaction.atomic(using=DEFAULT_DB):
        visit = Visit.objects.using(DEFAULT_DB).create(
            patient_id=int(patient_reg_no),
            patient_name=patient.pat_name,
            from_date=from_date,
            to_date=to_date,
            admission_days=request.session.get('admission_days'),
            is_ip_or_op=request.session.get('is_ip_or_op'),
            repeated_status=repeated_status,
        )

        # Therapies + items
        for row in therapy_rows_data:
            therapy_from_date = parse_date_safe(row.get('from_date')) or from_date
            therapy_to_date = parse_date_safe(row.get('to_date')) or to_date
            therapy_days = int(row.get('days') or ((therapy_to_date - therapy_from_date).days + 1) if therapy_from_date and therapy_to_date else 0)

            # -------------------------
            # Resolve preferred TimeSlot
            # -------------------------
            preferred_ts_obj = None
            preferred_slot_text = ''

            # 1) Prefer explicit id from frontend (could be slot_number)
            ts_id = row.get('time_slot_id') or row.get('preferred_time_slot_id')
            if ts_id:
                try:
                    from masters.models import SlotMaster
                    # Try matching slot_number first (SlotMaster uses slot_number)
                    preferred_ts_obj = SlotMaster.objects.filter(slot_number=ts_id, is_active=True).first()
                    if not preferred_ts_obj:
                        preferred_ts_obj = SlotMaster.objects.filter(pk=ts_id, is_active=True).first()
                except Exception:
                    preferred_ts_obj = None

            # 2) Fallback: try parse text like "06:30"
            if not preferred_ts_obj:
                sv = (row.get('slot_value') or row.get('slot') or row.get('preferred_time_slot_value') or '').strip()
                if sv:
                    preferred_slot_text = sv
                    try:
                        parsed_time = datetime.strptime(sv, "%H:%M").time()
                        from masters.models import SlotMaster
                        preferred_ts_obj = SlotMaster.objects.filter(slot_time=parsed_time, is_active=True).first()
                    except Exception:
                        preferred_ts_obj = None

            # 3) If we found an object, ensure we also have text form for debugging
            if not preferred_slot_text and preferred_ts_obj:
                try:
                    preferred_slot_text = preferred_ts_obj.slot_time.strftime("%H:%M")
                except Exception:
                    preferred_slot_text = ''

            # Prepare preferred_time_slot_id (slot_number PK) for assignment
            preferred_ts_pk = None
            if preferred_ts_obj:
                # TimeSlot uses slot_number as primary key in your model
                preferred_ts_pk = getattr(preferred_ts_obj, 'slot_number', None) or getattr(preferred_ts_obj, 'pk', None)

            # -------------------------
            # Create the store_Therapy row
            # -------------------------
            therapy_kwargs = {
                'visit': visit,
                'patient_id': int(patient_reg_no),
                'therapy_name': row.get('therapy_name'),
                'ext_int': row.get('ext_int') or '',
                'procured': row.get('procured') or '',
                'from_date': therapy_from_date,
                'to_date': therapy_to_date,
                'days': therapy_days,
                # save text fallback
                'preferred_time_slot_value': preferred_slot_text[:8] if preferred_slot_text else ''
            }

            # Assign FK by id to avoid instance/class mismatch issues.
            if preferred_ts_pk is not None:
                therapy_kwargs['preferred_time_slot_id'] = preferred_ts_pk

            therapy = store_Therapy.objects.using(DEFAULT_DB).create(**therapy_kwargs)

            # -------------------------
            # Create associated therapy items
            # -------------------------
            items_payload = row.get('items') or []
            items_to_create = []
            for it in items_payload:
                item_code = it.get('item_code') or it.get('item')
                if not item_code:
                    continue
                items_to_create.append(store_TherapyItem(
                    therapy=therapy,
                    item_code=item_code,
                    oil_class=it.get('oil_class') or '',
                    usage=it.get('usage') or '',
                    procured=it.get('procured') or therapy.procured or '',
                    from_date=therapy_from_date,
                    to_date=therapy_to_date,
                    days=therapy_days
                ))
            if items_to_create:
                store_TherapyItem.objects.using(DEFAULT_DB).bulk_create(items_to_create)

        # Prescriptions + items
        if prescription_rows_data:
            prescription = store_Prescription.objects.using(DEFAULT_DB).create(
                visit=visit,
                patient_id=int(patient_reg_no)
            )
            pres_items = []
            for row in prescription_rows_data:
                item_code = row.get('item') or row.get('item_code')
                if not item_code:
                    continue
                from_d = parse_date_safe(row.get('from_date'))
                to_d = parse_date_safe(row.get('to_date'))
                days = int(row.get('days') or ( (to_d - from_d).days + 1 if from_d and to_d else 0 ))
                pres_items.append(store_PrescriptionItem(
                    prescription=prescription,
                    item_code=item_code,
                    dosage=row.get('dosage') or '',
                    usage=row.get('usage') or '',
                    internal_external=row.get('internal_external') or '',
                    time=row.get('time') or '',
                    item_uom=row.get('item_uom') or '',
                    from_date=from_d,
                    to_date=to_d,
                    days=days,
                    procured_from=row.get('procured_from') or ''
                ))
            if pres_items:
                store_PrescriptionItem.objects.using(DEFAULT_DB).bulk_create(pres_items)

    # Run allocation outside transaction (may be long-running).
    # expand_therapies_for_visit should read store_Therapy.preferred_time_slot / preferred_time_slot_value
    allocation_tasks = []
    try:
        # expand_therapies_for_visit returns the list of tasks we discussed
        allocation_tasks = expand_therapies_for_visit(visit.id)
    except Exception as e:
        # log for debugging and create a failure summary entry
        logger.exception("Allocation failed for visit %s: %s", getattr(visit, 'id', None), str(e))
        allocation_tasks = [{
            "date": None,
            "therapy_name": "Allocation run failed",
            "slot": None,
            "status": "FAILED",
            "reason": str(e),
            "room_no": None,
            "therapists": []
        }]

    # store the tasks in session so the next page can show them
    request.session['allocation_tasks'] = allocation_tasks

    # Clear other session keys you previously cleared
    for key in ['patient_reg_no', 'from_date', 'to_date', 'admission_days', 'is_ip_or_op', 'therapy_rows_data', 'prescription_rows_data']:
        request.session.pop(key, None)

    # Redirect the doctor to an allocation-result page
    return redirect(reverse('patient:allocation_result'))

from Patient.models import AllocationAttempt
def _friendly_slot_label(slot_value):
    """
    slot_value expected as "HH:MM" (string) or None.
    Returns "H:MM AM/PM" or empty string.
    """
    if not slot_value:
        return ''
    try:
        dt = datetime.strptime(slot_value, "%H:%M")
        label = dt.strftime("%I:%M %p")
        # remove leading zero e.g. "08:30 AM" -> "8:30 AM"
        if label.startswith("0"):
            label = label[1:]
        return label
    except Exception:
        return slot_value

def allocation_result_view(request):
    visit_id = request.session.get('last_visit_id')

    tasks = []

    if visit_id:
        # try DB-backed AllocationAttempt first
        try:
            visit_id_int = int(visit_id)
        except Exception:
            visit_id_int = None

        if visit_id_int:
            attempts = AllocationAttempt.objects.filter(visit_id=visit_id_int).order_by('date')
            for a in attempts:
                extra = a.extra or {}
                slot_value = getattr(a, 'requested_time_slot_value', '') or ''
                slot_label = _friendly_slot_label(slot_value)
                tasks.append({
                    'date': a.date.isoformat() if a.date else None,
                    'therapy_name': getattr(a.therapy, 'therapy_name', a.therapy_name),
                    'slot': slot_value,
                    'slot_label': slot_label,
                    'status': a.status,
                    'reason': a.reason,
                    'room_no': extra.get('room_no') if isinstance(extra, dict) else None,
                    'therapists': extra.get('therapists') if isinstance(extra, dict) else []
                })
        else:
            # fallback to session stored tasks if visit_id cannot be parsed
            sess_tasks = request.session.pop('allocation_tasks', []) or []
            for t in sess_tasks:
                slot_value = t.get('slot') or t.get('requested_time_slot_value') or ''
                slot_label = _friendly_slot_label(slot_value)
                tasks.append({
                    'date': t.get('date'),
                    'therapy_name': t.get('therapy_name'),
                    'slot': slot_value,
                    'slot_label': slot_label,
                    'status': t.get('status'),
                    'reason': t.get('reason'),
                    'room_no': t.get('room_no'),
                    'therapists': t.get('therapists') or []
                })
    else:
        # no visit_id: use session fallback
        sess_tasks = request.session.pop('allocation_tasks', []) or []
        for t in sess_tasks:
            slot_value = t.get('slot') or t.get('requested_time_slot_value') or ''
            slot_label = _friendly_slot_label(slot_value)
            tasks.append({
                'date': t.get('date'),
                'therapy_name': t.get('therapy_name'),
                'slot': slot_value,
                'slot_label': slot_label,
                'status': t.get('status'),
                'reason': t.get('reason'),
                'room_no': t.get('room_no'),
                'therapists': t.get('therapists') or []
            })

    # summary counts
    success_count = sum(1 for t in tasks if (t.get('status') or '').upper() in ('BOOKED','SUCCESS'))
    failed_count  = sum(1 for t in tasks if (t.get('status') or '').upper() in ('FAILED','PARTIAL'))

    context = {
        'tasks': tasks,
        'success_count': success_count,
        'failed_count': failed_count,
    }
    return render(request, 'dashboards/doctorsAndHelpDesk/allocation_result.html', context)


# API for autofill data
def get_item_details(request):
    item_code = request.GET.get('item_code')
    try:
        item = ItemMaster.objects.using('therapy_db').get(item_code=item_code)
        data = {
            'item_uom': item.item_uom,
            'procured_from': item.item_procurred_from,
        }
        return JsonResponse(data)
    except ItemMaster.DoesNotExist:
        return JsonResponse({}, status=404)
    



from django.shortcuts import render, redirect
from django.contrib import messages
from django.contrib.auth.decorators import login_required

#######cancellation logic


from django.views.generic import ListView, TemplateView
from django.shortcuts import get_object_or_404
from django.db.models import Q
from django.utils import timezone
from MySql_Data_pull.models import Visit  # adjust path if needed
from .models import RoomBooking, TherapistBooking
from MySql_Data_pull.models import store_Therapy, store_TherapyItem, store_PrescriptionItem

# Removed PatientListView - Treatment Schedule page not needed
# class PatientListView(ListView):
#     model = Visit
#     template_name = "dashboards/prescriptions/patient_list.html"
#     context_object_name = "visits"
#     paginate_by = 25
# 
#     def get_queryset(self):
#         # Gather active bookings (status='BOOKED')
#         room_qs = RoomBooking.objects.filter(status='BOOKED')
#         therapist_qs = TherapistBooking.objects.filter(status='BOOKED')
# 
#         patient_ids_from_bookings = set(
#             list(room_qs.values_list('patient_id', flat=True)) +
#             list(therapist_qs.values_list('patient_id', flat=True))
#         )
#         patient_ids_from_bookings = {p for p in patient_ids_from_bookings if p is not None and p != ""}
# 
#         visit_ids_from_bookings = set(
#             list(room_qs.exclude(visit__isnull=True).values_list('visit__id', flat=True)) +
#             list(therapist_qs.exclude(visit__isnull=True).values_list('visit__id', flat=True))
#         )
# 
#         queries = Q()
#         if visit_ids_from_bookings:
#             queries |= Q(id__in=list(visit_ids_from_bookings))
#         if patient_ids_from_bookings and hasattr(Visit, 'patient_id'):
#             queries |= Q(patient_id__in=list(patient_ids_from_bookings))
# 
#         if queries:
#             qs = Visit.objects.filter(queries).distinct().order_by('-id')
#         else:
#             qs = Visit.objects.none()
#         return qs
    

from collections import defaultdict
class PatientSessionsView(TemplateView):
    template_name = "dashboards/prescriptions/patient_sessions.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        visit_id = self.kwargs.get('visit_id')
        visit = get_object_or_404(Visit, id=visit_id)

        # Query active bookings
        room_qs = RoomBooking.objects.filter(
            Q(patient_id=visit.patient_id) | Q(visit=visit),
            status='BOOKED'
        ).select_related('room', 'time_slot', 'therapy').order_by('date', 'time_slot__slot_number')

        therapist_qs = TherapistBooking.objects.filter(
            Q(patient_id=visit.patient_id) | Q(visit=visit),
            status='BOOKED'
        ).select_related('therapist', 'time_slot', 'therapy').order_by('date', 'time_slot__slot_number')

        # Helper to resolve a matching store_Therapy object for a booking
        def find_therapy(booking):
            if getattr(booking, 'therapy', None):
                return booking.therapy
            name = getattr(booking, 'therapy_name', None)
            if not name:
                return None
            return store_Therapy.objects.filter(
                visit=visit,
                therapy_name__iexact=name,
                from_date__lte=booking.date,
                to_date__gte=booking.date
            ).first()

        # Detect if therapy/prescription item models have an 'item' FK
        TherapyItemModel = None
        PrescriptionItemModel = None
        try:
            # get the model class for related items from store_Therapy (related_name 'items')
            TherapyItemModel = store_Therapy.items.field.remote_field.model if hasattr(store_Therapy, 'items') else None
        except Exception:
            # fallback: try to access via the related manager of an instance if needed
            TherapyItemModel = None

        try:
            PrescriptionItemModel = store_PrescriptionItem
        except Exception:
            PrescriptionItemModel = None

        def model_has_field(model_cls, field_name):
            if model_cls is None:
                return False
            try:
                return field_name in {f.name for f in model_cls._meta.get_fields()}
            except Exception:
                return False

        therapy_item_has_item_fk = model_has_field(TherapyItemModel, 'item')
        prescription_item_has_item_fk = model_has_field(PrescriptionItemModel, 'item')

        # Group sessions by (date, time_slot, therapy_name)
        grouped = defaultdict(lambda: {
            "date": None,
            "time_slot_display": "",
            "therapy_name": "",
            "room_no": None,
            "therapists": set(),
            "therapy_items": set(),            # store item names/codes
            "room_booking_ids": set(),
            "therapist_booking_ids": set(),
        })

        # Add room bookings (collect booking ids and therapy items)
        for rb in room_qs:
            th = find_therapy(rb)
            key = (rb.date, rb.time_slot_id, (th.therapy_name if th else rb.therapy_name))
            g = grouped[key]
            g["date"] = rb.date
            g["time_slot_display"] = str(rb.time_slot) if rb.time_slot else ""
            g["therapy_name"] = (th.therapy_name if th else rb.therapy_name) or ""
            g["room_no"] = getattr(rb.room, "room_no", g["room_no"]) or g["room_no"]
            g["room_booking_ids"].add(rb.id)

            # collect therapy items via therapy FK if present
            if th:
                if therapy_item_has_item_fk:
                    items_qs = th.items.select_related('item').all()
                else:
                    items_qs = th.items.all()
                for it in items_qs:
                    # prefer item name from FK if available
                    name = None
                    if therapy_item_has_item_fk and getattr(it, 'item', None):
                        name = getattr(it.item, 'item_name', None)
                    if not name:
                        name = getattr(it, 'item_code', None) or getattr(it, 'item_id', None)
                    if name:
                        g["therapy_items"].add(str(name))

        # Add therapist bookings (collect booking ids, therapists, items)
        for tb in therapist_qs:
            th = find_therapy(tb)
            key = (tb.date, tb.time_slot_id, (th.therapy_name if th else tb.therapy_name))
            g = grouped[key]
            g["date"] = tb.date
            g["time_slot_display"] = str(tb.time_slot) if tb.time_slot else ""
            g["therapy_name"] = (th.therapy_name if th else tb.therapy_name) or ""
            if getattr(tb, 'therapist', None):
                g["therapists"].add(getattr(tb.therapist, 'therapist_name', '') or '')
            g["therapist_booking_ids"].add(tb.id)

            if th:
                if therapy_item_has_item_fk:
                    items_qs = th.items.select_related('item').all()
                else:
                    items_qs = th.items.all()
                for it in items_qs:
                    name = None
                    if therapy_item_has_item_fk and getattr(it, 'item', None):
                        name = getattr(it.item, 'item_name', None)
                    if not name:
                        name = getattr(it, 'item_code', None) or getattr(it, 'item_id', None)
                    if name:
                        g["therapy_items"].add(str(name))

        # Turn grouped dict into sorted list for template
        sessions = []
        for g in grouped.values():
            therapists_str = ", ".join(sorted([t for t in g["therapists"] if t])) if g["therapists"] else "—"
            items_str = ", ".join(sorted(g["therapy_items"])) if g["therapy_items"] else "—"
            sessions.append({
                "date": g["date"],
                "time_slot_display": g["time_slot_display"],
                "therapy_name": g["therapy_name"],
                "room_no": g["room_no"] or "—",
                "therapists": therapists_str,
                "therapy_items_text": items_str,
                # pass booking id lists to template (convert sets -> lists)
                "room_booking_ids": list(g["room_booking_ids"]),
                "therapist_booking_ids": list(g["therapist_booking_ids"]),
                "booking_ids": list(g["room_booking_ids"] | g["therapist_booking_ids"]),
            })

        # Sort sessions by date then timeslot display
        sessions.sort(key=lambda s: (s["date"], s["time_slot_display"]))

        # Prescriptions + items (use select_related('item') only if that FK exists)
        if prescription_item_has_item_fk:
            prescription_items = store_PrescriptionItem.objects.filter(
                prescription__visit=visit
            ).select_related('item').order_by('from_date')
            prescriptions = store_Prescription.objects.filter(visit=visit).prefetch_related('items__item')
        else:
            prescription_items = store_PrescriptionItem.objects.filter(
                prescription__visit=visit
            ).order_by('from_date')
            prescriptions = store_Prescription.objects.filter(visit=visit).prefetch_related('items')

        # include therapies_for_visit with their items (no heavy select_related here)
        therapies_for_visit = store_Therapy.objects.filter(visit=visit).prefetch_related('items')

        ctx.update({
            "visit": visit,
            "sessions": sessions,
            "prescriptions": prescriptions,
            "prescription_items": prescription_items,
            "therapies_for_visit": therapies_for_visit,
        })
        return ctx
    


# =====================================================
# Booking actions (cancel / complete)
# =====================================================
from django.urls import reverse
from django.contrib import messages
from django.views.decorators.http import require_POST

@login_required
@require_POST
def cancel_session_bookings(request):
    """
    Cancel all booking ids sent in POST. Expects one or more 'booking_ids' fields.
    Example POST payload: booking_ids=12&booking_ids=13
    """
    from .models import RoomBooking, TherapistBooking

    ids = request.POST.getlist("booking_ids")
    if not ids:
        messages.error(request, "No bookings selected to cancel.")
        return redirect(request.META.get("HTTP_REFERER", reverse("patient:home")))

    canceled = 0
    errors = []
    with transaction.atomic():
        for bid in ids:
            try:
                # try RoomBooking first
                try:
                    b = RoomBooking.objects.get(id=bid)
                except RoomBooking.DoesNotExist:
                    b = TherapistBooking.objects.get(id=bid)
                # call the model's cancel method which cascades
                b.cancel(by_user=request.user, reason="Cancelled from sessions UI", cascade=True)
                canceled += 1
            except Exception as e:
                errors.append(f"{bid}: {e}")

    if canceled:
        messages.success(request, f"Cancelled {canceled} booking(s).")
    if errors:
        messages.error(request, "Some errors occurred: " + "; ".join(errors))

    return redirect(request.META.get("HTTP_REFERER", reverse("patient:patient_list")))


# Complete multiple bookings
@login_required
@require_POST
def complete_session_bookings(request):
    """
    Mark provided booking_ids as COMPLETED.
    """
    from .models import RoomBooking, TherapistBooking

    ids = request.POST.getlist("booking_ids")
    if not ids:
        messages.error(request, "No bookings selected to complete.")
        return redirect(request.META.get("HTTP_REFERER", reverse("patient:home")))

    completed = 0
    errors = []
    with transaction.atomic():
        for bid in ids:
            try:
                try:
                    b = RoomBooking.objects.get(id=bid)
                except RoomBooking.DoesNotExist:
                    b = TherapistBooking.objects.get(id=bid)
                b.status = "COMPLETED"
                b.updated_at = timezone.now()
                b.save(update_fields=["status", "updated_at"])
                completed += 1
            except Exception as e:
                errors.append(f"{bid}: {e}")

    if completed:
        messages.success(request, f"Marked {completed} booking(s) as completed.")
    if errors:
        messages.error(request, "Some errors occurred: " + "; ".join(errors))

    return redirect(request.META.get("HTTP_REFERER", reverse("patient:patient_list")))


# =====================================================
# Therapy item actions (update / cancel)
# =====================================================
############## Therapy item update/cancel/add/send-to-procurement ##############

from django.shortcuts import get_object_or_404, redirect, render
from django.contrib import messages
from django.utils import timezone
from django.views.decorators.http import require_POST
from django.contrib.auth.decorators import login_required
from datetime import datetime
from MySql_Data_pull.models import store_TherapyItem, store_TherapyItemDay

@login_required
def update_therapy_item(request, item_id):
    item = get_object_or_404(store_TherapyItem, id=item_id)

    if request.method == "POST":
        usage = request.POST.get("usage", item.usage)
        procured = request.POST.get("procured", item.procured)

        from_date_str = request.POST.get("from_date")
        to_date_str = request.POST.get("to_date")
        days_str = request.POST.get("days")

        # parse safely
        def parse_date_safe(s):
            try:
                return datetime.strptime(s, "%Y-%m-%d").date() if s else None
            except Exception:
                return None

        new_from_date = parse_date_safe(from_date_str) or item.from_date
        new_to_date = parse_date_safe(to_date_str) or item.to_date

        try:
            new_days = int(days_str) if days_str not in (None, "") else item.days
        except ValueError:
            new_days = item.days

        # track old range for cleanup
        old_from, old_to = item.from_date, item.to_date

        # update parent item
        item.usage = usage
        item.procured = procured
        item.from_date = new_from_date
        item.to_date = new_to_date
        item.days = new_days
        item.updated_at = timezone.now()
        item.save()

        # ---- update the day rows ----
        # 1. cancel days that are no longer in the range
        obsolete_days = store_TherapyItemDay.objects.filter(
            therapy_item=item,
            date__lt=new_from_date
        ) | store_TherapyItemDay.objects.filter(
            therapy_item=item,
            date__gt=new_to_date
        )
        for day in obsolete_days:
            day.status = "cancelled"
            day.cancelled_by = request.user
            day.cancelled_at = timezone.now()
            day.save(update_fields=["status", "cancelled_by", "cancelled_at", "updated_at"])

        # 2. add missing days (if extended range)
        store_TherapyItemDay.expand_for_item(item)

        messages.success(request, "Therapy item and day schedule updated successfully.")
        return redirect(request.META.get("HTTP_REFERER", reverse("patient:home")))

    return render(request, "dashboards/prescriptions/update_therapy_item.html", {"item": item})



@login_required
@require_POST
def cancel_therapy_item(request, item_id):
    from MySql_Data_pull.models import store_TherapyItem
    item = get_object_or_404(store_TherapyItem, id=item_id)
    if item.status == "cancelled":
        messages.info(request, "Therapy item already cancelled.")
    else:
        item.cancel(by_user=request.user)
        messages.success(request, "Therapy item cancelled.")
    return redirect(request.META.get("HTTP_REFERER", reverse("patient:patient_list")))








######### Prescription item update/cancel/add/send-to-procurement ###########

@login_required
def update_prescription_item(request, item_id):
    from MySql_Data_pull.models import store_PrescriptionItem
    item = get_object_or_404(store_PrescriptionItem, id=item_id)

    if request.method == "POST":
        item.dosage = request.POST.get("dosage", item.dosage)
        item.usage = request.POST.get("usage", item.usage)
        from_date = request.POST.get("from_date", None)
        to_date = request.POST.get("to_date", None)
        if from_date:
            item.from_date = from_date
        if to_date:
            item.to_date = to_date
        item.time = request.POST.get("time", item.time)
        item.item_uom = request.POST.get("item_uom", item.item_uom)
        new_status = request.POST.get("status", item.status)
        if new_status in dict(item.STATUS_CHOICES).keys():
            item.status = new_status
        item.updated_at = timezone.now()
        item.save(update_fields=["dosage", "usage", "from_date", "to_date", "time", "item_uom", "status", "updated_at"])
        messages.success(request, "Prescription item updated.")
        return redirect(request.META.get("HTTP_REFERER", reverse("patient:home")))

    return render(request, "dashboards/prescriptions/update_prescription_item.html", {"item": item})


@login_required
@require_POST
def cancel_prescription_item(request, item_id):
    from MySql_Data_pull.models import store_PrescriptionItem
    item = get_object_or_404(store_PrescriptionItem, id=item_id)
    if item.status == "cancelled":
        messages.info(request, "Prescription item already cancelled.")
    else:
        item.cancel(by_user=request.user)
        messages.success(request, "Prescription item cancelled.")
    return redirect(request.META.get("HTTP_REFERER", reverse("patient:patient_list")))


from django.shortcuts import render, get_object_or_404, redirect
from django.contrib import messages
from django.views.decorators.http import require_http_methods
from django.contrib.auth.decorators import login_required
from django.urls import reverse

# adjust these imports to your actual app/module paths
from MySql_Data_pull.models import store_Prescription, store_PrescriptionItem

@login_required
@require_http_methods(["GET", "POST"])
def add_prescription_item(request, prescription_id):
    """
    Add a new store_PrescriptionItem for a given store_Prescription.
    Auto-fills item_uom / procured_from / any ItemMaster attributes when item selected.
    Defaults from/to/days to prescription.visit.from_date/to_date if visit exists.
    """
    prescription = get_object_or_404(store_Prescription, id=prescription_id)
    visit = getattr(prescription, 'visit', None)

    # ----- INACTIVE PATIENT GUARD -----
    # If the patient's pat_status is 'N' (inactive/discharged), block all access.
    try:
        from final_allocation import is_patient_active
        _pat_id = getattr(visit, 'patient_id', None) if visit else None
        if _pat_id and not is_patient_active(_pat_id):
            messages.error(
                request,
                "This patient is inactive or has been discharged. "
                "Adding prescription items is not allowed."
            )
            return redirect(request.META.get('HTTP_REFERER', '/'))
    except Exception:
        pass  # fail-open: do not block if check itself errors

    # default dates from visit (if present)
    default_from = getattr(visit, 'from_date', None)
    default_to = getattr(visit, 'to_date', None)
    default_days = None
    if default_from and default_to:
        try:
            default_days = (default_to - default_from).days + 1
        except Exception:
            default_days = None

    all_items = ItemMaster.objects.using('therapy_db').all().order_by('item_name')

    if request.method == "POST":
        item_code = request.POST.get('item_code') or ''
        dosage = request.POST.get('dosage') or ''
        usage = request.POST.get('usage') or ''
        internal_external = request.POST.get('internal_external') or ''
        time = request.POST.get('time') or ''
        item_uom = request.POST.get('item_uom') or ''
        procured_from = request.POST.get('procured_from') or all_items.item_procurred_from or ''

        # allow overriding dates in the form, but default to visit dates
        from_date = request.POST.get('from_date') or (default_from.isoformat() if default_from else None)
        to_date = request.POST.get('to_date') or (default_to.isoformat() if default_to else None)
        days = request.POST.get('days')
        if not days:
            if default_days is not None:
                days = default_days
            else:
                days = 0
        try:
            days = int(days)
        except Exception:
            days = 0

        if not item_code:
            messages.error(request, "Please select an item.")
            return redirect(request.path)

        pi = store_PrescriptionItem.objects.create(
            prescription=prescription,
            item_code=item_code,
            dosage=dosage,
            usage=usage,
            internal_external=internal_external,
            time=time,
            item_uom=item_uom,
            procured_from=procured_from,
            from_date=from_date or None,
            to_date=to_date or None,
            days=days,
            status='active'
        )
        messages.success(request, f"Added prescription item {pi.item_code}.")
        # redirect back (referer) or to visit sessions view
        referer = request.META.get('HTTP_REFERER')
        if referer:
            return redirect(referer)
        # fallback: redirect to visit sessions (if visit exists)
        if visit:
            try:
                return redirect(reverse('patient:patient_sessions', kwargs={'visit_id': visit.id}))
            except Exception:
                pass
        return redirect('/')

    context = {
        'prescription': prescription,
        'procured_from':'procured_from',
        'visit': visit,
        'all_items': all_items,
        'default_from': default_from,
        'default_to': default_to,
        'default_days': default_days,
    }
    return render(request, 'dashboards/prescriptions/add_prescription_item.html', context)







# views.py (add to the views module that manages patient/therapy pages)

from django.shortcuts import render, get_object_or_404, redirect
from django.urls import reverse
from django.contrib import messages
from django.db import transaction, IntegrityError
from django.contrib.auth.decorators import login_required
from django.utils import timezone
from datetime import datetime

# change these imports if your models live somewhere else
from MySql_Data_pull.models import store_Therapy, store_TherapyItem,ItemMaster 
   # if ItemMaster lives in Patient app; else adjust


# patient/views.py
# views.py
from django.shortcuts import render, get_object_or_404, redirect
from django.urls import reverse
from django.contrib import messages
from django.views.decorators.http import require_http_methods

# adjust these imports to your app modules
from MySql_Data_pull.models import store_Therapy, store_TherapyItem
 # or the app where ItemMaster lives
from datetime import datetime
from django.utils.dateparse import parse_date
from django.shortcuts import render, get_object_or_404, redirect
from django.urls import reverse
from django.contrib import messages
from django.views.decorators.http import require_http_methods
from MySql_Data_pull.models import store_Therapy, store_TherapyItem  # adjust import path
 # adjust import path if ItemMaster lives in different app
from django.contrib.auth.decorators import login_required

@login_required
@require_http_methods(["GET", "POST"])
def add_therapy_item(request, visit_id):
    """
    Add a new store_TherapyItem for a given Visit.
    User selects a therapy (from visit's therapies) and an Item (from ItemMaster).
    from_date/to_date/days are taken from the parent therapy (no custom dates).
    """
    visit = get_object_or_404(Visit, id=visit_id)

    # ----- INACTIVE PATIENT GUARD -----
    # If the patient's pat_status is 'N' (inactive/discharged), block all access.
    try:
        from final_allocation import is_patient_active
        _pat_id = getattr(visit, 'patient_id', None)
        if _pat_id and not is_patient_active(_pat_id):
            messages.error(
                request,
                "This patient is inactive or has been discharged. "
                "Adding therapy items is not allowed."
            )
            return redirect(request.META.get('HTTP_REFERER', '/'))
    except Exception:
        pass  # fail-open: do not block if check itself errors

    # Fetch therapies for this visit
    therapies_for_visit = store_Therapy.objects.filter(visit=visit).order_by("from_date", "therapy_name")

    if not therapies_for_visit.exists():
        messages.error(request, "No therapies found for this visit.")
        return redirect(reverse("patient:patient_sessions", kwargs={"visit_id": visit.id}))

    # fetch item master list for the dropdown (from therapy_db)
    all_items = ItemMaster.objects.using("therapy_db").all().order_by("item_name")

    if request.method == "POST":
        therapy_id = request.POST.get("therapy_id")
        item_code = request.POST.get("item_code")

        if not therapy_id or not item_code:
            messages.error(request, "Please select both therapy and item.")
            return redirect(request.path)

        therapy = get_object_or_404(store_Therapy, id=therapy_id, visit=visit)

        oil_class = request.POST.get("oil_class") or None
        usage = request.POST.get("usage") or None

        # Prefer procured value from posted field; if empty fallback to item master procured_from then therapy.procured
        procured = request.POST.get("procured") or ''
        if not procured:
            # try to set from ItemMaster
            try:
                im = ItemMaster.objects.using("therapy_db").get(item_code=item_code)
                procured = getattr(im,"item_procurred_from", "") or getattr(therapy, "procured", "")
            except ItemMaster.DoesNotExist:
                procured = getattr(therapy, "procured", "")

        # Use therapy dates/days
        from_date = therapy.from_date
        to_date = therapy.to_date
        days = therapy.days
    
        # create the therapy item
        ti = store_TherapyItem.objects.create(
            therapy=therapy,
            item_code=item_code,
            oil_class=oil_class,
            usage=usage,
            procured=procured,
            from_date=from_date,
            to_date=to_date,
            days=days,
            status="active",
        )

        messages.success(
            request,
            f"Added therapy item {ti.item_code} to therapy '{therapy.therapy_name}'.",
        )
        return redirect(reverse("patient:patient_sessions", kwargs={"visit_id": visit.id}))

    # GET: render form
    context = {
        "visit": visit,
        "therapies_for_visit": therapies_for_visit,
        "all_items": all_items,
    }
    return render(request, "dashboards/prescriptions/add_therapy_item.html", context)




# put this in Patient/views.py (replace your old functions)
import logging
from datetime import datetime, timedelta
from django.http import JsonResponse
from django.views.decorators.http import require_GET

logger = logging.getLogger(__name__)

GENERAL_SLOTS = ["06:30","08:30","10:00","11:30","14:30","16:00","17:30"]

def slot_to_time(s):
    return datetime.strptime(s, "%H:%M").time()

def friendly_label(slot_str):
    try:
        dt = datetime.strptime(slot_str, "%H:%M")
        label = dt.strftime("%I:%M %p")
        if label.startswith("0"):
            label = label[1:]
        return label
    except:
        return slot_str

def compute_available_slots_for_date(date_obj, therapy_name, patient_type, therapy_code=None):
    """
    Returns list of {"value":"HH:MM","label":"H:MM AM/PM"} available on date_obj.
    Respects:
      - patient_type OP/IP rules
      - therapy category (hard/special)
      - room availability (if therapy requires room)
      - therapist capacity & leave (uses TherapistBooking and TherapistLeave)
    """
    from .models import TimeSlot, TreatmentRoom, RoomBooking, Therapist, TherapistBooking, TherapistLeave, TherapyDetails
    from reshedule import is_vamanam_treatment, get_vamanam_slots

    is_vam = is_vamanam_treatment(therapy_name, therapy_code)
    vam_slots = get_vamanam_slots()

    if is_vam:
        candidate_slots = list(vam_slots)
    else:
        candidate_slots = [s for s in GENERAL_SLOTS if s not in vam_slots]
        if patient_type == "OP":
            candidate_slots = [s for s in ["11:30", "17:30"] if s not in vam_slots]

    try:
        details = TherapyDetails.objects.get(therapy_name__iexact=therapy_name)
        therapy_category = (getattr(details, "therapy_category", "") or "").lower()
    except TherapyDetails.DoesNotExist:
        details = None
        therapy_category = ""

    if therapy_category in ["hard", "special"]:
        candidate_slots = [s for s in candidate_slots if s not in ["11:30", "17:30"]]

    try:
        from reshedule import is_group_vasthi_0830_only
        if is_group_vasthi_0830_only(therapy_name, therapy_code):
            candidate_slots = [s for s in candidate_slots if s == "08:30"]
            if not candidate_slots:
                candidate_slots = ["08:30"]
    except Exception:
        pass

    def requirements_from_details(det):
        if not det:
            return {"super_senior":0,"senior":0,"junior":0,"trainee":0,"total":0}
        return {
            "super_senior": det.no_of_super_senior_therapist or 0,
            "senior": det.no_of_senior_therapist or 0,
            "junior": det.no_of_junior_therapist or 0,
            "trainee": det.no_of_trainee_therapist or 0,
            "total": det.total_no_of_therapist or 0,
        }

    reqs = requirements_from_details(details)
    needs_room = bool(details and getattr(details, 'treatment_room_required', '').lower() == 'yes')
    needs_bath = bool(details and getattr(details, 'bathing_required', '').lower() == 'yes')

    available = []
    weekday = date_obj.weekday()

    # base queryset and leave set (use FK 'therapist' on TherapistLeave)
    all_therapists_qs = Therapist.objects.all()
    on_leave_ids = TherapistLeave.objects.filter(leave_day=weekday).values_list('therapist', flat=True)

    for slot_str in candidate_slots:
        start_time = slot_to_time(slot_str)

        # Room availability check (if therapy needs a room)
        room_ok = True
        if needs_room:
            from masters.models import SlotMaster
            timeslot_q = SlotMaster.objects.filter(slot_time=start_time, is_active=True).first()
            if timeslot_q:
                # RoomBooking.room is FK named 'room' — values_list('room',flat=True) returns PKs
                booked_room_pks = RoomBooking.objects.filter(date=date_obj, time_slot=timeslot_q, status='BOOKED').values_list('room', flat=True)
                # exclude by pk (works even if TreatmentRoom PK isn't 'id')
                free_room_exists = TreatmentRoom.objects.exclude(pk__in=booked_room_pks).exists()
            else:
                # if timeslot row missing, assume rooms exist (or optionally create timeslot)
                free_room_exists = TreatmentRoom.objects.exists()
            room_ok = free_room_exists

        if not room_ok:
            # no room => slot unavailable
            continue

        # Therapist capacity check
        from masters.models import SlotMaster
        timeslot_q = SlotMaster.objects.filter(slot_time=start_time, is_active=True).first()

        # exclude therapists on leave using pk
        available_therapists = all_therapists_qs.exclude(pk__in=on_leave_ids)

        if timeslot_q:
            # TherapistBooking.therapist is FK named 'therapist' -> values_list('therapist', flat=True) returns PKs
            booked_therapist_pks = TherapistBooking.objects.filter(date=date_obj, time_slot=timeslot_q, status='BOOKED').values_list('therapist', flat=True)
            available_therapists = available_therapists.exclude(pk__in=booked_therapist_pks)

        if needs_bath:
            available_therapists = available_therapists.filter(is_bathing_therapist=True)

        # Check grade counts
        grade_map = {
            "Super Senior Therapist": reqs["super_senior"],
            "Senior Therapist": reqs["senior"],
            "Junior Therapist": reqs["junior"],
            "Trainee Therapist": reqs["trainee"],
        }

        grade_ok = True
        for grade_name, needed_count in grade_map.items():
            if needed_count <= 0:
                continue
            have_count = available_therapists.filter(therapist_grade=grade_name).count()
            if have_count < needed_count:
                grade_ok = False
                break

        if not grade_ok:
            continue

        # passes checks
        available.append({"value": slot_str, "label": friendly_label(slot_str)})

    return available


@require_GET
def available_slots(request):
    """
    Supports:
      - date=YYYY-MM-DD  => {"slots":[...]}
      - from_date=YYYY-MM-DD&to_date=YYYY-MM-DD => {"dates":[{"date":"YYYY-MM-DD","slots":[...]}]}
    Required: therapy_name param
    Optional: patient_type (IP/OP), therapy_code (recommended for Therapy Master lookup; THEB037 exempt from Vasthi-group 08:30 rule)
    """
    therapy_name = request.GET.get("therapy_name", "").strip()
    patient_type = request.GET.get("patient_type", "").strip().upper()
    therapy_code = request.GET.get("therapy_code", "").strip() or None

    if not therapy_name:
        return JsonResponse({"error":"therapy_name is required"}, status=400)

    date_str = request.GET.get("date")
    from_date_str = request.GET.get("from_date")
    to_date_str = request.GET.get("to_date")

    if date_str:
        try:
            date_obj = datetime.strptime(date_str, "%Y-%m-%d").date()
        except Exception:
            return JsonResponse({"error":"invalid date format for 'date', expected YYYY-MM-DD"}, status=400)
        slots = compute_available_slots_for_date(date_obj, therapy_name, patient_type, therapy_code)
        return JsonResponse({"slots": slots})

    if from_date_str:
        try:
            from_date_obj = datetime.strptime(from_date_str, "%Y-%m-%d").date()
        except Exception:
            return JsonResponse({"error":"invalid date format for 'from_date', expected YYYY-MM-DD"}, status=400)
        if to_date_str:
            try:
                to_date_obj = datetime.strptime(to_date_str, "%Y-%m-%d").date()
            except Exception:
                return JsonResponse({"error":"invalid date format for 'to_date', expected YYYY-MM-DD"}, status=400)
        else:
            to_date_obj = from_date_obj

        if from_date_obj > to_date_obj:
            return JsonResponse({"error":"'from_date' must be <= 'to_date'"}, status=400)

        # safety cap
        max_days = 31
        delta_days = (to_date_obj - from_date_obj).days + 1
        if delta_days > max_days:
            return JsonResponse({"error": f"date range too large (max {max_days} days)"}, status=400)

        result_dates = []
        cur = from_date_obj
        while cur <= to_date_obj:
            slots = compute_available_slots_for_date(cur, therapy_name, patient_type, therapy_code)
            result_dates.append({"date": cur.isoformat(), "slots": slots})
            cur = cur + timedelta(days=1)

        return JsonResponse({"dates": result_dates})

    return JsonResponse({"error":"provide either 'date' or 'from_date' (with optional to_date)"}, status=400)


@require_GET
def time_slots(request):
    """
    Return all SlotMaster rows in order:
      { "slots": [ {"slot_number":1, "start_time":"06:30", "label":"6:30 AM", "is_vamanam_slot": false}, ... ] }
    """
    from masters.models import SlotMaster
    from reshedule import is_vamanam_treatment

    therapy_name = request.GET.get('therapy_name', '').strip()
    therapy_code = request.GET.get('therapy_code', '').strip()
    is_vam_param = request.GET.get('is_vamanam')
    filter_type = (request.GET.get('filter_type') or '').strip().lower()

    is_vam = False
    if is_vam_param is not None:
        is_vam = str(is_vam_param).lower() in ('1', 'true', 'yes')
    elif therapy_name or therapy_code:
        is_vam = is_vamanam_treatment(therapy_name, therapy_code)

    qs = SlotMaster.objects.filter(is_active=True).order_by('slot_number')
    if is_vam or filter_type == 'vamanam_only':
        qs = qs.filter(is_vamanam_slot=True)
    elif filter_type == 'regular_only' or request.GET.get('exclude_vamanam', '').lower() in ('1', 'true', 'yes'):
        qs = qs.filter(is_vamanam_slot=False)

    slots = []
    for t in qs:
        st = t.slot_time.strftime("%H:%M")
        label = t.slot_time.strftime("%I:%M %p").lstrip("0")
        slots.append({
            "slot_number": t.slot_number, 
            "start_time": st, 
            "label": label,
            "is_vamanam_slot": getattr(t, 'is_vamanam_slot', False)
        })
    return JsonResponse({"slots": slots})


@require_GET
def unit_numbers(request):
    """
    Return all active UnitNo options from master table:
      { "units": [ {"id": 1, "unit_name": "ml"}, ... ] }
    """
    try:
        units = UnitNo.objects.filter(is_active=True).order_by('unit_name')
        units_list = []
        for unit in units:
            units_list.append({
                "id": unit.id,
                "unit_name": unit.unit_name
            })
        return JsonResponse({"units": units_list})
    except Exception as e:
        print(f"Error fetching unit numbers: {e}")
        return JsonResponse({"units": []}, status=500)