from django.core.management.base import BaseCommand
from authentication.models import Module, Role

class Command(BaseCommand):
    help = 'Add prescription scheduling module to the system and assign to relevant roles'

    def handle(self, *args, **options):
        # Create or get the prescription scheduling module
        module, created = Module.objects.get_or_create(
            name='prescription_scheduling',
            defaults={
                'display_name': 'Prescription Scheduling',
                'description': 'Manage prescription status, dispatch to procurement departments, and track changes',
                'url_name': 'prescription_scheduling_dashboard',
                'icon': '📋',
                'is_active': True,
                'order': 50
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

        # Define roles that should have access to prescription scheduling
        roles_with_access = [
            'super_admin',
            'admin', 
            'doctor',
            'doctor_admin',
            'scheduling_staff',
            'prescription_scheduler',
            'prescription_admin',
            'procurement_staff',
            'ip_pharmacy_staff'
        ]

        # Add module to roles
        updated_roles = 0
        for role_name in roles_with_access:
            try:
                role = Role.objects.get(name=role_name)
                if module not in role.modules.all():
                    role.modules.add(module)
                    updated_roles += 1
                    self.stdout.write(
                        self.style.SUCCESS(f'Added prescription scheduling module to role: {role.display_name}')
                    )
                else:
                    self.stdout.write(
                        self.style.WARNING(f'Role {role.display_name} already has access to prescription scheduling module')
                    )
            except Role.DoesNotExist:
                self.stdout.write(
                    self.style.WARNING(f'Role {role_name} not found - skipping')
                )

        self.stdout.write(
            self.style.SUCCESS(f'Successfully configured prescription scheduling module. Updated {updated_roles} roles.')
        )
