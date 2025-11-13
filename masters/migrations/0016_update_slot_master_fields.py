# Generated migration to update SlotMaster fields

from django.db import migrations, models


def migrate_slot_times(apps, schema_editor):
    """Migrate start_time to slot_time"""
    SlotMaster = apps.get_model('masters', 'SlotMaster')
    from django.db import connection
    
    with connection.cursor() as cursor:
        # Copy start_time to slot_time
        cursor.execute("""
            UPDATE masters_slotmaster 
            SET slot_time = start_time
            WHERE slot_time IS NULL
        """)


def reverse_migrate_slot_times(apps, schema_editor):
    """Reverse migration - copy slot_time back to start_time"""
    from django.db import connection
    
    with connection.cursor() as cursor:
        cursor.execute("""
            UPDATE masters_slotmaster 
            SET start_time = slot_time
            WHERE start_time IS NULL
        """)


class Migration(migrations.Migration):

    dependencies = [
        ('masters', '0015_fix_therapist_grade_data'),
    ]

    operations = [
        # Add slot_time field as nullable first
        migrations.AddField(
            model_name='slotmaster',
            name='slot_time',
            field=models.TimeField(null=True, blank=True, verbose_name='Slot Time'),
        ),
        # Migrate data from start_time to slot_time
        migrations.RunPython(migrate_slot_times, reverse_migrate_slot_times),
        # Make slot_time non-nullable
        migrations.AlterField(
            model_name='slotmaster',
            name='slot_time',
            field=models.TimeField(verbose_name='Slot Time'),
        ),
        # Remove old fields
        migrations.RemoveField(
            model_name='slotmaster',
            name='start_time',
        ),
        migrations.RemoveField(
            model_name='slotmaster',
            name='end_time',
        ),
    ]


