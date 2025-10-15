# therapies/views.py
import json
from datetime import timedelta, datetime
from django.shortcuts import render
from django.http import JsonResponse, HttpResponseBadRequest
from django.apps import apps
from django.db.models import Q
from django.views.decorators.csrf import csrf_exempt
from django.utils.dateparse import parse_date
from django.db import transaction, IntegrityError

EXTERNAL_DB_ALIAS = 'therapy_db'  # external SQL Server alias

def get_model_safe(app_label, model_name):
    try:
        return apps.get_model(app_label, model_name)
    except Exception:
        return None

# External DB models (use .using(EXTERNAL_DB_ALIAS) when querying)
Registration = get_model_safe('MySql_Data_pull', 'Registration')
ItemMaster = get_model_safe('MySql_Data_pull', 'ItemMaster')

# Local models for lookup (existing)
TherapyDetails = get_model_safe('Patient', 'TherapyDetails')
TimeSlot = get_model_safe('Patient', 'TimeSlot')
TreatmentRoom = get_model_safe('Patient', 'TreatmentRoom')

# Masters
Procured = get_model_safe('masters', 'Procured')
OilClass = get_model_safe('masters', 'OilClass')
UsageType = get_model_safe('masters', 'UsageType')
PrescriptionTime = get_model_safe('masters', 'PrescriptionTime')
PrescriptionScope = get_model_safe('masters', 'PrescriptionScope')

# New scheduling models (expected to be in 'therapies' app)
TherapyAllocation = get_model_safe('Sheduling', 'TherapyAllocation')
PatientSnapshot = get_model_safe('Sheduling', 'PatientSnapshot')
Booking = get_model_safe('Sheduling', 'Booking')
BookingItem = get_model_safe('Sheduling', 'BookingItem')
BookingAssignment = get_model_safe('Sheduling', 'BookingAssignment')
CancellationRequest = get_model_safe('Sheduling', 'CancellationRequest')
AuditLog = get_model_safe('Sheduling', 'AuditLog')
NotificationQueue = get_model_safe('Sheduling', 'NotificationQueue')
TherapistModel = get_model_safe('Sheduling', 'Therapist') or get_model_safe('Patient', 'Therapist')

# Optional legacy model reference (if you have patient-specific therapy list model)
PatientTherapy = get_model_safe('your_app_name', 'PatientTherapy')  # fallback, adjust if needed


def _compute_patient_type_from_reg(reg_val):
    """Return 'OP' if reg_val contains exactly 5 digits, else 'IP'."""
    if reg_val is None:
        return 'IP'
    s = str(reg_val)
    digits = ''.join(ch for ch in s if ch.isdigit())
    if len(digits) == 5:
        return 'OP'
    return 'IP'


