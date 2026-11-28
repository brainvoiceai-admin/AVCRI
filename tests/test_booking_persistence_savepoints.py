"""
BUG-4C Regression Test Suite: Transaction & Savepoint Safety in `booking_persistence.py`.

Triggers GENUINE database UniqueConstraint `IntegrityError` conditions inside an outer
`transaction.atomic()` block for:
1. `create_room_booking_safe(..., use_atomic=False)`
2. `create_therapist_booking_safe(..., use_atomic=False)`
3. `safe_cancel_patient_bookings(...)` (both TherapistBooking and RoomBooking)

Also tests:
4. Normal operation outside an outer `transaction.atomic()` block (`use_atomic=False`).
5. Existing `use_atomic=True` behaviour both outside and inside an outer `transaction.atomic()`.

To verify PostgreSQL/strict-backend transaction safety on SQLite, tests wrap DB execution with a
`connection.execute_wrapper` that sets `connection.needs_rollback = True` whenever a genuine DB
`IntegrityError` is raised inside an active atomic block (mirroring PostgreSQL's aborted-transaction
state until a savepoint rollback occurs), and also inspect captured SQL for real `SAVEPOINT` and
`ROLLBACK TO SAVEPOINT` statements.
"""

from contextlib import contextmanager
from datetime import date, time
from unittest.mock import patch

from django.db import IntegrityError, connection, transaction
from django.test import TransactionTestCase
from django.test.utils import CaptureQueriesContext

from Patient.models import RoomBooking, RoomName, TherapistBooking, TreatmentRoom
from Sheduling.models import Booking, PatientSnapshot, TherapyAllocation
from allocation_engine.core.primitives.booking_persistence import (
    create_room_booking_safe,
    create_therapist_booking_safe,
    safe_cancel_patient_bookings,
)
from masters.models import SlotMaster, TherapistGrade, TherapistMaster, TherapyMaster


TARGET_DATE = date(2099, 11, 18)


@contextmanager
def strict_atomic_integrity_semantics():
    """
    Simulate PostgreSQL's strict transaction abort semantics on SQLite when a genuine
    DB `IntegrityError` fires inside an active atomic block.
    A nested `transaction.atomic()` savepoint cleanly clears `needs_rollback` on exit;
    without a nested savepoint, the next ORM query raises `TransactionManagementError`.
    Yields the list of genuine DB `IntegrityError` exceptions observed.
    """
    caught_errors = []

    def wrapper(execute, sql, params, many, context):
        try:
            return execute(sql, params, many, context)
        except IntegrityError as exc:
            caught_errors.append(exc)
            if connection.in_atomic_block:
                connection.needs_rollback = True
                connection.rollback_exc = exc
            raise

    with connection.execute_wrapper(wrapper):
        yield caught_errors


