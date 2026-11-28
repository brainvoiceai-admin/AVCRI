"""
BUG-7 Regression Test Suite: Scheduling Room-Occupancy Consistency (Option B).

Verifies that scheduling `allocate_treatment_room` (and `visit_allocator.expand_therapies_for_visit`):
1. Checks active `Booking` occupancy (`status__in=['scheduled', 'BOOKED']`, excluding cancelled)
   in addition to `RoomBooking`, across staying-room, Steam, Vamanam, OP, Dhara & Pizhichil,
   and IP legacy fallback paths.
2. Does NOT treat cancelled, cancelled-allocation, draft, or failed `Booking` rows as blockers.
3. Supports backward-compatible optional `booking_id=None` (`Booking.pk` == `RoomBooking.visit_id`)
   for self-exclusion across both `Booking` and `RoomBooking` checks while preserving positional compatibility.
4. Preserves existing `RoomBooking` occupancy checks.
"""

from datetime import date, time, timedelta
from unittest.mock import patch

from django.test import TestCase

import final_allocation
from Patient.models import RoomBooking, RoomName, TherapistBooking, TreatmentRoom
from Sheduling.models import Booking, PatientSnapshot, TherapyAllocation
from allocation_engine.scheduling import visit_allocator
from masters.models import SlotMaster, TherapistGrade, TherapistMaster, TherapyMaster

TEST_DATE = date(2099, 11, 26)


def _mk_room(room_no, *, floor="G", is_active=True, wc=False, steam=False, vamanam=False, vamanam_type="primary"):
    rn, _ = RoomName.objects.get_or_create(name=f"Room {room_no}", defaults={"is_active": True})
    room, _ = TreatmentRoom.objects.get_or_create(
        room_no=room_no,
        defaults={
            "room_name": rn,
            "floor": floor,
            "is_active": is_active,
            "is_wheelchair_accessible": wc,
            "is_steam_room": steam,
            "is_vamanam_room": vamanam,
            "vamanam_room_type": vamanam_type,
        },
    )
    room.floor = floor
    room.is_active = is_active
    room.is_wheelchair_accessible = wc
    room.is_steam_room = steam
    room.is_vamanam_room = vamanam
    room.vamanam_room_type = vamanam_type
    room.save()
    return room


