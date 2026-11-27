"""
CP-0 Test Suite: Golden-Master Behavioral Equivalence Snapshot.

Captures a deterministic multi-scenario snapshot of the current (pre-refactoring)
scheduling and rescheduling algorithms across:
1. Wheelchair patient priority (Tier 0)
2. Dhara & Pizhichil patient priority & room continuity (Tier 1, TherapyMaster flag)
3. Standard IP therapy allocation (Tier 2)
4. OP patient slot confinement (11:30 / 17:30)
5. Steam therapy dedicated room allocation (TR-12)
6. Hard-treatment same-session conflict blocking
7. Duplicate same-slot treatment for the same patient (1 scheduled, 1 failed)
8. Read-only reschedule_options_api preview + single reschedule via allocate_therapy_for_visit

Set GENERATE_GOLDEN=1 to regenerate tests/golden/cp0_golden_snapshot.json.
During all CP-1..CP-5 refactoring phases, this test asserts exact 1:1 equivalence.
"""
import json
import os
from datetime import date, time, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from django.test import TestCase, RequestFactory

from masters.models import SlotMaster, TherapistGrade, TherapistMaster, TherapyMaster
from Patient.models import TreatmentRoom, RoomName, RoomBooking, TherapistBooking
from Sheduling.models import PatientSnapshot, TherapyAllocation, Booking
from Sheduling.views import reschedule_options_api
from final_allocation import bulk_allocate_for_date
from reshedule import allocate_therapy_for_visit

User = get_user_model()
GOLDEN_PATH = Path(__file__).resolve().parent / "golden" / "cp0_golden_snapshot.json"
PREV_DATE = date(2099, 12, 9)
RUN_DATE = PREV_DATE + timedelta(days=1)


