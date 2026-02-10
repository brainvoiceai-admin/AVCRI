from django.http import JsonResponse
from django.db.models import Q
from datetime import date, datetime, timedelta
import re
import traceback

def search_patients_by_room_logic(request):
    """API endpoint to search patients by room number with prefix and hyphen-insensitive support"""
    if request.method != 'GET':
        return JsonResponse({'error': 'Only GET method allowed'}, status=405)
    
    room_query = request.GET.get('room', '').strip()
    
    if not room_query:
        return JsonResponse({
            'error': 'Room number required',
            'patients': []
        }, status=400)
    
    print(f"[DEBUG] search_patients_by_room (via util) called - room: '{room_query}'")
    
    try:
        from MySql_Data_pull.models import Registration, OPMaster, Treatment
        from Patient.models import Repeated_Visitors
        from masters.models import get_staying_room_display_number, StayingRoom
        from Sheduling.models import PatientSnapshot, TherapyAllocation, Booking
        
        patients = []
        # Track added registration numbers to prevent duplicates
        added_reg_nos = set()
        
        # Generate search terms for hyphen-insensitivity
        search_terms = {room_query}
        
        # 1. Handle "NR-15" -> "NR15" and "NR15" -> "NR-15"
        if '-' in room_query:
            search_terms.add(room_query.replace('-', ''))
        else:
            # Check if query has letters followed immediately by numbers (e.g., "NR15")
            match = re.match(r'^([a-zA-Z]+)(\d+)$', room_query)
            if match:
                search_terms.add(f"{match.group(1)}-{match.group(2)}")
                search_terms.add(f"{match.group(1)} {match.group(2)}")
                
        print(f"[DEBUG] Search terms: {search_terms}")
        
        today = date.today()
        
        # -------------------------------------------------------------
        # 1. Search in Treatment table (IP Therapy DB)
        # -------------------------------------------------------------
        treatment_patients = []
        try:
            treatment_q = Q()
            for term in search_terms:
                treatment_q |= Q(Pat_Room_No__istartswith=term)
            
            treatment_records = Treatment.objects.using('iptherapy_db').filter(
                treatment_q
            ).filter(
                Q(Pat_DoD__isnull=True) | Q(Pat_DoD__date__gte=today)
            ).filter(
                Q(DOA__isnull=True) | Q(DOA__date__lte=today)
            ).values('Pat_Reg_No', 'Pat_Room_No', 'Pat_Name', 'Pat_Sex', 'Pat_Age', 'DOA', 'Pat_DoD').distinct()[:100]
            
            for treatment in treatment_records:
                reg_no = treatment['Pat_Reg_No']
                treatment_patients.append({
                    'reg_no': reg_no,
                    'room_no': treatment.get('Pat_Room_No'),
                    'name': treatment.get('Pat_Name'),
                    'sex': treatment.get('Pat_Sex'),
                    'age': treatment.get('Pat_Age'),
                    'source': 'treatment'
                })
        except Exception as e:
            print(f"[DEBUG] Error searching Treatment table: {e}")
        
        # -------------------------------------------------------------
        # 2. Identify Target Room Numbers (IDs) from StayingRoom
        # -------------------------------------------------------------
        mapped_room_numbers = set()
        try:
            staying_room_q = Q()
            for term in search_terms:
                staying_room_q |= Q(room_no__istartswith=term)
            
            matching_staying_rooms = StayingRoom.objects.filter(staying_room_q)
            for sr in matching_staying_rooms:
                if sr.number:
                    try:
                        if str(sr.number).strip():
                            mapped_room_numbers.add(sr.number) # As string or whatever DB returns
                            if str(sr.number).isdigit():
                                mapped_room_numbers.add(int(sr.number))
                    except:
                        pass
            
            if room_query.isdigit():
                mapped_room_numbers.add(int(room_query))
                mapped_room_numbers.add(room_query)
        except Exception as e:
            print(f"[DEBUG] Error searching StayingRoom: {e}")
        
        # -------------------------------------------------------------
        # 3. Search PatientSnapshot (Local DB)
        # -------------------------------------------------------------
        snapshot_patients = []
        try:
            snapshot_q = Q()
            # Prefix search on string field
            for term in search_terms:
                snapshot_q |= Q(pat_room_no__istartswith=term)
            # Exact match on mapped IDs
            for mapped_num in mapped_room_numbers:
                snapshot_q |= Q(pat_room_no__iexact=str(mapped_num))
            
            snapshot_records_list = list(PatientSnapshot.objects.filter(
                snapshot_q
            ).values('pat_reg_no', 'pat_room_no', 'pat_name', 'pat_sex', 'pat_age')[:100])
            
            for snapshot in snapshot_records_list:
                # Add to result if not already in treatment patients
                if not any(tp['reg_no'] == snapshot['pat_reg_no'] for tp in treatment_patients):
                    snapshot_patients.append({
                        'reg_no': snapshot['pat_reg_no'],
                        'room_no': snapshot.get('pat_room_no'),
                        'name': snapshot.get('pat_name'),
                        'sex': snapshot.get('pat_sex'),
                        'age': snapshot.get('pat_age'),
                        'source': 'snapshot'
                    })
        except Exception as e:
            print(f"[DEBUG] Error searching PatientSnapshot: {e}")
        
        # -------------------------------------------------------------
        # 4. Search Registration (IP Patients)
        # -------------------------------------------------------------
        ip_patients_list = []
        try:
            search_q = Q()
            if mapped_room_numbers:
                search_q = Q(pat_room_no__in=list(mapped_room_numbers))
            
            # Also try prefix search on pat_room_no if it supports it (some might store "NR-1")
            for term in search_terms:
                 search_q |= Q(pat_room_no__istartswith=term)
            
            if search_q:
                thirty_days_ago = today - timedelta(days=30)
                search_q &= Q(pat_visit_date__date__gte=thirty_days_ago) # Recent visits
                
                ip_patients_list = list(Registration.objects.using('therapy_db').filter(
                    search_q,
                    pat_status='Y'
                ).values(
                    'pat_reg_no', 'pat_name', 'pat_sex', 'pat_age', 'pat_room_no', 'pat_ref_id', 'pat_visit_date', 'pat_room_date'
                ).order_by('-pat_visit_date', '-pat_room_date')[:100])
        except Exception as e:
            print(f"[DEBUG] Error searching Registration: {e}")
            
        # -------------------------------------------------------------
        # 5. Check Active Status (Business Logic Preservation)
        # -------------------------------------------------------------
        active_patient_reg_nos = set()
        try:
            # Check TherapyAllocation
            active_therapies = TherapyAllocation.objects.filter(
                from_date__lte=today,
                to_date__gte=today,
                status__in=['allocated', 'draft']
            ).values_list('patient__pat_reg_no', flat=True)
            for reg in active_therapies:
                if reg: active_patient_reg_nos.add(str(reg))
            
            # Check Booking
            active_bookings = Booking.objects.filter(
                date__gte=today,
                status__in=['scheduled', 'draft']
            ).values_list('allocation__patient__pat_reg_no', flat=True)
            for reg in active_bookings:
                if reg: active_patient_reg_nos.add(str(reg))
        except Exception as e:
            print(f"[DEBUG] Error checking active status: {e}")
            
        # -------------------------------------------------------------
        # 6. Merge and Enrich Results
        # -------------------------------------------------------------
        all_patient_sources = treatment_patients + snapshot_patients
        
        # Process IP Patients List first
        for patient in ip_patients_list:
            reg_no_str = str(patient['pat_reg_no']).strip()
            if reg_no_str in added_reg_nos: continue
            
            mapped_room = None
            try:
                mapped_room = get_staying_room_display_number(patient['pat_room_no'])
            except:
                mapped_room = patient['pat_room_no']
            
            patients.append({
                'registration_number': patient['pat_reg_no'],
                'patient_name': patient['pat_name'],
                'sex': patient['pat_sex'],
                'age': patient['pat_age'],
                'room_number': mapped_room,
                'ip_number': patient['pat_reg_no'],
                'pat_ref_id': patient.get('pat_ref_id'),
                'patient_type': 'IP',
                'source': 'IP'
            })
            added_reg_nos.add(reg_no_str)
            
        # Process Treatment/Snapshot Patients
        for tp in all_patient_sources:
            reg_no = tp['reg_no']
            reg_no_str = str(reg_no).strip()
            if reg_no_str in added_reg_nos: continue
            
            # Enrich with Registration info if available
            ip_patient = None
            op_patient = None
            
            try:
                ip_patient = Registration.objects.using('therapy_db').filter(
                    pat_reg_no=reg_no
                ).values('pat_reg_no', 'pat_name', 'pat_sex', 'pat_age', 'pat_room_no').first()
            except: pass
            
            if ip_patient:
                tp['name'] = ip_patient['pat_name']
                tp['sex'] = ip_patient['pat_sex']
                tp['age'] = ip_patient['pat_age']
            else:
                try:
                    op_patient = OPMaster.objects.using('hospital_db').filter(
                        NPat_Reg_No=reg_no
                    ).values('NPat_Reg_No', 'NPat_Name', 'NPat_Sex', 'Reg_Date').first()
                    if op_patient:
                        tp['name'] = op_patient['NPat_Name']
                        tp['sex'] = op_patient['NPat_Sex']
                except: pass
            
            patients.append({
                'registration_number': reg_no,
                'patient_name': tp['name'] or 'Unknown',
                'sex': tp['sex'],
                'age': tp['age'],
                'room_number': tp['room_no'],
                'ip_number': reg_no if not op_patient else None,
                'patient_type': 'OP' if op_patient else 'IP',
                'source': tp['source']
            })
            added_reg_nos.add(reg_no_str)

        # Prioritize active patients
        if active_patient_reg_nos:
            active = [p for p in patients if str(p['registration_number']) in active_patient_reg_nos]
            others = [p for p in patients if str(p['registration_number']) not in active_patient_reg_nos]
            patients = active + others
            
        return JsonResponse({
            'patients': patients[:20],
            'total_found': len(patients)
        })
        
    except Exception as e:
        traceback.print_exc()
        return JsonResponse({
            'error': f'Search failed: {str(e)}',
            'patients': []
        }, status=500)