class BookingPersistenceSavepointTests(TransactionTestCase):
    def setUp(self):
        self.slot1, _ = SlotMaster.objects.get_or_create(
            slot_number=61, defaults={"slot_time": time(8, 30), "is_active": True}
        )
        if self.slot1.slot_time != time(8, 30):
            self.slot1.slot_time = time(8, 30)
            self.slot1.save(update_fields=["slot_time"])

        self.slot2, _ = SlotMaster.objects.get_or_create(
            slot_number=62, defaults={"slot_time": time(10, 0), "is_active": True}
        )
        if self.slot2.slot_time != time(10, 0):
            self.slot2.slot_time = time(10, 0)
            self.slot2.save(update_fields=["slot_time"])

        self.grade, _ = TherapistGrade.objects.get_or_create(
            name="Senior Therapist", defaults={"display_order": 2, "is_active": True}
        )
        self.th1, _ = TherapistMaster.objects.get_or_create(
            therapist_code="TH_B4C_01",
            defaults={
                "therapist_name": "BUG4C Therapist 1",
                "therapist_gender": "Male",
                "therapist_grade": self.grade,
                "employee_code": "EMP_B4C_01",
                "is_bathing_therapist": True,
                "is_active": True,
            },
        )
        self.th2, _ = TherapistMaster.objects.get_or_create(
            therapist_code="TH_B4C_02",
            defaults={
                "therapist_name": "BUG4C Therapist 2",
                "therapist_gender": "Male",
                "therapist_grade": self.grade,
                "employee_code": "EMP_B4C_02",
                "is_bathing_therapist": False,
                "is_active": True,
            },
        )
        rn1, _ = RoomName.objects.get_or_create(name="Room TR-1", defaults={"is_active": True})
        rn2, _ = RoomName.objects.get_or_create(name="Room TR-2", defaults={"is_active": True})
        self.room1, _ = TreatmentRoom.objects.get_or_create(
            room_no="TR-1", defaults={"room_name": rn1, "floor": "G", "is_active": True}
        )
        self.room2, _ = TreatmentRoom.objects.get_or_create(
            room_no="TR-2", defaults={"room_name": rn2, "floor": "G", "is_active": True}
        )
        self.therapy, _ = TherapyMaster.objects.get_or_create(
            therapy_code="THEB_BUG4C",
            defaults={
                "therapy_name": "BUG4C Savepoint Therapy",
                "therapy_category": "Easy",
                "therapy_duration": "45",
                "bathing_required": "No",
                "treatment_room_required": "Yes",
                "total_no_of_therapist": 1,
                "no_of_senior_therapist": 1,
                "is_active": True,
            },
        )
        self.patient = PatientSnapshot.objects.create(
            pat_reg_no="884201",
            pat_name="BUG4C Patient",
            pat_sex="Male",
            pat_age="42",
            pat_room_no="DS-1",
        )
        self.alloc = TherapyAllocation.objects.create(
            patient=self.patient,
            therapy_code=self.therapy.therapy_code,
            therapy_name=self.therapy.therapy_name,
            timeslot=self.slot1,
            from_date=TARGET_DATE,
            to_date=TARGET_DATE,
            days=1,
            status="draft",
        )
        self.booking = Booking.objects.create(
            allocation=self.alloc,
            date=TARGET_DATE,
            timeslot=self.slot1,
            status="draft",
            snapshot_therapy_name=self.therapy.therapy_name,
        )

    @staticmethod
    def _count_savepoint_rollbacks(queries):
        sqls = [(q.get("sql") or "").upper() for q in queries]
        return sum(1 for s in sqls if "ROLLBACK TO SAVEPOINT" in s)

    @staticmethod
    def _has_any_savepoint(queries):
        sqls = [(q.get("sql") or "").upper() for q in queries]
        return any("SAVEPOINT" in s for s in sqls)

    def test_create_room_booking_safe_use_atomic_false_recovers_inside_outer_atomic(self):
        """
        1. Genuine DB UniqueConstraint IntegrityError in create_room_booking_safe(..., use_atomic=False)
        inside an outer transaction.atomic() rolls back only an inner savepoint and does NOT poison
        the outer transaction.
        """
        existing_rb = RoomBooking.objects.create(
            room=self.room1,
            date=TARGET_DATE,
            time_slot=self.slot1,
            therapy_name=self.therapy.therapy_name,
            patient_id=self.patient.id,
            visit=None,
            therapy=None,
            status="BOOKED",
        )

        # Force get_or_create to execute a genuine colliding SQL INSERT directly against unique_room_date_slot_status
        def colliding_insert(**kwargs):
            defaults = kwargs.pop("defaults", {})
            return RoomBooking.objects.create(**kwargs, **defaults), True

        with strict_atomic_integrity_semantics() as caught_errors, CaptureQueriesContext(connection) as ctx:
            with transaction.atomic():
                # Create an unrelated row in the same outer atomic block that must remain intact
                unrelated_rb = RoomBooking.objects.create(
                    room=self.room2,
                    date=TARGET_DATE,
                    time_slot=self.slot2,
                    therapy_name="Unrelated Therapy",
                    patient_id=self.patient.id,
                    status="BOOKED",
                )

                with patch.object(RoomBooking.objects, "get_or_create", side_effect=colliding_insert):
                    rb, created = create_room_booking_safe(
                        self.room1,
                        TARGET_DATE,
                        self.slot1,
                        self.therapy.therapy_name,
                        self.patient.id,
                        self.booking,
                        use_atomic=False,
                        refresh=True,
                    )

                # Genuine DB IntegrityError fired and recovery succeeded
                self.assertEqual(len(caught_errors), 1)
                self.assertFalse(created)
                self.assertIsNotNone(rb)
                self.assertEqual(rb.pk, existing_rb.pk)
                self.assertEqual(rb.visit_id, self.booking.pk)
                self.assertEqual(rb.therapy_id, self.alloc.pk)

                # Follow-up ORM query inside the SAME outer atomic block must succeed (no TransactionManagementError)
                self.assertEqual(
                    RoomBooking.objects.filter(date=TARGET_DATE, status="BOOKED").count(),
                    2,
                )
                self.assertTrue(RoomBooking.objects.filter(pk=unrelated_rb.pk, status="BOOKED").exists())

        self.assertGreaterEqual(self._count_savepoint_rollbacks(ctx.captured_queries), 1)
        existing_rb.refresh_from_db()
        self.assertEqual(existing_rb.visit_id, self.booking.pk)
        self.assertEqual(existing_rb.therapy_id, self.alloc.pk)
        self.assertEqual(RoomBooking.objects.filter(date=TARGET_DATE, status="BOOKED").count(), 2)

    def test_create_therapist_booking_safe_use_atomic_false_recovers_inside_outer_atomic(self):
        """
        2. Genuine DB UniqueConstraint IntegrityError in create_therapist_booking_safe(..., use_atomic=False)
        inside an outer transaction.atomic() rolls back only an inner savepoint and keeps the outer
        transaction healthy.
        """
        existing_tb = TherapistBooking.objects.create(
            therapist=self.th1,
            date=TARGET_DATE,
            time_slot=self.slot1,
            therapy_name=self.therapy.therapy_name,
            patient_id=self.patient.id,
            visit=None,
            therapy=None,
            is_bathing=False,
            status="BOOKED",
        )

        def colliding_insert(**kwargs):
            defaults = kwargs.pop("defaults", {})
            return TherapistBooking.objects.create(**kwargs, **defaults), True

        with strict_atomic_integrity_semantics() as caught_errors, CaptureQueriesContext(connection) as ctx:
            with transaction.atomic():
                unrelated_tb = TherapistBooking.objects.create(
                    therapist=self.th2,
                    date=TARGET_DATE,
                    time_slot=self.slot2,
                    therapy_name="Unrelated Therapy",
                    patient_id=self.patient.id,
                    status="BOOKED",
                )

                with patch.object(TherapistBooking.objects, "get_or_create", side_effect=colliding_insert):
                    tb, created = create_therapist_booking_safe(
                        self.th1,
                        TARGET_DATE,
                        self.slot1,
                        self.therapy.therapy_name,
                        self.patient.id,
                        self.alloc,
                        is_bathing=True,
                        use_atomic=False,
                        resolve_therapy_fk=True,
                        refresh=True,
                    )

                self.assertEqual(len(caught_errors), 1)
                self.assertFalse(created)
                self.assertIsNotNone(tb)
                self.assertEqual(tb.pk, existing_tb.pk)
                self.assertEqual(tb.visit_id, self.alloc.pk)
                self.assertEqual(tb.therapy_id, self.therapy.pk)
                self.assertTrue(tb.is_bathing)

                # Follow-up ORM query inside the SAME outer atomic block must succeed
                self.assertEqual(
                    TherapistBooking.objects.filter(date=TARGET_DATE, status="BOOKED").count(),
                    2,
                )
                self.assertTrue(TherapistBooking.objects.filter(pk=unrelated_tb.pk, status="BOOKED").exists())

        self.assertGreaterEqual(self._count_savepoint_rollbacks(ctx.captured_queries), 1)
        existing_tb.refresh_from_db()
        self.assertEqual(existing_tb.visit_id, self.alloc.pk)
        self.assertEqual(existing_tb.therapy_id, self.therapy.pk)
        self.assertTrue(existing_tb.is_bathing)

    def test_safe_cancel_patient_bookings_recovers_from_genuine_integrity_error_inside_outer_atomic(self):
        """
        3. Genuine DB UniqueConstraint IntegrityError during safe_cancel_patient_bookings() UPDATE
        inside an outer transaction.atomic() rolls back only the inner savepoint, executes delete()
        recovery cleanly, preserves unrelated rows, and allows follow-up queries in the outer block.
        """
        booked_tb = TherapistBooking.objects.create(
            therapist=self.th1,
            date=TARGET_DATE,
            time_slot=self.slot1,
            therapy_name=self.therapy.therapy_name,
            patient_id=self.patient.id,
            visit=self.alloc,
            therapy=self.therapy,
            status="BOOKED",
        )
        booked_rb = RoomBooking.objects.create(
            room=self.room1,
            date=TARGET_DATE,
            time_slot=self.slot1,
            therapy_name=self.therapy.therapy_name,
            patient_id=self.patient.id,
            visit=self.booking,
            therapy=self.alloc,
            status="BOOKED",
        )
        # Pre-existing CANCELLED rows that will cause genuine UniqueConstraint collision on UPDATE
        cancelled_tb = TherapistBooking.objects.create(
            therapist=self.th1,
            date=TARGET_DATE,
            time_slot=self.slot1,
            therapy_name=self.therapy.therapy_name,
            patient_id=self.patient.id,
            status="CANCELLED",
        )
        cancelled_rb = RoomBooking.objects.create(
            room=self.room1,
            date=TARGET_DATE,
            time_slot=self.slot1,
            therapy_name=self.therapy.therapy_name,
            patient_id=self.patient.id,
            status="CANCELLED",
        )
        # Unrelated bookings on slot2 that must remain untouched
        unrelated_tb = TherapistBooking.objects.create(
            therapist=self.th2,
            date=TARGET_DATE,
            time_slot=self.slot2,
            therapy_name="Other Slot Therapy",
            patient_id=self.patient.id,
            status="BOOKED",
        )
        unrelated_rb = RoomBooking.objects.create(
            room=self.room2,
            date=TARGET_DATE,
            time_slot=self.slot2,
            therapy_name="Other Slot Therapy",
            patient_id=self.patient.id,
            status="BOOKED",
        )

        # Simulate race condition: dup_exists check returns False just before the genuine colliding UPDATE runs
        from django.db.models.query import QuerySet

        orig_exists = QuerySet.exists
        intercepted_models = []

        def race_exists(qs_self):
            if qs_self.model in (TherapistBooking, RoomBooking) and "CANCELLED" in str(qs_self.query):
                intercepted_models.append(qs_self.model)
                return False
            return orig_exists(qs_self)

        with strict_atomic_integrity_semantics() as caught_errors, CaptureQueriesContext(connection) as ctx:
            with transaction.atomic():
                with patch.object(QuerySet, "exists", autospec=True, side_effect=race_exists):
                    safe_cancel_patient_bookings(
                        self.alloc,
                        dates=[TARGET_DATE],
                        booking_ids=[self.booking.pk],
                        timeslot=self.slot1,
                    )

                # Both TherapistBooking and RoomBooking UPDATEs must have hit genuine DB IntegrityError
                self.assertEqual(intercepted_models, [TherapistBooking, RoomBooking])
                self.assertEqual(len(caught_errors), 2)

                # Follow-up ORM queries inside the SAME outer atomic block must succeed
                self.assertFalse(TherapistBooking.objects.filter(pk=booked_tb.pk).exists())
                self.assertFalse(RoomBooking.objects.filter(pk=booked_rb.pk).exists())
                self.assertTrue(TherapistBooking.objects.filter(pk=cancelled_tb.pk, status="CANCELLED").exists())
                self.assertTrue(RoomBooking.objects.filter(pk=cancelled_rb.pk, status="CANCELLED").exists())
                self.assertTrue(TherapistBooking.objects.filter(pk=unrelated_tb.pk, status="BOOKED").exists())
                self.assertTrue(RoomBooking.objects.filter(pk=unrelated_rb.pk, status="BOOKED").exists())

        self.assertGreaterEqual(self._count_savepoint_rollbacks(ctx.captured_queries), 2)
        # Re-verify committed state after outer transaction exits
        self.assertFalse(TherapistBooking.objects.filter(pk=booked_tb.pk).exists())
        self.assertFalse(RoomBooking.objects.filter(pk=booked_rb.pk).exists())
        self.assertTrue(TherapistBooking.objects.filter(pk=unrelated_tb.pk, status="BOOKED").exists())
        self.assertTrue(RoomBooking.objects.filter(pk=unrelated_rb.pk, status="BOOKED").exists())

    def test_normal_operation_outside_atomic_and_use_atomic_true_preserved(self):
        """
        4 & 5. Outside an atomic block (`use_atomic=False`) and with `use_atomic=True`
        both outside and inside an outer atomic block continue working normally.
        """
        self.assertFalse(connection.in_atomic_block)

        # Outside outer atomic with use_atomic=False
        rb1, created1 = create_room_booking_safe(
            self.room1, TARGET_DATE, self.slot1, self.therapy.therapy_name, self.patient.id, self.booking,
            use_atomic=False, refresh=True,
        )
        tb1, tb_created1 = create_therapist_booking_safe(
            self.th1, TARGET_DATE, self.slot1, self.therapy.therapy_name, self.patient.id, self.alloc,
            use_atomic=False, resolve_therapy_fk=True, refresh=True,
        )
        self.assertFalse(connection.in_atomic_block)
        self.assertTrue(created1)
        self.assertTrue(tb_created1)
        self.assertEqual(rb1.therapy_id, self.alloc.pk)
        self.assertEqual(tb1.therapy_id, self.therapy.pk)

        # safe_cancel_patient_bookings outside an atomic block emits no spurious savepoints
        with CaptureQueriesContext(connection) as outside_cancel_ctx:
            safe_cancel_patient_bookings(
                self.alloc,
                dates=[TARGET_DATE],
                booking_ids=[self.booking.pk],
                timeslot=self.slot1,
            )
        self.assertFalse(connection.in_atomic_block)
        self.assertFalse(self._has_any_savepoint(outside_cancel_ctx.captured_queries))
        rb1.refresh_from_db()
        tb1.refresh_from_db()
        self.assertEqual(rb1.status, "CANCELLED")
        self.assertEqual(tb1.status, "CANCELLED")

        # Outside outer atomic with use_atomic=True
        rb2, created2 = create_room_booking_safe(
            self.room2, TARGET_DATE, self.slot2, self.therapy.therapy_name, self.patient.id, self.booking,
            use_atomic=True, refresh=False,
        )
        tb2, tb_created2 = create_therapist_booking_safe(
            self.th2, TARGET_DATE, self.slot2, self.therapy.therapy_name, self.patient.id, self.alloc,
            use_atomic=True, resolve_therapy_fk=True, refresh=False,
        )
        self.assertFalse(connection.in_atomic_block)
        self.assertTrue(created2)
        self.assertTrue(tb_created2)

        # Inside outer atomic with use_atomic=True (duplicate returns existing cleanly)
        with transaction.atomic():
            rb_dup, created_dup = create_room_booking_safe(
                self.room2, TARGET_DATE, self.slot2, self.therapy.therapy_name, self.patient.id, self.booking,
                use_atomic=True, refresh=False,
            )
            tb_dup, tb_created_dup = create_therapist_booking_safe(
                self.th2, TARGET_DATE, self.slot2, self.therapy.therapy_name, self.patient.id, self.alloc,
                use_atomic=True, resolve_therapy_fk=True, refresh=False,
            )
            self.assertFalse(created_dup)
            self.assertFalse(tb_created_dup)
            self.assertEqual(rb_dup.pk, rb2.pk)
            self.assertEqual(tb_dup.pk, tb2.pk)
