"""
Shared therapist availability predicates and context preloading (Layer 1B).

Encapsulates all therapist eligibility checks:
- Weekly recurring leave (`TherapistLeaveMaster`)
- Full-day and half-day emergency leave (`EmergencyLeave`)
- Deputation (`get_deputed_therapist_ids_for_date`, `is_therapist_deputed`)
- Treatment omission (`get_omitted_therapist_*`, `is_therapist_omitted_for_treatment`)
- On-call active schedule (`is_therapist_on_call_active`)
- Shift-slot eligibility (`_shift_enforcement_enabled`, `_shift_eligibility_sets_for_slot`)
- Gender normalization (`get_therapist_gender`)
- Daily session count (cap 5 standard / 6 overtime) and difficulty-category load balancing
"""

from allocation_engine.core.primitives.shift_utils import (
    _shift_eligibility_sets_for_slot,
    _shift_enforcement_enabled,
)


def get_therapist_gender(therapist):
    """Normalize TherapistMaster.therapist_gender to 'male', 'female', or None."""
    try:
        v = getattr(therapist, 'therapist_gender', None)
        if v:
            v_str = str(v).strip()
            if v_str.lower().startswith('m'):
                return 'male'
            if v_str.lower().startswith('f'):
                return 'female'
    except Exception:
        pass
    return None


