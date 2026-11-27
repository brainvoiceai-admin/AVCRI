"""Hard-treatment session restriction rules (max 1 Hard treatment per morning/evening session)."""
import datetime
import re


def is_hard_treatment(therapy_obj=None, therapy_name=None, therapy_code=None, category=None):
    """
    Returns True if the therapy difficulty category is 'hard' (case-insensitive).
    Returns False for 'Medium', 'Easy', or any other category.
    """
    if category is not None and str(category).strip():
        return str(category).strip().lower() == "hard"

    if therapy_obj is not None:
        if isinstance(therapy_obj, dict):
            c = therapy_obj.get("therapy_category")
            if c is not None and str(c).strip():
                return str(c).strip().lower() == "hard"
            if not therapy_name:
                therapy_name = therapy_obj.get("therapy_name")
            if not therapy_code:
                therapy_code = therapy_obj.get("therapy_code")
        elif hasattr(therapy_obj, "therapy_category") and therapy_obj.therapy_category:
            return str(therapy_obj.therapy_category).strip().lower() == "hard"
        elif hasattr(therapy_obj, "therapy") and therapy_obj.therapy:
            th = therapy_obj.therapy
            if hasattr(th, "therapy_category") and th.therapy_category:
                return str(th.therapy_category).strip().lower() == "hard"
            if hasattr(th, "therapy_name") and not therapy_name:
                therapy_name = th.therapy_name
            if hasattr(th, "therapy_code") and not therapy_code:
                therapy_code = th.therapy_code
        if hasattr(therapy_obj, "therapy_code") and therapy_obj.therapy_code and not therapy_code:
            therapy_code = therapy_obj.therapy_code
        if hasattr(therapy_obj, "therapy_name") and therapy_obj.therapy_name and not therapy_name:
            therapy_name = therapy_obj.therapy_name
        if hasattr(therapy_obj, "snapshot_therapy_name") and therapy_obj.snapshot_therapy_name and not therapy_name:
            therapy_name = therapy_obj.snapshot_therapy_name

    try:
        from masters.models import TherapyMaster
        tm = None
        if therapy_code:
            tm = TherapyMaster.objects.filter(therapy_code__iexact=str(therapy_code).strip()).first()
        if not tm and therapy_name:
            tname = str(therapy_name).strip()
            tm = TherapyMaster.objects.filter(therapy_name__iexact=tname).first()
            if not tm:
                norm_key = " ".join(tname.lower().split())
                for cand in TherapyMaster.objects.all():
                    cand_name = getattr(cand, "therapy_name", "") or ""
                    if " ".join(cand_name.lower().split()) == norm_key:
                        tm = cand
                        break
        if tm and getattr(tm, "therapy_category", None):
            return str(tm.therapy_category).strip().lower() == "hard"
    except Exception:
        pass

    return False


def get_slot_session(slot):
    """
    Returns 'morning' if slot is in Forenoon / Morning (< 13:00, slots 1-4: 06:30, 08:30, 10:00, 11:30).
    Returns 'evening' if slot is in Afternoon / Evening (>= 13:00, slots 5-7: 14:30, 16:00, 17:30).
    Returns None if slot cannot be determined.
    """
    if slot is None:
        return None

    if hasattr(slot, "slot_time") and slot.slot_time:
        st = slot.slot_time
        if isinstance(st, str):
            for fmt in ("%H:%M:%S", "%H:%M", "%I:%M %p", "%I:%M%p"):
                try:
                    st = datetime.datetime.strptime(st.strip(), fmt).time()
                    break
                except ValueError:
                    pass
        if isinstance(st, datetime.time):
            return "morning" if st < datetime.time(13, 0) else "evening"

    if hasattr(slot, "start_time") and slot.start_time:
        st = slot.start_time
        if isinstance(st, str):
            for fmt in ("%H:%M:%S", "%H:%M", "%I:%M %p", "%I:%M%p"):
                try:
                    st = datetime.datetime.strptime(st.strip(), fmt).time()
                    break
                except ValueError:
                    pass
        if isinstance(st, datetime.time):
            return "morning" if st < datetime.time(13, 0) else "evening"

    if isinstance(slot, datetime.time):
        return "morning" if slot < datetime.time(13, 0) else "evening"

    if isinstance(slot, int):
        if 1 <= slot <= 4:
            return "morning"
        if 5 <= slot <= 7:
            return "evening"
        try:
            from masters.models import SlotMaster
            sm = SlotMaster.objects.filter(pk=slot).first()
            if sm and sm.slot_time:
                return "morning" if sm.slot_time < datetime.time(13, 0) else "evening"
        except Exception:
            pass

    if isinstance(slot, str):
        s = slot.strip().lower()
        m = re.search(r"slot\s*(\d+)", s)
        if m:
            num = int(m.group(1))
            return "morning" if num <= 4 else "evening"
        if s.isdigit():
            num = int(s)
            if 1 <= num <= 4:
                return "morning"
            if 5 <= num <= 7:
                return "evening"
        for fmt in ("%H:%M:%S", "%H:%M", "%I:%M %p", "%I:%M%p"):
            try:
                t = datetime.datetime.strptime(s, fmt).time()
                return "morning" if t < datetime.time(13, 0) else "evening"
            except ValueError:
                pass

    return None


