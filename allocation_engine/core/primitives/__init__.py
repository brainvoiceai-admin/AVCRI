"""
Layer 1A: Core Primitives.

Strict boundary rule: modules in this package may ONLY import standard library,
Django, and Layer 0 models (Sheduling.models, Patient.models, masters.models,
MySql_Data_pull.models). They must NEVER import from core.allocators, rules,
scheduling, rescheduling, Sheduling services/views, final_allocation, or reshedule.
"""
from .exceptions import IncompleteAssignmentError
from .date_utils import daterange
from .patient_utils import (
    is_patient_active,
    parse_patient_age,
    resolve_desired_gender,
)
from .therapy_catalog import (
    therapy_cache,
    clear_therapy_cache,
    get_therapy_details,
    therapy_needs_room,
    therapy_needs_bath,
    get_therapist_grade_name,
    therapist_requirements,
)
from .shift_utils import (
    _shift_enforcement_enabled,
    _shift_eligibility_sets_for_slot,
)
from .slot_utils import (
    map_to_canonical_slot,
    _slot_time_value,
)
from .room_utils import get_treatment_rooms_for_staying_room
from .booking_persistence import (
    create_room_booking_safe,
    create_therapist_booking_safe,
    safe_cancel_patient_bookings,
)

__all__ = [
    "IncompleteAssignmentError",
    "daterange",
    "is_patient_active",
    "parse_patient_age",
    "resolve_desired_gender",
    "therapy_cache",
    "clear_therapy_cache",
    "get_therapy_details",
    "therapy_needs_room",
    "therapy_needs_bath",
    "get_therapist_grade_name",
    "therapist_requirements",
    "_shift_enforcement_enabled",
    "_shift_eligibility_sets_for_slot",
    "map_to_canonical_slot",
    "_slot_time_value",
    "create_room_booking_safe",
    "create_therapist_booking_safe",
    "safe_cancel_patient_bookings",
]
