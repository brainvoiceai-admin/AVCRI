from django.core.management.base import BaseCommand
from django.contrib.auth.models import Permission
from django.contrib.contenttypes.models import ContentType
from authentication.models import Module, Role, CustomUser
from django.db import transaction


class Command(BaseCommand):
    help = 'Set up Therapist Availability module with permissions and role assignments'

    def add_arguments(self, parser):
        parser.add_argument(
            '--force',
            action='store_true',
            help='Force recreation of module and permissions',
        )

    def handle(self, *args, **options):
        force = options.get('force', False)
        
        with transaction.atomic():
            # Create or get the Therapist Availability module
            module, created = Module.objects.get_or_create(
                name='therapist_availability',
                defaults={
                    'display_name': 'Therapist Availability',
                    'description': 'Therapist availability dashboard for checking available therapists and leave schedules',
                    'icon': '👥',
                    'url_name': 'therapist_availability_dashboard',
                    'is_active': True,
                    'order': 12
                }
            )
            
            if created:
                self.stdout.write(
                    self.style.SUCCESS(f'Created module: {module.display_name}')
                )
            elif force:
                module.display_name = 'Therapist Availability'
                module.description = 'Therapist availability dashboard for checking available therapists and leave schedules'
                module.icon = '👥'
                module.url_name = 'therapist_availability_dashboard'
                module.is_active = True
                module.order = 12
                module.save()
                self.stdout.write(
                    self.style.SUCCESS(f'Updated module: {module.display_name}')
                )
            else:
                self.stdout.write(
                    self.style.WARNING(f'Module already exists: {module.display_name}')
                )

            # Create custom permissions for Therapist Availability
            permissions_data = [
                {
                    'codename': 'view_therapist_availability',
                    'name': 'Can view therapist availability',
                    'description': 'Allows access to the therapist availability dashboard'
                },
                {
                    'codename': 'check_available_therapists',
                    'name': 'Can check available therapists',
                    'description': 'Allows checking available therapists based on filters'
                },
                {
                    'codename': 'view_therapist_leaves',
                    'name': 'Can view therapist leaves',
                    'description': 'Allows viewing therapist leave schedules'
                },
                {
                    'codename': 'manage_therapist_schedules',
                    'name': 'Can manage therapist schedules',
                    'description': 'Allows managing therapist availability and schedules'
                }
            ]

            created_permissions = []
            for perm_data in permissions_data:
                permission, created = Permission.objects.get_or_create(
                    codename=perm_data['codename'],
                    defaults={
                        'name': perm_data['name'],
                        'content_type': ContentType.objects.get_for_model(CustomUser)
                    }
                )
                
                if created:
                    created_permissions.append(permission)
                    self.stdout.write(
                        self.style.SUCCESS(f'Created permission: {permission.name}')
                    )
                else:
                    self.stdout.write(
                        self.style.WARNING(f'Permission already exists: {permission.name}')
                    )

            # Assign module to relevant roles
            roles_to_assign = [
                'therapist',
                'super_admin',
                'doctor_admin',
                'nurse',
                'scheduling_staff'
            ]

            assigned_roles = []
            for role_name in roles_to_assign:
                try:
                    role = Role.objects.get(name=role_name)
                    role.modules.add(module)
                    assigned_roles.append(role)
                    self.stdout.write(
                        self.style.SUCCESS(f'Added module to role: {role.display_name}')
                    )
                except Role.DoesNotExist:
                    self.stdout.write(
                        self.style.WARNING(f'Role not found: {role_name}')
                    )

            # Summary
            self.stdout.write(
                self.style.SUCCESS('\n=== Therapist Availability Module Setup Complete ===')
            )
            self.stdout.write(f'Module: {module.display_name}')
            self.stdout.write(f'Permissions created: {len(created_permissions)}')
            self.stdout.write(f'Roles assigned: {len(assigned_roles)}')
            self.stdout.write('\nModule is now available in the navigation menu for assigned roles.')
