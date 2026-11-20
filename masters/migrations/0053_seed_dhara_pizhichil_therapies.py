from django.db import migrations


def seed_dhara_pizhichil_therapies(apps, schema_editor):
    TherapyMaster = apps.get_model('masters', 'TherapyMaster')

    for tm in TherapyMaster.objects.all():
        name = (tm.therapy_name or '').lower()
        if 'dhara' in name and ('piz' in name or 'pizh' in name):
            tm.is_dhara_pizhichil = True
            tm.save(update_fields=['is_dhara_pizhichil'])


def rollback_dhara_pizhichil_therapies(apps, schema_editor):
    TherapyMaster = apps.get_model('masters', 'TherapyMaster')
    TherapyMaster.objects.filter(is_dhara_pizhichil=True).update(is_dhara_pizhichil=False)


class Migration(migrations.Migration):

    dependencies = [
        ('masters', '0052_therapymaster_is_dhara_pizhichil'),
    ]

    operations = [
        migrations.RunPython(seed_dhara_pizhichil_therapies, rollback_dhara_pizhichil_therapies),
    ]