@csrf_exempt
def therapy_entry(request):
    """
    Single endpoint:
      - GET: render template or handle lookups by ?action=...
      - POST: perform allocate/mark_completed/request_cancellation via ?action=...
    """

    # --- POST actions (allocate, mark_completed, request_cancellation) ---
    if request.method == 'POST':
        action_post = (request.GET.get('action') or '').strip().lower()
        try:
            payload = json.loads(request.body.decode('utf-8') or '{}')
        except Exception:
            return JsonResponse({'error': 'invalid_json'}, status=400)

        # ---------- allocate ----------
        if action_post == 'allocate':
            # required fields
            required = ['patient_reg_no', 'therapy_code', 'therapy_name', 'from_date', 'to_date', 'items_groups']
            missing = [k for k in required if not payload.get(k)]
            if missing:
                return JsonResponse({'error': 'missing_fields', 'missing': missing}, status=400)

            fdate = parse_date(payload['from_date'])
            tdate = parse_date(payload['to_date'])
            if not fdate or not tdate or fdate > tdate:
                return JsonResponse({'error': 'invalid_dates'}, status=400)

            # resolve timeslot (accept "HH:MM" or slot_number)
            timeslot_obj = None
            ts_val = payload.get('timeslot') or payload.get('slot') or ''
            if ts_val:
                # try HH:MM
                try:
                    parts = ts_val.split(':')
                    if len(parts) == 2:
                        hh = int(parts[0]); mm = int(parts[1])
                        from_time = datetime.strptime(f"{hh:02d}:{mm:02d}", "%H:%M").time()
                        if TimeSlot is not None:
                            timeslot_obj = TimeSlot.objects.filter(start_time=from_time).first()
                    else:
                        # try slot_number int
                        if TimeSlot is not None:
                            timeslot_obj = TimeSlot.objects.filter(slot_number=int(ts_val)).first()
                except Exception:
                    timeslot_obj = None

                if timeslot_obj is None and TimeSlot is not None and ts_val:
                    return JsonResponse({'error': 'timeslot_not_found', 'timeslot': ts_val}, status=400)

            # room resolution (optional)
            room_obj = None
            room_no = payload.get('room_no') or payload.get('room')
            if room_no:
                if TreatmentRoom is not None:
                    room_obj = TreatmentRoom.objects.filter(room_no=room_no).first()
                    if not room_obj:
                        return JsonResponse({'error': 'room_not_found', 'room_no': room_no}, status=400)

            # therapists optional
            therapist_codes = payload.get('therapists') or []
            therapists = []
            if therapist_codes and TherapistModel is not None:
                qs = TherapistModel.objects.filter(therapist_code__in=therapist_codes)
                found_codes = set(t.therapist_code for t in qs)
                missing_ts = [c for c in therapist_codes if c not in found_codes]
                if missing_ts:
                    return JsonResponse({'error': 'therapists_not_found', 'missing': missing_ts}, status=400)
                therapists = list(qs)

            # ensure patient snapshot
            pat_no = str(payload['patient_reg_no'])
            ps_defaults = {
                'pat_name': payload.get('patient_name') or '',
                'pat_age': payload.get('patient_age') or '',
                'pat_sex': payload.get('patient_sex') or '',
                'pat_ref_id': payload.get('pat_ref_id') or ''
            }
            if PatientSnapshot is None:
                return JsonResponse({'error': 'PatientSnapshot model not found'}, status=500)
            ps, _ = PatientSnapshot.objects.get_or_create(pat_reg_no=pat_no, defaults=ps_defaults)
            changed = False
            if ps_defaults['pat_name'] and getattr(ps, 'pat_name', '') != ps_defaults['pat_name']:
                ps.pat_name = ps_defaults['pat_name']; changed = True
            if ps_defaults['pat_age'] and getattr(ps, 'pat_age', '') != ps_defaults['pat_age']:
                ps.pat_age = ps_defaults['pat_age']; changed = True
            if ps_defaults['pat_sex'] and getattr(ps, 'pat_sex', '') != ps_defaults['pat_sex']:
                ps.pat_sex = ps_defaults['pat_sex']; changed = True
            if ps_defaults['pat_ref_id'] and getattr(ps, 'pat_ref_id', '') != ps_defaults['pat_ref_id']:
                ps.pat_ref_id = ps_defaults['pat_ref_id']; changed = True
            if changed:
                ps.save()

            # create allocation and per-date bookings atomically (all-or-nothing)
            try:
                with transaction.atomic():
                    if TherapyAllocation is None or Booking is None or BookingItem is None or BookingAssignment is None:
                        return JsonResponse({'error': 'required models missing (TherapyAllocation/Booking/BookingItem/BookingAssignment)'}, status=500)

                    alloc = TherapyAllocation.objects.create(
                        patient=ps,
                        therapy_code=payload.get('therapy_code'),
                        therapy_name=payload.get('therapy_name'),
                        ext_int=payload.get('ext_int') or '',
                        timeslot=timeslot_obj,
                        room=room_obj,
                        items_groups=payload.get('items_groups') or [],
                        oil_class=payload.get('oil_class') or payload.get('oil_class_id') or '',
                        usage=payload.get('usage') or '',
                        procured_from=payload.get('procured') or payload.get('procured_from') or '',
                        from_date=fdate,
                        to_date=tdate,
                        days=(tdate - fdate).days + 1,
                        notes=payload.get('notes') or ''
                    )

                    bookings_created = []
                    for i in range((tdate - fdate).days + 1):
                        single_date = fdate + timedelta(days=i)
                        b = Booking.objects.create(allocation=alloc, date=single_date, timeslot=timeslot_obj, room=room_obj, status='scheduled')
                        created_items = []
                        for grp in payload.get('items_groups', []):
                            grp_dosage = grp.get('dosage','')
                            grp_uno = grp.get('uno','')
                            for it in grp.get('items', []):
                                bi = BookingItem.objects.create(
                                    booking=b,
                                    item_code=it.get('item_code') or it.get('id') or it.get('item_name'),
                                    item_name=it.get('item_name') or it.get('text') or '',
                                    dosage=it.get('dosage') or grp_dosage or '',
                                    uno=it.get('uno') or grp_uno or '',
                                    status='scheduled'
                                )
                                created_items.append({'item_code': bi.item_code, 'item_name': bi.item_name})
                        assigns = []
                        for t in therapists:
                            a = BookingAssignment.objects.create(booking=b, booking_item=None, therapist=t, role=getattr(t,'therapist_grade',''), assigned_for='booking', status='assigned')
                            assigns.append(getattr(t,'therapist_code',''))
                        bookings_created.append({'date': single_date.isoformat(), 'booking_id': b.pk, 'items_count': len(created_items), 'therapists': assigns})

                    # optional audit & notifications
                    try:
                        if AuditLog is not None:
                            AuditLog.objects.create(user=None, action='allocate_therapy', obj_type='TherapyAllocation', obj_id=str(alloc.pk), data={'bookings': bookings_created})
                    except Exception:
                        pass

                    try:
                        if NotificationQueue is not None and (payload.get('procured') or payload.get('procured_from')):
                            # queue a procurement notification aggregated for the allocation
                            NotificationQueue.objects.create(target_type='procurement', target_identifier=payload.get('procured') or payload.get('procured_from'), channel='internal', payload={'allocation_id': alloc.pk}, status='queued')
                    except Exception:
                        pass

                    return JsonResponse({'status': 'ok', 'allocation_id': alloc.pk, 'bookings_created': len(bookings_created)}, status=201)

            except IntegrityError as e:
                return JsonResponse({'error': 'conflict', 'details': str(e)}, status=409)

        # ---------- mark_completed ----------
        if action_post == 'mark_completed':
            booking_id = payload.get('booking_id')
            if not booking_id:
                return JsonResponse({'error': 'booking_id_required'}, status=400)
            if Booking is None:
                return JsonResponse({'error': 'Booking model missing'}, status=500)
            try:
                b = Booking.objects.get(pk=booking_id)
                b.status = 'completed'
                b.save(update_fields=['status','updated_at'] if hasattr(b,'updated_at') else ['status'])
                return JsonResponse({'status': 'ok', 'booking_id': booking_id})
            except Booking.DoesNotExist:
                return JsonResponse({'error': 'booking_not_found'}, status=404)

        # ---------- request_cancellation ----------
        if action_post == 'request_cancellation':
            alloc_id = payload.get('allocation_id')
            from_d = parse_date(payload.get('from_date') or '')
            to_d = parse_date(payload.get('to_date') or '')
            reason = payload.get('reason') or ''
            if not alloc_id or not from_d or not to_d:
                return JsonResponse({'error': 'allocation_id_and_dates_required'}, status=400)
            if TherapyAllocation is None or CancellationRequest is None:
                return JsonResponse({'error': 'required models missing (TherapyAllocation/CancellationRequest)'}, status=500)
            alloc_obj = TherapyAllocation.objects.filter(pk=alloc_id).first()
            if not alloc_obj:
                return JsonResponse({'error': 'allocation_not_found'}, status=404)
            CancellationRequest.objects.create(allocation=alloc_obj, requested_by=None, from_date=from_d, to_date=to_d, items=payload.get('items') or [], reason=reason, status='pending')
            return JsonResponse({'status': 'ok', 'allocation_id': alloc_id, 'from': from_d.isoformat(), 'to': to_d.isoformat()})

        return JsonResponse({'error': 'unknown_action'}, status=400)

    # ---------------- GET actions / template rendering ----------------
    action = (request.GET.get('action') or '').strip().lower()

    # search patients
    if action == 'search_patients':
        q = (request.GET.get('q') or '').strip()
        results = []
        if Registration is not None:
            try:
                qs = Registration.objects.using(EXTERNAL_DB_ALIAS).all()
                if q:
                    if q.isdigit():
                        qs = qs.filter(pat_reg_no__icontains=q)
                    else:
                        qs = qs.filter(pat_name__icontains=q)
                qs = qs[:50]
                for p in qs:
                    reg_no = getattr(p, 'pat_reg_no', '')
                    patient_type = _compute_patient_type_from_reg(reg_no)
                    results.append({
                        'pat_reg_no': reg_no,
                        'pat_name': getattr(p, 'pat_name', '') or '',
                        'pat_age': getattr(p, 'pat_age', '') or '',
                        'pat_sex': getattr(p, 'pat_sex', '') or '',
                        'pat_ref_id': getattr(p, 'pat_ref_id', '') or '',
                        'pat_op_reg_no': getattr(p, 'pat_op_reg_no', '') or '',
                        'patient_type': patient_type,
                    })
            except Exception:
                results = []
        return JsonResponse(results, safe=False)

    # get patient details from external DB
    if action == 'get_patient':
        reg_no = (request.GET.get('reg_no') or '').strip()
        if not reg_no or Registration is None:
            return JsonResponse({}, status=404)
        try:
            patient = Registration.objects.using(EXTERNAL_DB_ALIAS).get(pat_reg_no=reg_no)
        except Exception:
            return JsonResponse({}, status=404)
        patient_type = _compute_patient_type_from_reg(getattr(patient, 'pat_reg_no', ''))
        ip_no = getattr(patient, 'pat_op_reg_no', '') or getattr(patient, 'pat_reg_no', '')
        data = {
            'pat_reg_no': getattr(patient, 'pat_reg_no', ''),
            'pat_name': getattr(patient, 'pat_name', ''),
            'pat_age': getattr(patient, 'pat_age', ''),
            'pat_sex': getattr(patient, 'pat_sex', ''),
            'pat_room_no': getattr(patient, 'pat_room_no', ''),
            'pat_op_reg_no': getattr(patient, 'pat_op_reg_no', ''),
            'pat_ref_id': getattr(patient, 'pat_ref_id', ''),
            'ip_no': ip_no,
            'patient_type': patient_type,
        }
        return JsonResponse(data)

    # search therapies
    if action == 'search_therapies':
        q = (request.GET.get('q') or '').strip()
        results = []
        if TherapyDetails is not None:
            qs = TherapyDetails.objects.all()
            if q:
                qs = qs.filter(Q(therapy_name__icontains=q) | Q(therapy_code__icontains=q))
            qs = qs[:50]
            for t in qs:
                results.append({
                    'therapy_code': getattr(t, 'therapy_code', ''),
                    'therapy_name': getattr(t, 'therapy_name', '')
                })
        return JsonResponse(results, safe=False)

    # search items (external DB)
    if action == 'search_items':
        q = (request.GET.get('q') or '').strip()
        results = []
        if ItemMaster is not None:
            try:
                qs = ItemMaster.objects.using(EXTERNAL_DB_ALIAS).all()
                if q:
                    qs = qs.filter(Q(item_name__icontains=q) | Q(item_code__icontains=q))
                qs = qs[:50]
                for i in qs:
                    results.append({
                        'item_code': getattr(i, 'item_code', ''),
                        'item_name': getattr(i, 'item_name', ''),
                        'item_uom': getattr(i, 'item_uom', '') or ''
                    })
            except Exception:
                results = []
        return JsonResponse(results, safe=False)

    # masters (procured / oil / usage / slots etc.)
    if action == 'masters':
        typ = (request.GET.get('type') or '').strip().lower()
        model = None
        if typ == 'procured':
            model = Procured
        elif typ in ('oil', 'oilclass'):
            model = OilClass
        elif typ in ('usage', 'usagetype'):
            model = UsageType
        elif typ in ('ptime', 'prescriptiontime'):
            model = PrescriptionTime
        elif typ in ('scope', 'prescriptionscope'):
            model = PrescriptionScope

        if model is None:
            return JsonResponse([], safe=False)

        out = []
        try:
            qs = model.objects.filter(is_active=True).order_by('name')[:200]
            for x in qs:
                out.append({'id': getattr(x, 'id', None), 'name': getattr(x, 'name', str(x))})
        except Exception:
            out = []
        return JsonResponse(out, safe=False)

    # slots
    if action == 'slots':
        results = []
        if TimeSlot is not None:
            try:
                qs = TimeSlot.objects.all().order_by('slot_number')
                for s in qs:
                    start = getattr(s, 'start_time', '')
                    if hasattr(start, 'strftime'):
                        start_s = start.strftime('%H:%M')
                    else:
                        start_s = str(start)
                    results.append({'slot_number': getattr(s, 'slot_number', ''), 'start_time': start_s})
            except Exception:
                results = []
        return JsonResponse({'slots': results})

    # allocation_status (per-allocation bookings)
    if action == 'allocation_status':
        alloc_id = request.GET.get('allocation_id')
        if not alloc_id or TherapyAllocation is None:
            return JsonResponse({'error': 'allocation_id required'}, status=400)
        try:
            alloc = TherapyAllocation.objects.prefetch_related('bookings__items', 'bookings__assignments').select_related('timeslot', 'room', 'patient').get(pk=alloc_id)
        except TherapyAllocation.DoesNotExist:
            return JsonResponse({'error': 'not_found'}, status=404)
        out = {
            'allocation_id': alloc.pk,
            'therapy_name': alloc.therapy_name,
            'from_date': alloc.from_date.isoformat(),
            'to_date': alloc.to_date.isoformat(),
            'bookings': []
        }
        # iterate booking objects if present (field names may vary; using related_name 'bookings' expected)
        for b in alloc.bookings.all().order_by('date'):
            items = []
            try:
                for it in b.items.all():
                    items.append({'id': it.pk, 'item_code': it.item_code, 'item_name': it.item_name, 'status': it.status})
            except Exception:
                items = []
            therapists = []
            try:
                for a in b.assignments.all():
                    therapists.append(getattr(a.therapist, 'therapist_code', '') or getattr(a.therapist, 'id', ''))
            except Exception:
                therapists = []
            slot_s = ''
            try:
                slot_s = b.timeslot.start_time.strftime('%H:%M') if getattr(b, 'timeslot', None) and getattr(b.timeslot, 'start_time', None) else ''
            except Exception:
                slot_s = ''
            out['bookings'].append({
                'booking_id': b.pk,
                'date': b.date.isoformat(),
                'slot': slot_s,
                'room': getattr(b.room, 'room_no', None),
                'therapists': therapists,
                'status': getattr(b, 'status', ''),
                'items': items
            })
        return JsonResponse(out, safe=False)

    # patient_therapies: prefer new TherapyAllocation model
    if action == 'patient_therapies':
        reg = (request.GET.get('patient_reg_no') or '').strip()
        if not reg:
            return JsonResponse([], safe=False)
        if TherapyAllocation is not None:
            qs = TherapyAllocation.objects.filter(patient__pat_reg_no=str(reg)).select_related('timeslot','room').prefetch_related('bookings')
            out = []
            for a in qs:
                out.append({
                    'allocation_id': a.pk,
                    'therapy_code': a.therapy_code,
                    'therapy_name': a.therapy_name,
                    'ext_int': a.ext_int,
                    'slot': getattr(a.timeslot,'start_time',None).strftime('%H:%M') if getattr(a,'timeslot',None) and getattr(a.timeslot,'start_time',None) else '',
                    'oil_class': a.oil_class,
                    'usage': a.usage,
                    'procured': a.procured_from,
                    'from_date': a.from_date.isoformat(),
                    'to_date': a.to_date.isoformat(),
                    'days': a.days,
                    'items_groups': a.items_groups or []
                })
            return JsonResponse(out, safe=False)

        # fallback if you still have any other model (PatientTherapy)
        if PatientTherapy is not None:
            out = []
            try:
                qs = PatientTherapy.objects.filter(patient__pat_reg_no=reg)[:200]
                for pt in qs:
                    out.append({
                        'therapy_code': getattr(pt, 'therapy_code', getattr(pt, 'therapy_id', '')),
                        'therapy_name': getattr(pt, 'therapy_name', '') or str(getattr(pt, 'therapy', '')),
                        'ext_int': getattr(pt, 'ext_int', ''),
                        'slot': getattr(pt, 'slot', '') and (getattr(pt.slot, 'start_time', '') if hasattr(pt, 'slot') else getattr(pt, 'slot')),
                        'oil_class': getattr(pt, 'oil_class', ''),
                        'usage': getattr(pt, 'usage', ''),
                        'procured': getattr(pt, 'procured_from', ''),
                        'from_date': getattr(pt, 'from_date', ''),
                        'to_date': getattr(pt, 'to_date', ''),
                        'days': getattr(pt, 'days', ''),
                        'items_groups': []
                    })
            except Exception:
                out = []
            return JsonResponse(out, safe=False)

        return JsonResponse([], safe=False)

    # --------------- RENDER TEMPLATE WITH masters context ---------------
    masters_context = {}

    # procured list
    try:
        if Procured is not None:
            qs = Procured.objects.filter(is_active=True).order_by('name')[:200]
            masters_context['procured_list'] = [{'id': getattr(x, 'id', None), 'name': getattr(x, 'name', str(x))} for x in qs]
        else:
            masters_context['procured_list'] = []
    except Exception:
        masters_context['procured_list'] = []

    # oil list
    try:
        if OilClass is not None:
            qs = OilClass.objects.filter(is_active=True).order_by('name')[:200]
            masters_context['oil_list'] = [{'id': getattr(x,'id', None), 'name': getattr(x,'name', str(x))} for x in qs]
        else:
            masters_context['oil_list'] = []
    except Exception:
        masters_context['oil_list'] = []

    # usage list
    try:
        if UsageType is not None:
            qs = UsageType.objects.filter(is_active=True).order_by('name')[:200]
            masters_context['usage_list'] = [{'id': getattr(x,'id', None), 'name': getattr(x,'name', str(x))} for x in qs]
        else:
            masters_context['usage_list'] = []
    except Exception:
        masters_context['usage_list'] = []

    # time slots
    try:
        if TimeSlot is not None:
            slots = []
            for s in TimeSlot.objects.all().order_by('slot_number'):
                start = getattr(s, 'start_time', '')
                if hasattr(start, 'strftime'):
                    start_s = start.strftime('%H:%M')
                else:
                    start_s = str(start)
                slots.append({'slot_number': getattr(s, 'slot_number', ''), 'start_time': start_s})
            masters_context['slots'] = slots
        else:
            masters_context['slots'] = []
    except Exception:
        masters_context['slots'] = []

    return render(request, 'updated_dash/therapy_entry.html', context={'masters': masters_context})

















