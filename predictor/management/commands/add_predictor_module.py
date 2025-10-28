from django.core.management.base import BaseCommand
from authentication.models import Module, Role

class Command(BaseCommand):
    help = "Add the Predictor module to the system and assign it to admin roles"

    def handle(self, *args, **options):
        # Create or update the Predictor module
        module, created = Module.objects.get_or_create(
            name='demand_prediction',
            defaults={
                'display_name': 'Demand Prediction',
                'description': 'Patient demand forecasting and prediction analytics',
                'url_name': 'predictor:prediction_dashboard',
                'icon': '📈',
                'order': 20,
                'is_active': True
            }
        )
        
        if created:
            self.stdout.write(
                self.style.SUCCESS(f'Successfully created module: {module.display_name}')
            )
        else:
            # Update existing module
            module.display_name = 'Demand Prediction'
            module.description = 'Patient demand forecasting and prediction analytics'
            module.url_name = 'predictor:prediction_dashboard'
            module.icon = '📈'
            module.order = 20
            module.is_active = True
            module.save()
            self.stdout.write(
                self.style.SUCCESS(f'Successfully updated module: {module.display_name}')
            )

        # Add the module to admin and super_admin roles
        admin_roles = Role.objects.filter(name__in=['admin', 'super_admin'])
        
        for role in admin_roles:
            if module not in role.modules.all():
                role.modules.add(module)
                self.stdout.write(
                    self.style.SUCCESS(f'Added module to role: {role.display_name}')
                )
            else:
                self.stdout.write(
                    self.style.WARNING(f'Module already assigned to role: {role.display_name}')
                )

        # Also check if there are any custom roles that should have this module
        custom_roles = Role.objects.exclude(name__in=['admin', 'super_admin'])
        for role in custom_roles:
            # You can add logic here to determine which custom roles should have access
            # For now, we'll leave it as is since it's admin-specific functionality
            pass

        self.stdout.write(
            self.style.SUCCESS('Predictor module setup completed successfully!')
        )
        
        # Display module information
        self.stdout.write(f'\nModule Details:')
        self.stdout.write(f'Name: {module.name}')
        self.stdout.write(f'Display Name: {module.display_name}')
        self.stdout.write(f'URL Name: {module.url_name}')
        self.stdout.write(f'Icon: {module.icon}')
        self.stdout.write(f'Order: {module.order}')
        self.stdout.write(f'Active: {module.is_active}')
        
        # Display roles that have access
        roles_with_access = Role.objects.filter(modules=module)
        self.stdout.write(f'\nRoles with access:')
        for role in roles_with_access:
            self.stdout.write(f'- {role.display_name} ({role.name})')
