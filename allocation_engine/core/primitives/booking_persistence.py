"""Safe transactional persistence helpers for RoomBooking and TherapistBooking."""
from contextlib import nullcontext
from django.db import IntegrityError, transaction


def _savepoint_if_atomic(use_atomic=False):
    """Return a transaction/savepoint context when requested or already inside an outer atomic block."""
    if use_atomic or transaction.get_connection().in_atomic_block:
        return transaction.atomic()
    return nullcontext()


def create_room_booking_safe(
    room,
    date,
    time_slot,
    therapy_name,
    patient_id,
    visit,
    *,
    therapy_allocation=None,
    use_atomic=False,
    refresh=True,
):
    """
    Create RoomBooking safely.

    Args:
        visit: Sheduling.Booking instance (for RoomBooking.visit FK).
        therapy_allocation: Optional Sheduling.TherapyAllocation instance (for RoomBooking.therapy FK).
        use_atomic: If True, wraps in transaction.atomic() (reshedule.py / standalone callers).
                    If False, runs inside caller's existing transaction (final_allocation.py).
        refresh: If True, calls full save() + refresh_from_db() when updating FKs (SQLite FK safety).
    """
    from Patient.models import RoomBooking
    from Sheduling.models import TherapyAllocation

    resolved_allocation = None
    if isinstance(therapy_allocation, TherapyAllocation):
        resolved_allocation = therapy_allocation
    elif therapy_allocation is None and visit is not None:
        candidate_alloc = getattr(visit, 'allocation', None)
        if isinstance(candidate_alloc, TherapyAllocation):
            resolved_allocation = candidate_alloc

    ctx = _savepoint_if_atomic(use_atomic=use_atomic)
    try:
        with ctx:
            defaults = {
                'therapy_name': therapy_name,
                'patient_id': patient_id,
                'visit': visit,
            }
            if resolved_allocation is not None:
                defaults['therapy'] = resolved_allocation

            rb, created = RoomBooking.objects.get_or_create(
                room=room,
                date=date,
                time_slot=time_slot,
                status='BOOKED',
                defaults=defaults,
            )

            needs_save = False
            update_fields = []
            if not created and rb.visit is None and visit is not None:
                rb.visit = visit
                needs_save = True
                update_fields.append('visit')
            elif created and rb.visit != visit and visit is not None:
                rb.visit = visit
                needs_save = True
                update_fields.append('visit')

            if resolved_allocation is not None:
                explicit_alloc_override = (
                    isinstance(therapy_allocation, TherapyAllocation)
                    and (rb.visit_id is None or rb.visit_id == getattr(visit, 'pk', None))
                )
                if (
                    rb.therapy_id is None
                    or (created and rb.therapy_id != resolved_allocation.id)
                    or (explicit_alloc_override and rb.therapy_id != resolved_allocation.id)
                ):
                    rb.therapy = resolved_allocation
                    needs_save = True
                    update_fields.append('therapy')

            if needs_save:
                if refresh:
                    rb.save()
                    rb.refresh_from_db()
                else:
                    rb.save(update_fields=update_fields)
            return rb, created
    except IntegrityError:
        rb = RoomBooking.objects.filter(
            room=room, date=date, time_slot=time_slot, status='BOOKED'
        ).first()
        if rb:
            recovery_fields = []
            if rb.visit is None and visit is not None:
                rb.visit = visit
                recovery_fields.append('visit')
            if resolved_allocation is not None and rb.therapy_id is None:
                rb.therapy = resolved_allocation
                recovery_fields.append('therapy')
            if recovery_fields:
                try:
                    if refresh:
                        rb.save()
                        rb.refresh_from_db()
                    else:
                        rb.save(update_fields=recovery_fields)
                except Exception as e:
                    print(f"[DEBUG create_room_booking_safe] Error updating recovery fields: {e}")
        return rb, False