#algorithm
import json
from datetime import datetime, timedelta, time, date

from django.http import JsonResponse, HttpResponseBadRequest
from django.views.decorators.http import require_POST
from django.views.decorators.csrf import csrf_exempt
from django.db import transaction, IntegrityError

# import your new models (adjust the app name if different)
from .models import (
    PatientSnapshot,
    TherapyAllocation,
    Booking,
    BookingItem,
    BookingAssignment,
    NotificationQueue,
    AuditLog,
    AllocationChange,
   
)
from Patient.models import Therapist, TimeSlot,TreatmentRoom # or from therapies.models if Therapist located there

# helper to iterate date range inclusive
def daterange(start_date: date, end_date: date):
    d = start_date
    while d <= end_date:
        yield d
        d += timedelta(days=1)

def parse_date(s):
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except Exception:
        return None

def parse_time_hhmm(s):
    try:
        t = datetime.strptime(s, "%H:%M").time()
        return t
    except Exception:
        return None

@csrf_exempt
@require_POST
def allocate_therapy(request):
    """
    POST JSON payload expected (example below).
    Will create TherapyAllocation, Bookings, BookingItems, BookingAssignments, Notifications, Audit.
    """
    try:
        payload = json.loads(request.body)
    except json.JSONDecodeError:
        return HttpResponseBadRequest("Invalid JSON")

    # Required top-level fields (front-end should send these)
    # patient_reg_no (string), therapy_code, therapy_name, from_date, to_date
    required = ["patient_reg_no", "therapy_code", "therapy_name", "from_date", "to_date", "items_groups"]
    missing = [k for k in required if k not in payload]
    if missing:
        return JsonResponse({"error": "Missing required fields", "missing": missing}, status=400)

    # parse dates
    from_date = parse_date(payload["from_date"])
    to_date = parse_date(payload["to_date"])
    if not from_date or not to_date or from_date > to_date:
        return JsonResponse({"error": "Invalid from_date / to_date"}, status=400)

    # timeslot: accept either slot_number (int) or "HH:MM" string
    timeslot = None
    if payload.get("timeslot_slot_number") is not None:
        try:
            timeslot = TimeSlot.objects.get(slot_number=int(payload["timeslot_slot_number"]))
        except TimeSlot.DoesNotExist:
            return JsonResponse({"error": "TimeSlot with that slot_number not found"}, status=400)
    elif payload.get("timeslot"):
        t = parse_time_hhmm(payload["timeslot"])
        if not t:
            return JsonResponse({"error": "Invalid timeslot format, expected HH:MM"}, status=400)
        timeslot = TimeSlot.objects.filter(start_time=t).first()
        if not timeslot:
            # Optionally create a timeslot if you want; for safety we require an existing one:
            return JsonResponse({"error": "TimeSlot with that start_time not found"}, status=400)

    # room (optional)
    room = None
    room_no = payload.get("room_no")  # optional string
    if room_no:
        room = TreatmentRoom.objects.filter(room_no=room_no).first()
        if not room:
            return JsonResponse({"error": f"TreatmentRoom {room_no} not found"}, status=400)

    # therapists: optional list of therapist_codes that should be assigned for every date
    therapist_codes = payload.get("therapists") or []
    therapists = []
    if therapist_codes:
        therapists_qs = Therapist.objects.filter(therapist_code__in=therapist_codes)
        found_codes = set(t.therapist_code for t in therapists_qs)
        missing_ts = [c for c in therapist_codes if c not in found_codes]
        if missing_ts:
            return JsonResponse({"error": "Some therapists not found", "missing_therapists": missing_ts}, status=400)
        therapists = list(therapists_qs)

    # items_groups expected as list of groups:
    # [{ "items":[{"item_code":"KAS","item_name":"Kashayam"}, ...], "dosage":"10 ml", "uno":"1" }, ...]
    items_groups = payload.get("items_groups")
    if not isinstance(items_groups, list) or len(items_groups) == 0:
        return JsonResponse({"error": "items_groups must be a non-empty list"}, status=400)

    # optional masters
    oil_class = payload.get("oil_class") or ""
    usage = payload.get("usage") or ""
    procured_from = payload.get("procured_from") or ""
    ext_int = payload.get("ext_int") or ""
    allocated_by_user_id = payload.get("allocated_by_user_id", None)

    # get request.user if available (prefer that)
    allocated_by_user = getattr(request, "user", None) if getattr(request, "user", None) and request.user.is_authenticated else None

    # create / update patient snapshot
    pat_reg_no = str(payload["patient_reg_no"])
    pat_name = payload.get("patient_name")
    pat_age = payload.get("patient_age")
    pat_sex = payload.get("patient_sex")
    pat_ref_id = payload.get("pat_ref_id")

    patient_snapshot, _ = PatientSnapshot.objects.get_or_create(
        pat_reg_no=pat_reg_no,
        defaults={
            "pat_name": pat_name,
            "pat_age": pat_age,
            "pat_sex": pat_sex,
            "pat_ref_id": pat_ref_id
        }
    )
    # update small fields if provided
    changed = False
    if pat_name and patient_snapshot.pat_name != pat_name:
        patient_snapshot.pat_name = pat_name; changed = True
    if pat_age and patient_snapshot.pat_age != pat_age:
        patient_snapshot.pat_age = pat_age; changed = True
    if pat_sex and patient_snapshot.pat_sex != pat_sex:
        patient_snapshot.pat_sex = pat_sex; changed = True
    if pat_ref_id and patient_snapshot.pat_ref_id != pat_ref_id:
        patient_snapshot.pat_ref_id = pat_ref_id; changed = True
    if changed:
        patient_snapshot.save(update_fields=["pat_name","pat_age","pat_sex","pat_ref_id","updated_at"])

    # start atomic transaction for entire allocation (all-or-nothing)
    try:
        with transaction.atomic():
            allocation = TherapyAllocation.objects.create(
                patient=patient_snapshot,
                therapy_code=payload["therapy_code"],
                therapy_name=payload["therapy_name"],
                ext_int=ext_int,
                timeslot=timeslot,
                room=room,
                items_groups=items_groups,
                oil_class=oil_class,
                usage=usage,
                procured_from=procured_from,
                from_date=from_date,
                to_date=to_date,
                days=(to_date - from_date).days + 1,
                required_therapist_roles=payload.get("required_therapist_roles", []),
                allocated_by=allocated_by_user if allocated_by_user else None,
                notes=payload.get("notes","")
            )

            created_bookings = []
            notifications_to_enqueue = []

            # iterate dates and create Booking, BookingItem, BookingAssignment
            for d in daterange(from_date, to_date):
                # create booking (UniqueConstraint on room/date/timeslot will guard)
                booking = Booking.objects.create(
                    allocation=allocation,
                    date=d,
                    timeslot=timeslot,
                    room=room,
                    status="scheduled"
                )

                # create items for this booking
                created_items = []
                for grp in items_groups:
                    grp_dosage = grp.get("dosage","")
                    grp_uno = grp.get("uno","")
                    for it in grp.get("items", []):
                        bi = BookingItem.objects.create(
                            booking=booking,
                            item_code=it.get("item_code"),
                            item_name=it.get("item_name"),
                            dosage=it.get("dosage") or grp_dosage or "",
                            uno=it.get("uno") or grp_uno or "",
                            status="scheduled"
                        )
                        created_items.append({
                            "item_code": bi.item_code,
                            "item_name": bi.item_name,
                            "dosage": bi.dosage,
                            "uno": bi.uno
                        })

                # assign therapists (same therapists assigned to each date)
                created_assignments = []
                for t in therapists:
                    assign = BookingAssignment.objects.create(
                        booking=booking,
                        booking_item=None,
                        therapist=t,
                        role=getattr(t, "therapist_grade", ""),
                        assigned_for="booking",
                        status="assigned"
                    )
                    created_assignments.append(assign)

                created_bookings.append({
                    "date": d.isoformat(),
                    "booking_id": booking.pk,
                    "items_count": len(created_items),
                    "therapists": [t.therapist_code for t in therapists],
                    "room_no": room.room_no if room else None
                })

                # prepare a notification entry for procurement / patient / therapists (simple aggregated payload)
                if procured_from:
                    notifications_to_enqueue.append({
                        "target_type": "procurement",
                        "target_identifier": procured_from,
                        "channel": "webhook",
                        "payload": {
                            "action": "reserve",
                            "allocation_id": allocation.pk,
                            "patient_reg_no": patient_snapshot.pat_reg_no,
                            "date": d.isoformat(),
                            "items": created_items
                        }
                    })

            # create notification rows
            for n in notifications_to_enqueue:
                NotificationQueue.objects.create(
                    target_type=n["target_type"],
                    target_identifier=n.get("target_identifier",""),
                    channel=n.get("channel","webhook"),
                    payload=n["payload"],
                    status="queued"
                )

            # audit + allocation change
            AuditLog.objects.create(
                user=allocated_by_user,
                action="allocate_therapy",
                obj_type="TherapyAllocation",
                obj_id=str(allocation.pk),
                data={"created_bookings": created_bookings}
            )
            AllocationChange.objects.create(
                allocation=allocation,
                changed_by=allocated_by_user,
                change_type="create_allocation",
                diff={"added": created_bookings},
                reason=payload.get("reason","")
            )

            # commit transaction end
            return JsonResponse({
                "status": "success",
                "allocation_id": allocation.pk,
                "bookings_created": len(created_bookings)
            }, status=201)

    except IntegrityError as e:
        # detect conflicts and return readable info
        conflict_info = {"error": "conflict", "details": str(e)}
        # try to detect room conflict: find any date where a Booking exists for same room/date/timeslot
        if room and timeslot:
            conflicting = Booking.objects.filter(room=room, date__gte=from_date, date__lte=to_date, timeslot=timeslot).values("date","pk")
            if conflicting.exists():
                conflict_info["room_conflicts"] = list(conflicting)
        # detect therapist conflicts
        t_conflicts = []
        for t in therapists:
            # any BookingAssignment for therapist in that date/slot
            ass_conf = BookingAssignment.objects.filter(therapist=t, booking_date__gte=from_date, booking_date__lte=to_date, booking_timeslot=timeslot, status__in=["assigned","BOOKED"]).values("booking_date","id")
            if ass_conf.exists():
                t_conflicts.append({"therapist_code": t.therapist_code, "conflicts": list(ass_conf)})
        if t_conflicts:
            conflict_info["therapist_conflicts"] = t_conflicts

        return JsonResponse(conflict_info, status=409)
    except Exception as exc:
        return JsonResponse({"error": "server_error", "details": str(exc)}, status=500)
