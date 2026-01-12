from django.core.management.base import BaseCommand
from authentication.models import Module, Role
from django.db import transaction
import sys


class Command(BaseCommand):
    help = 'Set up Prescription Usage Master module with default superadmin access'

    def add_arguments(self, parser):
        parser.add_argument(
            '--force',
            action='store_true',
            help='Force update even if module exists',
        )

    def handle(self, *args, **options):
        force = options.get('force', False)
        
        try:
            with transaction.atomic():
                # Create or get the prescription usage module
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
                
                if created:
                    self.stdout.write(
                        self.style.SUCCESS(f'✅ Created module: {module.display_name}')
                    )
                else:
                    if force:
                        # Update existing module
                        module.display_name = 'Prescription Usage Master'
                        module.description = 'Manage prescription usage types for prescriptions'
                        module.url_name = 'prescriptionusage_manage'
                        module.icon = '💊'
                        module.is_active = True
                        module.order = 55
                        module.save()
                        self.stdout.write(
                            self.style.SUCCESS(f'✅ Updated module: {module.display_name}')
                        )
                    else:
                        self.stdout.write(
                            self.style.WARNING(f'⚠️  Module already exists: {module.display_name}')
                        )

                # Verify module is active
                if not module.is_active:
                    module.is_active = True
                    module.save()
                    self.stdout.write(
                        self.style.SUCCESS(f'✅ Activated module: {module.display_name}')
                    )

                # Verify module exists and is accessible
                self.stdout.write(
                    self.style.SUCCESS(
                        f'\n✅ Setup complete! Prescription Usage Master module is ready.\n'
                        f'   - Module Name: {module.name}\n'
                        f'   - Display Name: {module.display_name}\n'
                        f'   - URL Name: {module.url_name}\n'
                        f'   - Is Active: {module.is_active}\n'
                        f'   - URL: /masters/prescription-usages/\n'
                        f'   - Super Admin has automatic access to all active modules\n'
                        f'   - Other users can be assigned access through Role Management\n'
                        f'\n   To assign to other users:\n'
                        f'   1. Go to Administration → Module Management\n'
                        f'   2. Find "Prescription Usage Master"\n'
                        f'   3. Assign it to roles or users as needed'
                    )
                )
                
                # Verify super admin access
                from authentication.models import CustomUser
                super_admins = CustomUser.objects.filter(role='super_admin', is_active=True)
                if super_admins.exists():
                    self.stdout.write(
                        self.style.SUCCESS(
                            f'\n   Found {super_admins.count()} active super admin(s) with automatic access'
                        )
                    )
                
        except Exception as e:
            self.stdout.write(
                self.style.ERROR(f'❌ Error setting up module: {str(e)}')
            )
            import traceback
            self.stdout.write(traceback.format_exc())
            sys.exit(1)