class SchedulingRoomBookingCheckTests(TestCase):
    def setUp(self):
        self.slot_0830, _ = SlotMaster.objects.get_or_create(
            slot_number=201,
            defaults={"slot_time": time(8, 30), "is_active": True},
        )
        if self.slot_0830.slot_time != time(8, 30) or not self.slot_0830.is_active:
            self.slot_0830.slot_time = time(8, 30)
            self.slot_0830.is_active = True
            self.slot_0830.save(update_fields=["slot_time", "is_active"])

        self.slot_1000, _ = SlotMaster.objects.get_or_create(
            slot_number=202,
            defaults={"slot_time": time(10, 0), "is_active": True},
        )
        if self.slot_1000.slot_time != time(10, 0) or not self.slot_1000.is_active:
            self.slot_1000.slot_time = time(10, 0)
            self.slot_1000.is_active = True
            self.slot_1000.save(update_fields=["slot_time", "is_active"])

        self.slot_0630, _ = SlotMaster.objects.get_or_create(
            slot_number=203,
            defaults={"slot_time": time(6, 30), "is_active": True, "is_vamanam_slot": True},
        )
        self.slot_0630.slot_time = time(6, 30)
        self.slot_0630.is_active = True
        self.slot_0630.is_vamanam_slot = True
        self.slot_0630.save(update_fields=["slot_time", "is_active", "is_vamanam_slot"])

        # Treatment rooms
        self.tr1 = _mk_room("TR-1", floor="G", wc=False)
        self.tr2 = _mk_room("TR-2", floor="G", wc=True)
        self.tr9 = _mk_room("TR-9", floor="1", steam=True, vamanam=True, vamanam_type="secondary")
        self.tr11 = _mk_room("TR-11", floor="1", vamanam=True, vamanam_type="primary")
        self.tr12 = _mk_room("TR-12", floor="1", steam=True, vamanam=True, vamanam_type="primary")
        self.trc1 = _mk_room("TRC-1", floor="C")

        # Grade & Therapist
        self.grade_senior, _ = TherapistGrade.objects.get_or_create(
            name="Senior Therapist",
            defaults={"display_order": 2, "is_active": True},
        )
        self.therapist = TherapistMaster.objects.create(
            therapist_code="TH_BUG7_M1",
            therapist_name="BUG7 Therapist",
            therapist_gender="Male",
            therapist_grade=self.grade_senior,
            employee_code="EMP_BUG7_M1",
            is_bathing_therapist=True,
            is_helping_therapist=False,
            is_active=True,
        )

        # Therapies
        self.th_regular = TherapyMaster.objects.create(
            therapy_code="THEB_B7_REG",
            therapy_name="BUG7 Regular Oil Therapy",
            therapy_category="Easy",
            therapy_duration="45",
            bathing_required="No",
            treatment_room_required="Yes",
            no_of_senior_therapist=1,
            total_no_of_therapist=1,
            is_active=True,
        )
        self.th_steam = TherapyMaster.objects.create(
            therapy_code="THEB_B7_STEAM",
            therapy_name="BUG7 Steam Bath",
            therapy_category="Easy",
            therapy_duration="30",
            bathing_required="No",
            treatment_room_required="Yes",
            no_of_senior_therapist=1,
            total_no_of_therapist=1,
            is_steam_therapy=True,
            is_active=True,
        )
        self.th_vamanam = TherapyMaster.objects.create(
            therapy_code="THEB_B7_VAM",
            therapy_name="BUG7 Vamanam",
            therapy_category="Hard",
            therapy_duration="60",
            bathing_required="No",
            treatment_room_required="Yes",
            no_of_senior_therapist=1,
            total_no_of_therapist=1,
            is_vamanam=True,
            is_active=True,
        )
        self.th_dp = TherapyMaster.objects.create(
            therapy_code="THEB_B7_DP",
            therapy_name="BUG7 Dhara Pizhichil",
            therapy_category="Hard",
            therapy_duration="60",
            bathing_required="Yes",
            treatment_room_required="Yes",
            no_of_senior_therapist=1,
            total_no_of_therapist=1,
            is_dhara_pizhichil=True,
            is_active=True,
        )

        # Patients
        self.occ_patient = PatientSnapshot.objects.create(
            pat_reg_no="770001",
            pat_name="BUG7 Occupant Patient",
            pat_sex="Male",
            pat_age="45",
            pat_room_no="DS-1",
        )
        self.ip_ds1_patient = PatientSnapshot.objects.create(
            pat_reg_no="770002",
            pat_name="BUG7 IP DS-1 Patient",
            pat_sex="Male",
            pat_age="38",
            pat_room_no="DS-1",
        )
        self.ip_no_room_patient = PatientSnapshot.objects.create(
            pat_reg_no="770003",
            pat_name="BUG7 IP No Staying Room",
            pat_sex="Male",
            pat_age="41",
            pat_room_no="",
        )
        self.op_patient = PatientSnapshot.objects.create(
            pat_reg_no="57001",
            pat_name="BUG7 OP Patient",
            pat_sex="Male",
            pat_age="33",
            pat_room_no="",
        )
        self.op_ct_patient = PatientSnapshot.objects.create(
            pat_reg_no="57002",
            pat_name="BUG7 OP Cottage Patient",
            pat_sex="Male",
            pat_age="35",
            pat_room_no="CT-1",
        )

    def _create_orphan_booking(
        self,
        room,
        slot,
        *,
        booking_status="scheduled",
        alloc_status="allocated",
        patient=None,
        therapy=None,
        booking_date=TEST_DATE,
    ):
        """Create a Booking row with NO corresponding RoomBooking row."""
        pat = patient or self.occ_patient
        th = therapy or self.th_regular
        alloc = TherapyAllocation.objects.create(
            patient=pat,
            therapy_code=th.therapy_code,
            therapy_name=th.therapy_name,
            timeslot=slot,
            room=room,
            from_date=booking_date,
            to_date=booking_date,
            days=1,
            status=alloc_status,
        )
        return Booking.objects.create(
            allocation=alloc,
            date=booking_date,
            timeslot=slot,
            room=room,
            status=booking_status,
            snapshot_therapy_name=th.therapy_name,
        )

    def test_staying_room_skips_orphan_booking_and_picks_alternative(self):
        """Staying-room path (DS-1) skips TR-1 occupied by an orphan scheduled Booking and returns TR-2."""
        self._create_orphan_booking(self.tr1, self.slot_0830, booking_status="scheduled")

        room = final_allocation.allocate_treatment_room(
            TEST_DATE,
            self.slot_0830,
            therapy_name=self.th_regular.therapy_name,
            patient_id=self.ip_ds1_patient.id,
            patient_staying_room="DS-1",
            patient=self.ip_ds1_patient,
        )
        self.assertIsNotNone(room)
        self.assertEqual(room.room_no, "TR-2")

    def test_end_to_end_expand_therapies_for_visit_succeeds_with_alternative_room(self):
        """End-to-end visit_allocator succeeds and allocates TR-2 instead of failing on orphan Booking in TR-1."""
        self._create_orphan_booking(self.tr1, self.slot_0830, booking_status="scheduled")

        alloc = TherapyAllocation.objects.create(
            patient=self.ip_ds1_patient,
            therapy_code=self.th_regular.therapy_code,
            therapy_name=self.th_regular.therapy_name,
            timeslot=self.slot_0830,
            room=None,
            from_date=TEST_DATE,
            to_date=TEST_DATE,
            days=1,
            status="draft",
        )
        booking = Booking.objects.create(
            allocation=alloc,
            date=TEST_DATE,
            timeslot=self.slot_0830,
            room=None,
            status="draft",
            snapshot_therapy_name=self.th_regular.therapy_name,
        )

        with patch.object(final_allocation, "is_patient_active", return_value=True):
            tasks = visit_allocator.expand_therapies_for_visit(
                alloc.id,
                TEST_DATE.isoformat(),
                create_bookings=True,
            )

        self.assertIsInstance(tasks, list)
        self.assertEqual(len(tasks), 1)
        self.assertEqual(tasks[0]["status"], "BOOKED", f"Expected BOOKED, got {tasks[0]}")
        self.assertEqual(tasks[0]["room_no"], "TR-2")

        booking.refresh_from_db()
        self.assertEqual(booking.status, "scheduled")
        self.assertEqual(booking.room.room_no, "TR-2")
        self.assertTrue(
            RoomBooking.objects.filter(
                room=self.tr2, date=TEST_DATE, time_slot=self.slot_0830, visit=booking, status="BOOKED"
            ).exists()
        )
        self.assertEqual(
            TherapistBooking.objects.filter(visit=alloc, date=TEST_DATE, status="BOOKED").count(),
            1,
        )

    def test_steam_therapy_falls_back_when_primary_room_has_orphan_booking(self):
        """Steam therapy skips TR-12 occupied by an orphan scheduled Booking and picks TR-9; None when both busy."""
        self._create_orphan_booking(self.tr12, self.slot_0830, booking_status="scheduled")

        room = final_allocation.allocate_treatment_room(
            TEST_DATE,
            self.slot_0830,
            therapy_name=self.th_steam.therapy_name,
            patient_id=self.ip_ds1_patient.id,
            patient_staying_room="DS-1",
            patient=self.ip_ds1_patient,
        )
        self.assertIsNotNone(room)
        self.assertEqual(room.room_no, "TR-9")

        # Occupy TR-9 with an orphan BOOKED Booking too -> must return None
        self._create_orphan_booking(self.tr9, self.slot_0830, booking_status="BOOKED")
        room_none = final_allocation.allocate_treatment_room(
            TEST_DATE,
            self.slot_0830,
            therapy_name=self.th_steam.therapy_name,
            patient_id=self.ip_ds1_patient.id,
            patient_staying_room="DS-1",
            patient=self.ip_ds1_patient,
        )
        self.assertIsNone(room_none)

    def test_vamanam_therapy_falls_back_when_primary_rooms_have_orphan_bookings(self):
        """Vamanam skips primary rooms TR-11/TR-12 with orphan Bookings and picks secondary TR-9; None when all busy."""
        self._create_orphan_booking(self.tr11, self.slot_0630, booking_status="scheduled")

        room_p2 = final_allocation.allocate_treatment_room(
            TEST_DATE,
            self.slot_0630,
            therapy_name=self.th_vamanam.therapy_name,
            patient_id=self.ip_ds1_patient.id,
            patient_staying_room="DS-1",
            patient=self.ip_ds1_patient,
        )
        self.assertIsNotNone(room_p2)
        self.assertEqual(room_p2.room_no, "TR-12")

        self._create_orphan_booking(self.tr12, self.slot_0630, booking_status="scheduled")
        room_sec = final_allocation.allocate_treatment_room(
            TEST_DATE,
            self.slot_0630,
            therapy_name=self.th_vamanam.therapy_name,
            patient_id=self.ip_ds1_patient.id,
            patient_staying_room="DS-1",
            patient=self.ip_ds1_patient,
        )
        self.assertIsNotNone(room_sec)
        self.assertEqual(room_sec.room_no, "TR-9")

        self._create_orphan_booking(self.tr9, self.slot_0630, booking_status="scheduled")
        room_none = final_allocation.allocate_treatment_room(
            TEST_DATE,
            self.slot_0630,
            therapy_name=self.th_vamanam.therapy_name,
            patient_id=self.ip_ds1_patient.id,
            patient_staying_room="DS-1",
            patient=self.ip_ds1_patient,
        )
        self.assertIsNone(room_none)

    def test_op_room_allocation_skips_orphan_booking(self):
        """OP room allocation skips TR-1 with orphan Booking (picks TR-2) and respects orphan Booking on TRC-1."""
        self._create_orphan_booking(self.tr1, self.slot_0830, booking_status="scheduled")

        op_room = final_allocation.allocate_treatment_room(
            TEST_DATE,
            self.slot_0830,
            therapy_name=self.th_regular.therapy_name,
            patient_id=self.op_patient.id,
            patient_staying_room="",
            patient=self.op_patient,
        )
        self.assertIsNotNone(op_room)
        self.assertEqual(op_room.room_no, "TR-2")

        # OP patient with CT-1 staying room -> TRC-1 occupied by orphan Booking must return None
        self._create_orphan_booking(self.trc1, self.slot_0830, booking_status="scheduled")
        op_ct_room = final_allocation.allocate_treatment_room(
            TEST_DATE,
            self.slot_0830,
            therapy_name=self.th_regular.therapy_name,
            patient_id=self.op_ct_patient.id,
            patient_staying_room="OP-57002",
            patient=self.op_ct_patient,
        )
        self.assertIsNone(op_ct_room)

    def test_dhara_pizhichil_strict_continuity_respects_orphan_booking(self):
        """Dhara & Pizhichil returns None when its locked room has an orphan Booking (never substitutes)."""
        prev_day = TEST_DATE - timedelta(days=1)
        dp_patient = PatientSnapshot.objects.create(
            pat_reg_no="770009",
            pat_name="BUG7 Dhara Patient",
            pat_sex="Male",
            pat_age="50",
            pat_room_no="DS-1",
        )
        TherapyAllocation.objects.create(
            patient=dp_patient,
            therapy_code=self.th_dp.therapy_code,
            therapy_name=self.th_dp.therapy_name,
            timeslot=self.slot_0830,
            room=self.tr1,
            from_date=prev_day,
            to_date=TEST_DATE,
            days=2,
            status="scheduled",
        )

        # Occupy locked TR-1 on TEST_DATE @ 08:30 with an orphan Booking
        self._create_orphan_booking(self.tr1, self.slot_0830, booking_status="scheduled")

        room_busy = final_allocation.allocate_treatment_room(
            TEST_DATE,
            self.slot_0830,
            therapy_name=self.th_dp.therapy_name,
            patient_id=dp_patient.id,
            patient_staying_room="DS-1",
            patient=dp_patient,
        )
        self.assertIsNone(room_busy)

        # Free slot 10:00 still preserves TR-1 continuity
        room_free = final_allocation.allocate_treatment_room(
            TEST_DATE,
            self.slot_1000,
            therapy_name=self.th_dp.therapy_name,
            patient_id=dp_patient.id,
            patient_staying_room="DS-1",
            patient=dp_patient,
        )
        self.assertIsNotNone(room_free)
        self.assertEqual(room_free.room_no, "TR-1")

    def test_ip_legacy_fallback_without_staying_room_respects_orphan_booking(self):
        """All scheduling legacy fallback branches (last_room, same_floor, all-rooms) skip orphan scheduled Bookings."""
        # Branch 2/3: last_room='TR-1' (floor G) occupied by orphan Booking -> skips TR-1, picks same-floor TR-2
        self._create_orphan_booking(self.tr1, self.slot_0830, booking_status="scheduled")

        room_from_last = final_allocation.allocate_treatment_room(
            TEST_DATE,
            self.slot_0830,
            last_room="TR-1",
            therapy_name=self.th_regular.therapy_name,
            patient_id=self.ip_no_room_patient.id,
            patient_staying_room="",
            patient=self.ip_no_room_patient,
        )
        self.assertIsNotNone(room_from_last)
        self.assertEqual(room_from_last.room_no, "TR-2")

        # Branch 4: no staying room and no last_room -> skips TR-1 (first ordered room), picks TR-2
        room_all_scan = final_allocation.allocate_treatment_room(
            TEST_DATE,
            self.slot_0830,
            last_room=None,
            therapy_name=self.th_regular.therapy_name,
            patient_id=self.ip_no_room_patient.id,
            patient_staying_room=None,
            patient=self.ip_no_room_patient,
        )
        self.assertIsNotNone(room_all_scan)
        self.assertNotEqual(room_all_scan.room_no, "TR-1")
        self.assertFalse(room_all_scan.room_no.upper().startswith("TRC"))

        # When both floor-G rooms (TR-1 and TR-2) have orphan Bookings, same_floor skips both and all-rooms picks floor-1 room (never TRC)
        self._create_orphan_booking(self.tr2, self.slot_0830, booking_status="scheduled")
        room_other_floor = final_allocation.allocate_treatment_room(
            TEST_DATE,
            self.slot_0830,
            last_room="TR-1",
            therapy_name=self.th_regular.therapy_name,
            patient_id=self.ip_no_room_patient.id,
            patient_staying_room="",
            patient=self.ip_no_room_patient,
        )
        self.assertIsNotNone(room_other_floor)
        self.assertNotIn(room_other_floor.room_no, {"TR-1", "TR-2", "TRC-1"})

        # Wheelchair eligibility is still enforced in legacy fallback: only TR-2 is wheelchair accessible, and it's occupied -> None
        wc_none = final_allocation.allocate_treatment_room(
            TEST_DATE,
            self.slot_0830,
            last_room="TR-2",
            therapy_name=self.th_regular.therapy_name,
            patient_id=self.ip_no_room_patient.id,
            patient_staying_room="",
            patient=self.ip_no_room_patient,
            is_wheelchair=True,
        )
        self.assertIsNone(wc_none)

    def test_cancelled_draft_and_failed_bookings_do_not_block_rooms(self):
        """Cancelled, cancelled-allocation, draft, and failed Bookings do not block room allocation; BOOKED does."""
        cases = [
            ("cancelled_booking", "cancelled", "allocated"),
            ("cancelled_alloc", "scheduled", "cancelled"),
            ("draft_booking", "draft", "draft"),
            ("failed_booking", "failed", "failed"),
        ]
        for idx, (label, bk_status, alloc_status) in enumerate(cases):
            case_date = TEST_DATE + timedelta(days=idx + 1)
            with self.subTest(case=label):
                self._create_orphan_booking(
                    self.tr1,
                    self.slot_0830,
                    booking_status=bk_status,
                    alloc_status=alloc_status,
                    booking_date=case_date,
                )
                room = final_allocation.allocate_treatment_room(
                    case_date,
                    self.slot_0830,
                    therapy_name=self.th_regular.therapy_name,
                    patient_id=self.ip_ds1_patient.id,
                    patient_staying_room="DS-1",
                    patient=self.ip_ds1_patient,
                )
                self.assertIsNotNone(room)
                self.assertEqual(room.room_no, "TR-1")

                # Legacy fallback (no staying room) also must not treat non-active bookings as blockers
                legacy_room = final_allocation.allocate_treatment_room(
                    case_date,
                    self.slot_0830,
                    last_room="TR-1",
                    therapy_name=self.th_regular.therapy_name,
                    patient_id=self.ip_no_room_patient.id,
                    patient_staying_room="",
                    patient=self.ip_no_room_patient,
                )
                self.assertIsNotNone(legacy_room)
                self.assertEqual(legacy_room.room_no, "TR-1")

        # Contrast: status='BOOKED' on Booking DOES block TR-1
        booked_date = TEST_DATE + timedelta(days=10)
        self._create_orphan_booking(
            self.tr1,
            self.slot_0830,
            booking_status="BOOKED",
            alloc_status="allocated",
            booking_date=booked_date,
        )
        room_blocked = final_allocation.allocate_treatment_room(
            booked_date,
            self.slot_0830,
            therapy_name=self.th_regular.therapy_name,
            patient_id=self.ip_ds1_patient.id,
            patient_staying_room="DS-1",
            patient=self.ip_ds1_patient,
        )
        self.assertIsNotNone(room_blocked)
        self.assertEqual(room_blocked.room_no, "TR-2")

    def test_booking_self_exclusion_and_positional_compatibility(self):
        """Passing booking_id=booking.pk excludes self in Booking and RoomBooking while keeping positional args intact."""
        own_booking = self._create_orphan_booking(
            self.tr1,
            self.slot_0830,
            booking_status="scheduled",
            patient=self.ip_ds1_patient,
        )
        # Also create matching RoomBooking with visit=own_booking (Booking.pk == RoomBooking.visit_id)
        RoomBooking.objects.create(
            room=self.tr1,
            date=TEST_DATE,
            time_slot=self.slot_0830,
            therapy_name=self.th_regular.therapy_name,
            patient_id=self.ip_ds1_patient.id,
            visit=own_booking,
            therapy=own_booking.allocation,
            status="BOOKED",
        )

        # Self-exclusion via booking_id=own_booking.pk -> TR-1 remains available to own_booking
        room_self = final_allocation.allocate_treatment_room(
            TEST_DATE,
            self.slot_0830,
            therapy_name=self.th_regular.therapy_name,
            patient_id=self.ip_ds1_patient.id,
            patient_staying_room="DS-1",
            patient=self.ip_ds1_patient,
            booking_id=own_booking.pk,
        )
        self.assertIsNotNone(room_self)
        self.assertEqual(room_self.room_no, "TR-1")

        # Self-exclusion via visit_allocator shim and in legacy fallback
        room_legacy_self = visit_allocator.allocate_treatment_room(
            TEST_DATE,
            self.slot_0830,
            last_room="TR-1",
            therapy_name=self.th_regular.therapy_name,
            patient_id=self.ip_ds1_patient.id,
            patient_staying_room="",
            patient=self.ip_ds1_patient,
            booking_id=own_booking.pk,
        )
        self.assertIsNotNone(room_legacy_self)
        self.assertEqual(room_legacy_self.room_no, "TR-1")

        # Different booking_id -> TR-1 is blocked, picks TR-2
        other_booking = self._create_orphan_booking(
            None,
            self.slot_0830,
            booking_status="draft",
            patient=self.occ_patient,
        )
        room_other = final_allocation.allocate_treatment_room(
            TEST_DATE,
            self.slot_0830,
            therapy_name=self.th_regular.therapy_name,
            patient_id=self.occ_patient.id,
            patient_staying_room="DS-1",
            patient=self.occ_patient,
            booking_id=other_booking.pk,
        )
        self.assertIsNotNone(room_other)
        self.assertEqual(room_other.room_no, "TR-2")

        # Positional compatibility: 8th positional arg remains is_wheelchair=True
        pos_room = final_allocation.allocate_treatment_room(
            TEST_DATE,
            self.slot_1000,
            None,
            self.th_regular.therapy_name,
            self.ip_ds1_patient.id,
            "DS-1",
            self.ip_ds1_patient,
            True,
        )
        self.assertIsNotNone(pos_room)
        self.assertEqual(pos_room.room_no, "TR-2")
        self.assertTrue(pos_room.is_wheelchair_accessible)

    def test_existing_room_booking_occupancy_checks_remain_effective(self):
        """Active RoomBooking rows (even with no Booking row) continue to block rooms; CANCELED does not."""
        RoomBooking.objects.create(
            room=self.tr1,
            date=TEST_DATE,
            time_slot=self.slot_0830,
            therapy_name=self.th_regular.therapy_name,
            patient_id=self.occ_patient.id,
            status="BOOKED",
        )

        # Staying-room path skips TR-1
        room_stay = final_allocation.allocate_treatment_room(
            TEST_DATE,
            self.slot_0830,
            therapy_name=self.th_regular.therapy_name,
            patient_id=self.ip_ds1_patient.id,
            patient_staying_room="DS-1",
            patient=self.ip_ds1_patient,
        )
        self.assertIsNotNone(room_stay)
        self.assertEqual(room_stay.room_no, "TR-2")

        # Legacy fallback path also skips TR-1
        room_legacy = final_allocation.allocate_treatment_room(
            TEST_DATE,
            self.slot_0830,
            last_room="TR-1",
            therapy_name=self.th_regular.therapy_name,
            patient_id=self.ip_no_room_patient.id,
            patient_staying_room="",
            patient=self.ip_no_room_patient,
        )
        self.assertIsNotNone(room_legacy)
        self.assertEqual(room_legacy.room_no, "TR-2")

        # CANCELED RoomBooking does NOT block TR-1
        RoomBooking.objects.filter(room=self.tr1, date=TEST_DATE, time_slot=self.slot_0830).update(
            status="CANCELED"
        )
        room_freed = final_allocation.allocate_treatment_room(
            TEST_DATE,
            self.slot_0830,
            therapy_name=self.th_regular.therapy_name,
            patient_id=self.ip_ds1_patient.id,
            patient_staying_room="DS-1",
            patient=self.ip_ds1_patient,
        )
        self.assertIsNotNone(room_freed)
        self.assertEqual(room_freed.room_no, "TR-1")
