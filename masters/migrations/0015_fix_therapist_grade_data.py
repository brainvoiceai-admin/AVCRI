# Data migration to fix therapist grade foreign key references

from django.db import migrations


def fix_therapist_grade_data(apps, schema_editor):
    """Fix any therapist records that still have invalid grade references"""
    TherapistGrade = apps.get_model('masters', 'TherapistGrade')
    TherapistMaster = apps.get_model('masters', 'TherapistMaster')
    
    from django.db import connection
    
    # First, ensure all standard grades exist
    grades_data = [
        {'name': 'Trainee Therapist', 'display_order': 1, 'is_active': True},
        {'name': 'Junior Therapist', 'display_order': 2, 'is_active': True},
        {'name': 'Senior Therapist', 'display_order': 3, 'is_active': True},
        {'name': 'Super Senior Therapist', 'display_order': 4, 'is_active': True},
    ]
    
    grade_map = {}
    for grade_data in grades_data:
        grade, created = TherapistGrade.objects.get_or_create(
            name=grade_data['name'],
            defaults={
                'display_order': grade_data['display_order'],
                'is_active': grade_data['is_active']
            }
        )
        grade_map[grade_data['name']] = grade
    
    # Also handle common variations
    variations = {
        'Trainee': 'Trainee Therapist',
        'Junior': 'Junior Therapist',
        'Senior': 'Senior Therapist',
        'Super Senior': 'Super Senior Therapist',
    }
    
    # Check for any therapists with invalid grade references
    with connection.cursor() as cursor:
        # Get all therapists and check their grade_id
        cursor.execute("""
            SELECT id, therapist_grade_id 
            FROM masters_therapistmaster
        """)
        therapists = cursor.fetchall()
        
        # Also try to get the old string value if it still exists in some form
        # Check if there's a way to get the original string value
        # Since the field is now ForeignKey, we need to check for NULL or invalid IDs
        
        # Find therapists with NULL or invalid grade_id
        cursor.execute("""
            SELECT tm.id 
            FROM masters_therapistmaster tm
            LEFT JOIN masters_therapistgrade tg ON tm.therapist_grade_id = tg.id
            WHERE tm.therapist_grade_id IS NOT NULL AND tg.id IS NULL
        """)
        invalid_therapists = cursor.fetchall()
        
        # For invalid therapists, set to a default grade (Junior Therapist)
        default_grade = grade_map.get('Junior Therapist')
        if default_grade:
            for (therapist_id,) in invalid_therapists:
                cursor.execute("""
                    UPDATE masters_therapistmaster 
                    SET therapist_grade_id = %s 
                    WHERE id = %s
                """, [default_grade.id, therapist_id])


def reverse_fix_therapist_grade_data(apps, schema_editor):
    """Reverse migration - not needed"""
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('masters', '0014_alter_therapistmaster_therapist_grade'),
    ]

    operations = [
        migrations.RunPython(fix_therapist_grade_data, reverse_fix_therapist_grade_data),
    ]


