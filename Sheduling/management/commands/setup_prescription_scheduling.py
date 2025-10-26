from django.core.management.base import BaseCommand
from authentication.models import Module, Role
from django.contrib.auth.models import Permission
from django.contrib.contenttypes.models import ContentType

class Command(BaseCommand):
    help = 'Set up prescription scheduling module and permissions'

    def handle(self, *args, **options):
        # Create or get the prescription scheduling module
        module, created = Module.objects.get_or_create(
            name='prescription_scheduling',
            defaults={
                'description': 'Prescription Scheduling and Management',
                'is_active': True
            }
        )
        
        if created:
            self.stdout.write(
                self.style.SUCCESS('Created prescription scheduling module')
            )
        else:
            self.stdout.write(
                self.style.WARNING('Prescription scheduling module already exists')
            )

        # Create or get roles
        roles_data = [
            {
                'name': 'prescription_scheduler',
                'display_name': 'Prescription Scheduler',
                'description': 'Can manage prescription scheduling and dispatch'
            },
            {
                'name': 'prescription_admin',
                'display_name': 'Prescription Admin',
                'description': 'Full access to prescription scheduling system'
            },
            {
                'name': 'procurement_staff',
                'display_name': 'Procurement Staff',
                'description': 'Can view and update prescription status in procurement departments'
            }
        ]

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
                self.stdout.write(
                    self.style.SUCCESS(f'Created role: {role.name}')
                )
            else:
                self.stdout.write(
                    self.style.WARNING(f'Role already exists: {role.name}')
                )

            # Add module to role
            role.modules.add(module)

        self.stdout.write(
            self.style.SUCCESS('Successfully set up prescription scheduling module and permissions')
        )