def create_therapist_booking_safe(
    therapist,
    date,
    time_slot,
    therapy_name,
    patient_id,
    visit,
    is_bathing=False,
    *,
    use_atomic=False,
    resolve_therapy_fk=True,
    refresh=True,
):
    """
    Create TherapistBooking safely, enforcing daily session cap (max 6) and treatment omissions.

    Args:
        use_atomic: True for reshedule.py / standalone callers; False inside final_allocation's atomic block.
        resolve_therapy_fk: If True, resolves and populates TherapistBooking.therapy (TherapyMaster FK).
        refresh: If True, uses full save() + refresh_from_db() for SQLite FK persistence.
    Returns:
        (therapist_booking_instance_or_None, created_bool)
    """
    from Patient.models import TherapistBooking
    from masters.models import TherapyMaster, TherapistMaster

    # Resolve therapist to TherapistMaster instance if needed (e.g. int/str/Patient.Therapist)
    therapist_master = None
    if isinstance(therapist, TherapistMaster):
        therapist_master = therapist
    elif hasattr(therapist, 'therapist_code'):
        therapist_master = TherapistMaster.objects.filter(
            therapist_code=therapist.therapist_code, is_active=True
        ).first()
    elif isinstance(therapist, int) and not isinstance(therapist, bool):
        therapist_master = TherapistMaster.objects.filter(pk=therapist).first()
    elif isinstance(therapist, str):
        code_or_pk = therapist.strip()
        if code_or_pk.isdigit():
            therapist_master = TherapistMaster.objects.filter(pk=int(code_or_pk)).first()
            if therapist_master is None:
                therapist_master = TherapistMaster.objects.filter(therapist_code=code_or_pk).first()
        elif code_or_pk:
            therapist_master = TherapistMaster.objects.filter(therapist_code=code_or_pk).first()

    if therapist_master is None:
        return None, False

    booking_therapist = therapist_master

    # CRITICAL: Final atomic DB check - prevent creating booking if therapist already has 6 sessions
    if booking_therapist and date:
        current_session_count = TherapistBooking.objects.filter(
            therapist=booking_therapist,
            date=date,
            status='BOOKED',
        ).count()
        if current_session_count >= 6:
            print(
                f"[DEBUG create_therapist_booking_safe] BLOCKED: Therapist "
                f"{getattr(booking_therapist, 'therapist_code', 'UNKNOWN')} already has "
                f"{current_session_count} sessions (max 6) - refusing to create booking"
            )
            return None, False

    therapy_obj = None
    if resolve_therapy_fk:
        try:
            therapy_code = getattr(visit, "therapy_code", None) if visit is not None else None
            visit_therapy_name = getattr(visit, "therapy_name", None) if visit is not None else None
            if therapy_code:
                therapy_obj = TherapyMaster.objects.filter(therapy_code=therapy_code).first()
            if not therapy_obj and (therapy_name or visit_therapy_name):
                name_for_lookup = therapy_name or visit_therapy_name
                therapy_obj = TherapyMaster.objects.filter(therapy_name__iexact=name_for_lookup).first()
        except Exception as e:
            print(f"[DEBUG create_therapist_booking_safe] Error resolving TherapyMaster for '{therapy_name}': {e}")

    # Treatment Omission check: strictly prevent booking if therapist has approved omission
    if booking_therapist:
        try:
            from masters.models import is_therapist_omitted_for_treatment
            treatment_to_check = (
                therapy_obj
                or therapy_name
                or getattr(visit, 'therapy_name', None)
                or getattr(visit, 'therapy_code', None)
            )
            if treatment_to_check and is_therapist_omitted_for_treatment(booking_therapist, treatment_to_check):
                print(
                    f"[DEBUG create_therapist_booking_safe] BLOCKED: Therapist "
                    f"{getattr(booking_therapist, 'therapist_code', 'UNKNOWN')} has approved omission "
                    f"for treatment '{treatment_to_check}' - refusing to create booking"
                )
                return None, False
        except Exception as e:
            print(f"[DEBUG create_therapist_booking_safe] Error in treatment omission check: {e}")

    is_ht = getattr(booking_therapist, 'is_helping_therapist', False)
    ctx = _savepoint_if_atomic(use_atomic=use_atomic)

    try:
        with ctx:
            tb_defaults = {
                'therapy_name': therapy_name,
                'patient_id': patient_id,
                'visit': visit,
            }
            if resolve_therapy_fk:
                tb_defaults['therapy'] = therapy_obj
            if hasattr(TherapistBooking, 'is_helping_therapist_assignment'):
                tb_defaults['is_helping_therapist_assignment'] = is_ht

            tb, created = TherapistBooking.objects.get_or_create(
                therapist=booking_therapist,
                date=date,
                time_slot=time_slot,
                status='BOOKED',
                defaults=tb_defaults,
            )

            needs_save = False
            update_fields = []
            if (refresh and tb.visit != visit and visit is not None) or (not refresh and not created and tb.visit is None and visit is not None):
                tb.visit = visit
                update_fields.append('visit')
                if refresh and patient_id:
                    tb.patient_id = patient_id
                    update_fields.append('patient_id')
                needs_save = True

            if resolve_therapy_fk and therapy_obj is not None and getattr(tb, "therapy_id", None) is None:
                tb.therapy = therapy_obj
                update_fields.append('therapy')
                needs_save = True

            if hasattr(tb, 'is_helping_therapist_assignment') and tb.is_helping_therapist_assignment != is_ht:
                tb.is_helping_therapist_assignment = is_ht
                update_fields.append('is_helping_therapist_assignment')
                needs_save = True

            if needs_save:
                if refresh:
                    tb.save()
                    tb.refresh_from_db()
                else:
                    tb.save(update_fields=update_fields)

            try:
                if is_bathing and hasattr(tb, 'is_bathing'):
                    b_count = getattr(visit, 'bathing_therapists_count', 0) if visit else 0
                    if b_count <= 1 and visit and time_slot:
                        TherapistBooking.objects.filter(
                            visit=visit,
                            date=date,
                            time_slot=time_slot,
                            status='BOOKED',
                        ).exclude(pk=tb.pk).update(is_bathing=False)

                    if getattr(tb, 'is_bathing', False) != bool(is_bathing):
                        tb.is_bathing = bool(is_bathing)
                        if refresh:
                            tb.save()
                            tb.refresh_from_db()
                        else:
                            tb.save(update_fields=['is_bathing'])
            except Exception as e:
                print(f"[DEBUG create_therapist_booking_safe] Error setting is_bathing: {e}")

            return tb, created
    except IntegrityError:
        tb = TherapistBooking.objects.filter(
            therapist=booking_therapist, date=date, time_slot=time_slot, status='BOOKED'
        ).first()
        try:
            if tb and is_bathing and hasattr(tb, 'is_bathing'):
                if tb.visit and tb.time_slot:
                    TherapistBooking.objects.filter(
                        visit=tb.visit,
                        date=tb.date,
                        time_slot=tb.time_slot,
                        status='BOOKED',
                    ).exclude(pk=tb.pk).update(is_bathing=False)
                if not tb.is_bathing:
                    tb.is_bathing = True
                    tb.save(update_fields=['is_bathing'])
        except Exception as e:
            print(f"[DEBUG create_therapist_booking_safe] Error updating is_bathing on existing: {e}")

        if tb:
            tb_recovery_fields = []
            if tb.visit is None and visit is not None:
                tb.visit = visit
                tb_recovery_fields.append('visit')
            if resolve_therapy_fk and therapy_obj is not None and getattr(tb, 'therapy_id', None) is None:
                tb.therapy = therapy_obj
                tb_recovery_fields.append('therapy')
            if tb_recovery_fields:
                try:
                    tb.save(update_fields=tb_recovery_fields)
                except Exception as e:
                    print(f"[DEBUG create_therapist_booking_safe] Error updating recovery fields: {e}")
        return tb, False


