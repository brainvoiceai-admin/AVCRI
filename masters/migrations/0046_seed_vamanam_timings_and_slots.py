from django.db import migrations
from datetime import time


def seed_vamanam_data(apps, schema_editor):
    VamanamTimingMaster = apps.get_model('masters', 'VamanamTimingMaster')
    SlotMaster = apps.get_model('masters', 'SlotMaster')
    TreatmentRoom = apps.get_model('Patient', 'TreatmentRoom')

    # 1. Seed VamanamTimingMaster
    t1, _ = VamanamTimingMaster.objects.get_or_create(
        display_order=1,
        defaults={
            'timing_name': '05:00 AM',
            'timing_time': time(5, 0),
            'is_active': True,
        }
    )
    t1.timing_name = '05:00 AM'
    t1.timing_time = time(5, 0)
    t1.is_active = True
    t1.save()

    t2, _ = VamanamTimingMaster.objects.get_or_create(
        display_order=2,
        defaults={
            'timing_name': '05:30 AM',
            'timing_time': time(5, 30),
            'is_active': True,
        }
    )
    t2.timing_name = '05:30 AM'
    t2.timing_time = time(5, 30)
    t2.is_active = True
    t2.save()

    # 2. Configure 6:30 AM in SlotMaster as Vamanam slot
    slot_0630 = SlotMaster.objects.filter(slot_time=time(6, 30)).first()
    if slot_0630:
        slot_0630.is_vamanam_slot = True
        slot_0630.save(update_fields=['is_vamanam_slot'])

    # Unmark 05:00 and 05:30 from being exclusive vamanam slots in SlotMaster
    SlotMaster.objects.filter(slot_time__in=[time(5, 0), time(5, 30)]).update(is_vamanam_slot=False)

    # 3. Configure Treatment Rooms
    # TR-11 & TR-12: Primary
    TreatmentRoom.objects.filter(room_no__in=['TR-11', 'TR-12']).update(
        is_vamanam_room=True,
        vamanam_room_type='primary'
    )
    # TR-9: Secondary
    TreatmentRoom.objects.filter(room_no='TR-9').update(
        is_vamanam_room=True,
        vamanam_room_type='secondary'
    )


def reverse_vamanam_data(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('masters', '0045_vamanamtimingmaster'),
        ('Patient', '0045_treatmentroom_vamanam_room_type'),
    ]

    operations = [
        migrations.RunPython(seed_vamanam_data, reverse_vamanam_data),
    ]
