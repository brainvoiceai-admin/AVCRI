# Data migration: backfill snapshot_therapy_name from allocation.therapy_name
# so Past therapy column shows a value for existing bookings.

from django.db import migrations


def backfill_snapshot_therapy_name(apps, schema_editor):
    Booking = apps.get_model('Sheduling', 'Booking')
    updated = 0
    for b in Booking.objects.select_related('allocation').filter(snapshot_therapy_name=''):
        name = (b.allocation.therapy_name or '')[:255]
        b.snapshot_therapy_name = name
        b.save(update_fields=['snapshot_therapy_name'])
        updated += 1
    if updated:
        print(f'Backfilled snapshot_therapy_name for {updated} bookings.')


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('Sheduling', '0018_add_booking_snapshot_therapy_name'),
    ]

    operations = [
        migrations.RunPython(backfill_snapshot_therapy_name, noop),
    ]
