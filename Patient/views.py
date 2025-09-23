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
from MySql_Data_pull.models import Registration, store_Therapy, store_TherapyItem, store_Prescription, store_PrescriptionItem, ItemMaster,Visit
import json
from .models import Repeated_Visitors
from datetime import date, datetime

# Step 1: Patient Lookup
def patient_lookup_view(request):
    if request.method == "POST":
        reg_number = request.POST.get('reg_number')
        from_date_str = request.POST.get('from_date')
        to_date_str = request.POST.get('to_date')

        try:
            patient = Registration.objects.using('therapy_db').get(pat_reg_no=reg_number)
            request.session['patient_reg_no'] = str(patient.pat_reg_no)

            # Store date and days data in the session
            request.session['from_date'] = from_date_str
            request.session['to_date'] = to_date_str
            
            if from_date_str and to_date_str:
                from_date = datetime.strptime(from_date_str, '%Y-%m-%d').date()
                to_date = datetime.strptime(to_date_str, '%Y-%m-%d').date()
                admission_days = (to_date - from_date).days + 1
                request.session['admission_days'] = admission_days
            else:
                request.session['admission_days'] = None
            
            # 🎯 Calculate and store IP/OP status
            request.session['is_ip_or_op'] = 'OP' if len(str(reg_number)) == 5 else 'IP'

            return redirect('therapy_entry')
        except Registration.DoesNotExist:
            error_message = "Registration number not found."
            return render(request, 'patient_lookup.html', {'error': error_message})
    
    return render(request, 'dashboards/doctorsAndHelpDesk/patient_lookup.html')


def search_patients_api(request):
    query = request.GET.get('q', '')
    if query:
        patients = Registration.objects.using('therapy_db').filter(
            Q(pat_reg_no__icontains=query) | Q(pat_name__icontains=query)
        ).values('pat_reg_no', 'pat_name')[:10]
        return JsonResponse(list(patients), safe=False)
    return JsonResponse([], safe=False)

# In yourappname/views.py

def get_patient_details_api(request):
    pat_reg_no = request.GET.get('pat_reg_no')
    try:
        # Step 1: Query the patient details from the live server.
        patient = Registration.objects.using('therapy_db').get(pat_reg_no=pat_reg_no)
        
        # Step 2: Query the VIP status from your local Django database.
        # Your database router will handle this automatically because
        # the `Repeated_Visitors` model is not marked as `managed=False`
        # and doesn't have a `db_table` pointing to the live server.
        vip_status = "Yes" if Repeated_Visitors.objects.filter(register_number=pat_reg_no, is_vip=1).exists() else "No"
        repeated_status = "Yes" if Repeated_Visitors.objects.filter(register_number=pat_reg_no, total_visits__gt=2).exists() else "No"

        
        data = {
    'pat_name': patient.pat_name,
    'pat_age': patient.pat_age,
    'pat_sex': patient.pat_sex,
    'vip_status': vip_status,
    'pat_op_reg_no': patient.pat_op_reg_no,
    'pat_room_no': patient.pat_room_no,
    'pat_ref_id': patient.pat_ref_id,
    'repeated_status': repeated_status,
}
        return JsonResponse(data)
    except Registration.DoesNotExist:
        return JsonResponse({'error': 'Patient with this registration number does not exist.'}, status=404)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)
    





# Step 2: Therapy Entry
def therapy_entry_view(request):
    patient_reg_no = request.session.get('patient_reg_no')
    if not patient_reg_no:
        return redirect('patient_lookup')

    patient = get_object_or_404(Registration.objects.using('therapy_db'), pat_reg_no=patient_reg_no)
    all_therapy_items = ItemMaster.objects.using('therapy_db').all()

    if request.method == 'POST':
        try:
            # Safely load the JSON data sent from the JavaScript fetch request
            therapy_data = json.loads(request.body.decode('utf-8')).get('therapy_data', [])
        except json.JSONDecodeError:
            return JsonResponse({'status': 'error', 'message': 'Invalid JSON data.'}, status=400)

        # Store the collected data in the session for later use
        request.session['therapy_rows_data'] = therapy_data
        
        # Send a success response so the JavaScript knows to redirect
        return JsonResponse({'status': 'success'}, status=200)

    # This is for a GET request (initial page load)
    context = {
        'patient': patient,
        'all_therapy_items': all_therapy_items,
    }
    return render(request, 'dashboards/doctorsAndHelpDesk/therapy_entry.html', context)

from .models import TherapyDetails
def search_therapies_api(request):
    query = request.GET.get('q', '')
    if query:
        therapies = TherapyDetails.objects.filter(
            therapy_name__icontains=query
        ).values('therapy_code', 'therapy_name')[:10]
        return JsonResponse(list(therapies), safe=False)
    return JsonResponse([], safe=False)

# The updated prescription_entry_view
# In yourappname/views.py