def patient_has_hard_treatment_in_session(
    patient_id,
    target_date,
    session,
    exclude_booking_id=None,
    exclude_allocation_id=None,
    in_memory_tasks=None,
):
    """
    Checks if the patient already has an active, scheduled, or booked Hard treatment
    on target_date in the given session ('morning' or 'evening').
    Exception: Medium and Easy treatments (e.g. Lepam) do not conflict.
    """
    if not patient_id or not target_date or not session:
        return False

    session = str(session).strip().lower()
    if session not in ('morning', 'evening'):
        return False

    if isinstance(target_date, str):
        try:
            target_date = datetime.datetime.strptime(target_date, "%Y-%m-%d").date()
        except Exception:
            pass

    try:
        from Sheduling.models import PatientSnapshot, Booking
        from Patient.models import TherapistBooking, RoomBooking

        patient_snapshot_ids = set()
        pat_reg_no = None

        if hasattr(patient_id, 'pat_reg_no'):
            pat_reg_no = getattr(patient_id, 'pat_reg_no', None)
            if hasattr(patient_id, 'pk'):
                patient_snapshot_ids.add(patient_id.pk)
        elif isinstance(patient_id, int):
            patient_snapshot_ids.add(patient_id)
            ps = PatientSnapshot.objects.filter(pk=patient_id).first()
            if ps and ps.pat_reg_no:
                pat_reg_no = ps.pat_reg_no
        elif isinstance(patient_id, str):
            if patient_id.isdigit():
                ps = PatientSnapshot.objects.filter(pk=int(patient_id)).first()
                if ps:
                    patient_snapshot_ids.add(ps.pk)
                    pat_reg_no = ps.pat_reg_no
            if not pat_reg_no:
                pat_reg_no = patient_id

        if pat_reg_no:
            other_ids = PatientSnapshot.objects.filter(pat_reg_no=str(pat_reg_no).strip()).values_list('id', flat=True)
            patient_snapshot_ids.update(other_ids)

        # 2. Check TherapistBooking records (status='BOOKED')
        tb_qs = TherapistBooking.objects.filter(date=target_date, status='BOOKED')
        if patient_snapshot_ids:
            tb_qs = tb_qs.filter(patient_id__in=patient_snapshot_ids)
        if exclude_allocation_id:
            tb_qs = tb_qs.exclude(visit_id=exclude_allocation_id)

        for tb in tb_qs.select_related('time_slot'):
            tb_session = get_slot_session(tb.time_slot)
            if tb_session == session:
                th_obj = getattr(tb, 'therapy', None)
                th_name = getattr(tb, 'therapy_name', None)
                if is_hard_treatment(therapy_obj=th_obj, therapy_name=th_name):
                    return True

        # 3. Check RoomBooking records (status in ['BOOKED', 'scheduled'])
        rb_qs = RoomBooking.objects.filter(date=target_date, status__in=['BOOKED', 'scheduled'])
        if patient_snapshot_ids:
            rb_qs = rb_qs.filter(patient_id__in=patient_snapshot_ids)
        if exclude_allocation_id:
            rb_qs = rb_qs.exclude(therapy_id=exclude_allocation_id)
            if hasattr(RoomBooking, 'visit'):
                rb_qs = rb_qs.exclude(visit_id=exclude_allocation_id)

        for rb in rb_qs.select_related('time_slot'):
            rb_session = get_slot_session(rb.time_slot)
            if rb_session == session:
                th_obj = getattr(rb, 'therapy', None)
                th_name = getattr(rb, 'therapy_name', None)
                if is_hard_treatment(therapy_obj=th_obj, therapy_name=th_name):
                    return True

        # 4. Check Booking records (status in ['scheduled', 'allocated', 'BOOKED'])
        b_qs = Booking.objects.filter(date=target_date, status__in=['scheduled', 'allocated', 'BOOKED'])
        if patient_snapshot_ids:
            b_qs = b_qs.filter(allocation__patient__id__in=patient_snapshot_ids)
        if exclude_booking_id:
            b_qs = b_qs.exclude(pk=exclude_booking_id)
        if exclude_allocation_id:
            b_qs = b_qs.exclude(allocation_id=exclude_allocation_id)

        for b in b_qs.select_related('timeslot', 'allocation'):
            b_session = get_slot_session(b.timeslot)
            if b_session == session:
                alloc = getattr(b, 'allocation', None)
                snap_name = getattr(b, 'snapshot_therapy_name', None)
                if is_hard_treatment(therapy_obj=alloc, therapy_name=snap_name):
                    return True

        # 5. Check in_memory_tasks if provided
        if in_memory_tasks:
            for task in in_memory_tasks:
                if isinstance(task, dict) and task.get('status') == 'BOOKED':
                    if exclude_booking_id and task.get('booking_id') == exclude_booking_id:
                        continue
                    if exclude_allocation_id and task.get('allocation_id') == exclude_allocation_id:
                        continue
                    t_slot = task.get('slot')
                    t_session = get_slot_session(t_slot)
                    if t_session == session:
                        t_name = task.get('therapy_name')
                        if is_hard_treatment(therapy_name=t_name):
                            return True

    except Exception as e:
        print(f"[DEBUG patient_has_hard_treatment_in_session] Error: {e}")

    return False
