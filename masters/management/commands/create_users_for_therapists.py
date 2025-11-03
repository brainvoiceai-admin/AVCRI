from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from authentication.models import TherapistProfile, PatientProfile
from masters.models import TherapistMaster
from Sheduling.models import PatientSnapshot

User = get_user_model()


class Command(BaseCommand):
    help = 'Create user accounts for TherapistMaster and PatientSnapshot records that don\'t have users'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be created without making changes',
        )
        parser.add_argument(
            '--therapists-only',
            action='store_true',
            help='Only create users for therapists',
        )
        parser.add_argument(
            '--patients-only',
            action='store_true',
            help='Only create users for patients',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        therapists_only = options['therapists_only']
        patients_only = options['patients_only']

        if dry_run:
            self.stdout.write(self.style.WARNING('DRY RUN MODE - No changes will be made'))

        if not patients_only:
            self.create_users_for_therapists(dry_run)
        
        if not therapists_only:
            self.create_users_for_patients(dry_run)

        self.stdout.write(self.style.SUCCESS('\nUser creation completed!'))

    def create_users_for_therapists(self, dry_run):
        """Create user accounts for TherapistMaster records without users"""
        therapists = TherapistMaster.objects.filter(user__isnull=True)
        self.stdout.write(f'\nFound {therapists.count()} therapists without user accounts')

        created_count = 0
        skipped_count = 0

        for therapist in therapists:
            # Check if therapist code already has a profile (from another user)
            existing_profile = TherapistProfile.objects.filter(therapist_code=therapist.therapist_code).first()
            if existing_profile:
                # Link existing user to therapist master
                if not dry_run:
                    therapist.user = existing_profile.user
                    therapist.therapist_profile = existing_profile
                    therapist.save()
                self.stdout.write(f'  ✓ Linked existing user for {therapist.therapist_code} ({therapist.therapist_name})')
                skipped_count += 1
                continue

            # Generate username from therapist code
            username = therapist.therapist_code.lower().replace(' ', '_').replace('-', '_')
            base_username = username
            
            # Ensure username is unique
            counter = 1
            while User.objects.filter(username=username).exists():
                username = f"{base_username}_{counter}"
                counter += 1

            # Generate email
            email = f"{username}@avcri.local"
            
            # Check if email exists
            if User.objects.filter(email=email).exists():
                email = f"{username}_{therapist.therapist_code}@avcri.local"

            # Split name
            name_parts = therapist.therapist_name.split(maxsplit=1)
            first_name = name_parts[0] if name_parts else therapist.therapist_name
            last_name = name_parts[1] if len(name_parts) > 1 else ''

            # Default password
            default_password = f"{therapist.therapist_code}@{therapist.employee_code}"

            if dry_run:
                self.stdout.write(
                    f'  [DRY RUN] Would create user for {therapist.therapist_code} ({therapist.therapist_name})'
                )
                self.stdout.write(f'    Username: {username}, Password: {default_password}')
            else:
                try:
                    # Create user account
                    user = User.objects.create_user(
                        username=username,
                        email=email,
                        password=default_password,
                        first_name=first_name,
                        last_name=last_name,
                        role='therapist'
                    )

                    # Create therapist profile
                    therapist_profile = TherapistProfile.objects.create(
                        user=user,
                        therapist_code=therapist.therapist_code,
                        employee_code=therapist.employee_code,
                        therapist_grade=therapist.therapist_grade or 'Junior',
                        is_bathing_therapist=therapist.is_bathing_therapist
                    )

                    # Link to therapist master
                    therapist.user = user
                    therapist.therapist_profile = therapist_profile
                    therapist.save()

                    self.stdout.write(
                        self.style.SUCCESS(
                            f'  ✓ Created user for {therapist.therapist_code} ({therapist.therapist_name})'
                        )
                    )
                    self.stdout.write(f'    Username: {username}, Password: {default_password}')
                    created_count += 1
                except Exception as e:
                    self.stdout.write(
                        self.style.ERROR(
                            f'  ✗ Error creating user for {therapist.therapist_code}: {str(e)}'
                        )
                    )

        self.stdout.write(f'\nTherapist users: {created_count} created, {skipped_count} linked from existing profiles')

    def create_users_for_patients(self, dry_run):
        """Create user accounts for PatientSnapshot records without users"""
        # Get patient snapshots that don't have corresponding PatientProfile
        patient_snapshots = PatientSnapshot.objects.all()
        
        # Filter out those that already have a PatientProfile with matching reg_no
        from django.db.models import Q
        existing_reg_nos = set(
            PatientProfile.objects.values_list('patient_reg_no', flat=True)
        )
        
        patients_without_users = patient_snapshots.exclude(
            pat_reg_no__in=existing_reg_nos
        )
        
        self.stdout.write(f'\nFound {patients_without_users.count()} patient snapshots without user accounts')

        created_count = 0
        skipped_count = 0

        for patient_snapshot in patients_without_users[:100]:  # Limit to first 100 to avoid overwhelming
            # Check if a user with matching reg_no in profile exists
            existing_profile = PatientProfile.objects.filter(
                patient_reg_no=patient_snapshot.pat_reg_no
            ).first()
            
            if existing_profile:
                skipped_count += 1
                continue

            # Generate username from reg_no
            username = f"pat_{patient_snapshot.pat_reg_no.lower().replace(' ', '_').replace('-', '_')}"
            base_username = username
            
            # Ensure username is unique
            counter = 1
            while User.objects.filter(username=username).exists():
                username = f"{base_username}_{counter}"
                counter += 1

            # Generate email
            email = f"{username}@avcri.local"
            if User.objects.filter(email=email).exists():
                email = f"{username}_{patient_snapshot.pat_reg_no}@avcri.local"

            # Use patient name or generate one
            patient_name = patient_snapshot.pat_name or f"Patient {patient_snapshot.pat_reg_no}"
            name_parts = patient_name.split(maxsplit=1)
            first_name = name_parts[0] if name_parts else patient_name
            last_name = name_parts[1] if len(name_parts) > 1 else ''

            # Default password
            default_password = f"patient@{patient_snapshot.pat_reg_no}"

            if dry_run:
                self.stdout.write(
                    f'  [DRY RUN] Would create user for patient {patient_snapshot.pat_reg_no} ({patient_name})'
                )
                self.stdout.write(f'    Username: {username}, Password: {default_password}')
            else:
                try:
                    # Create user account
                    user = User.objects.create_user(
                        username=username,
                        email=email,
                        password=default_password,
                        first_name=first_name,
                        last_name=last_name,
                        role='patient'
                    )

                    # Create patient profile
                    PatientProfile.objects.create(
                        user=user,
                        patient_reg_no=patient_snapshot.pat_reg_no,
                        date_of_birth=None,
                        gender=patient_snapshot.pat_sex or 'male'
                    )

                    self.stdout.write(
                        self.style.SUCCESS(
                            f'  ✓ Created user for patient {patient_snapshot.pat_reg_no} ({patient_name})'
                        )
                    )
                    self.stdout.write(f'    Username: {username}, Password: {default_password}')
                    created_count += 1
                except Exception as e:
                    self.stdout.write(
                        self.style.ERROR(
                            f'  ✗ Error creating user for patient {patient_snapshot.pat_reg_no}: {str(e)}'
                        )
                    )

        if patients_without_users.count() > 100:
            self.stdout.write(
                self.style.WARNING(
                    f'\n  Note: Only processed first 100 patients. Run again to process more.'
                )
            )

        self.stdout.write(f'\nPatient users: {created_count} created, {skipped_count} skipped (already have profiles)')

