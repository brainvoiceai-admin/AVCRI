from django.core.management.base import BaseCommand
from django.contrib.auth.models import Permission
from django.contrib.contenttypes.models import ContentType
from authentication.models import Module, Role


class Command(BaseCommand):
    help = 'Set up Treatment Room Availability module with permissions and role assignments'

    def handle(self, *args, **options):
        try:
            # Import models here to avoid circular imports
            from Patient.models import TreatmentRoom
            
            self.stdout.write('Setting up Treatment Room Availability module...')
            
            # Get or create ContentType for TreatmentRoom
            content_type = ContentType.objects.get_for_model(TreatmentRoom)
            
            # Create or get the Treatment Room Availability module
            module, created = Module.objects.get_or_create(
                name='room_availability',
                defaults={
                    'display_name': 'Treatment Room Availability',
                    'description': 'Treatment room availability dashboard for checking available rooms and occupancy schedules',
                    'url_name': 'room_availability_dashboard',
                    'icon': '🚪',
                    'is_active': True,
                    'order': 20
                }
            )
            
            if created:
                self.stdout.write(self.style.SUCCESS(f'  ✓ Created module: {module.display_name}'))
            else:
                # Update existing module
                module.display_name = 'Treatment Room Availability'
                module.description = 'Treatment room availability dashboard for checking available rooms and occupancy schedules'
                module.url_name = 'room_availability_dashboard'
                module.icon = '🚪'
                module.is_active = True
                module.save()
                self.stdout.write(self.style.WARNING(f'  ⚠ Module already exists, updated: {module.display_name}'))
            
            # Create custom permissions for Treatment Room Availability
            permissions = [
                {
                    'codename': 'view_room_availability',
                    'name': 'Can view room availability',
                    'description': 'Allows access to the treatment room availability dashboard'
                },
                {
                    'codename': 'view_available_rooms',
                    'name': 'Can view available rooms',
                    'description': 'Allows viewing available treatment rooms'
                },
                {
                    'codename': 'view_occupied_rooms',
                    'name': 'Can view occupied rooms',
                    'description': 'Allows viewing occupied treatment rooms'
                },
                {
                    'codename': 'manage_room_availability',
                    'name': 'Can manage room availability',
                    'description': 'Allows managing treatment room availability and schedules'
                }
            ]
            
            created_permissions = []
            for perm_data in permissions:
                perm, created = Permission.objects.get_or_create(
                    codename=perm_data['codename'],
                    content_type=content_type,
                    defaults={'name': perm_data['name']}
                )
                created_permissions.append(perm)
                if created:
                    self.stdout.write(self.style.SUCCESS(f"  ✓ Created permission: {perm.name}"))
                else:
                    self.stdout.write(f"  → Permission already exists: {perm.name}")
            
            # Assign module to relevant roles (similar to therapist availability)
            roles_to_assign = [
                'Super Admin',
                'Admin',
                'Reception',
                'Therapist',
                'General Manager',
                'super_admin',
                'admin',
                'therapist',
                'scheduling_staff'
            ]
            
            assigned_roles = []
            for role_name in roles_to_assign:
                try:
                    # Try case-insensitive lookup
                    role = Role.objects.filter(name__iexact=role_name).first()
                    if not role:
                        # Try searching display_name
                        role = Role.objects.filter(display_name__iexact=role_name).first()
                        
                    if role:
                        # Add module to role's modules
                        if module not in role.modules.all():
                            role.modules.add(module)
                            assigned_roles.append(role.name)
                            self.stdout.write(self.style.SUCCESS(f'  ✓ Assigned module to role: {role.name}'))
                        else:
                            self.stdout.write(f'  → Module already assigned to role: {role.name}')
                    else:
                        self.stdout.write(self.style.WARNING(f'  ⚠ Role not found: {role_name}'))
                except Exception as e:
                    self.stdout.write(self.style.WARNING(f'  ⚠ Error processing role {role_name}: {str(e)}'))
            
            self.stdout.write(
                self.style.SUCCESS('\\n=== Treatment Room Availability Module Setup Complete ===')
            )
            self.stdout.write(f'Module Name: {module.display_name}')
            self.stdout.write(f'URL: /sheduling/room-availability/')
            self.stdout.write(f'URL Name: {module.url_name}')
            self.stdout.write(f'Permissions Created: {len(created_permissions)}')
            self.stdout.write(f'Roles Assigned: {len(assigned_roles)}')
            
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'Error setting up module: {str(e)}'))
            import traceback
            traceback.print_exc()
