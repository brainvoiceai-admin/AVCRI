"""
BUG-2 Regression Test Suite: Rescheduling Pass-1 Therapist Eligibility & Bathing Guards.

Covers all six guards in RESCHEDULING_PASS1_CONFIG via `reshedule.assign_continuity_therapists_pass1`:
1. Shift-slot and on-call eligibility enforcement (`enforce_shift_and_oncall=True`)
2. Doctor-approved unpreferred therapist exclusion (`exclude_unpreferred_therapists=True`)
3. Helping therapist exclusion outside active preferred roster (`exclude_helping_from_continuity=True`)
4. Same-slot patient conflict guard (`check_same_slot_conflict=True`)
5. In-loop bathing therapist tracking (`set_bath_assigned_in_loop=True`)
6. Senior-tag vs bathing therapist separation validation (`validate_senior_not_bathing=True`)

Also verifies:
- Legitimate rescheduling history fallbacks remain enabled (`fallback_bathing_from_history=True`,
  `fallback_to_previous_day_bookings=True`).
- Scheduling Pass-1 configuration (`SCHEDULING_PASS1_CONFIG`) remains unchanged.
"""

from datetime import date, time, timedelta
from unittest.mock import patch

import pytest
from django.test import TestCase
from django.utils import timezone

from Patient.models import RoomBooking, RoomName, TherapistBooking, TreatmentRoom
from Sheduling.models import (
    Booking,
    PatientPreferredTherapistRoster,
    PatientSnapshot,
    TherapistContinuityPlan,
    TherapistPreferenceRequest,
    TherapyAllocation,
)
from allocation_engine.core.allocators.continuity_pass1 import (
    RESCHEDULING_PASS1_CONFIG,
    SCHEDULING_PASS1_CONFIG,
)
from masters.models import (
    ShiftMaster,
    ShiftSlotMapping,
    SlotMaster,
    TherapistGrade,
    TherapistMaster,
    TherapistShiftMapping,
    TherapyMaster,
)
from reshedule import assign_continuity_therapists_pass1


TARGET_DATE = date(2099, 10, 15)
YESTERDAY = TARGET_DATE - timedelta(days=1)