def safe_cancel_patient_bookings(
    allocation,
    date_from=None,
    date_to=None,
    dates=None,
    booking_ids=None,
    timeslot=None,
    slot_ids=None,
):
    """
    Safely cancel Patient.TherapistBooking and Patient.RoomBooking rows associated with
    a TherapyAllocation / set of Booking IDs without failing on UniqueConstraint
    (unique_therapist_date_slot_status / unique_room_date_slot_status).
    If a CANCELLED row already exists for the same (therapist/room, date, time_slot),
    deletes the redundant BOOKED row instead of raising IntegrityError.
    """
    from Patient.models import TherapistBooking as TB, RoomBooking as RB

    active_statuses = ['BOOKED', 'scheduled']

    def _cancel_tb_qs(qs):
        for tb in list(qs.filter(status__in=active_statuses)):
            try:
                dup_exists = TB.objects.filter(
                    therapist_id=tb.therapist_id,
                    date=tb.date,
                    time_slot_id=tb.time_slot_id,
                    status='CANCELLED',
                ).exclude(pk=tb.pk).exists()
                if dup_exists:
                    tb.delete()
                else:
                    with _savepoint_if_atomic():
                        TB.objects.filter(pk=tb.pk).update(status='CANCELLED')
            except IntegrityError:
                try:
                    tb.delete()
                except Exception:
                    pass
            except Exception as exc:
                print(f"[safe_cancel_patient_bookings] Error cancelling TherapistBooking pk={tb.pk}: {exc}")

    def _cancel_rb_qs(qs):
        for rb in list(qs.filter(status__in=active_statuses)):
            try:
                dup_exists = RB.objects.filter(
                    room_id=rb.room_id,
                    date=rb.date,
                    time_slot_id=rb.time_slot_id,
                    status='CANCELLED',
                ).exclude(pk=rb.pk).exists()
                if dup_exists:
                    rb.delete()
                else:
                    with _savepoint_if_atomic():
                        RB.objects.filter(pk=rb.pk).update(status='CANCELLED')
            except IntegrityError:
                try:
                    rb.delete()
                except Exception:
                    pass
            except Exception as exc:
                print(f"[safe_cancel_patient_bookings] Error cancelling RoomBooking pk={rb.pk}: {exc}")

    date_filter = {}
    if dates is not None:
        date_filter['date__in'] = list(dates)
    else:
        if date_from is not None:
            date_filter['date__gte'] = date_from
        if date_to is not None:
            date_filter['date__lte'] = date_to

    slot_filter = {}
    if timeslot is not None:
        slot_filter['time_slot'] = timeslot
    elif slot_ids:
        slot_filter['time_slot_id__in'] = list(slot_ids)

    # 1) TherapistBookings linked to this allocation
    tb_alloc_qs = TB.objects.filter(visit=allocation, **date_filter)
    if timeslot is not None:
        tb_alloc_qs = tb_alloc_qs.filter(time_slot=timeslot)
    _cancel_tb_qs(tb_alloc_qs)

    # 2) Orphaned TherapistBookings for this patient (no visit FK), scoped to matching slot(s)
    if getattr(allocation, 'patient_id', None) and slot_filter:
        _cancel_tb_qs(
            TB.objects.filter(
                patient_id=allocation.patient_id,
                visit__isnull=True,
                **date_filter,
                **slot_filter,
            )
        )

    # 3) RoomBookings linked to the exact Booking rows being cancelled
    if booking_ids:
        rb_visit_qs = RB.objects.filter(visit_id__in=list(booking_ids))
        if timeslot is not None:
            rb_visit_qs = rb_visit_qs.filter(time_slot=timeslot)
        _cancel_rb_qs(rb_visit_qs)

    # 4) RoomBookings linked to this allocation via therapy FK
    rb_alloc_qs = RB.objects.filter(therapy=allocation, **date_filter)
    if timeslot is not None:
        rb_alloc_qs = rb_alloc_qs.filter(time_slot=timeslot)
    _cancel_rb_qs(rb_alloc_qs)

    # 5) Orphaned RoomBookings for this patient (no therapy/visit FK), scoped to matching slot(s)
    if getattr(allocation, 'patient_id', None) and slot_filter:
        _cancel_rb_qs(
            RB.objects.filter(
                patient_id=allocation.patient_id,
                therapy__isnull=True,
                visit__isnull=True,
                **date_filter,
                **slot_filter,
            )
        )
