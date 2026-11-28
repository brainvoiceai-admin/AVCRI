"""
BUG-3 Regression Test Suite: Pass-1 Failed Therapist Lock Handling.

Verifies that when `create_therapist_booking_safe()` fails (returns None) during
`assign_continuity_therapists_pass1(..., create_bookings=True)`:
1. Daily session cap (>= 6) rejection removes therapist from assigned_therapists & locked_therapist_slots.
2. Treatment omission rejection removes therapist from assigned_therapists & locked_therapist_slots.
3. Partial success (1st therapist locks, 2nd fails) keeps only the 1st therapist locked and restores
   only the 2nd therapist's decremented grade count and remaining_requirements['total'].
4. Failed bathing/senior therapist is cleared from result['bath_assigned'] / result['senior_therapist'].
5. Both scheduling and rescheduling Pass-1 configs handle failed locks cleanly, while
   `create_bookings=False` (read-only preview) continues to work without persisting bookings.
"""

from datetime import date, time, timedelta
from unittest.mock import patch

import pytest
from django.test import TestCase

from Patient.models import TherapistBooking
from Sheduling.models import (
    Booking,
    PatientSnapshot,
    TherapistContinuityPlan,
    TherapyAllocation,
)
from allocation_engine.core.allocators.continuity_pass1 import (
    RESCHEDULING_PASS1_CONFIG,
    SCHEDULING_PASS1_CONFIG,
    assign_continuity_therapists_pass1,
)
from allocation_engine.core.primitives.booking_persistence import (
    create_therapist_booking_safe as real_create_therapist_booking_safe,
)
from masters.models import (
    SlotMaster,
    TherapistGrade,
    TherapistMaster,
    TherapistTreatmentOmission,
    TherapyMaster,
)


TARGET_DATE = date(2099, 10, 25)
YESTERDAY = TARGET_DATE - timedelta(days=1)


