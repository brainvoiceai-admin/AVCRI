from django.core.management.base import BaseCommand
from django.contrib.auth.models import Permission
from django.contrib.contenttypes.models import ContentType
from authentication.models import Module, Role, CustomUser
from Sheduling.models import PrescriptionScheduling, PrescriptionItem, PrescriptionChangeLog, PrescriptionDispatch

class Command(BaseCommand):
    help = 'Complete setup of prescription scheduling module with permissions and role assignments'

    def handle(self, *args, **options):
        self.stdout.write('Setting up complete prescription scheduling module...')
        
        # Step 1: Create or update the module
        module, created = Module.objects.get_or_create(
            name='prescription_scheduling',
            defaults={
                'display_name': 'Prescription Scheduling',
                'description': 'Manage prescription status, dispatch to procurement departments, and track changes throughout the prescription lifecycle',
                'url_name': 'prescription_scheduling_dashboard',
                'icon': '📋',
                'is_active': True,
                'order': 50
            }
        )
        
        if created:
            self.stdout.write(self.style.SUCCESS('✅ Created prescription scheduling module'))
        else:
            # Update existing module
            module.display_name = 'Prescription Scheduling'
            module.description = 'Manage prescription status, dispatch to procurement departments, and track changes throughout the prescription lifecycle'
            module.url_name = 'prescription_scheduling_dashboard'
            module.icon = '📋'
            module.is_active = True
            module.order = 50
            module.save()
            self.stdout.write(self.style.SUCCESS('✅ Updated prescription scheduling module'))

        # Step 2: Create or update roles
        roles_data = [
            {
                'name': 'prescription_scheduler',
                'display_name': 'Prescription Scheduler',
                'description': 'Can manage prescription scheduling and dispatch to procurement departments'
            },
            {
                'name': 'prescription_admin',
                'display_name': 'Prescription Admin',
                'description': 'Full access to prescription scheduling system with administrative privileges'
            },
            {
                'name': 'procurement_staff',
                'display_name': 'Procurement Staff',
                'description': 'Can view and update prescription status in procurement departments'
            }
        ]

        created_roles = 0
        for role_data in roles_data:
            role, created = Role.objects.get_or_create(
                name=role_data['name'],
                defaults={
                    'display_name': role_data['display_name'],
                    'description': role_data['description'],
                    'is_active': True
                }
            )
            
            if created:
                created_roles += 1
                self.stdout.write(self.style.SUCCESS(f'✅ Created role: {role.display_name}'))
            else:
                self.stdout.write(self.style.WARNING(f'⚠️  Role already exists: {role.display_name}'))

        # Step 3: Assign module to roles
        roles_with_access = [
            'super_admin',
            'admin', 
            'doctor',
            'scheduling_staff',
            'prescription_scheduler',
            'prescription_admin',
            'procurement_staff',
            'ip_pharmacy_staff'
        ]

        updated_roles = 0
        for role_name in roles_with_access:
            try:
                role = Role.objects.get(name=role_name)
                if module not in role.modules.all():
                    role.modules.add(module)
                    updated_roles += 1
                    self.stdout.write(self.style.SUCCESS(f'✅ Added module to role: {role.display_name}'))
                else:
                    self.stdout.write(self.style.WARNING(f'⚠️  Role {role.display_name} already has module access'))
            except Role.DoesNotExist:
                self.stdout.write(self.style.WARNING(f'⚠️  Role {role_name} not found - skipping'))

        # Step 4: Create custom permissions
        custom_permissions = [
            ('send_final_prescription', 'Can send final prescriptions to procurement'),
            ('view_prescription_details', 'Can view detailed prescription information'),
            ('update_prescription_status', 'Can update prescription status'),
            ('view_change_log', 'Can view prescription change logs'),
            ('manage_prescription_dispatch', 'Can manage prescription dispatch'),
            ('bulk_prescription_operations', 'Can perform bulk prescription operations'),
        ]

        created_permissions = 0
        for codename, name in custom_permissions:
            permission, created = Permission.objects.get_or_create(
                codename=codename,
                name=name,
                content_type=ContentType.objects.get_for_model(PrescriptionScheduling),
            )
            if created:
                created_permissions += 1
                self.stdout.write(self.style.SUCCESS(f'✅ Created permission: {name}'))

        # Step 5: Display summary
        self.stdout.write('\n' + '='*60)
        self.stdout.write(self.style.SUCCESS('PRESCRIPTION SCHEDULING MODULE SETUP COMPLETE'))
        self.stdout.write('='*60)
        self.stdout.write(f'📋 Module: {module.display_name}')
        self.stdout.write(f'🔗 URL: /prescription-scheduling/')
        self.stdout.write(f'👥 Roles with access: {updated_roles + len(roles_with_access)}')
        self.stdout.write(f'🔐 Custom permissions: {created_permissions}')
        self.stdout.write(f'🆕 New roles created: {created_roles}')
        
        self.stdout.write('\n📋 Available Features:')
        self.stdout.write('  • Draft Prescription Management')
        self.stdout.write('  • Scheduled Prescription Tracking')
        self.stdout.write('  • Dispatched Prescription Monitoring')
        self.stdout.write('  • Change Log and Audit Trail')
        self.stdout.write('  • Procurement Department Integration')
        self.stdout.write('  • Real-time Status Updates')
        
        self.stdout.write('\n🎯 Next Steps:')
        self.stdout.write('  1. Assign users to appropriate roles')
        self.stdout.write('  2. Test the prescription scheduling dashboard')
        self.stdout.write('  3. Configure procurement department integration')
        self.stdout.write('  4. Set up notification preferences')
        
        self.stdout.write('\n' + '='*60)
        self.stdout.write(self.style.SUCCESS('Setup completed successfully! 🎉'))
        self.stdout.write('='*60)
