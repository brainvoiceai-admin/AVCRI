from django.core.management.base import BaseCommand
from django.contrib.auth.models import Permission
from django.contrib.contenttypes.models import ContentType
from authentication.models import Module, Role, CustomUser
from django.db import transaction


class Command(BaseCommand):
    help = 'Set up Therapist Dashboard module with permissions and role assignments'

    def add_arguments(self, parser):
        parser.add_argument(
            '--force',
            action='store_true',
            help='Force recreation of module and permissions',
        )

    def handle(self, *args, **options):
        force = options.get('force', False)
        
        with transaction.atomic():
            # Create or get the Therapist Dashboard module
            module, created = Module.objects.get_or_create(
                name='therapist_dashboard',
                defaults={
                    'display_name': 'Therapist Dashboard',
                    'description': 'Therapist dashboard for viewing assigned sessions and managing therapy schedules',
                    'icon': '🧑‍⚕️',
                    'url_name': 'therapist_dashboard',
                    'is_active': True,
                    'order': 11
                }
            )
            
            if created:
                self.stdout.write(
                    self.style.SUCCESS(f'Created module: {module.display_name}')
                )
            elif force:
                module.display_name = 'Therapist Dashboard'
                module.description = 'Therapist dashboard for viewing assigned sessions and managing therapy schedules'
                module.icon = '🧑‍⚕️'
                module.url_name = 'therapist_dashboard'
                module.is_active = True
                module.order = 11
                module.save()
                self.stdout.write(
                    self.style.SUCCESS(f'Updated module: {module.display_name}')
                )
            else:
                self.stdout.write(
                    self.style.WARNING(f'Module already exists: {module.display_name}')
                )

            # Create custom permissions for Therapist Dashboard
            permissions_data = [
                {
                    'codename': 'view_therapist_dashboard',
                    'name': 'Can view therapist dashboard',
                    'description': 'Allows access to the therapist dashboard'
                },
                {
                    'codename': 'view_assigned_sessions',
                    'name': 'Can view assigned sessions',
                    'description': 'Allows therapists to view their assigned therapy sessions'
                },
                {
                    'codename': 'view_session_history',
                    'name': 'Can view session history',
                    'description': 'Allows therapists to view their session history'
                },
                {
                    'codename': 'update_session_status',
                    'name': 'Can update session status',
                    'description': 'Allows therapists to update session status (in-progress, completed)'
                },
                {
                    'codename': 'view_patient_details',
                    'name': 'Can view patient details',
                    'description': 'Allows therapists to view patient information for their sessions'
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

            # Create a specific Therapist role if it doesn't exist
            therapist_role, created = Role.objects.get_or_create(
                name='therapist',
                defaults={
                    'display_name': 'Therapist',
                    'description': 'Therapist role with access to their assigned sessions and dashboard',
                    'is_active': True
                }
            )
            
            if created:
                therapist_role.modules.add(module)
                self.stdout.write(
                    self.style.SUCCESS('Created Therapist role with module access')
                )

            # Summary
            self.stdout.write(
                self.style.SUCCESS('\n=== Therapist Dashboard Module Setup Complete ===')
            )
            self.stdout.write(f'Module: {module.display_name}')
            self.stdout.write(f'Permissions created: {len(created_permissions)}')
            self.stdout.write(f'Roles assigned: {len(assigned_roles)}')
            self.stdout.write('\nModule is now available in the navigation menu for assigned roles.')

    def create_sample_therapist_user(self):
        """Create a sample therapist user for testing"""
        try:
            therapist_user, created = CustomUser.objects.get_or_create(
                username='therapist_test',
                defaults={
                    'email': 'therapist@example.com',
                    'first_name': 'Test',
                    'last_name': 'Therapist',
                    'role': 'therapist',
                    'is_active': True
                }
            )
            
            if created:
                therapist_user.set_password('therapist123')
                therapist_user.save()
                self.stdout.write(
                    self.style.SUCCESS('Created sample therapist user: therapist_test / therapist123')
                )
            else:
                self.stdout.write(
                    self.style.WARNING('Sample therapist user already exists')
                )
        except Exception as e:
            self.stdout.write(
                self.style.ERROR(f'Error creating sample therapist user: {e}')
            )
