from datetime import time
from django.db import migrations


def seed_vasthi_data(apps, schema_editor):
    SlotMaster = apps.get_model('masters', 'SlotMaster')
    TherapyMaster = apps.get_model('masters', 'TherapyMaster')

    # Seed 08:30 AM slot as Vasthi slot
    slot_0830 = SlotMaster.objects.filter(slot_time=time(8, 30)).first()
    if slot_0830:
        slot_0830.is_vasthi_slot = True
        slot_0830.save(update_fields=['is_vasthi_slot'])

    # Seed existing therapies belonging to 'vasthi' group (except Mathra Vasthi THEB037)
    for tm in TherapyMaster.objects.select_related('therapy_group').all():
        code = (tm.therapy_code or '').strip().upper()
        if code == 'THEB037':
            continue
        gname = ''
        if getattr(tm, 'therapy_group', None) and tm.therapy_group.name:
            gname = tm.therapy_group.name.strip().lower()
        if gname == 'vasthi' or 'vasthi' in (tm.therapy_name or '').lower():
            # Exclude Mathra Vasthi from auto-seed
            if 'mathra' not in (tm.therapy_name or '').lower():
                tm.is_vasthi = True
                tm.save(update_fields=['is_vasthi'])


def rollback_vasthi_data(apps, schema_editor):
    SlotMaster = apps.get_model('masters', 'SlotMaster')
    TherapyMaster = apps.get_model('masters', 'TherapyMaster')

    SlotMaster.objects.filter(is_vasthi_slot=True).update(is_vasthi_slot=False)
    TherapyMaster.objects.filter(is_vasthi=True).update(is_vasthi=False)


class Migration(migrations.Migration):

    dependencies = [
        ('masters', '0042_slotmaster_is_vasthi_slot_therapymaster_is_vasthi'),
    ]

    operations = [
        migrations.RunPython(seed_vasthi_data, rollback_vasthi_data),
    ]
