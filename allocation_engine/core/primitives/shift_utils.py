"""Shift-to-slot eligibility helpers for therapist allocation."""


def _shift_enforcement_enabled():
    """
    Enable shift filtering only when both masters are configured and populated.
    Prevents changing behaviour in environments where shift masters haven't been filled yet.
    """
    try:
        from masters.models import ShiftSlotMapping, TherapistShiftMapping
        return (
            ShiftSlotMapping.objects.filter(is_active=True).exists()
            and TherapistShiftMapping.objects.filter(is_active=True).exists()
        )
    except Exception:
        return False


def _shift_eligibility_sets_for_slot(slot_master):
    """
    Returns (mapped_ids, eligible_ids) for a given SlotMaster.
    - mapped_ids: therapists who have at least one active shift mapping
    - eligible_ids: subset of mapped_ids whose shifts contain slot_master (plus on-call therapists)
    """
    from masters.models import TherapistShiftMapping, TherapistMaster

    mapped_ids = set(
        TherapistShiftMapping.objects.filter(is_active=True)
        .values_list("therapist_id", flat=True)
        .distinct()
    )
    if not mapped_ids:
        return set(), set()

    eligible_ids = set(
        TherapistShiftMapping.objects.filter(
            is_active=True,
            shift__shift_slots__slot=slot_master,
            shift__shift_slots__is_active=True,
        ).values_list("therapist_id", flat=True).distinct()
    )
    # Ensure on-call therapists are not blocked by standard shift mapping
    eligible_ids.update(
        TherapistMaster.objects.filter(is_on_call=True).values_list("id", flat=True)
    )
    return mapped_ids, eligible_ids