@pytest.mark.django_db(transaction=True)
class Pass1FailedLockHandlingTests(TestCase):
    def setUp(self):
        self.slots = []
        slot_times = [
            (31, time(6, 30)),
            (32, time(8, 30)),
            (33, time(10, 0)),
            (34, time(11, 30)),
            (35, time(14, 30)),
            (36, time(16, 0)),
            (37, time(17, 30)),
        ]
        for num, st in slot_times:
            s, _ = SlotMaster.objects.get_or_create(
                slot_number=num, defaults={"slot_time": st, "is_active": True}
            )
            if s.slot_time != st:
                s.slot_time = st
                s.save(update_fields=["slot_time"])
            self.slots.append(s)
        self.target_slot = self.slots[6]  # 17:30 (6 earlier slots available to fill cap = 6)

        self.grade_senior, _ = TherapistGrade.objects.get_or_create(
            name="Senior Therapist", defaults={"display_order": 2, "is_active": True}
        )
        self.grade_junior, _ = TherapistGrade.objects.get_or_create(
            name="Junior Therapist", defaults={"display_order": 3, "is_active": True}
        )

        self.therapy_1sr, _ = TherapyMaster.objects.get_or_create(
            therapy_code="THEB_BUG3_1SR",
            defaults={
                "therapy_name": "BUG3 One Senior Therapy",
                "therapy_category": "Medium",
                "therapy_duration": "45",
                "bathing_required": "No",
                "treatment_room_required": "Yes",
                "total_no_of_therapist": 1,
                "no_of_senior_therapist": 1,
                "is_active": True,
            },
        )
        self.therapy_2t, _ = TherapyMaster.objects.get_or_create(
            therapy_code="THEB_BUG3_2T",
            defaults={
                "therapy_name": "BUG3 Senior Plus Junior Therapy",
                "therapy_category": "Medium",
                "therapy_duration": "60",
                "bathing_required": "No",
                "treatment_room_required": "Yes",
                "total_no_of_therapist": 2,
                "no_of_senior_therapist": 1,
                "no_of_junior_therapist": 1,
                "is_active": True,
            },
        )
        self.therapy_bath, _ = TherapyMaster.objects.get_or_create(
            therapy_code="THEB_BUG3_BATH",
            defaults={
                "therapy_name": "BUG3 Bathing Therapy",
                "therapy_category": "Medium",
                "therapy_duration": "45",
                "bathing_required": "Yes",
                "treatment_room_required": "Yes",
                "total_no_of_therapist": 1,
                "no_of_senior_therapist": 1,
                "is_active": True,
            },
        )

        self.patient = PatientSnapshot.objects.create(
            pat_reg_no="883001",
            pat_name="BUG3 Test Patient",
            pat_sex="Male",
            pat_age="45",
            pat_room_no="DS-1",
            is_vip=True,
        )
        self.other_patient = PatientSnapshot.objects.create(
            pat_reg_no="883099",
            pat_name="BUG3 Other Patient",
            pat_sex="Male",
            pat_age="40",
            pat_room_no="DS-2",
        )

    def _make_therapist(self, code, grade=None, is_bathing=False):
        t, _ = TherapistMaster.objects.get_or_create(
            therapist_code=code,
            defaults={
                "therapist_name": f"Therapist {code}",
                "therapist_gender": "Male",
                "therapist_grade": grade or self.grade_senior,
                "employee_code": f"EMP_{code}",
                "is_bathing_therapist": is_bathing,
                "is_helping_therapist": False,
                "is_active": True,
            },
        )
        return t

    def _fill_six_sessions(self, therapist):
        """Book 6 earlier slots on TARGET_DATE so create_therapist_booking_safe enforces the 6-session cap."""
        filler_alloc = TherapyAllocation.objects.create(
            patient=self.other_patient,
            therapy_code=self.therapy_1sr.therapy_code,
            therapy_name=self.therapy_1sr.therapy_name,
            timeslot=self.slots[0],
            from_date=TARGET_DATE,
            to_date=TARGET_DATE,
            days=1,
            status="allocated",
        )
        for s in self.slots[:6]:
            TherapistBooking.objects.create(
                therapist=therapist,
                date=TARGET_DATE,
                time_slot=s,
                therapy_name=self.therapy_1sr.therapy_name,
                patient_id=self.other_patient.id,
                visit=filler_alloc,
                status="BOOKED",
            )

    def _make_alloc_booking_and_plan(self, therapy, therapists, is_vip=True):
        alloc = TherapyAllocation.objects.create(
            patient=self.patient,
            therapy_code=therapy.therapy_code,
            therapy_name=therapy.therapy_name,
            timeslot=self.target_slot,
            from_date=YESTERDAY,
            to_date=TARGET_DATE,
            days=2,
            status="draft",
            is_vip=is_vip,
        )
        booking = Booking.objects.create(
            allocation=alloc,
            date=TARGET_DATE,
            timeslot=self.target_slot,
            status="draft",
            snapshot_therapy_name=therapy.therapy_name,
            is_vip=is_vip,
        )
        for idx, t in enumerate(therapists):
            TherapistContinuityPlan.objects.create(
                date=TARGET_DATE,
                time_slot=self.target_slot,
                patient=self.patient,
                allocation=alloc,
                therapist=t,
                therapy_name=therapy.therapy_name,
                is_bathing=getattr(t, "is_bathing_therapist", False),
                priority=idx,
                source_date=YESTERDAY,
            )
        return alloc, booking

    def test_session_cap_rejection_removes_therapist_restores_grade_and_releases_lock(self):
        """
        Real DB reproduction: VIP Pass 1 bypasses the candidate-loop cap check, then
        create_therapist_booking_safe enforces current_session_count >= 6 and returns (None, False).
        The rejected therapist must NOT remain in assigned_therapists or locked_therapist_slots,
        and senior/total remaining requirements must be restored.
        """
        th_capped = self._make_therapist("TH_B3_CAP1", grade=self.grade_senior)
        self._fill_six_sessions(th_capped)

        alloc, booking = self._make_alloc_booking_and_plan(self.therapy_1sr, [th_capped], is_vip=True)
        locked = set()

        res = assign_continuity_therapists_pass1(
            booking, alloc, TARGET_DATE, locked, create_bookings=True, config=SCHEDULING_PASS1_CONFIG
        )

        self.assertEqual(res["assigned_therapists"], [])
        self.assertFalse(res["success"])
        self.assertNotIn((th_capped.id, self.target_slot.id), locked)
        self.assertEqual(res["remaining_requirements"]["senior"], 1)
        self.assertEqual(res["remaining_requirements"]["total"], 1)
        self.assertFalse(
            TherapistBooking.objects.filter(
                therapist=th_capped, date=TARGET_DATE, time_slot=self.target_slot, status="BOOKED"
            ).exists()
        )

    def test_treatment_omission_rejection_removes_therapist_and_restores_requirements(self):
        """
        When create_therapist_booking_safe rejects a therapist because an approved
        TherapistTreatmentOmission exists at persistence time, Pass 1 must exclude the therapist,
        release locked_therapist_slots, and restore the grade requirement.
        """
        th_omit = self._make_therapist("TH_B3_OMIT1", grade=self.grade_senior)
        alloc, booking = self._make_alloc_booking_and_plan(self.therapy_1sr, [th_omit], is_vip=False)
        locked = set()

        real_returns = []

        def create_omission_then_book(*args, **kwargs):
            # Simulate an approved omission becoming active before persistence
            TherapistTreatmentOmission.objects.get_or_create(
                therapist=th_omit,
                treatment=self.therapy_1sr,
                defaults={"status": "approved", "is_active": True, "reason": "BUG3 omission test"},
            )
            ret = real_create_therapist_booking_safe(*args, **kwargs)
            real_returns.append(ret)
            return ret

        with patch(
            "allocation_engine.core.allocators.continuity_pass1.create_therapist_booking_safe",
            side_effect=create_omission_then_book,
        ):
            res = assign_continuity_therapists_pass1(
                booking, alloc, TARGET_DATE, locked, create_bookings=True, config=SCHEDULING_PASS1_CONFIG
            )

        self.assertEqual(real_returns, [(None, False)])
        self.assertEqual(res["assigned_therapists"], [])
        self.assertFalse(res["success"])
        self.assertNotIn((th_omit.id, self.target_slot.id), locked)
        self.assertEqual(res["remaining_requirements"]["senior"], 1)
        self.assertEqual(res["remaining_requirements"]["total"], 1)

    def test_partial_success_keeps_locked_therapist_and_restores_only_failed_therapist(self):
        """
        2-therapist therapy (1 Senior + 1 Junior):
        - Senior T1 locks successfully.
        - Junior T2 hits the 6-session cap inside create_therapist_booking_safe and returns None.
        Expected: T1 remains assigned & locked (senior=0), T2 is excluded & unlocked (junior=1, total=1).
        """
        th_ok = self._make_therapist("TH_B3_OK1", grade=self.grade_senior)
        th_fail = self._make_therapist("TH_B3_FAIL2", grade=self.grade_junior)
        self._fill_six_sessions(th_fail)

        alloc, booking = self._make_alloc_booking_and_plan(self.therapy_2t, [th_ok, th_fail], is_vip=True)
        locked = set()

        res = assign_continuity_therapists_pass1(
            booking, alloc, TARGET_DATE, locked, create_bookings=True, config=SCHEDULING_PASS1_CONFIG
        )

        self.assertEqual(res["assigned_therapists"], [th_ok])
        self.assertTrue(res["success"])
        self.assertIn((th_ok.id, self.target_slot.id), locked)
        self.assertNotIn((th_fail.id, self.target_slot.id), locked)
        self.assertEqual(res["remaining_requirements"]["senior"], 0)
        self.assertEqual(res["remaining_requirements"]["junior"], 1)
        self.assertEqual(res["remaining_requirements"]["total"], 1)
        self.assertTrue(
            TherapistBooking.objects.filter(
                therapist=th_ok, date=TARGET_DATE, time_slot=self.target_slot, status="BOOKED"
            ).exists()
        )
        self.assertFalse(
            TherapistBooking.objects.filter(
                therapist=th_fail, date=TARGET_DATE, time_slot=self.target_slot, status="BOOKED"
            ).exists()
        )

    def test_failed_bathing_therapist_is_cleared_from_bath_assigned(self):
        """If the chosen bathing therapist fails to lock, result['bath_assigned'] must be cleared."""
        th_bath_capped = self._make_therapist("TH_B3_BCAP", grade=self.grade_senior, is_bathing=True)
        self._fill_six_sessions(th_bath_capped)

        alloc, booking = self._make_alloc_booking_and_plan(self.therapy_bath, [th_bath_capped], is_vip=True)
        locked = set()

        res = assign_continuity_therapists_pass1(
            booking, alloc, TARGET_DATE, locked, create_bookings=True, config=SCHEDULING_PASS1_CONFIG
        )

        self.assertEqual(res["assigned_therapists"], [])
        self.assertIsNone(res["bath_assigned"])
        self.assertFalse(res["success"])
        self.assertEqual(res["remaining_requirements"]["senior"], 1)
        self.assertEqual(res["remaining_requirements"]["total"], 1)

    def test_rescheduling_config_handles_failed_lock_and_preserves_readonly_preview(self):
        """
        1. Under RESCHEDULING_PASS1_CONFIG with create_bookings=True, a failed lock is rolled back cleanly.
        2. With create_bookings=False (read-only preview), no TherapistBooking is persisted and the
           eligible continuity therapist is still reported in assigned_therapists.
        """
        th_capped = self._make_therapist("TH_B3_RS_CAP", grade=self.grade_senior)
        self._fill_six_sessions(th_capped)
        alloc, booking = self._make_alloc_booking_and_plan(self.therapy_1sr, [th_capped], is_vip=True)

        # 1) Rescheduling commit mode rejects failed lock
        locked_commit = set()
        res_commit = assign_continuity_therapists_pass1(
            booking, alloc, TARGET_DATE, locked_commit, create_bookings=True, config=RESCHEDULING_PASS1_CONFIG
        )
        self.assertEqual(res_commit["assigned_therapists"], [])
        self.assertFalse(res_commit["success"])
        self.assertEqual(locked_commit, set())
        self.assertEqual(res_commit["remaining_requirements"]["senior"], 1)
        self.assertEqual(res_commit["remaining_requirements"]["total"], 1)

        # 2) Read-only preview mode (create_bookings=False) must NOT require persisted bookings
        th_free = self._make_therapist("TH_B3_RS_FREE", grade=self.grade_senior)
        alloc_prev, booking_prev = self._make_alloc_booking_and_plan(self.therapy_1sr, [th_free], is_vip=False)
        tb_before = TherapistBooking.objects.filter(date=TARGET_DATE, time_slot=self.target_slot).count()

        res_preview = assign_continuity_therapists_pass1(
            booking_prev, alloc_prev, TARGET_DATE, set(), create_bookings=False, config=RESCHEDULING_PASS1_CONFIG
        )
        self.assertTrue(res_preview["success"])
        self.assertEqual(res_preview["assigned_therapists"], [th_free])
        self.assertEqual(res_preview["remaining_requirements"]["total"], 0)
        self.assertEqual(
            TherapistBooking.objects.filter(date=TARGET_DATE, time_slot=self.target_slot).count(),
            tb_before,
        )
