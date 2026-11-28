"""
BUG-5 Regression Test Suite: TherapyMaster Stale-Cache Elimination.

Covers:
1. Creation after a previous lookup miss (negative-cache staleness).
2. TherapyMaster instance update via `.save()` (therapist counts, room/bath flags, category, Dhara flag).
3. Therapy renaming (old name returns None, new name and whitespace variants return updated row).
4. Therapy deletion via `.delete()`.
5. Bulk update via `QuerySet.update()`.
6. Bulk delete via `QuerySet.delete()`.
7. Backward-compatible imports for `therapy_cache` and `clear_therapy_cache`, plus blank/missing-name behaviour.
"""

from types import SimpleNamespace

from django.test import TestCase

import final_allocation
import reshedule
from allocation_engine.core.primitives import (
    clear_therapy_cache as prim_clear_therapy_cache,
    therapy_cache as prim_therapy_cache,
)
from allocation_engine.core.primitives.therapy_catalog import (
    clear_therapy_cache,
    get_therapy_details,
    therapist_requirements,
    therapy_cache,
    therapy_needs_bath,
    therapy_needs_room,
)
from allocation_engine.rules.dhara_pizhichil import is_dhara_pizhichil_treatment
from masters.models import TherapyMaster


class TherapyCatalogFreshLookupTests(TestCase):
    def setUp(self):
        clear_therapy_cache()

    def tearDown(self):
        clear_therapy_cache()

    def test_create_after_previous_miss_returns_new_record(self):
        """1. Lookup miss followed by TherapyMaster creation must not stay stuck on cached None."""
        missing_name = "BUG5 Brand New Therapy"
        alloc_stub = SimpleNamespace(therapy_name=missing_name, therapy_code="THEB_B5_NEW")

        self.assertIsNone(get_therapy_details(missing_name))
        self.assertFalse(therapy_needs_room(alloc_stub))
        self.assertFalse(therapy_needs_bath(alloc_stub))
        self.assertEqual(therapist_requirements(alloc_stub, default_total_if_missing=1)["total"], 1)

        tm = TherapyMaster.objects.create(
            therapy_code="THEB_B5_NEW",
            therapy_name=missing_name,
            therapy_category="Hard",
            therapy_duration="60",
            bathing_required="Yes",
            treatment_room_required="Yes",
            no_of_senior_therapist=1,
            no_of_junior_therapist=1,
            total_no_of_therapist=2,
            is_active=True,
        )

        fetched = get_therapy_details(missing_name)
        self.assertIsNotNone(fetched)
        self.assertEqual(fetched.pk, tm.pk)
        self.assertTrue(therapy_needs_room(alloc_stub))
        self.assertTrue(therapy_needs_bath(alloc_stub))
        req = therapist_requirements(alloc_stub, default_total_if_missing=1)
        self.assertEqual(req["total"], 2)
        self.assertEqual(req["senior"], 1)
        self.assertEqual(req["junior"], 1)
        self.assertEqual(req["therapy_category"], "Hard")

    def test_update_via_save_immediately_reflected(self):
        """2. Updating TherapyMaster fields via `.save()` is reflected immediately without cache clear."""
        name = "BUG5 Updatable Therapy"
        tm = TherapyMaster.objects.create(
            therapy_code="THEB_B5_UPD",
            therapy_name=name,
            therapy_category="Easy",
            therapy_duration="30",
            bathing_required="No",
            treatment_room_required="No",
            no_of_senior_therapist=0,
            no_of_junior_therapist=1,
            total_no_of_therapist=1,
            is_dhara_pizhichil=False,
            is_active=True,
        )
        alloc_stub = SimpleNamespace(therapy_name=name, therapy_code=tm.therapy_code)

        # Warm lookup before mutation
        initial = get_therapy_details(name)
        self.assertEqual(initial.total_no_of_therapist, 1)
        self.assertFalse(therapy_needs_room(alloc_stub))
        self.assertFalse(therapy_needs_bath(alloc_stub))

        # Mutate via .save()
        tm.therapy_category = "Hard"
        tm.bathing_required = "Yes"
        tm.treatment_room_required = "Yes"
        tm.no_of_senior_therapist = 1
        tm.no_of_junior_therapist = 2
        tm.total_no_of_therapist = 3
        tm.is_dhara_pizhichil = True
        tm.save()

        refreshed = get_therapy_details(name)
        self.assertEqual(refreshed.total_no_of_therapist, 3)
        self.assertTrue(therapy_needs_room(alloc_stub))
        self.assertTrue(therapy_needs_bath(alloc_stub))
        req = therapist_requirements(alloc_stub)
        self.assertEqual(req["total"], 3)
        self.assertEqual(req["senior"], 1)
        self.assertEqual(req["junior"], 2)
        self.assertEqual(req["therapy_category"], "Hard")
        self.assertTrue(is_dhara_pizhichil_treatment(therapy_name=name))

    def test_rename_invalidates_old_name_and_resolves_new_name(self):
        """3. Renaming TherapyMaster makes old name miss and new name (plus whitespace variant) resolve."""
        tm = TherapyMaster.objects.create(
            therapy_code="THEB_B5_REN",
            therapy_name="BUG5 Old Therapy",
            therapy_category="Medium",
            therapy_duration="45",
            bathing_required="No",
            treatment_room_required="Yes",
            total_no_of_therapist=2,
            is_active=True,
        )

        # Warm lookup under old name
        self.assertEqual(get_therapy_details("BUG5 Old Therapy").pk, tm.pk)
        # Warm miss under future new name
        self.assertIsNone(get_therapy_details("BUG5   Renamed   Therapy"))

        tm.therapy_name = "BUG5 Renamed Therapy"
        tm.save(update_fields=["therapy_name", "updated_at"])

        self.assertIsNone(get_therapy_details("BUG5 Old Therapy"))
        renamed = get_therapy_details("  BUG5   Renamed   Therapy  ")
        self.assertIsNotNone(renamed)
        self.assertEqual(renamed.pk, tm.pk)
        self.assertEqual(renamed.therapy_name, "BUG5 Renamed Therapy")

    def test_delete_instance_immediately_returns_none(self):
        """4. Deleting a TherapyMaster instance causes subsequent lookups to return None."""
        name = "BUG5 Deletable Therapy"
        tm = TherapyMaster.objects.create(
            therapy_code="THEB_B5_DEL",
            therapy_name=name,
            therapy_category="Easy",
            therapy_duration="30",
            bathing_required="Yes",
            treatment_room_required="Yes",
            total_no_of_therapist=2,
            is_active=True,
        )
        alloc_stub = SimpleNamespace(therapy_name=name, therapy_code=tm.therapy_code)

        self.assertIsNotNone(get_therapy_details(name))
        self.assertTrue(therapy_needs_room(alloc_stub))

        tm.delete()

        self.assertIsNone(get_therapy_details(name))
        self.assertFalse(therapy_needs_room(alloc_stub))
        self.assertFalse(therapy_needs_bath(alloc_stub))

    def test_queryset_bulk_update_immediately_reflected(self):
        """5. Bulk `QuerySet.update()` changes are immediately visible to lookup helpers."""
        name = "BUG5 Bulk Update Therapy"
        tm = TherapyMaster.objects.create(
            therapy_code="THEB_B5_BUPD",
            therapy_name=name,
            therapy_category="Easy",
            therapy_duration="30",
            bathing_required="No",
            treatment_room_required="No",
            total_no_of_therapist=1,
            is_active=True,
        )
        alloc_stub = SimpleNamespace(therapy_name=name, therapy_code=tm.therapy_code)

        self.assertEqual(therapist_requirements(alloc_stub)["total"], 1)
        self.assertFalse(therapy_needs_bath(alloc_stub))

        TherapyMaster.objects.filter(pk=tm.pk).update(
            total_no_of_therapist=4,
            no_of_senior_therapist=2,
            no_of_junior_therapist=2,
            bathing_required="Yes",
            treatment_room_required="Yes",
        )

        refreshed = get_therapy_details(name)
        self.assertEqual(refreshed.total_no_of_therapist, 4)
        self.assertEqual(therapist_requirements(alloc_stub)["total"], 4)
        self.assertTrue(therapy_needs_bath(alloc_stub))
        self.assertTrue(therapy_needs_room(alloc_stub))

    def test_queryset_bulk_delete_immediately_returns_none(self):
        """6. Bulk `QuerySet.delete()` removes records from subsequent lookups immediately."""
        name = "BUG5 Bulk Delete Therapy"
        tm = TherapyMaster.objects.create(
            therapy_code="THEB_B5_BDEL",
            therapy_name=name,
            therapy_category="Medium",
            therapy_duration="45",
            bathing_required="No",
            treatment_room_required="Yes",
            total_no_of_therapist=2,
            is_active=True,
        )

        self.assertEqual(get_therapy_details(name).pk, tm.pk)

        TherapyMaster.objects.filter(pk=tm.pk).delete()

        self.assertIsNone(get_therapy_details(name))

    def test_backward_compatible_exports_and_blank_lookup_behaviour(self):
        """7. Preserve therapy_cache/clear_therapy_cache exports and blank/missing-name handling."""
        self.assertIsInstance(therapy_cache, dict)
        self.assertIs(prim_therapy_cache, therapy_cache)
        self.assertIs(final_allocation.therapy_cache, therapy_cache)
        self.assertIs(reshedule.therapy_cache, therapy_cache)
        self.assertIs(prim_clear_therapy_cache, clear_therapy_cache)
        self.assertIs(final_allocation.clear_therapy_cache, clear_therapy_cache)
        self.assertIs(reshedule.clear_therapy_cache, clear_therapy_cache)

        # clear_therapy_cache() remains a safe callable
        clear_therapy_cache()

        # Blank/None inputs preserve existing None return behaviour
        self.assertIsNone(get_therapy_details(None))
        self.assertIsNone(get_therapy_details(""))
        self.assertIsNone(get_therapy_details("   "))
