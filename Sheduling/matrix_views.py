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
        
        # (B) Schedule Map: pat_id -> date_str -> { therapist_id: {name, is_bathing} }
        schedule_map = defaultdict(lambda: defaultdict(dict))
        
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
                        'name': b.visit.patient.pat_name,
                        'reg_no': b.visit.patient.pat_reg_no
                    }
                else:
                    try:
                        s = PatientSnapshot.objects.filter(id=pat_id).first()
                        if s:
                            patient_info[pat_id] = {'name': s.pat_name, 'reg_no': s.pat_reg_no}
                        else:
                            patient_info[pat_id] = {'name': f"ID {pat_id}", 'reg_no': str(pat_id)} 
                    except:
                        patient_info[pat_id] = {'name': f"ID {pat_id}", 'reg_no': str(pat_id)}

            t_id = b.therapist.id
            schedule_map[pat_id][d_str][t_id] = {
                'id': t_id,
                'name': b.therapist.therapist_name,
                'is_bathing': b.is_bathing # CORRECTED: Use booking specific flag
            }
            
        # 3.5 Fetch Previous Treatment Info (for Day 1 comparison)
        previous_map = defaultdict(set)
        patient_ids = list(schedule_map.keys())
        if patient_ids:
            # Fetch most recent booking date prior to from_date for each patient
            past_bookings = TherapistBooking.objects.filter(
                patient_id__in=patient_ids,
                date__lt=from_date,
                status__in=['BOOKED', 'scheduled', 'COMPLETED']
            ).values('patient_id', 'date', 'therapist_id').order_by('patient_id', '-date')
            
            # Extract latest per patient
            last_dates = {}
            for pb in past_bookings:
                pid = pb['patient_id']
                d = pb['date']
                if pid not in last_dates:
                    last_dates[pid] = d
                    previous_map[pid].add(pb['therapist_id'])
                elif last_dates[pid] == d:
                    previous_map[pid].add(pb['therapist_id'])

        # 4. Construct Matrix Rows
        rows = []
        
        # Generate complete date list for columns
        date_cols = []
        curr = from_date
        while curr <= to_date:
            date_cols.append(curr.strftime('%Y-%m-%d'))
            curr += timedelta(days=1)
            
        # Process each patient
        for pat_id, dates_data in schedule_map.items():
            row = {
                'patient': patient_info[pat_id],
                'cells': {}
            }
            
            day_1_set = set() # To store the anchor/Day 1 therapist set
            
            for i, d_str in enumerate(date_cols):
                curr_objs = dates_data.get(d_str, {})
                curr_set = set(curr_objs.keys())
                
                # Determine Reference Set for Comparison
                ref_set = set()
                if i == 0:
                    # Day 1: Comparision against Previous Treatment
                    ref_set = previous_map.get(pat_id, set())
                    # Capture Day 1 Set for subsequent days
                    day_1_set = curr_set
                else:
                    # Subsequent Days: Compare against the FIRST DAY therapist
                    ref_set = day_1_set
                
                # Analyze Missing Therapists from Reference
                missing_set = ref_set - curr_set
                has_unexcused_loss = False
                
                if missing_set:
                    # Check if any missing therapist was NOT on leave (i.e. available but changed)
                    date_obj = parse_date(d_str)
                    leaves_today = leave_cache.get(date_obj, set())
                    
                    for m_id in missing_set:
                        if m_id not in leaves_today:
                            has_unexcused_loss = True
                            break
                            
                # Enrich therapists with status
                therapist_list = []
                for t_vals in curr_objs.values():
                    t_data = t_vals.copy()
                    
                    if t_data['id'] in ref_set:
                         t_data['status'] = 'green' # Same as reference (Day 1 or Prev Treatment)
                    else:
                        # New therapist replacing someone or adding on
                        if has_unexcused_loss:
                            t_data['status'] = 'red' # Replaced available therapist
                        elif missing_set:
                             t_data['status'] = 'gray' # Replaced therapist on leave
                        else:
                             t_data['status'] = 'green' # Pure addition (neutral/good)
                        
                    therapist_list.append(t_data)
                
                cell_data = {
                    'therapists': therapist_list,
                    'status': 'active' if curr_set else 'empty'
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
