from django.core.management.base import BaseCommand
from django.contrib.auth.models import Permission
from django.contrib.contenttypes.models import ContentType
from authentication.models import Module, Role, CustomUser
from django.db import transaction


class Command(BaseCommand):
    help = 'Set up Patient Dashboard module with permissions and role assignments'

    def add_arguments(self, parser):
        parser.add_argument(
            '--force',
            action='store_true',
            help='Force recreation of module and permissions',
        )

    def handle(self, *args, **options):
        force = options.get('force', False)
        
        with transaction.atomic():
            # Create or get the Patient Dashboard module
            module, created = Module.objects.get_or_create(
                name='patient_dashboard',
                defaults={
                    'display_name': 'Patient Dashboard',
                    'description': 'Patient dashboard for viewing therapy sessions and prescriptions',
                    'icon': '🧑‍⚕️',
                    'url_name': 'patient_dashboard',
                    'is_active': True,
                    'order': 10
                }
            )
            
            if created:
                self.stdout.write(
                    self.style.SUCCESS(f'Created module: {module.display_name}')
                )
            elif force:
                module.display_name = 'Patient Dashboard'
                module.description = 'Patient dashboard for viewing therapy sessions and prescriptions'
                module.icon = '🧑‍⚕️'
                module.url_name = 'patient_dashboard'
                module.is_active = True
                module.order = 10
                module.save()
                self.stdout.write(
                    self.style.SUCCESS(f'Updated module: {module.display_name}')
                )
            else:
                self.stdout.write(
                    self.style.WARNING(f'Module already exists: {module.display_name}')
                )

            # Create custom permissions for Patient Dashboard
            permissions_data = [
                {
                    'codename': 'view_patient_dashboard',
                    'name': 'Can view patient dashboard',
                    'description': 'Allows access to the patient dashboard'
                },
                {
                    'codename': 'view_own_therapy_sessions',
                    'name': 'Can view own therapy sessions',
                    'description': 'Allows patients to view their own therapy sessions'
                },
                {
                    'codename': 'view_own_prescriptions',
                    'name': 'Can view own prescriptions',
                    'description': 'Allows patients to view their own prescriptions'
                },
                {
                    'codename': 'view_session_history',
                    'name': 'Can view session history',
                    'description': 'Allows patients to view their session history'
                },
                {
                    'codename': 'export_patient_data',
                    'name': 'Can export patient data',
                    'description': 'Allows patients to export their data'
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
                'patient',
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

            # Note: Permissions are created but not assigned to roles as the Role model
            # doesn't have a permissions field. Permissions can be assigned to users directly
            # or through Django's built-in permission system.

            # Create a specific Patient role if it doesn't exist
            patient_role, created = Role.objects.get_or_create(
                name='patient',
                defaults={
                    'display_name': 'Patient',
                    'description': 'Patient role with access to their own dashboard',
                    'is_active': True
                }
            )
            
            if created:
                patient_role.modules.add(module)
                self.stdout.write(
                    self.style.SUCCESS('Created Patient role with module access')
                )

            # Summary
            self.stdout.write(
                self.style.SUCCESS('\n=== Patient Dashboard Module Setup Complete ===')
            )
            self.stdout.write(f'Module: {module.display_name}')
            self.stdout.write(f'Permissions created: {len(created_permissions)}')
            self.stdout.write(f'Roles assigned: {len(assigned_roles)}')
            self.stdout.write('\nModule is now available in the navigation menu for assigned roles.')

    def create_sample_patient_user(self):
        """Create a sample patient user for testing"""
        try:
            patient_user, created = CustomUser.objects.get_or_create(
                username='patient_test',
                defaults={
                    'email': 'patient@example.com',
                    'first_name': 'Test',
                    'last_name': 'Patient',
                    'role': 'patient',
                    'is_active': True
                }
            )
            
            if created:
                patient_user.set_password('patient123')
                patient_user.save()
                self.stdout.write(
                    self.style.SUCCESS('Created sample patient user: patient_test / patient123')
                )
            else:
                self.stdout.write(
                    self.style.WARNING('Sample patient user already exists')
                )
        except Exception as e:
            self.stdout.write(
                self.style.ERROR(f'Error creating sample patient user: {e}')
            )
