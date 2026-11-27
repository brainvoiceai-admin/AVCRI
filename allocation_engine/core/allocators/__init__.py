"""
Shared allocation services (Layer 1B).

May import Layer 1A (`allocation_engine.core.primitives`) and Layer 2 (`allocation_engine.rules`).
Must NEVER import scheduling/rescheduling orchestrators, `Sheduling.views`, or legacy root files.
"""

from allocation_engine.core.allocators.prioritization import get_patient_category_priority
from allocation_engine.core.allocators.slot_policy import (
    allocate_treatment_slot,
    get_allowed_slot_values,
)
from allocation_engine.core.allocators.room_allocator import (
    RESCHEDULING_ROOM_CONFIG,
    RoomAllocationConfig,
    SCHEDULING_ROOM_CONFIG,
    allocate_treatment_room,
)
from allocation_engine.core.allocators.therapist_availability import (
    TherapistAvailabilityContext,
    get_therapist_gender,
)
from allocation_engine.core.allocators.therapist_allocator import (
    RESCHEDULING_THERAPIST_CONFIG,
    SCHEDULING_THERAPIST_CONFIG,
    TherapistAllocationConfig,
    allocate_therapists,
    allocate_therapists_with_grade_substitution,
    make_readonly_therapist_config,
)
from allocation_engine.core.allocators.continuity_pass1 import (
    Pass1Config,
    RESCHEDULING_PASS1_CONFIG,
    SCHEDULING_PASS1_CONFIG,
    assign_continuity_therapists_pass1,
)

__all__ = [
    'get_patient_category_priority',
    'get_allowed_slot_values',
    'allocate_treatment_slot',
    'RoomAllocationConfig',
    'SCHEDULING_ROOM_CONFIG',
    'RESCHEDULING_ROOM_CONFIG',
    'allocate_treatment_room',
    'TherapistAvailabilityContext',
    'get_therapist_gender',
    'TherapistAllocationConfig',
    'SCHEDULING_THERAPIST_CONFIG',
    'RESCHEDULING_THERAPIST_CONFIG',
    'make_readonly_therapist_config',
    'allocate_therapists',
    'allocate_therapists_with_grade_substitution',
    'Pass1Config',
    'SCHEDULING_PASS1_CONFIG',
    'RESCHEDULING_PASS1_CONFIG',
    'assign_continuity_therapists_pass1',
]
