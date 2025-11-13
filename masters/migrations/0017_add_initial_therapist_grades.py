# Data migration to add initial therapist grades

from django.db import migrations


def add_initial_therapist_grades(apps, schema_editor):
    """Add standard therapist grades to the database"""
    TherapistGrade = apps.get_model('masters', 'TherapistGrade')
    
    # Standard grades with display order
    grades = [
        {'name': 'Trainee Therapist', 'display_order': 1, 'is_active': True},
        {'name': 'Junior Therapist', 'display_order': 2, 'is_active': True},
        {'name': 'Senior Therapist', 'display_order': 3, 'is_active': True},
        {'name': 'Super Senior Therapist', 'display_order': 4, 'is_active': True},
    ]
    
    # Create grades if they don't exist
    for grade_data in grades:
        TherapistGrade.objects.get_or_create(
            name=grade_data['name'],
            defaults={
                'display_order': grade_data['display_order'],
                'is_active': grade_data['is_active']
            }
        )


def reverse_add_initial_therapist_grades(apps, schema_editor):
    """Remove the initial therapist grades (optional - for rollback)"""
    TherapistGrade = apps.get_model('masters', 'TherapistGrade')
    grade_names = [
        'Trainee Therapist',
        'Junior Therapist',
        'Senior Therapist',
        'Super Senior Therapist',
    ]
    TherapistGrade.objects.filter(name__in=grade_names).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('masters', '0016_update_slot_master_fields'),
    ]

    operations = [
        migrations.RunPython(add_initial_therapist_grades, reverse_add_initial_therapist_grades),
    ]