def prescription_entry_view(request):
    patient_reg_no = request.session.get('patient_reg_no')
    if not patient_reg_no:
        return redirect('patient_lookup')

    patient = get_object_or_404(Registration.objects.using('therapy_db'), pat_reg_no=patient_reg_no)
    all_prescription_items = ItemMaster.objects.using('therapy_db').all()

    if request.method == 'POST':
        # This view now only handles the final submission
        try:
            data = json.loads(request.body.decode('utf-8'))
            prescription_rows = data.get('prescription_data', [])
            
            # Save the submitted data to the session
            # Note: This is a temporary way to pass data to the review page.
            # You might save to the database here and pass a prescription ID instead.
            request.session['prescription_rows_data'] = prescription_rows

            if prescription_rows:
                # The final submission will happen on the review page
                return JsonResponse({'status': 'success'}, status=200)
            else:
                return JsonResponse({'status': 'error', 'message': 'No prescription data provided.'}, status=400)

        except json.JSONDecodeError:
            return JsonResponse({'status': 'error', 'message': 'Invalid JSON data'}, status=400)
    
    # ... (rest of the GET request logic for the template) ...
    context = {
        'patient': patient,
        'all_prescription_items': all_prescription_items,
    }
    return render(request, 'dashboards/doctorsAndHelpDesk/prescription_entry.html', context)
    
   

# Step 4: Review Page
def review_view(request):
    patient_reg_no = request.session.get('patient_reg_no')
    if not patient_reg_no:
        return redirect('patient_lookup')

    patient = get_object_or_404(Registration.objects.using('therapy_db'), pat_reg_no=patient_reg_no)
    
    try:
        vip_status = "Yes" if Repeated_Visitors.objects.filter(register_number=patient_reg_no, is_vip=1).exists() else "No"
    except Exception:
        vip_status = "N/A"

    from_date = request.session.get('from_date')
    to_date = request.session.get('to_date')
    admission_days = request.session.get('admission_days')
    is_ip_or_op = request.session.get('is_ip_or_op')
    repeated_status = request.session.get('repeated_status')
    therapy_data = request.session.get('therapy_rows_data', [])
    prescription_data = request.session.get('prescription_rows_data', [])
    
    # ... (Your data processing loops are unchanged) ...
    for therapy_row in therapy_data:
        try:
            item_code = therapy_row.get('item')
            if item_code:
                item_master = ItemMaster.objects.using('therapy_db').get(item_code=item_code)
                therapy_row['item_name'] = item_master.item_name
        except ItemMaster.DoesNotExist:
            therapy_row['item_name'] = 'Item not found'

    for prescription_row in prescription_data:
        try:
            item_code = prescription_row.get('item')
            if item_code:
                item_master = ItemMaster.objects.using('therapy_db').get(item_code=item_code)
                prescription_row['item_name'] = item_master.item_name
        except ItemMaster.DoesNotExist:
            prescription_row['item_name'] = 'Item not found'

    context = {
        'patient': patient,
        'vip_status': vip_status,
        'from_date': from_date,
        'to_date': to_date,
        'admission_days': admission_days,
        'is_ip_or_op': is_ip_or_op,
        'therapy_data': therapy_data,
        'prescription_data': prescription_data,
        'repeated_status': repeated_status,
    }
    return render(request, 'dashboards/doctorsAndHelpDesk/review_page.html', context)





# Step 5: Final Submission
def submit_all_data(request):
    patient_reg_no = request.session.get('patient_reg_no')
    if not patient_reg_no:
        return redirect('patient_lookup')
        
    from_date_str = request.session.get('from_date')
    to_date_str = request.session.get('to_date')
    record = Repeated_Visitors.objects.filter(register_number=patient_reg_no).first()
    repeated_status = "Yes" if record and record.total_visits > 2 else "No"
    # Create the new Visit record
    visit = Visit.objects.create(
        patient_id=int(patient_reg_no),
        from_date=datetime.strptime(from_date_str, '%Y-%m-%d').date() if from_date_str else None,
        to_date=datetime.strptime(to_date_str, '%Y-%m-%d').date() if to_date_str else None,
        admission_days=request.session.get('admission_days'),
        is_ip_or_op=request.session.get('is_ip_or_op'),
        repeated_status=repeated_status,
    )

    # Save Therapy Data and link to the Visit record
    therapy_rows_data = request.session.get('therapy_rows_data', [])
    for row in therapy_rows_data:
        therapy = store_Therapy.objects.create(
            visit=visit,
            patient_id=int(patient_reg_no),
            therapy_name=row.get('therapy_name'),
            ext_int=row.get('ext_int'),
            procured=row.get('procured'),
            from_date=row.get('from_date'),
            to_date=row.get('to_date'),
            days=row.get('days')
        )
        store_TherapyItem.objects.create(
            therapy=therapy,
            item_code=row.get('item'),
            oil_class=row.get('oil_class'),
            usage=row.get('usage')
        )

    # Save Prescription Data and link to the Visit record
    prescription_rows_data = request.session.get('prescription_rows_data', [])
    if prescription_rows_data:
        prescription = store_Prescription.objects.create(
            visit=visit,
            patient_id=int(patient_reg_no)
        )
        for row in prescription_rows_data:
            store_PrescriptionItem.objects.create(
                prescription=prescription,
                item_code=row.get('item'),
                dosage=row.get('dosage'),
                usage=row.get('usage'),
                internal_external=row.get('internal_external'),
                time=row.get('time'),
                item_uom=row.get('item_uom')
            )
    
    # Clear all session data after successful submission
    if 'patient_reg_no' in request.session:
        del request.session['patient_reg_no']
    if 'from_date' in request.session:
        del request.session['from_date']
    if 'to_date' in request.session:
        del request.session['to_date']
    if 'admission_days' in request.session:
        del request.session['admission_days']
    if 'is_ip_or_op' in request.session:
        del request.session['is_ip_or_op']
    if 'therapy_rows_data' in request.session:
        del request.session['therapy_rows_data']
    if 'prescription_rows_data' in request.session:
        del request.session['prescription_rows_data']

    return redirect("patient_lookup")


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