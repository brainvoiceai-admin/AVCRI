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
        
        # 1. Fetch Schedule Data
        # Strategy: Use Booking model (per-date) as the source of truth for validity.
        # TherapyAllocation.status can be 'failed' even when some individual Booking dates are 'scheduled'.
        # So we build a set of valid (allocation_id, date) tuples from Booking records that are NOT failed/cancelled.
        # Then we only include TherapistBooking rows matching those valid pairs.
        from Sheduling.models import Booking
        valid_bookings_qs = Booking.objects.filter(
            date__range=[from_date, to_date]
        ).exclude(
            status__icontains='cancel'
        ).exclude(
            status__icontains='fail'
        ).values_list('allocation_id', 'date')
        
        # Build a fast lookup set: {(allocation_id, date), ...}
        valid_pairs = set((alloc_id, d) for alloc_id, d in valid_bookings_qs)
        
        # Fetch all TherapistBookings in range (excluding self-cancelled/failed)
        bookings = TherapistBooking.objects.filter(
            date__range=[from_date, to_date]
        ).exclude(
            status__icontains='cancel'
        ).exclude(
            status__icontains='fail'
        ).select_related('therapist', 'visit__patient', 'time_slot').order_by('date')
        
        # 2. Build Caches
        patient_info = {}  # pat_key -> {name, reg_no}
        
        # Schedule Map: pat_key -> therapy_name -> slot_key -> date_str -> { 'therapists': {therapist_id: {...}} }
        schedule_map = defaultdict(lambda: defaultdict(lambda: defaultdict(lambda: defaultdict(lambda: {'therapists': {}}))))
        
        # Track slot_id for each slot_key to use in historical queries
        slot_id_map = {}  # slot_key -> time_slot_id

        # Map from pat_key used in schedule_map -> actual patient_id field value in TherapistBooking
        # We need this because the historical queries also use patient_id
        pat_key_to_booking_patient_id = {}  # pat_key -> patient_id value used in TherapistBooking
        
        # Leave Cache
        leave_cache = defaultdict(set)  # date -> {therapist_master_ids}
        
        def populate_leave_cache(f_date, t_date):
            # Emergency leaves
            e_leaves = EmergencyLeave.objects.filter(from_date__lte=t_date, to_date__gte=f_date)
            for l in e_leaves:
                s = max(l.from_date, f_date)
                e = min(l.to_date, t_date)
                curr = s
                while curr <= e:
                    if l.therapist_id:
                        leave_cache[curr].add(l.therapist_id)
                    curr += timedelta(days=1)
                    
            # Weekly leaves
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

            # Skip TherapistBooking rows where the per-date Booking is failed/cancelled.
            # This handles cases where TherapyAllocation has partial failures (some dates failed,
            # some scheduled) — we only show dates with a valid scheduled Booking.
            if b.visit_id is not None and (b.visit_id, b.date) not in valid_pairs:
                continue
            
            # Determine patient key for grouping:
            # Use visit.patient.id (PatientSnapshot.id) as a stable key if available,
            # otherwise fall back to b.patient_id (the raw BigIntegerField)
            pat_snapshot_id = None
            if b.visit and b.visit.patient:
                pat_snapshot_id = b.visit.patient.id
            
            # Use PatientSnapshot.id as key if available (stable), else raw patient_id
            pat_key = pat_snapshot_id if pat_snapshot_id is not None else b.patient_id
            
            if pat_key is None:
                continue
            
            # Store the raw patient_id used in TherapistBooking for historical queries
            # Both fields (patient_id and visit->patient.id) may differ; we need patient_id for queries
            if pat_key not in pat_key_to_booking_patient_id:
                if b.patient_id is not None:
                    pat_key_to_booking_patient_id[pat_key] = b.patient_id
                else:
                    pat_key_to_booking_patient_id[pat_key] = None
            
            # Capture Patient Info
            if pat_key not in patient_info:
                if b.visit and b.visit.patient:
                    patient_info[pat_key] = {
                        'id': pat_key,
                        'name': b.visit.patient.pat_name or f"ID {pat_key}",
                        'reg_no': b.visit.patient.pat_reg_no or str(pat_key)
                    }
                elif b.patient_id:
                    try:
                        s = PatientSnapshot.objects.filter(id=b.patient_id).first()
                        if s:
                            patient_info[pat_key] = {'id': pat_key, 'name': s.pat_name or f"ID {pat_key}", 'reg_no': s.pat_reg_no or str(pat_key)}
                        else:
                            patient_info[pat_key] = {'id': pat_key, 'name': f"ID {pat_key}", 'reg_no': str(pat_key)}
                    except:
                        patient_info[pat_key] = {'id': pat_key, 'name': f"ID {pat_key}", 'reg_no': str(pat_key)}
                else:
                    patient_info[pat_key] = {'id': pat_key, 'name': f"ID {pat_key}", 'reg_no': str(pat_key)}

            t_id = b.therapist.id
            # Normalize therapy name to prevent fragmentation
            t_name = b.therapy_name.strip() if b.therapy_name else "General"
            
            # Get slot information
            slot_key = "No Slot"
            if b.time_slot:
                slot_time = b.time_slot.slot_time if hasattr(b.time_slot, 'slot_time') else str(b.time_slot)
                try:
                    from datetime import datetime
                    if isinstance(slot_time, str):
                        for fmt in ['%H:%M:%S', '%H:%M', '%I:%M %p', '%I:%M:%S %p']:
                            try:
                                time_obj = datetime.strptime(slot_time, fmt).time()
                                slot_key = time_obj.strftime('%I:%M %p')
                                break
                            except:
                                continue
                        else:
                            slot_key = slot_time
                    else:
                        slot_key = slot_time.strftime('%I:%M %p') if hasattr(slot_time, 'strftime') else str(slot_time)
                except:
                    slot_key = str(slot_time)
                
                # Store slot_id mapping for this key
                slot_id_map[slot_key] = b.time_slot_id
            
            # Store therapist info grouped by pat_key -> therapy -> slot -> date -> therapists
            schedule_map[pat_key][t_name][slot_key][d_str]['therapists'][t_id] = {
                'id': t_id,
                'name': b.therapist.therapist_name,
                'is_bathing': b.is_bathing
            }
            
        # 4. Construct Matrix Rows
        rows = []
        date_cols = []
        curr = from_date
        while curr <= to_date:
            date_cols.append(curr.strftime('%Y-%m-%d'))
            curr += timedelta(days=1)
            
        # Sort patient keys by name for consistent grouping and display
        sorted_pat_keys = sorted(schedule_map.keys(), key=lambda pk: patient_info[pk]['name'].lower())
        
        for pat_key in sorted_pat_keys:
            therapies_data = schedule_map[pat_key]
            # Sort therapies by name
            sorted_t_names = sorted(therapies_data.keys())
            
            # Get the raw patient_id value stored in TherapistBooking for historical queries
            raw_patient_id = pat_key_to_booking_patient_id.get(pat_key)
            
            for t_name in sorted_t_names:
                slots_data = therapies_data[t_name]
                # Sort slots by time
                sorted_slots = sorted(slots_data.keys())
                
                for slot_key in sorted_slots:
                    dates_data = slots_data[slot_key]
                    row = {
                        'patient': patient_info[pat_key],
                        'therapy_name': t_name,
                        'slot': slot_key,
                        'cells': {}
                    }
                    
                    target_slot_id = slot_id_map.get(slot_key)
                    baseline_set = None
                    
                    for i, d_str in enumerate(date_cols):
                        curr_data = dates_data.get(d_str, {'therapists': {}})
                        curr_objs = curr_data.get('therapists', {})
                        curr_set = set(curr_objs.keys())
                        
                        if not curr_set:
                            row['cells'][d_str] = {'therapists': [], 'status': 'empty'}
                            continue
                            
                        date_obj = parse_date(d_str)
                        reference_set = set()
                        
                        if baseline_set is None:
                            # DAY 1 LOGIC: Compare with the PREVIOUS booking for same patient+therapy+slot
                            # Use pat_key (PatientSnapshot.id) for the query since TherapistBooking.patient_id
                            # stores PatientSnapshot.id (not reg_no)
                            query = TherapistBooking.objects.filter(
                                therapy_name=t_name,
                                date__lt=date_obj
                            ).exclude(
                                status__icontains='cancel'
                            ).exclude(
                                status__icontains='fail'
                            ).exclude(
                                visit__status__icontains='cancel'
                            ).exclude(
                                visit__status__icontains='fail'
                            )
                            
                            # Filter by patient — try PatientSnapshot.id via visit FK first (most accurate)
                            if raw_patient_id is not None:
                                query = query.filter(patient_id=raw_patient_id)
                            else:
                                # Fall back to visit->patient relationship
                                query = query.filter(visit__patient__id=pat_key)
                            
                            # Ensure we only compare within the same slot
                            if target_slot_id:
                                query = query.filter(time_slot_id=target_slot_id)
                            else:
                                query = query.filter(time_slot__isnull=True)
                                
                            last_booking = query.order_by('-date').first()
                            
                            if last_booking:
                                # Get all therapists from that previous date+slot
                                prev_query = TherapistBooking.objects.filter(
                                    therapy_name=t_name,
                                    date=last_booking.date,
                                    time_slot_id=last_booking.time_slot_id
                                ).exclude(
                                    status__icontains='cancel'
                                ).exclude(
                                    status__icontains='fail'
                                ).exclude(
                                    visit__status__icontains='cancel'
                                ).exclude(
                                    visit__status__icontains='fail'
                                )
                                if raw_patient_id is not None:
                                    prev_query = prev_query.filter(patient_id=raw_patient_id)
                                else:
                                    prev_query = prev_query.filter(visit__patient__id=pat_key)
                                reference_set = set(prev_query.values_list('therapist_id', flat=True))
                            else:
                                reference_set = set()
                                
                            baseline_set = curr_set
                        else:
                            # Day 2+ — compare against the FIRST day's therapists (baseline)
                            reference_set = baseline_set
                            
                        # Determine which therapists are missing from the reference
                        missing_set = reference_set - curr_set
                        has_unexcused_loss = False
                        if missing_set:
                            leaves_today = leave_cache.get(date_obj, set())
                            for m_id in missing_set:
                                if m_id not in leaves_today:
                                    has_unexcused_loss = True
                                    break
                                    
                        therapist_list = []
                        # Sort by therapist_id for consistent display order
                        for t_id in sorted(curr_objs.keys()):
                            t_data = curr_objs[t_id].copy()
                            if t_id in reference_set:
                                t_data['status'] = 'green'   # Same therapist as reference
                            else:
                                if has_unexcused_loss:
                                    t_data['status'] = 'red'   # Different therapist (unexcused change)
                                elif missing_set:
                                    t_data['status'] = 'gray'  # Different (on leave — excused)
                                else:
                                    t_data['status'] = 'green'  # New therapist (no prior reference)
                            therapist_list.append(t_data)
    
                        row['cells'][d_str] = {
                            'therapists': therapist_list,
                            'status': 'active'
                        }
                    
                    rows.append(row)
            
        response = JsonResponse({
            'columns': date_cols,
            'rows': rows,
            'meta': {
                'total_bookings_fetched': bookings.count(),
                'total_patients': len(schedule_map),
                'total_rows': len(rows),
                'date_range': f"{from_date} to {to_date}"
            }
        })
        response['Cache-Control'] = 'no-cache, no-store, must-revalidate'
        return response

    except Exception as e:
        import traceback
        return JsonResponse({
            'error': f"Server Error: {str(e)}",
            'detail': traceback.format_exc()
        }, status=500)
