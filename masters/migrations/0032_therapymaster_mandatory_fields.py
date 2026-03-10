# Migration: Make Therapy Master fields mandatory except therapy_group

from django.db import migrations, models
from django.db.models import Q


def fill_null_values(apps, schema_editor):
    """Fill NULL values in TherapyMaster before making fields non-nullable."""
    TherapyMaster = apps.get_model('masters', 'TherapyMaster')
    for therapy in TherapyMaster.objects.filter(
        Q(therapy_category__isnull=True) |
        Q(therapy_duration__isnull=True) |
        Q(bathing_required__isnull=True) |
        Q(treatment_room_required__isnull=True) |
        Q(cost_of_therapy__isnull=True)
    ):
        if therapy.therapy_category is None:
            therapy.therapy_category = ''
        if therapy.therapy_duration is None:
            therapy.therapy_duration = ''
        if therapy.bathing_required is None:
            therapy.bathing_required = 'No'
        if therapy.treatment_room_required is None:
            therapy.treatment_room_required = 'No'
        if therapy.cost_of_therapy is None:
            therapy.cost_of_therapy = 0
        therapy.save()


def reverse_fill(apps, schema_editor):
    """No-op reverse - we cannot restore NULLs when reversing."""
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('masters', '0031_itemmaster_min_max_to_separate_fields'),
    ]

    operations = [
        migrations.RunPython(fill_null_values, reverse_fill),
        migrations.AlterField(
            model_name='therapymaster',
            name='therapy_category',
            field=models.CharField(max_length=100, verbose_name='Therapy Category'),
        ),
        migrations.AlterField(
            model_name='therapymaster',
            name='therapy_duration',
            field=models.CharField(max_length=50, verbose_name='Duration'),
        ),
        migrations.AlterField(
            model_name='therapymaster',
            name='bathing_required',
            field=models.CharField(max_length=10, verbose_name='Bathing Required'),
        ),
        migrations.AlterField(
            model_name='therapymaster',
            name='treatment_room_required',
            field=models.CharField(max_length=10, verbose_name='Room Required'),
        ),
        migrations.AlterField(
            model_name='therapymaster',
            name='cost_of_therapy',
            field=models.DecimalField(decimal_places=2, default=0, max_digits=10, verbose_name='Cost'),
        ),
    ]
