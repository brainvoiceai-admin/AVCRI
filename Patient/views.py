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
from final_allocation import expand_therapies_for_visit

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
    patient_reg_no = request.session.get('patient_reg_no')
    if not patient_reg_no:
        return redirect('patient_lookup')

    patient = get_object_or_404(Registration.objects.using(DB_ALIAS), pat_reg_no=patient_reg_no)
    all_prescription_items = ItemMaster.objects.using(DB_ALIAS).all()

    if request.method == 'POST':
        try:
            data = json.loads(request.body.decode('utf-8'))
            prescription_rows = data.get('prescription_data', [])
        except json.JSONDecodeError:
            return JsonResponse({'status': 'error', 'message': 'Invalid JSON data'}, status=400)

        request.session['prescription_rows_data'] = prescription_rows

        if prescription_rows:
            return JsonResponse({'status': 'success'}, status=200)
        return JsonResponse({'status': 'error', 'message': 'No prescription data provided.'}, status=400)

    context = {
        'patient': patient,
        'all_prescription_items': all_prescription_items,
    }
    return render(request, 'dashboards/doctorsAndHelpDesk/prescription_entry.html', context)


def review_view(request):
    patient_reg_no = request.session.get('patient_reg_no')
    if not patient_reg_no:
        return redirect('patient_lookup')

    patient = get_object_or_404(Registration.objects.using(DB_ALIAS), pat_reg_no=patient_reg_no)

    try:
        vip_status = "Yes" if Repeated_Visitors.objects.using(DB_ALIAS).filter(register_number=patient_reg_no, is_vip=1).exists() else "No"
    except Exception:
        vip_status = "N/A"

    from_date = request.session.get('from_date')
    to_date = request.session.get('to_date')
    admission_days = request.session.get('admission_days')
    is_ip_or_op = request.session.get('is_ip_or_op')
    repeated_status = request.session.get('repeated_status')
    therapy_data = request.session.get('therapy_rows_data', [])
    prescription_data = request.session.get('prescription_rows_data', [])

    # Resolve item names for therapies (supports multiple items per therapy)
    for therapy_row in therapy_data:
        items = therapy_row.get('items') or []
        resolved = []
        for it in items:
            item_code = it.get('item_code') or it.get('item')
            if item_code:
                try:
                    item_master = ItemMaster.objects.using(DB_ALIAS).get(item_code=item_code)
                    resolved.append({
                        'item_code': item_code,
                        'item_name': item_master.item_name,
                        'oil_class': it.get('oil_class') or '',
                        'usage': it.get('usage') or '',
                        'procured': it.get('procured') or '',
                    })
                except ItemMaster.DoesNotExist:
                    resolved.append({
                        'item_code': item_code,
                        'item_name': 'Item not found',
                        'oil_class': it.get('oil_class') or '',
                        'usage': it.get('usage') or '',
                        'procured': it.get('procured') or '',
                    })
        therapy_row['resolved_items'] = resolved

    # Resolve prescription row item names and ensure from/to/days fields are present
    for pres_row in prescription_data:
        item_code = pres_row.get('item') or pres_row.get('item_code')
        if item_code:
            try:
                item_master = ItemMaster.objects.using(DB_ALIAS).get(item_code=item_code)
                pres_row['item_name'] = item_master.item_name
            except ItemMaster.DoesNotExist:
                pres_row['item_name'] = 'Item not found'
        # ensure date fields exist (they come from frontend)
        pres_row['from_date'] = pres_row.get('from_date') or ''
        pres_row['to_date'] = pres_row.get('to_date') or ''
        pres_row['days'] = pres_row.get('days') or 0
        pres_row['procured_from'] = pres_row.get('procured_from') or pres_row.get('procured_from') or ''

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