class TherapistAvailabilityContext:
    """
    Preloaded availability context for a single (date, time_slot, therapy_requirements) query.
    Avoids redundant DB queries when evaluating many candidate therapists.
    """

    def __init__(self, date, time_slot, therapy_requirements=None):
        from masters.models import EmergencyLeave, TherapyMaster

        self.date = date
        self.time_slot = time_slot
        self.day_of_week = date.weekday()
        self.therapy_requirements = therapy_requirements or {}
        self.th_code_req = self.therapy_requirements.get("therapy_code")
        self.th_name_req = self.therapy_requirements.get("therapy_name")

        # Treatment omission exclusions
        self.omitted_codes = set()
        self.omitted_ids = set()
        try:
            from masters.models import (
                get_omitted_therapist_codes_for_treatment,
                get_omitted_therapist_ids_for_treatment,
            )
            if self.th_code_req:
                self.omitted_codes.update(get_omitted_therapist_codes_for_treatment(self.th_code_req))
                self.omitted_ids.update(get_omitted_therapist_ids_for_treatment(self.th_code_req))
            if self.th_name_req:
                self.omitted_codes.update(get_omitted_therapist_codes_for_treatment(self.th_name_req))
                self.omitted_ids.update(get_omitted_therapist_ids_for_treatment(self.th_name_req))
        except Exception as e:
            print(f"[DEBUG TreatmentOmission] Error resolving omitted therapists: {e}")

        # Shift eligibility
        self.shift_filter_enabled = _shift_enforcement_enabled()
        self.mapped_ids, self.eligible_ids = (set(), set())
        if self.shift_filter_enabled:
            self.mapped_ids, self.eligible_ids = _shift_eligibility_sets_for_slot(time_slot)

        # Difficulty category therapy names (Easy / Medium / Hard load balancing)
        self.therapy_category = None
        self.category_therapy_names = set()
        try:
            self.therapy_category = self.therapy_requirements.get("therapy_category")
            if self.therapy_category:
                self.category_therapy_names = set(
                    TherapyMaster.objects.filter(
                        therapy_category__iexact=str(self.therapy_category)
                    ).values_list("therapy_name", flat=True)
                )
        except Exception:
            self.therapy_category = None
            self.category_therapy_names = set()

        # Preload emergency leaves overlapping the date
        try:
            em_leaves_qs = EmergencyLeave.objects.filter(from_date__lte=date, to_date__gte=date)
            full_day_leaves = []
            self.half_day_leaves = []
            for el in em_leaves_qs:
                if el.is_half_day and (not el.half_day_date or el.half_day_date == date):
                    self.half_day_leaves.append(el)
                else:
                    full_day_leaves.append(el)
            self.full_leave_therapist_ids = set(
                el.therapist_id for el in full_day_leaves if el.therapist_id
            )
            self.full_leave_emp_codes = set(
                el.employee_code for el in full_day_leaves if el.employee_code
            )
        except Exception:
            self.full_leave_therapist_ids = set()
            self.full_leave_emp_codes = set()
            self.half_day_leaves = []

        # Preload deputed therapist IDs for date
        try:
            from masters.models import get_deputed_therapist_ids_for_date
            self.deputed_therapist_ids = get_deputed_therapist_ids_for_date(date)
        except Exception:
            self.deputed_therapist_ids = set()

    def is_shift_blocked(self, therapist) -> bool:
        """Return True if therapist is mapped to a shift that excludes this slot."""
        t_id = getattr(therapist, "id", None)
        return bool(
            self.shift_filter_enabled
            and t_id in self.mapped_ids
            and t_id not in self.eligible_ids
        )

    def is_on_leave(self, therapist, slot=None) -> bool:
        """
        Return True if therapist is unavailable due to weekly leave, emergency leave
        (full or half day), deputation, treatment omission, or inactive on-call status.
        """
        from masters.models import (
            TherapistLeaveMaster,
            is_therapist_deputed,
            is_therapist_omitted_for_treatment,
            is_therapist_on_call_active,
        )

        target_slot = slot if slot is not None else self.time_slot
        if TherapistLeaveMaster.objects.filter(
            therapist=therapist, leave_day=self.day_of_week
        ).exists():
            return True

        t_id = getattr(therapist, 'id', None)
        emp_code = getattr(therapist, 'employee_code', None)
        if t_id in self.full_leave_therapist_ids:
            return True
        if emp_code and emp_code in self.full_leave_emp_codes:
            return True

        for el in self.half_day_leaves:
            if (t_id and el.therapist_id == t_id) or (emp_code and el.employee_code == emp_code):
                if el.is_slot_on_leave(self.date, target_slot):
                    return True

        # Deputation check
        if t_id and t_id in self.deputed_therapist_ids:
            return True
        if is_therapist_deputed(therapist, self.date):
            return True

        # Treatment omission check
        if t_id and t_id in self.omitted_ids:
            return True
        if emp_code and emp_code in self.omitted_codes:
            return True
        t_code = getattr(therapist, 'therapist_code', None)
        if t_code and t_code in self.omitted_codes:
            return True
        if self.th_code_req or self.th_name_req:
            if is_therapist_omitted_for_treatment(therapist, self.th_code_req or self.th_name_req):
                return True

        # On-call active check
        if not is_therapist_on_call_active(therapist, self.date, target_slot):
            return True

        return False

    def is_booked_at_slot(self, therapist) -> bool:
        """Return True if therapist already has a BOOKED TherapistBooking at (date, time_slot)."""
        from Patient.models import TherapistBooking

        return TherapistBooking.objects.filter(
            therapist=therapist,
            date=self.date,
            time_slot=self.time_slot,
            status='BOOKED',
        ).exists()

    def get_daily_session_count(self, therapist, allocated=()) -> int:
        """Count BOOKED sessions on self.date plus in-run allocations."""
        from Patient.models import TherapistBooking

        try:
            db_count = TherapistBooking.objects.filter(
                therapist=therapist,
                date=self.date,
                status='BOOKED',
            ).count()
            current_run_count = sum(1 for a in allocated if a == therapist)
            return db_count + current_run_count
        except Exception:
            return sum(1 for a in allocated if a == therapist)

    def get_daily_category_count(self, therapist) -> int:
        """Count BOOKED sessions on self.date in the same therapy difficulty category."""
        if not self.category_therapy_names:
            return 0
        from Patient.models import TherapistBooking

        try:
            return TherapistBooking.objects.filter(
                therapist=therapist,
                date=self.date,
                status='BOOKED',
                therapy_name__in=self.category_therapy_names,
            ).count()
        except Exception:
            return 0

    def can_assign(self, therapist, allocated=(), allow_extra: bool = False) -> bool:
        """Check shift eligibility and daily session cap (5 normal, 6 with allow_extra)."""
        if self.is_shift_blocked(therapist):
            return False
        session_count = self.get_daily_session_count(therapist, allocated=allocated)
        max_sessions = 6 if allow_extra else 5
        return session_count < max_sessions
