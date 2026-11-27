"""
Layer 2: Independent Therapy-Specific Business Rules.

Strict boundary rule: modules in this package may ONLY import standard library,
Django, Layer 0 models, and Layer 1A primitives (allocation_engine.core.primitives).
They must NEVER import core.allocators, scheduling, rescheduling, views,
final_allocation, or reshedule.
"""
from .steam import (
    is_steam_therapy_treatment,
    is_steam_therapy_530_tr12_only,
    get_steam_therapy_rooms,
)
from .vamanam import (
    VAMANAM_THERAPY_CODE,
    is_vamanam_treatment,
    get_vamanam_slots,
    get_vamanam_timings,
    get_vamanam_rooms_by_tier,
    get_vamanam_treatment_rooms,
    get_primary_vamanam_treatment_rooms,
    get_secondary_vamanam_treatment_rooms,
    allocate_vamanam_treatment_room,
)
from .vasthi import (
    GROUP_VASTHI_MATHRA_THERAPY_CODE,
    VASTHI_THERAPY_GROUP_NAME_NORMALIZED,
    is_vasthi_treatment,
    is_group_vasthi_0830_only,
    get_vasthi_slots,
    get_vasthi_slot_names,
    allocate_vasthi_treatment_room,
)
from .dhara_pizhichil import (
    is_dhara_pizhichil_treatment,
    get_dhara_pizhichil_assigned_room,
)
from .wheelchair import (
    get_wheelchair_accessible_rooms,
)
from .hard_treatment import (
    is_hard_treatment,
    get_slot_session,
    patient_has_hard_treatment_in_session,
)
from .senior_tag import (
    is_treatment_requiring_senior_tag,
    get_senior_tag_count_for_therapist,
)

__all__ = [
    "is_steam_therapy_treatment",
    "is_steam_therapy_530_tr12_only",
    "get_steam_therapy_rooms",
    "VAMANAM_THERAPY_CODE",
    "is_vamanam_treatment",
    "get_vamanam_slots",
    "get_vamanam_timings",
    "get_vamanam_rooms_by_tier",
    "get_vamanam_treatment_rooms",
    "get_primary_vamanam_treatment_rooms",
    "get_secondary_vamanam_treatment_rooms",
    "allocate_vamanam_treatment_room",
    "GROUP_VASTHI_MATHRA_THERAPY_CODE",
    "VASTHI_THERAPY_GROUP_NAME_NORMALIZED",
    "is_vasthi_treatment",
    "is_group_vasthi_0830_only",
    "get_vasthi_slots",
    "get_vasthi_slot_names",
    "allocate_vasthi_treatment_room",
    "is_dhara_pizhichil_treatment",
    "get_dhara_pizhichil_assigned_room",
    "get_wheelchair_accessible_rooms",
    "is_hard_treatment",
    "get_slot_session",
    "patient_has_hard_treatment_in_session",
    "is_treatment_requiring_senior_tag",
    "get_senior_tag_count_for_therapist",
]
