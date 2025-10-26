from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from authentication.models import Module, Role
from django.db import transaction

User = get_user_model()

class Command(BaseCommand):
    help = 'Setup the therapy scheduling module with proper permissions and roles'

    def add_arguments(self, parser):
        parser.add_argument(
            '--force',
            action='store_true',
            help='Force update existing module and permissions',
        )

    def handle(self, *args, **options):
        force = options['force']
        
        with transaction.atomic():
            # Create or update the scheduling module
            module, created = Module.objects.get_or_create(
                name='therapy_scheduling',
                defaults={
                    'display_name': 'Therapy Scheduling',
                    'description': 'Manage therapy scheduling, allocations, and therapist assignments',
                    'url_name': 'scheduling_dashboard',
                    'icon': '📅',
                    'is_active': True,
                    'order': 10
                }
            )
            
            if not created and force:
                module.display_name = 'Therapy Scheduling'
                module.description = 'Manage therapy scheduling, allocations, and therapist assignments'
                module.url_name = 'scheduling_dashboard'
                module.icon = '📅'
                module.is_active = True
                module.order = 10
                module.save()
                self.stdout.write(
                    self.style.WARNING('Updated existing therapy scheduling module')
                )
            elif created:
                self.stdout.write(
                    self.style.SUCCESS('Created therapy scheduling module')
                )
            else:
                self.stdout.write(
                    self.style.WARNING('Therapy scheduling module already exists. Use --force to update.')
                )

            # Create or update roles with scheduling permissions
            self.setup_scheduling_roles()
            
            # Update existing user roles to include scheduling module
            self.update_user_permissions()
            
            self.stdout.write(
                self.style.SUCCESS('Successfully setup therapy scheduling module with permissions!')
            )

    def setup_scheduling_roles(self):
        """Create or update roles with scheduling permissions"""
        
        # Super Admin - has access to everything
        super_admin_role, created = Role.objects.get_or_create(
            name='super_admin_role',
            defaults={
                'display_name': 'Super Admin Role',
                'description': 'Full access to all modules including therapy scheduling',
                'is_active': True
            }
        )
        if created:
            super_admin_role.modules.set(Module.objects.filter(is_active=True))
            self.stdout.write('Created Super Admin role with all permissions')
        
        # Scheduling Staff Role
        scheduling_role, created = Role.objects.get_or_create(
            name='scheduling_staff_role',
            defaults={
                'display_name': 'Scheduling Staff Role',
                'description': 'Dedicated role for therapy scheduling staff',
                'is_active': True
            }
        )
        
        # Add scheduling module to scheduling staff role
        scheduling_module = Module.objects.get(name='therapy_scheduling')
        scheduling_role.modules.add(scheduling_module)
        
        # Add other relevant modules for scheduling staff
        relevant_modules = Module.objects.filter(
            name__in=[
                'patient_lookup',
                'therapy_schedule', 
                'treatment_schedule',
                'reports'
            ],
            is_active=True
        )
        scheduling_role.modules.add(*relevant_modules)
        
        if created:
            self.stdout.write('Created Scheduling Staff role with scheduling permissions')
        else:
            self.stdout.write('Updated Scheduling Staff role with scheduling permissions')

        # Doctor Role - add scheduling access
        doctor_role, created = Role.objects.get_or_create(
            name='doctor_role',
            defaults={
                'display_name': 'Doctor Role',
                'description': 'Doctor role with therapy scheduling access',
                'is_active': True
            }
        )
        
        # Add scheduling module to doctor role
        doctor_role.modules.add(scheduling_module)
        
        # Add other relevant modules for doctors
        doctor_modules = Module.objects.filter(
            name__in=[
                'patient_lookup',
                'add_therapy',
                'add_prescription',
                'treatment_schedule',
                'reports'
            ],
            is_active=True
        )
        doctor_role.modules.add(*doctor_modules)
        
        if created:
            self.stdout.write('Created Doctor role with scheduling permissions')
        else:
            self.stdout.write('Updated Doctor role with scheduling permissions')

        # Therapist Role - add scheduling access
        therapist_role, created = Role.objects.get_or_create(
            name='therapist_role',
            defaults={
                'display_name': 'Therapist Role',
                'description': 'Therapist role with therapy scheduling access',
                'is_active': True
            }
        )
        
        # Add scheduling module to therapist role
        therapist_role.modules.add(scheduling_module)
        
        # Add other relevant modules for therapists
        therapist_modules = Module.objects.filter(
            name__in=[
                'therapy_schedule',
                'treatment_schedule'
            ],
            is_active=True
        )
        therapist_role.modules.add(*therapist_modules)
        
        if created:
            self.stdout.write('Created Therapist role with scheduling permissions')
        else:
            self.stdout.write('Updated Therapist role with scheduling permissions')

        # Admin Role - add scheduling access
        admin_role, created = Role.objects.get_or_create(
            name='admin_role',
            defaults={
                'display_name': 'Admin Role',
                'description': 'Administrative role with therapy scheduling access',
                'is_active': True
            }
        )
        
        # Add scheduling module to admin role
        admin_role.modules.add(scheduling_module)
        
        # Add other relevant modules for admins
        admin_modules = Module.objects.filter(
            name__in=[
                'user_management',
                'demand_prediction',
                'audit_log',
                'master_tables',
                'reports'
            ],
            is_active=True
        )
        admin_role.modules.add(*admin_modules)
        
        if created:
            self.stdout.write('Created Admin role with scheduling permissions')
        else:
            self.stdout.write('Updated Admin role with scheduling permissions')

    def update_user_permissions(self):
        """Update existing users with appropriate scheduling permissions"""
        
        # Get the scheduling module
        try:
            scheduling_module = Module.objects.get(name='therapy_scheduling')
        except Module.DoesNotExist:
            self.stdout.write(
                self.style.ERROR('Scheduling module not found. Run this command first.')
            )
            return

        # Update users based on their roles
        updated_count = 0
        
        # Super admins - already have access to all modules
        super_admins = User.objects.filter(role='super_admin')
        self.stdout.write(f'Found {super_admins.count()} super admins (already have full access)')
        
        # Scheduling staff - assign scheduling staff role
        scheduling_staff = User.objects.filter(role='scheduling_staff')
        try:
            scheduling_role = Role.objects.get(name='scheduling_staff_role')
            for user in scheduling_staff:
                if not user.custom_role:
                    user.custom_role = scheduling_role
                    user.save()
                    updated_count += 1
            self.stdout.write(f'Updated {updated_count} scheduling staff users')
        except Role.DoesNotExist:
            self.stdout.write('Scheduling staff role not found')
        
        # Doctors - assign doctor role if they don't have custom role
        doctors = User.objects.filter(role='doctor')
        try:
            doctor_role = Role.objects.get(name='doctor_role')
            for user in doctors:
                if not user.custom_role:
                    user.custom_role = doctor_role
                    user.save()
                    updated_count += 1
            self.stdout.write(f'Updated {updated_count} doctor users')
        except Role.DoesNotExist:
            self.stdout.write('Doctor role not found')
        
        # Therapists - assign therapist role if they don't have custom role
        therapists = User.objects.filter(role='therapist')
        try:
            therapist_role = Role.objects.get(name='therapist_role')
            for user in therapists:
                if not user.custom_role:
                    user.custom_role = therapist_role
                    user.save()
                    updated_count += 1
            self.stdout.write(f'Updated {updated_count} therapist users')
        except Role.DoesNotExist:
            self.stdout.write('Therapist role not found')
        
        # Admins - assign admin role if they don't have custom role
        admins = User.objects.filter(role='admin')
        try:
            admin_role = Role.objects.get(name='admin_role')
            for user in admins:
                if not user.custom_role:
                    user.custom_role = admin_role
                    user.save()
                    updated_count += 1
            self.stdout.write(f'Updated {updated_count} admin users')
        except Role.DoesNotExist:
            self.stdout.write('Admin role not found')
        
        self.stdout.write(
            self.style.SUCCESS(f'Total users updated: {updated_count}')
        )

    def create_sample_data(self):
        """Create sample data for testing (optional)"""
        self.stdout.write('Creating sample data...')
        
        # This could include creating sample therapy allocations, etc.
        # For now, we'll just note that this could be expanded
        self.stdout.write('Sample data creation not implemented yet')
