# Generated manually
from django.db import migrations

def create_prescription_usage_module(apps, schema_editor):
    """Create the Prescription Usage Master module"""
    try:
        Module = apps.get_model('authentication', 'Module')
        
        module, created = Module.objects.get_or_create(
            name='prescription_usage_manage',
            defaults={
                'display_name': 'Prescription Usage Master',
                'description': 'Manage prescription usage types for prescriptions',
                'url_name': 'prescriptionusage_manage',
                'icon': '💊',
                'is_active': True,
                'order': 55
            }
        )
        
        if not created:
            # Update if exists
            module.display_name = 'Prescription Usage Master'
            module.description = 'Manage prescription usage types for prescriptions'
            module.url_name = 'prescriptionusage_manage'
            module.icon = '💊'
            module.is_active = True
            module.order = 55
            module.save()
    except Exception as e:
        # If Module model doesn't exist yet, skip
        pass

def reverse_create_module(apps, schema_editor):
    """Remove the module if migration is reversed"""
    try:
        Module = apps.get_model('authentication', 'Module')
        Module.objects.filter(name='prescription_usage_manage').delete()
    except Exception:
        pass

class Migration(migrations.Migration):

    dependencies = [
        ('masters', '0019_prescriptionusage'),
        ('authentication', '0004_module_role_customuser_custom_role'),
    ]

    operations = [
        migrations.RunPython(create_prescription_usage_module, reverse_create_module),
    ]