@pytest.mark.django_db(transaction=True)
class ReschedulingPass1GuardsTests(TestCase):
    def setUp(self):
        self.slot_0830, _ = SlotMaster.objects.get_or_create(
            slot_number=21, defaults={"slot_time": time(8, 30), "is_active": True}
        )
        if self.slot_0830.slot_time != time(8, 30):
            self.slot_0830.slot_time = time(8, 30)
            self.slot_0830.save(update_fields=["slot_time"])

        self.slot_1600, _ = SlotMaster.objects.get_or_create(
            slot_number=22, defaults={"slot_time": time(16, 0), "is_active": True}
        )
        if self.slot_1600.slot_time != time(16, 0):
            self.slot_1600.slot_time = time(16, 0)
            self.slot_1600.save(update_fields=["slot_time"])

        self.grade_senior, _ = TherapistGrade.objects.get_or_create(
            name="Senior Therapist", defaults={"display_order": 2, "is_active": True}
        )
        self.grade_junior, _ = TherapistGrade.objects.get_or_create(
            name="Junior Therapist", defaults={"display_order": 3, "is_active": True}
        )

        rn1, _ = RoomName.objects.get_or_create(name="Room BUG2-TR-1", defaults={"is_active": True})
        self.room1, _ = TreatmentRoom.objects.get_or_create(
            room_no="TR-1", defaults={"room_name": rn1, "floor": "G", "is_active": True}
        )

        self.therapy_single, _ = TherapyMaster.objects.get_or_create(
            therapy_code="THEB_BUG2_1T",
            defaults={
                "therapy_name": "BUG2 Single Therapist Therapy",
                "therapy_category": "Medium",
                "therapy_duration": "45",
                "bathing_required": "No",
                "treatment_room_required": "Yes",
                "total_no_of_therapist": 1,
                "no_of_senior_therapist": 1,
                "is_active": True,
            },
        )
        self.therapy_bath_2t, _ = TherapyMaster.objects.get_or_create(
            therapy_code="THEB_BUG2_2TB",
            defaults={
                "therapy_name": "BUG2 Two Therapist Bathing Therapy",
                "therapy_category": "Medium",
                "therapy_duration": "60",
                "bathing_required": "Yes",
                "treatment_room_required": "Yes",
                "total_no_of_therapist": 2,
                "no_of_senior_therapist": 1,
                "no_of_junior_therapist": 1,
                "is_active": True,
            },
        )
        self.therapy_special_dp, _ = TherapyMaster.objects.get_or_create(
            therapy_code="THEB_BUG2_DP5",
            defaults={
                "therapy_name": "dhara & pizhichil (5)",
                "therapy_category": "Hard",
                "therapy_duration": "60",
                "bathing_required": "Yes",
                "treatment_room_required": "Yes",
                "total_no_of_therapist": 2,
                "no_of_senior_therapist": 2,
                "is_dhara_pizhichil": True,
                "is_active": True,
            },
        )

        self.patient = PatientSnapshot.objects.create(
            pat_reg_no="882001",
            pat_name="BUG2 Guard Test Patient",
            pat_sex="Male",
            pat_age="42",
            pat_room_no="DS-1",
        )

    def _make_therapist(
        self,
        code,
        *,
        grade=None,
        is_bathing=False,
        is_helping=False,
        is_on_call=False,
        on_call_status=True,
    ):
        t, _ = TherapistMaster.objects.get_or_create(
            therapist_code=code,
            defaults={
                "therapist_name": f"Therapist {code}",
                "therapist_gender": "Male",
                "therapist_grade": grade or self.grade_senior,
                "employee_code": f"EMP_{code}",
                "is_bathing_therapist": is_bathing,
                "is_helping_therapist": is_helping,
                "is_on_call": is_on_call,
                "on_call_status": on_call_status,
                "is_active": True,
            },
        )
        return t

    def _make_alloc_and_booking(self, therapy, slot=None, status="failed", from_date=YESTERDAY):
        slot = slot or self.slot_0830
        alloc = TherapyAllocation.objects.create(
            patient=self.patient,
            therapy_code=therapy.therapy_code,
            therapy_name=therapy.therapy_name,
            timeslot=slot,
            from_date=from_date,
            to_date=TARGET_DATE,
            days=2,
            status="failed" if status == "failed" else "allocated",
        )
        booking = Booking.objects.create(
            allocation=alloc,
            date=TARGET_DATE,
            timeslot=slot,
            status=status,
            snapshot_therapy_name=therapy.therapy_name,
        )
        return alloc, booking

    # ------------------------------------------------------------------
    # Guard 1: Shift-slot and On-Call Eligibility
    # ------------------------------------------------------------------
    def test_guard1_shift_eligibility_blocks_off_shift_and_allows_on_shift(self):
        th_morning_only = self._make_therapist("TH_B2_SH_M")
        th_evening_ok = self._make_therapist("TH_B2_SH_E")

        shift_morn, _ = ShiftMaster.objects.get_or_create(shift_name="BUG2 Morning Shift")
        shift_eve, _ = ShiftMaster.objects.get_or_create(shift_name="BUG2 Evening Shift")
        ShiftSlotMapping.objects.get_or_create(shift=shift_morn, slot=self.slot_0830, defaults={"is_active": True})
        ShiftSlotMapping.objects.get_or_create(shift=shift_eve, slot=self.slot_1600, defaults={"is_active": True})
        TherapistShiftMapping.objects.get_or_create(therapist=th_morning_only, shift=shift_morn, defaults={"is_active": True})
        TherapistShiftMapping.objects.get_or_create(therapist=th_evening_ok, shift=shift_eve, defaults={"is_active": True})

        alloc, booking = self._make_alloc_and_booking(self.therapy_single, slot=self.slot_1600)
        TherapistContinuityPlan.objects.create(
            date=TARGET_DATE,
            time_slot=self.slot_1600,
            patient=self.patient,
            allocation=alloc,
            therapist=th_morning_only,
            therapy_name=self.therapy_single.therapy_name,
            priority=0,
            source_date=YESTERDAY,
        )
        TherapistContinuityPlan.objects.create(
            date=TARGET_DATE,
            time_slot=self.slot_1600,
            patient=self.patient,
            allocation=alloc,
            therapist=th_evening_ok,
            therapy_name=self.therapy_single.therapy_name,
            priority=1,
            source_date=YESTERDAY,
        )

        res = assign_continuity_therapists_pass1(booking, alloc, TARGET_DATE, set(), create_bookings=False)
        assigned_codes = [t.therapist_code for t in res["assigned_therapists"]]

        self.assertNotIn("TH_B2_SH_M", assigned_codes)
        self.assertEqual(assigned_codes, ["TH_B2_SH_E"])

    def test_guard1_on_call_blocks_inactive_and_allows_active_on_call(self):
        th_oncall_off = self._make_therapist("TH_B2_OC_OFF", is_on_call=True, on_call_status=False)
        th_oncall_on = self._make_therapist("TH_B2_OC_ON", is_on_call=True, on_call_status=True)
        th_oncall_on.on_call_start_date = YESTERDAY
        th_oncall_on.on_call_end_date = TARGET_DATE + timedelta(days=1)
        th_oncall_on.save(update_fields=["on_call_start_date", "on_call_end_date"])
        th_oncall_on.on_call_slots.add(self.slot_0830)

        alloc, booking = self._make_alloc_and_booking(self.therapy_single, slot=self.slot_0830)
        TherapistContinuityPlan.objects.create(
            date=TARGET_DATE,
            time_slot=self.slot_0830,
            patient=self.patient,
            allocation=alloc,
            therapist=th_oncall_off,
            therapy_name=self.therapy_single.therapy_name,
            priority=0,
            source_date=YESTERDAY,
        )
        TherapistContinuityPlan.objects.create(
            date=TARGET_DATE,
            time_slot=self.slot_0830,
            patient=self.patient,
            allocation=alloc,
            therapist=th_oncall_on,
            therapy_name=self.therapy_single.therapy_name,
            priority=1,
            source_date=YESTERDAY,
        )

        res = assign_continuity_therapists_pass1(booking, alloc, TARGET_DATE, set(), create_bookings=False)
        assigned_codes = [t.therapist_code for t in res["assigned_therapists"]]

        self.assertNotIn("TH_B2_OC_OFF", assigned_codes)
        self.assertEqual(assigned_codes, ["TH_B2_OC_ON"])

    # ------------------------------------------------------------------
    # Guard 2: Unpreferred Therapist Exclusion
    # ------------------------------------------------------------------
    @patch("Sheduling.preference_views.is_patient_active", return_value=True)
    def test_guard2_excludes_doctor_approved_unpreferred_therapist(self, _mock_active):
        th_unpref = self._make_therapist("TH_B2_UNP")
        th_ok = self._make_therapist("TH_B2_OK")

        alloc, booking = self._make_alloc_and_booking(self.therapy_single, slot=self.slot_0830)
        TherapistContinuityPlan.objects.create(
            date=TARGET_DATE,
            time_slot=self.slot_0830,
            patient=self.patient,
            allocation=alloc,
            therapist=th_unpref,
            therapy_name=self.therapy_single.therapy_name,
            priority=0,
            source_date=YESTERDAY,
        )
        TherapistContinuityPlan.objects.create(
            date=TARGET_DATE,
            time_slot=self.slot_0830,
            patient=self.patient,
            allocation=alloc,
            therapist=th_ok,
            therapy_name=self.therapy_single.therapy_name,
            priority=1,
            source_date=YESTERDAY,
        )

        pref = TherapistPreferenceRequest.objects.create(
            patient_id=self.patient.pat_reg_no,
            patient_name=self.patient.pat_name,
            status="APPROVED",
            is_active=True,
            action_date=timezone.now(),
            unpreferred_therapist_codes=[th_unpref.therapist_code],
            unpreferred_therapist_names=[th_unpref.therapist_name],
        )
        pref.unpreferred_therapists.add(th_unpref)

        res = assign_continuity_therapists_pass1(booking, alloc, TARGET_DATE, set(), create_bookings=False)
        assigned_codes = [t.therapist_code for t in res["assigned_therapists"]]

        self.assertNotIn("TH_B2_UNP", assigned_codes)
        self.assertEqual(assigned_codes, ["TH_B2_OK"])

    # ------------------------------------------------------------------
    # Guard 3: Helping Therapist Exclusion Outside Permitted Preferred Roster
    # ------------------------------------------------------------------
    def test_guard3_excludes_helping_therapist_outside_preferred_roster(self):
        th_helping = self._make_therapist("TH_B2_HT_OUT", is_helping=True)
        th_regular = self._make_therapist("TH_B2_REG", is_helping=False)

        alloc, booking = self._make_alloc_and_booking(self.therapy_single, slot=self.slot_0830)
        TherapistContinuityPlan.objects.create(
            date=TARGET_DATE,
            time_slot=self.slot_0830,
            patient=self.patient,
            allocation=alloc,
            therapist=th_helping,
            therapy_name=self.therapy_single.therapy_name,
            priority=0,
            source_date=YESTERDAY,
        )
        TherapistContinuityPlan.objects.create(
            date=TARGET_DATE,
            time_slot=self.slot_0830,
            patient=self.patient,
            allocation=alloc,
            therapist=th_regular,
            therapy_name=self.therapy_single.therapy_name,
            priority=1,
            source_date=YESTERDAY,
        )

        res = assign_continuity_therapists_pass1(booking, alloc, TARGET_DATE, set(), create_bookings=False)
        assigned_codes = [t.therapist_code for t in res["assigned_therapists"]]

        self.assertNotIn("TH_B2_HT_OUT", assigned_codes)
        self.assertEqual(assigned_codes, ["TH_B2_REG"])

    @patch("allocation_engine.core.primitives.patient_utils.is_patient_active", return_value=True)
    def test_guard3_allows_helping_therapist_when_in_active_preferred_roster(self, _mock_active):
        th_helping_rostered = self._make_therapist("TH_B2_HT_IN", is_helping=True)
        PatientPreferredTherapistRoster.objects.create(
            patient_reg_no=self.patient.pat_reg_no,
            patient_name=self.patient.pat_name,
            therapist_codes=[th_helping_rostered.therapist_code],
            is_active=True,
        )

        alloc, booking = self._make_alloc_and_booking(self.therapy_single, slot=self.slot_0830)
        TherapistContinuityPlan.objects.create(
            date=TARGET_DATE,
            time_slot=self.slot_0830,
            patient=self.patient,
            allocation=alloc,
            therapist=th_helping_rostered,
            therapy_name=self.therapy_single.therapy_name,
            priority=0,
            source_date=YESTERDAY,
        )

        res = assign_continuity_therapists_pass1(booking, alloc, TARGET_DATE, set(), create_bookings=False)
        assigned_codes = [t.therapist_code for t in res["assigned_therapists"]]

        self.assertEqual(assigned_codes, ["TH_B2_HT_IN"])

    # ------------------------------------------------------------------
    # Guard 4: Same-Slot Patient Conflict Guard
    # ------------------------------------------------------------------
    def test_guard4_skips_pass1_when_patient_already_booked_at_same_slot(self):
        th1 = self._make_therapist("TH_B2_SS1")
        th2 = self._make_therapist("TH_B2_SS2")

        alloc1, booking1 = self._make_alloc_and_booking(self.therapy_single, slot=self.slot_0830, status="scheduled")
        RoomBooking.objects.create(
            room=self.room1,
            date=TARGET_DATE,
            time_slot=self.slot_0830,
            therapy=alloc1,
            therapy_name=self.therapy_single.therapy_name,
            patient_id=self.patient.id,
            visit=booking1,
            status="BOOKED",
        )
        TherapistBooking.objects.create(
            therapist=th1,
            date=TARGET_DATE,
            time_slot=self.slot_0830,
            therapy_name=self.therapy_single.therapy_name,
            patient_id=self.patient.id,
            visit=alloc1,
            status="BOOKED",
        )

        # Second allocation for the SAME patient at the SAME slot
        alloc2, booking2 = self._make_alloc_and_booking(self.therapy_single, slot=self.slot_0830, status="failed")
        TherapistContinuityPlan.objects.create(
            date=TARGET_DATE,
            time_slot=self.slot_0830,
            patient=self.patient,
            allocation=alloc2,
            therapist=th2,
            therapy_name=self.therapy_single.therapy_name,
            priority=0,
            source_date=YESTERDAY,
        )

        locked = set()
        res = assign_continuity_therapists_pass1(booking2, alloc2, TARGET_DATE, locked, create_bookings=False)

        self.assertFalse(res["success"])
        self.assertEqual(res["assigned_therapists"], [])
        self.assertEqual(locked, set())

    # ------------------------------------------------------------------
    # Guard 5: In-Loop Bathing Assignment Tracking (`set_bath_assigned_in_loop=True`)
    # ------------------------------------------------------------------
    def test_guard5_assigns_non_bathing_partner_after_bathing_therapist_in_loop(self):
        th_bath = self._make_therapist("TH_B2_BATH", grade=self.grade_senior, is_bathing=True)
        th_partner = self._make_therapist("TH_B2_NONB", grade=self.grade_junior, is_bathing=False)

        alloc, booking = self._make_alloc_and_booking(self.therapy_bath_2t, slot=self.slot_0830)
        TherapistContinuityPlan.objects.create(
            date=TARGET_DATE,
            time_slot=self.slot_0830,
            patient=self.patient,
            allocation=alloc,
            therapist=th_bath,
            therapy_name=self.therapy_bath_2t.therapy_name,
            is_bathing=True,
            priority=0,
            source_date=YESTERDAY,
        )
        TherapistContinuityPlan.objects.create(
            date=TARGET_DATE,
            time_slot=self.slot_0830,
            patient=self.patient,
            allocation=alloc,
            therapist=th_partner,
            therapy_name=self.therapy_bath_2t.therapy_name,
            is_bathing=False,
            priority=1,
            source_date=YESTERDAY,
        )

        res = assign_continuity_therapists_pass1(booking, alloc, TARGET_DATE, set(), create_bookings=False)
        assigned_codes = [t.therapist_code for t in res["assigned_therapists"]]

        self.assertEqual(assigned_codes, ["TH_B2_BATH", "TH_B2_NONB"])
        self.assertEqual(res["bath_assigned"], th_bath)
        self.assertEqual(res["remaining_requirements"]["total"], 0)

    # ------------------------------------------------------------------
    # Guard 6: Senior-Tag vs Bathing Therapist Separation (`validate_senior_not_bathing=True`)
    # ------------------------------------------------------------------
    def test_guard6_special_treatment_separates_senior_tag_from_bathing_therapist(self):
        self.assertTrue(RESCHEDULING_PASS1_CONFIG.validate_senior_not_bathing)

        th_sr_bath = self._make_therapist("TH_B2_SR_BATH", grade=self.grade_senior, is_bathing=True)
        th_sr_other = self._make_therapist("TH_B2_SR_OTH", grade=self.grade_senior, is_bathing=False)

        alloc, booking = self._make_alloc_and_booking(self.therapy_special_dp, slot=self.slot_0830)
        TherapistContinuityPlan.objects.create(
            date=TARGET_DATE,
            time_slot=self.slot_0830,
            patient=self.patient,
            allocation=alloc,
            therapist=th_sr_bath,
            therapy_name=self.therapy_special_dp.therapy_name,
            is_bathing=True,
            priority=0,
            source_date=YESTERDAY,
        )
        TherapistContinuityPlan.objects.create(
            date=TARGET_DATE,
            time_slot=self.slot_0830,
            patient=self.patient,
            allocation=alloc,
            therapist=th_sr_other,
            therapy_name=self.therapy_special_dp.therapy_name,
            is_bathing=False,
            priority=1,
            source_date=YESTERDAY,
        )

        res = assign_continuity_therapists_pass1(booking, alloc, TARGET_DATE, set(), create_bookings=False)
        self.assertEqual(res["bath_assigned"], th_sr_bath)
        self.assertEqual(res["senior_therapist"], th_sr_other)
        self.assertNotEqual(res["bath_assigned"], res["senior_therapist"])

    # ------------------------------------------------------------------
    # Fallback Preservation & Scheduling Config Immutability
    # ------------------------------------------------------------------
    def test_preserves_rescheduling_history_fallbacks_and_scheduling_config(self):
        self.assertTrue(RESCHEDULING_PASS1_CONFIG.fallback_bathing_from_history)
        self.assertTrue(RESCHEDULING_PASS1_CONFIG.fallback_to_previous_day_bookings)

        # Scheduling Pass-1 config must remain untouched
        self.assertEqual(SCHEDULING_PASS1_CONFIG.mode, "scheduling")
        self.assertTrue(SCHEDULING_PASS1_CONFIG.check_same_slot_conflict)
        self.assertTrue(SCHEDULING_PASS1_CONFIG.enforce_shift_and_oncall)
        self.assertTrue(SCHEDULING_PASS1_CONFIG.exclude_helping_from_continuity)
        self.assertTrue(SCHEDULING_PASS1_CONFIG.expand_preferred_roster_therapists)
        self.assertTrue(SCHEDULING_PASS1_CONFIG.exclude_unpreferred_therapists)
        self.assertFalse(SCHEDULING_PASS1_CONFIG.fallback_bathing_from_history)
        self.assertFalse(SCHEDULING_PASS1_CONFIG.fallback_to_previous_day_bookings)
        self.assertTrue(SCHEDULING_PASS1_CONFIG.set_bath_assigned_in_loop)
        self.assertTrue(SCHEDULING_PASS1_CONFIG.validate_senior_not_bathing)

        # End-to-end check: when TherapistContinuityPlan is empty, previous-day booking fallback still works
        th_prev = self._make_therapist("TH_B2_PREV", grade=self.grade_senior, is_bathing=True)
        prev_alloc = TherapyAllocation.objects.create(
            patient=self.patient,
            therapy_code=self.therapy_single.therapy_code,
            therapy_name=self.therapy_single.therapy_name,
            timeslot=self.slot_0830,
            from_date=YESTERDAY,
            to_date=YESTERDAY,
            days=1,
            status="allocated",
        )
        TherapistBooking.objects.create(
            therapist=th_prev,
            date=YESTERDAY,
            time_slot=self.slot_0830,
            therapy_name=self.therapy_single.therapy_name,
            patient_id=self.patient.id,
            visit=prev_alloc,
            status="BOOKED",
        )

        alloc_today, booking_today = self._make_alloc_and_booking(self.therapy_single, slot=self.slot_0830)
        res = assign_continuity_therapists_pass1(booking_today, alloc_today, TARGET_DATE, set(), create_bookings=False)
        self.assertTrue(res["success"])
        self.assertEqual([t.therapist_code for t in res["assigned_therapists"]], ["TH_B2_PREV"])
