from datetime import time
from django.db import migrations
from django.db.models import Max


def seed_vamanam_slots(apps, schema_editor):
    SlotMaster = apps.get_model('masters', 'SlotMaster')
    max_val = SlotMaster.objects.aggregate(Max('slot_number'))['slot_number__max'] or 0
    
    # 05:00 AM slot
    slot_500 = SlotMaster.objects.filter(slot_time=time(5, 0)).first()
    if not slot_500:
        max_val += 1
        SlotMaster.objects.create(
            slot_number=max_val,
            slot_time=time(5, 0),
            slot_name="Vamanam Slot (05:00 AM)",
            is_vamanam_slot=True,
            is_active=True
        )
    else:
        slot_500.is_vamanam_slot = True
        slot_500.save()

    # 05:30 AM slot
    slot_530 = SlotMaster.objects.filter(slot_time=time(5, 30)).first()
    if not slot_530:
        max_val += 1
        SlotMaster.objects.create(
            slot_number=max_val,
            slot_time=time(5, 30),
            slot_name="Vamanam Slot (05:30 AM)",
            is_vamanam_slot=True,
            is_active=True
        )
    else:
        slot_530.is_vamanam_slot = True
        slot_530.save()


def remove_vamanam_slots(apps, schema_editor):
    SlotMaster = apps.get_model('masters', 'SlotMaster')
    SlotMaster.objects.filter(slot_time__in=[time(5, 0), time(5, 30)], is_vamanam_slot=True).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('masters', '0040_slotmaster_is_vamanam_slot_therapymaster_is_vamanam'),
    ]

    operations = [
        migrations.RunPython(seed_vamanam_slots, remove_vamanam_slots),
    ]
