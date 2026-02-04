from datetime import timedelta
from collections import defaultdict
from django.http import JsonResponse
from django.utils.dateparse import parse_date
from django.views.decorators.http import require_http_methods
from .decorators import api_access_required, scheduling_access_required
from Patient.models import TherapistBooking
from masters.models import TherapistLeaveMaster, EmergencyLeave
from Sheduling.models import PatientSnapshot

@api_access_required
def continuity_matrix_api(request):
    """
    API to return Therapist Continuity Matrix data.
    Query params: from_date, to_date, exclude_leave (true/false)
    """
    try:
        from_date_str = request.GET.get('from_date')
        to_date_str = request.GET.get('to_date')
        exclude_leave_str = request.GET.get('exclude_leave', 'true')
        
        if not from_date_str or not to_date_str:
             return JsonResponse({'error': 'Date range required'}, status=400)
             
        try:
            from_date = parse_date(from_date_str)
            to_date = parse_date(to_date_str)
        except:
            return JsonResponse({'error': 'Invalid date format'}, status=400)
            
        exclude_leave = (exclude_leave_str.lower() == 'true')
        
        # 1. Fetch Schedule Data (TherapistBooking is the source of truth for assignments)
        # Using 'visit__patient' to get patient details
        bookings = TherapistBooking.objects.filter(
            date__range=[from_date, to_date],
            status__in=['BOOKED', 'scheduled', 'COMPLETED']
        ).select_related('therapist', 'visit__patient').order_by('date')
        
        # 2. Build Caches
        # (A) Patient Info Cache
        patient_info = {} # pat_id -> {name, reg_no}
        
        # (B) Schedule Map: pat_id -> therapy_name -> date_str -> { therapist_id: {name, is_bathing} }
        schedule_map = defaultdict(lambda: defaultdict(lambda: defaultdict(dict)))
        
        # (C) Leave Cache
        leave_cache = defaultdict(set) # date -> {therapist_ids}
        
        # helper to check leave
        def populate_leave_cache(f_date, t_date):
            # Emergency
            e_leaves = EmergencyLeave.objects.filter(from_date__lte=t_date, to_date__gte=f_date)
            for l in e_leaves:
                s = max(l.from_date, f_date)
                e = min(l.to_date, t_date)
                curr = s
                while curr <= e:
                    if l.therapist_id:
                        leave_cache[curr].add(l.therapist_id)
                    curr += timedelta(days=1)
                    
            # Weekly
            weekly = TherapistLeaveMaster.objects.all().values('therapist_id', 'leave_day')
            dow_map = defaultdict(set)
            for w in weekly:
                dow_map[w['leave_day']].add(w['therapist_id'])
                
            curr = f_date
            while curr <= t_date:
                dow = curr.weekday()
                if dow in dow_map:
                    leave_cache[curr].update(dow_map[dow])
                curr += timedelta(days=1)
                
        populate_leave_cache(from_date, to_date)
        
        # 3. Process Bookings to Map
        for b in bookings:
            d_str = b.date.strftime('%Y-%m-%d')
            
            pat_id = b.patient_id
            if not pat_id: continue
            
            # Capture Patient Info
            if pat_id not in patient_info:
                if b.visit and b.visit.patient:
                    patient_info[pat_id] = {
                        'id': pat_id,
                        'name': b.visit.patient.pat_name,
                        'reg_no': b.visit.patient.pat_reg_no
                    }
                else:
                    try:
                        s = PatientSnapshot.objects.filter(id=pat_id).first()
                        if s:
                            patient_info[pat_id] = {'id': pat_id, 'name': s.pat_name, 'reg_no': s.pat_reg_no}
                        else:
                            patient_info[pat_id] = {'id': pat_id, 'name': f"ID {pat_id}", 'reg_no': str(pat_id)} 
                    except:
                        patient_info[pat_id] = {'id': pat_id, 'name': f"ID {pat_id}", 'reg_no': str(pat_id)}

            t_id = b.therapist.id
            t_name = b.therapy_name if b.therapy_name else "General"
            
            schedule_map[pat_id][t_name][d_str][t_id] = {
                'id': t_id,
                'name': b.therapist.therapist_name,
                'is_bathing': b.is_bathing # CORRECTED: Use booking specific flag
            }
            
        # 4. Construct Matrix Rows
        rows = []
        
        # Generate complete date list for columns
        date_cols = []
        curr = from_date
        while curr <= to_date:
            date_cols.append(curr.strftime('%Y-%m-%d'))
            curr += timedelta(days=1)
            
        # Process each patient
        for pat_id, therapies_data in schedule_map.items():
            for t_name, dates_data in therapies_data.items():
                row = {
                    'patient': patient_info[pat_id],
                    'therapy_name': t_name,
                    'cells': {}
                }
                
                baseline_set = None # This preserves Day-1 therapists for subsequent days
                
                for i, d_str in enumerate(date_cols):
                    curr_objs = dates_data.get(d_str, {})
                    curr_set = set(curr_objs.keys())
                    
                    # If no data for this day, mark as empty
                    if not curr_set:
                        row['cells'][d_str] = {
                            'therapists': [],
                            'status': 'empty'
                        }
                        continue
                        
                    date_obj = parse_date(d_str)
                    reference_set = set()
                    
                    if baseline_set is None:
                        # === DAY 1 LOGIC (First day of treatment in this range) ===
                        # Verify continuity by comparing with PREVIOUS TREATMENT therapist
                        # (if any exists)
                        
                        # Fetch last valid booking BEFORE this date
                        last_booking = TherapistBooking.objects.filter(
                            patient_id=pat_id,
                            therapy_name=t_name,
                            date__lt=date_obj,
                            status__in=['BOOKED', 'scheduled', 'COMPLETED']
                        ).order_by('-date').first()
                        
                        if last_booking:
                            # Get all therapists for that previous day
                            prev_bookings = TherapistBooking.objects.filter(
                                patient_id=pat_id,
                                therapy_name=t_name,
                                date=last_booking.date,
                                status__in=['BOOKED', 'scheduled', 'COMPLETED']
                            ).values_list('therapist_id', flat=True)
                            reference_set = set(prev_bookings)
                        else:
                            reference_set = set() # No history found
                            
                        # Set Baseline for FUTURE days (Day 2 -> End)
                        baseline_set = curr_set
                    else:
                        # === SUBSEQUENT DAYS LOGIC ===
                        # Verify against FIRST DAY only (baseline_set)
                        # Do NOT compare against immediately previous day
                        reference_set = baseline_set
                        
                    # === COMMON VERIFICATION LOGIC ===
                    # Check for missing therapists FROM THE REFERENCE SET
                    missing_set = reference_set - curr_set
                    has_unexcused_loss = False
                    
                    if missing_set:
                        leaves_today = leave_cache.get(date_obj, set())
                        for m_id in missing_set:
                            if m_id not in leaves_today:
                                has_unexcused_loss = True
                                break
                                
                    # Determine colors for each allocated therapist
                    therapist_list = []
                    for t_vals in curr_objs.values():
                        t_data = t_vals.copy()
                        
                        # DEBUG LOGGING
                        debug_info = {
                            'patient': patient_info[pat_id]['name'],
                            'therapy': t_name,
                            'date': d_str,
                            'therapist': t_data['name'],
                            'therapist_id': t_data['id'],
                            'is_day_1': (baseline_set == curr_set),
                            'reference_set': [curr_objs.get(rid, {}).get('name', f'ID_{rid}') for rid in reference_set] if reference_set else 'NO_HISTORY',
                            'current_set': list(curr_objs.values()),
                            'missing_set': list(missing_set) if missing_set else [],
                            'has_unexcused_loss': has_unexcused_loss
                        }
                        
                        if t_data['id'] in reference_set:
                            t_data['status'] = 'green' # Same as reference
                            debug_info['decision'] = 'GREEN: Therapist matches reference'
                        else:
                            # New or Replacement
                            if has_unexcused_loss:
                                t_data['status'] = 'red' # Reference therapist matched was available but replaced
                                debug_info['decision'] = 'RED: Reference therapist(s) were available but replaced'
                            elif missing_set:
                                 t_data['status'] = 'gray' # Reference therapist on leave
                                 debug_info['decision'] = 'GRAY: Reference therapist is on leave'
                            else:
                                 t_data['status'] = 'green' # Pure addition
                                 debug_info['decision'] = 'GREEN: Pure addition (no prior history or adding therapist)'
                        
                        # Log to console for debugging
                        print(f"[CONTINUITY DEBUG] {debug_info}")
                            
                        therapist_list.append(t_data)

                    cell_data = {
                        'therapists': therapist_list,
                        'status': 'active'
                    }
                    
                    row['cells'][d_str] = cell_data
                
                rows.append(row)
            
        return JsonResponse({
            'columns': date_cols,
            'rows': rows
        })
    except Exception as e:
        import traceback
        return JsonResponse({
            'error': f"Server Error: {str(e)}",
            'detail': traceback.format_exc()
        }, status=500)
