"""
Populate Floor master from existing TreatmentRoom.floor text values,
then link each TreatmentRoom to its Floor record via floor_master FK.

Run after migration on a new machine:

    python manage.py migrate
    python manage.py migrate_floors

Safe to run multiple times — uses get_or_create and skips already-linked rooms.
"""

from django.core.management.base import BaseCommand
from django.db import connection, transaction
from Patient.models import Floor, TreatmentRoom


class Command(BaseCommand):
    help = (
        "Read distinct floor values from TreatmentRoom.floor (text column), "
        "create Floor master records, and set floor_master FK on each room."
    )

    def handle(self, *args, **options):
        cursor = connection.cursor()
        cursor.execute(
            'SELECT DISTINCT floor FROM Patient_treatmentroom '
            'WHERE floor IS NOT NULL AND floor != ""'
        )
        floor_values = [row[0] for row in cursor.fetchall()]

        if not floor_values:
            self.stdout.write(self.style.WARNING("No floor values found in TreatmentRoom table."))
            return

        self.stdout.write(f"Found {len(floor_values)} distinct floor value(s): {floor_values}\n")

        created_count = 0
        linked_count = 0

        with transaction.atomic():
            for fval in floor_values:
                obj, created = Floor.objects.get_or_create(name=fval)
                tag = "Created" if created else "Exists "
                if created:
                    created_count += 1
                self.stdout.write(f"  [{tag}] Floor: {obj.name}  (id={obj.id})")

                updated = TreatmentRoom.objects.filter(
                    floor=fval, floor_master__isnull=True
                ).update(floor_master=obj)

                if updated:
                    linked_count += updated
                    self.stdout.write(f"           -> Linked {updated} room(s)")

        self.stdout.write(self.style.SUCCESS(
            f"\nDone! {created_count} floor(s) created, {linked_count} room(s) linked."
        ))
