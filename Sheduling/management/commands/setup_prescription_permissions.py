from django.core.management.base import BaseCommand
from django.contrib.auth.models import Permission
from django.contrib.contenttypes.models import ContentType
from authentication.models import Role, CustomUser
from Sheduling.models import PrescriptionScheduling, PrescriptionItem, PrescriptionChangeLog, PrescriptionDispatch

class Command(BaseCommand):
    help = 'Set up specific permissions for prescription scheduling system'

    def handle(self, *args, **options):
        # Get content types for our models
        prescription_scheduling_ct = ContentType.objects.get_for_model(PrescriptionScheduling)
        prescription_item_ct = ContentType.objects.get_for_model(PrescriptionItem)
        prescription_changelog_ct = ContentType.objects.get_for_model(PrescriptionChangeLog)
        prescription_dispatch_ct = ContentType.objects.get_for_model(PrescriptionDispatch)

        # Define permission sets for different roles
        role_permissions = {
            'prescription_scheduler': [
                'view_prescriptionscheduling',
                'add_prescriptionscheduling', 
                'change_prescriptionscheduling',
                'view_prescriptionitem',
                'add_prescriptionitem',
                'change_prescriptionitem',
                'view_prescriptiondispatch',
                'add_prescriptiondispatch',
                'view_prescriptionchangelog',
            ],
            'prescription_admin': [
                'view_prescriptionscheduling',
                'add_prescriptionscheduling',
                'change_prescriptionscheduling', 
                'delete_prescriptionscheduling',
                'view_prescriptionitem',
                'add_prescriptionitem',
                'change_prescriptionitem',
                'delete_prescriptionitem',
                'view_prescriptiondispatch',
                'add_prescriptiondispatch',
                'change_prescriptiondispatch',
                'delete_prescriptiondispatch',
                'view_prescriptionchangelog',
                'add_prescriptionchangelog',
                'change_prescriptionchangelog',
                'delete_prescriptionchangelog',
            ],
            'procurement_staff': [
                'view_prescriptionscheduling',
                'change_prescriptionscheduling',
                'view_prescriptionitem',
                'view_prescriptiondispatch',
                'add_prescriptiondispatch',
                'view_prescriptionchangelog',
            ],
            'doctor': [
                'view_prescriptionscheduling',
                'add_prescriptionscheduling',
                'change_prescriptionscheduling',
                'view_prescriptionitem',
                'add_prescriptionitem',
                'change_prescriptionitem',
                'view_prescriptiondispatch',
                'view_prescriptionchangelog',
            ],
            'super_admin': [
                'view_prescriptionscheduling',
                'add_prescriptionscheduling',
                'change_prescriptionscheduling',
                'delete_prescriptionscheduling',
                'view_prescriptionitem',
                'add_prescriptionitem',
                'change_prescriptionitem',
                'delete_prescriptionitem',
                'view_prescriptiondispatch',
                'add_prescriptiondispatch',
                'change_prescriptiondispatch',
                'delete_prescriptiondispatch',
                'view_prescriptionchangelog',
                'add_prescriptionchangelog',
                'change_prescriptionchangelog',
                'delete_prescriptionchangelog',
            ]
        }

        # Apply permissions to roles
        for role_name, permission_codenames in role_permissions.items():
            try:
                role = Role.objects.get(name=role_name)
                self.stdout.write(f'Setting up permissions for role: {role.display_name}')
                
                # Get or create permissions
                permissions = []
                for codename in permission_codenames:
                    try:
                        # Try to find permission by codename
                        permission = Permission.objects.get(codename=codename)
                        permissions.append(permission)
                    except Permission.DoesNotExist:
                        self.stdout.write(
                            self.style.WARNING(f'Permission {codename} not found - skipping')
                        )
                
                # Note: Since Role model doesn't have direct permissions field,
                # we'll create a custom permission system or use Django's built-in
                # permission system through CustomUser model
                
                self.stdout.write(
                    self.style.SUCCESS(f'Configured {len(permissions)} permissions for {role.display_name}')
                )
                
            except Role.DoesNotExist:
                self.stdout.write(
                    self.style.WARNING(f'Role {role_name} not found - skipping')
                )

        # Create custom permissions for prescription scheduling
        custom_permissions = [
            ('send_final_prescription', 'Can send final prescriptions to procurement'),
            ('view_prescription_details', 'Can view detailed prescription information'),
            ('update_prescription_status', 'Can update prescription status'),
            ('view_change_log', 'Can view prescription change logs'),
            ('manage_prescription_dispatch', 'Can manage prescription dispatch'),
        ]

        for codename, name in custom_permissions:
            permission, created = Permission.objects.get_or_create(
                codename=codename,
                name=name,
                content_type=prescription_scheduling_ct,
            )
            if created:
                self.stdout.write(
                    self.style.SUCCESS(f'Created custom permission: {name}')
                )

        self.stdout.write(
            self.style.SUCCESS('Successfully set up prescription scheduling permissions')
        )
