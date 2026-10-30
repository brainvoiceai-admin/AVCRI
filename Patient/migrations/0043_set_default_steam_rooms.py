from django.db import migrations


def set_default_steam_rooms(apps, schema_editor):
    TreatmentRoom = apps.get_model('Patient', 'TreatmentRoom')
    TreatmentRoom.objects.filter(room_no__in=['TR-12', 'TR-9']).update(is_steam_room=True)


def unset_default_steam_rooms(apps, schema_editor):
    TreatmentRoom = apps.get_model('Patient', 'TreatmentRoom')
    TreatmentRoom.objects.filter(room_no__in=['TR-12', 'TR-9']).update(is_steam_room=False)


class Migration(migrations.Migration):

    dependencies = [
        ('Patient', '0042_treatmentroom_is_steam_room'),
    ]

    operations = [
        migrations.RunPython(set_default_steam_rooms, unset_default_steam_rooms),
    ]