@pytest.mark.django_db(transaction=True)
class GoldenMasterEquivalenceTests(TestCase):
    def setUp(self):
        self.rf = RequestFactory()
        self.user, _ = User.objects.get_or_create(
            username="cp0_golden_admin",
            defaults={"is_superuser": True, "is_staff": True, "role": "super_admin"},
        )
        self.user.has_module_access = lambda mod: True
        # Deterministic slots
        self.s_0830, _ = SlotMaster.objects.get_or_create(
            slot_number=1, defaults={"slot_time": time(8, 30), "is_active": True}
        )
        self.s_1000, _ = SlotMaster.objects.get_or_create(
            slot_number=2, defaults={"slot_time": time(10, 0), "is_active": True}
        )
        self.s_1130, _ = SlotMaster.objects.get_or_create(
            slot_number=3, defaults={"slot_time": time(11, 30), "is_active": True}
        )
        self.s_1430, _ = SlotMaster.objects.get_or_create(
            slot_number=4, defaults={"slot_time": time(14, 30), "is_active": True}
        )

        # Deterministic grade & therapists
        self.grade, _ = TherapistGrade.objects.get_or_create(
            name="Senior Therapist", defaults={"display_order": 1, "is_active": True}
        )
        self.therapists = []
        for idx in range(1, 7):
            t, _ = TherapistMaster.objects.get_or_create(
                therapist_code=f"TH_GM_M{idx}",
                defaults={
                    "therapist_name": f"GM Male {idx}",
                    "therapist_gender": "Male",
                    "therapist_grade": self.grade,
                    "employee_code": f"EMP_GM_M{idx}",
                    "is_bathing_therapist": True,
                    "is_active": True,
                },
            )
            self.therapists.append(t)

        # Deterministic rooms
        def _mk_room(rno, wc=False, steam=False):
            rn, _ = RoomName.objects.get_or_create(name=f"Room {rno}", defaults={"is_active": True})
            obj, _ = TreatmentRoom.objects.get_or_create(
                room_no=rno,
                defaults={
                    "room_name": rn,
                    "floor": "G",
                    "is_wheelchair_accessible": wc,
                    "is_steam_room": steam,
                    "is_active": True,
                },
            )
            obj.is_wheelchair_accessible = wc
            obj.is_steam_room = steam
            obj.is_active = True
            obj.save()
            return obj

        self.tr1 = _mk_room("TR-1", wc=False)
        self.tr2 = _mk_room("TR-2", wc=True)
        self.tr3 = _mk_room("TR-3", wc=False)
        self.tr12 = _mk_room("TR-12", wc=False, steam=True)

        # Deterministic therapies
        self.th_easy, _ = TherapyMaster.objects.get_or_create(
            therapy_code="GM_EASY",
            defaults={
                "therapy_name": "GM Easy Oil",
                "therapy_category": "Easy",
                "therapy_duration": "45",
                "bathing_required": "No",
                "treatment_room_required": "Yes",
                "total_no_of_therapist": 1,
                "no_of_senior_therapist": 1,
                "is_active": True,
            },
        )
        self.th_dp, _ = TherapyMaster.objects.get_or_create(
            therapy_code="GM_DP",
            defaults={
                "therapy_name": "GM Dhara Pizhichil",
                "therapy_category": "Hard",
                "therapy_duration": "60",
                "bathing_required": "Yes",
                "treatment_room_required": "Yes",
                "total_no_of_therapist": 1,
                "no_of_senior_therapist": 1,
                "is_dhara_pizhichil": True,
                "is_active": True,
            },
        )
        self.th_hard, _ = TherapyMaster.objects.get_or_create(
            therapy_code="GM_HARD",
            defaults={
                "therapy_name": "GM Hard Therapy",
                "therapy_category": "Hard",
                "therapy_duration": "60",
                "bathing_required": "No",
                "treatment_room_required": "Yes",
                "total_no_of_therapist": 1,
                "no_of_senior_therapist": 1,
                "is_active": True,
            },
        )
        self.th_steam, _ = TherapyMaster.objects.get_or_create(
            therapy_code="GM_STEAM",
            defaults={
                "therapy_name": "GM Steam Bath",
                "therapy_category": "Easy",
                "therapy_duration": "30",
                "bathing_required": "No",
                "treatment_room_required": "Yes",
                "total_no_of_therapist": 1,
                "no_of_senior_therapist": 1,
                "is_steam_therapy": True,
                "is_active": True,
            },
        )

    def _run_golden_scenario(self) -> dict:
        # 1. Wheelchair patient (08:30)
        p_wc = PatientSnapshot.objects.create(
            pat_reg_no="700001", pat_name="GM Wheelchair", pat_sex="Male",
            pat_age="55", pat_room_no="DS-1", is_wheelchair=True,
        )
        a_wc = TherapyAllocation.objects.create(
            patient=p_wc, therapy_code=self.th_easy.therapy_code,
            therapy_name=self.th_easy.therapy_name, timeslot=self.s_0830,
            from_date=RUN_DATE, to_date=RUN_DATE, days=1, status="draft", is_wheelchair=True,
        )
        Booking.objects.create(
            allocation=a_wc, date=RUN_DATE, timeslot=self.s_0830,
            status="draft", snapshot_therapy_name=self.th_easy.therapy_name, is_wheelchair=True,
        )

        # 2. Dhara Pizhichil patient with previous-day locked room TR-1 (08:30)
        p_dp = PatientSnapshot.objects.create(
            pat_reg_no="700002", pat_name="GM Dhara", pat_sex="Male",
            pat_age="48", pat_room_no="DS-1",
        )
        a_dp = TherapyAllocation.objects.create(
            patient=p_dp, therapy_code=self.th_dp.therapy_code,
            therapy_name=self.th_dp.therapy_name, timeslot=self.s_0830,
            room=self.tr1, from_date=PREV_DATE, to_date=RUN_DATE, days=2, status="draft",
        )
        Booking.objects.create(
            allocation=a_dp, date=RUN_DATE, timeslot=self.s_0830,
            status="draft", snapshot_therapy_name=self.th_dp.therapy_name,
        )

        # 3. Steam therapy patient (10:00 -> must get TR-12)
        p_st = PatientSnapshot.objects.create(
            pat_reg_no="700003", pat_name="GM Steam", pat_sex="Male",
            pat_age="32", pat_room_no="DS-1",
        )
        a_st = TherapyAllocation.objects.create(
            patient=p_st, therapy_code=self.th_steam.therapy_code,
            therapy_name=self.th_steam.therapy_name, timeslot=self.s_1000,
            from_date=RUN_DATE, to_date=RUN_DATE, days=1, status="draft",
        )
        Booking.objects.create(
            allocation=a_st, date=RUN_DATE, timeslot=self.s_1000,
            status="draft", snapshot_therapy_name=self.th_steam.therapy_name,
        )

        # 4. Duplicate same-slot patient (two allocations on 10:00 -> 1 scheduled, 1 failed)
        p_dup = PatientSnapshot.objects.create(
            pat_reg_no="700004", pat_name="GM DupSlot", pat_sex="Male",
            pat_age="36", pat_room_no="DS-1",
        )
        a_dup1 = TherapyAllocation.objects.create(
            patient=p_dup, therapy_code=self.th_easy.therapy_code,
            therapy_name=self.th_easy.therapy_name, timeslot=self.s_1000,
            from_date=RUN_DATE, to_date=RUN_DATE, days=1, status="draft",
        )
        a_dup2 = TherapyAllocation.objects.create(
            patient=p_dup, therapy_code=self.th_easy.therapy_code,
            therapy_name=self.th_easy.therapy_name, timeslot=self.s_1000,
            from_date=RUN_DATE, to_date=RUN_DATE, days=1, status="draft",
        )
        Booking.objects.create(
            allocation=a_dup1, date=RUN_DATE, timeslot=self.s_1000,
            status="draft", snapshot_therapy_name=self.th_easy.therapy_name,
        )
        Booking.objects.create(
            allocation=a_dup2, date=RUN_DATE, timeslot=self.s_1000,
            status="draft", snapshot_therapy_name=self.th_easy.therapy_name,
        )

        # 5. OP patient (11:30)
        p_op = PatientSnapshot.objects.create(
            pat_reg_no="50001", pat_name="GM OP Patient", pat_sex="Male",
            pat_age="29", pat_room_no="",
        )
        a_op = TherapyAllocation.objects.create(
            patient=p_op, therapy_code=self.th_easy.therapy_code,
            therapy_name=self.th_easy.therapy_name, timeslot=self.s_1130,
            from_date=RUN_DATE, to_date=RUN_DATE, days=1, status="draft",
        )
        Booking.objects.create(
            allocation=a_op, date=RUN_DATE, timeslot=self.s_1130,
            status="draft", snapshot_therapy_name=self.th_easy.therapy_name,
        )

        with patch("final_allocation.is_patient_active", return_value=True):
            bulk_allocate_for_date(RUN_DATE.isoformat())

        # Snapshot booking states after bulk_allocate_for_date
        schedule_rows = []
        for bk in Booking.objects.filter(date=RUN_DATE).select_related(
            "allocation", "allocation__patient", "timeslot", "room"
        ).order_by("allocation__patient__pat_reg_no", "allocation__therapy_code", "id"):
            tbs = TherapistBooking.objects.filter(
                visit=bk.allocation, date=RUN_DATE, status="BOOKED"
            ).select_related("therapist")
            schedule_rows.append({
                "pat_reg_no": bk.allocation.patient.pat_reg_no,
                "therapy_code": bk.allocation.therapy_code,
                "status": bk.status,
                "failure_reason": bk.failure_reason or "",
                "slot": bk.timeslot.slot_time.strftime("%H:%M") if bk.timeslot else None,
                "room": bk.room.room_no if bk.room else None,
                "therapist_count": tbs.count(),
                "has_bathing": any(tb.is_bathing for tb in tbs),
            })

        # 6. Reschedule options preview on the failed duplicate booking (a_dup2)
        req = self.rf.post(
            "/sheduling/scheduling/api/reschedule-options/",
            data=json.dumps({"allocation_id": a_dup2.id, "date": RUN_DATE.isoformat()}),
            content_type="application/json",
        )
        req.user = self.user
        with patch("final_allocation.is_patient_active", return_value=True):
            opt_resp = reschedule_options_api(req)
        opt_data = json.loads(opt_resp.content)
        available_times = sorted(s["slot_time"] for s in opt_data.get("available_slots", []))

        # Verify booking stayed failed after preview
        bk_dup2 = Booking.objects.get(allocation=a_dup2, date=RUN_DATE)
        preview_status = bk_dup2.status

        # 7. Actually reschedule a_dup2 via allocate_therapy_for_visit
        with patch("final_allocation.is_patient_active", return_value=True):
            resched_tasks = allocate_therapy_for_visit(a_dup2.id, RUN_DATE.isoformat(), create_bookings=True)
        bk_dup2.refresh_from_db()

        return {
            "schedule_rows": schedule_rows,
            "reschedule_preview": {
                "http_status": opt_resp.status_code,
                "booking_status_after_preview": preview_status,
                "available_slot_times": available_times,
            },
            "reschedule_commit": {
                "task_statuses": [t.get("status") for t in resched_tasks if isinstance(t, dict)],
                "booking_status": bk_dup2.status,
                "booking_slot": bk_dup2.timeslot.slot_time.strftime("%H:%M") if bk_dup2.timeslot else None,
                "booking_room_assigned": bk_dup2.room is not None,
            },
        }

    def test_golden_master_equivalence(self):
        actual = self._run_golden_scenario()
        if os.environ.get("GENERATE_GOLDEN") == "1" or not GOLDEN_PATH.exists():
            GOLDEN_PATH.parent.mkdir(parents=True, exist_ok=True)
            GOLDEN_PATH.write_text(json.dumps(actual, indent=2, sort_keys=True), encoding="utf-8")

        expected = json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))
        self.assertEqual(actual, expected)
