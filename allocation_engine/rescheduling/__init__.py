"""
Rescheduling orchestrator package (Layer 3B).

Must NEVER import `allocation_engine.scheduling`, `final_allocation`,
`reshedule`, or `resheduleMorningandNight`.
"""

from allocation_engine.rescheduling.slot_attempter import attempt_allocate_slot
from allocation_engine.rescheduling.visit_rescheduler import (
    allocate_therapy_for_visit,
    expand_therapies_for_visit,
)
from allocation_engine.rescheduling.options_preview import (
    compute_reschedule_options_preview,
    preview_continuity_for_booking,
    preview_slot_reschedule,
)
from allocation_engine.rescheduling.leave_reassignment import process_reassignments

__all__ = [
    'attempt_allocate_slot',
    'expand_therapies_for_visit',
    'allocate_therapy_for_visit',
    'preview_continuity_for_booking',
    'preview_slot_reschedule',
    'compute_reschedule_options_preview',
    'process_reassignments',
]