DEFAULT_DB = 'default'
def submit_all_data(request):
    patient_reg_no = request.session.get('patient_reg_no')
    if not patient_reg_no:
        return redirect('patient_lookup')

    patient = get_object_or_404(Registration.objects.using(DB_ALIAS), pat_reg_no=patient_reg_no)

    from_date_str = request.session.get('from_date')
    to_date_str = request.session.get('to_date')
    record = Repeated_Visitors.objects.using(DEFAULT_DB).filter(register_number=patient_reg_no).first()
    repeated_status = "Yes" if record and getattr(record, 'total_visits', 0) > 2 else "No"

    from_date = parse_date_safe(from_date_str)
    to_date = parse_date_safe(to_date_str)

    therapy_rows_data = request.session.get('therapy_rows_data', [])
    prescription_rows_data = request.session.get('prescription_rows_data', [])

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

            therapy = store_Therapy.objects.using(DEFAULT_DB).create(
                visit=visit,
                patient_id=int(patient_reg_no),
                therapy_name=row.get('therapy_name'),
                ext_int=row.get('ext_int') or '',
                procured=row.get('procured') or '',
                from_date=therapy_from_date,
                to_date=therapy_to_date,
                days=therapy_days,
            )

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

    # Run allocation outside transaction (may be long-running)
    try:
        tasks = expand_therapies_for_visit(visit.id)
        # optional logging here
    except Exception as e:
        # log exception
        pass

    # Clear session keys
    for key in ['patient_reg_no', 'from_date', 'to_date', 'admission_days', 'is_ip_or_op', 'therapy_rows_data', 'prescription_rows_data']:
        request.session.pop(key, None)

    return redirect('patient_lookup')






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

class PatientListView(ListView):
    model = Visit
    template_name = "dashboards/prescriptions/patient_list.html"   # see templates section below
    context_object_name = "visits"
    paginate_by = 25

    def get_queryset(self):
        # Gather active bookings (status='BOOKED')
        room_qs = RoomBooking.objects.filter(status='BOOKED')
        therapist_qs = TherapistBooking.objects.filter(status='BOOKED')

        patient_ids_from_bookings = set(
            list(room_qs.values_list('patient_id', flat=True)) +
            list(therapist_qs.values_list('patient_id', flat=True))
        )
        patient_ids_from_bookings = {p for p in patient_ids_from_bookings if p is not None and p != ""}

        visit_ids_from_bookings = set(
            list(room_qs.exclude(visit__isnull=True).values_list('visit__id', flat=True)) +
            list(therapist_qs.exclude(visit__isnull=True).values_list('visit__id', flat=True))
        )

        queries = Q()
        if visit_ids_from_bookings:
            queries |= Q(id__in=list(visit_ids_from_bookings))
        if patient_ids_from_bookings and hasattr(Visit, 'patient_id'):
            queries |= Q(patient_id__in=list(patient_ids_from_bookings))

        if queries:
            qs = Visit.objects.filter(queries).distinct().order_by('-id')
        else:
            qs = Visit.objects.none()
        return qs
    

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
        return redirect(request.META.get("HTTP_REFERER", reverse("patient:patient_list")))

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
        return redirect(request.META.get("HTTP_REFERER", reverse("patient:patient_list")))

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

@login_required
def update_therapy_item(request, item_id):
    from MySql_Data_pull.models import store_TherapyItem
    item = get_object_or_404(store_TherapyItem, id=item_id)

    if request.method == "POST":
        # accept posted values (keep previous if empty)
        item.usage = request.POST.get("usage", item.usage)
        from_date = request.POST.get("from_date", None)
        to_date = request.POST.get("to_date", None)
        days = request.POST.get("days", None)
        procured = request.POST.get("procured", item.procured)

        if from_date:
            item.from_date = from_date
        if to_date:
            item.to_date = to_date
        try:
            item.days = int(days) if days not in (None, "") else item.days
        except ValueError:
            pass
        item.procured = procured
        item.updated_at = timezone.now()
        item.save(update_fields=["usage", "from_date", "to_date", "days", "procured", "updated_at"])
        messages.success(request, "Therapy item updated.")
        return redirect(request.META.get("HTTP_REFERER", reverse("patient:patient_list")))

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
        return redirect(request.META.get("HTTP_REFERER", reverse("patient:patient_list")))

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

