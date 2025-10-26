from django.core.management.base import BaseCommand
from django.contrib.auth.models import Permission
from authentication.models import Module, Role, CustomUser
from django.contrib.contenttypes.models import ContentType
from django.db import transaction

class Command(BaseCommand):
    help = 'Set up the procurement module with permissions and role assignments'

    def handle(self, *args, **options):
        with transaction.atomic():
            # Create the procurement module
            module, created = Module.objects.get_or_create(
                name='procurement_dashboard',
                defaults={
                    'display_name': 'Procurement Dashboard',
                    'description': 'Manage prescription preparation and dispatch for procurement departments',
                    'url_name': 'procurement_dashboard',
                    'icon': '📦',
                    'is_active': True,
                    'order': 15
                }
            )
            
            if created:
                self.stdout.write(
                    self.style.SUCCESS(f'✅ Created module: {module.display_name}')
                )
            else:
                self.stdout.write(
                    self.style.WARNING(f'⚠️  Module already exists: {module.display_name}')
                )

            # Add module to relevant roles
            roles_to_add = [
                'doctor_admin',
                'doctor', 
                'super_admin',
                'nurse',
                'scheduling_staff'
            ]
            
            for role_name in roles_to_add:
                try:
                    role = Role.objects.get(name=role_name)
                    if module not in role.modules.all():
                        role.modules.add(module)
                        self.stdout.write(
                            self.style.SUCCESS(f'✅ Added {module.display_name} to {role.display_name}')
                        )
                    else:
                        self.stdout.write(
                            self.style.WARNING(f'⚠️  {module.display_name} already assigned to {role.display_name}')
                        )
                except Role.DoesNotExist:
                    self.stdout.write(
                        self.style.ERROR(f'❌ Role {role_name} not found')
                    )

            # Create custom permissions for procurement
            self.create_procurement_permissions()

            self.stdout.write(
                self.style.SUCCESS('\n🎉 Procurement module setup completed successfully!')
            )

    def create_procurement_permissions(self):
        """Create custom permissions for the procurement module"""
        
        # Get the content type for PrescriptionScheduling model
        try:
            from Sheduling.models import PrescriptionScheduling
            content_type = ContentType.objects.get_for_model(PrescriptionScheduling)
        except:
            self.stdout.write(
                self.style.ERROR('❌ Could not find PrescriptionScheduling model')
            )
            return

        # Define custom permissions
        permissions = [
            ('view_procurement_dashboard', 'Can view procurement dashboard'),
            ('manage_procurement_prescriptions', 'Can manage procurement prescriptions'),
            ('mark_prescriptions_dispatched', 'Can mark prescriptions as dispatched'),
            ('view_procurement_reports', 'Can view procurement reports'),
        ]

        created_permissions = []
        for codename, name in permissions:
            permission, created = Permission.objects.get_or_create(
                codename=codename,
                content_type=content_type,
                defaults={'name': name}
            )
            if created:
                created_permissions.append(permission)
                self.stdout.write(
                    self.style.SUCCESS(f'✅ Created permission: {name}')
                )
            else:
                self.stdout.write(
                    self.style.WARNING(f'⚠️  Permission already exists: {name}')
                )

        # Assign permissions to roles
        role_permissions = {
            'doctor_admin': ['view_procurement_dashboard', 'manage_procurement_prescriptions', 'mark_prescriptions_dispatched', 'view_procurement_reports'],
            'doctor': ['view_procurement_dashboard', 'manage_procurement_prescriptions', 'mark_prescriptions_dispatched'],
            'super_admin': ['view_procurement_dashboard', 'manage_procurement_prescriptions', 'mark_prescriptions_dispatched', 'view_procurement_reports'],
            'nurse': ['view_procurement_dashboard', 'mark_prescriptions_dispatched'],
            'scheduling_staff': ['view_procurement_dashboard', 'manage_procurement_prescriptions', 'mark_prescriptions_dispatched'],
        }

        for role_name, permission_codenames in role_permissions.items():
            try:
                role = Role.objects.get(name=role_name)
                for codename in permission_codenames:
                    try:
                        permission = Permission.objects.get(
                            codename=codename,
                            content_type=content_type
                        )
                        # Note: We're not directly assigning permissions to roles here
                        # as the current system uses modules for access control
                        self.stdout.write(
                            self.style.SUCCESS(f'✅ Permission {codename} available for {role.display_name}')
                        )
                    except Permission.DoesNotExist:
                        self.stdout.write(
                            self.style.ERROR(f'❌ Permission {codename} not found')
                        )
            except Role.DoesNotExist:
                self.stdout.write(
                    self.style.ERROR(f'❌ Role {role_name} not found')
                )

        if created_permissions:
            self.stdout.write(
                self.style.SUCCESS(f'✅ Created {len(created_permissions)} new permissions')
            )
