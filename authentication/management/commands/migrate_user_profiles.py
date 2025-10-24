from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from authentication.models import (
    PatientProfile, TherapistProfile, DoctorProfile, 
    AdminProfile, NurseProfile, StaffProfile
)
from masters.models import TherapistMaster

User = get_user_model()

class Command(BaseCommand):
    help = 'Migrate existing user data to new profile structure'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be migrated without making changes',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        
        if dry_run:
            self.stdout.write(self.style.WARNING('DRY RUN MODE - No changes will be made'))
        
        # Migrate existing users to appropriate profiles
        self.migrate_patients(dry_run)
        self.migrate_therapists(dry_run)
        self.migrate_doctors(dry_run)
        self.migrate_admins(dry_run)
        self.migrate_nurses(dry_run)
        self.migrate_staff(dry_run)
        
        self.stdout.write(self.style.SUCCESS('Migration completed successfully!'))

    def migrate_patients(self, dry_run):
        """Migrate users with patient role to PatientProfile"""
        patients = User.objects.filter(role='patient')
        self.stdout.write(f'Found {patients.count()} patients to migrate')
        
        for user in patients:
            if not hasattr(user, 'patient_profile'):
                if not dry_run:
                    PatientProfile.objects.create(
                        user=user,
                        patient_reg_no=f"PAT{user.id:06d}",  # Generate reg number
                        is_vip=False  # Default to non-VIP
                    )
                self.stdout.write(f'  - Created PatientProfile for {user.username}')

    def migrate_therapists(self, dry_run):
        """Migrate users with therapist role to TherapistProfile"""
        therapists = User.objects.filter(role='therapist')
        self.stdout.write(f'Found {therapists.count()} therapists to migrate')
        
        for user in therapists:
            if not hasattr(user, 'therapist_profile'):
                # Try to find existing therapist in TherapistMaster
                therapist_master = None
                if hasattr(user, 'therapist_code') and user.therapist_code:
                    try:
                        therapist_master = TherapistMaster.objects.get(therapist_code=user.therapist_code)
                    except TherapistMaster.DoesNotExist:
                        pass
                
                if not dry_run:
                    TherapistProfile.objects.create(
                        user=user,
                        therapist_code=therapist_master.therapist_code if therapist_master else f"TH{user.id:06d}",
                        employee_code=therapist_master.employee_code if therapist_master else f"EMP{user.id:06d}",
                        therapist_grade=therapist_master.therapist_grade if therapist_master else "Junior",
                        is_bathing_therapist=therapist_master.is_bathing_therapist if therapist_master else True
                    )
                self.stdout.write(f'  - Created TherapistProfile for {user.username}')

    def migrate_doctors(self, dry_run):
        """Migrate users with doctor role to DoctorProfile"""
        doctors = User.objects.filter(role='doctor')
        self.stdout.write(f'Found {doctors.count()} doctors to migrate')
        
        for user in doctors:
            if not hasattr(user, 'doctor_profile'):
                if not dry_run:
                    DoctorProfile.objects.create(
                        user=user,
                        doctor_id=f"DOC{user.id:06d}",
                        specialization="General Medicine",  # Default specialization
                        department="Medical",
                        qualification="MBBS",  # Default qualification
                        experience_years=0
                    )
                self.stdout.write(f'  - Created DoctorProfile for {user.username}')

    def migrate_admins(self, dry_run):
        """Migrate users with admin role to AdminProfile"""
        admins = User.objects.filter(role__in=['admin', 'super_admin'])
        self.stdout.write(f'Found {admins.count()} admins to migrate')
        
        for user in admins:
            if not hasattr(user, 'admin_profile'):
                if not dry_run:
                    AdminProfile.objects.create(
                        user=user,
                        admin_id=f"ADM{user.id:06d}",
                        department="Administration",
                        designation="Administrator" if user.role == 'admin' else "Super Administrator"
                    )
                self.stdout.write(f'  - Created AdminProfile for {user.username}')

    def migrate_nurses(self, dry_run):
        """Migrate users with nurse role to NurseProfile"""
        nurses = User.objects.filter(role='nurse')
        self.stdout.write(f'Found {nurses.count()} nurses to migrate')
        
        for user in nurses:
            if not hasattr(user, 'nurse_profile'):
                if not dry_run:
                    NurseProfile.objects.create(
                        user=user,
                        nurse_id=f"NUR{user.id:06d}",
                        department="Nursing",
                        qualification="B.Sc Nursing",  # Default qualification
                        experience_years=0
                    )
                self.stdout.write(f'  - Created NurseProfile for {user.username}')

    def migrate_staff(self, dry_run):
        """Migrate other staff users to StaffProfile"""
        staff_roles = ['scheduling_staff', 'ip_pharmacy_staff', 'imu_staff', 
                      'finance_staff', 'hr', 'housekeeping_staff']
        staff = User.objects.filter(role__in=staff_roles)
        self.stdout.write(f'Found {staff.count()} staff members to migrate')
        
        for user in staff:
            if not hasattr(user, 'staff_profile'):
                if not dry_run:
                    StaffProfile.objects.create(
                        user=user,
                        staff_id=f"STF{user.id:06d}",
                        department=self.get_department_for_role(user.role),
                        designation=self.get_designation_for_role(user.role)
                    )
                self.stdout.write(f'  - Created StaffProfile for {user.username}')

    def get_department_for_role(self, role):
        """Get department name based on role"""
        department_mapping = {
            'scheduling_staff': 'Scheduling',
            'ip_pharmacy_staff': 'Pharmacy',
            'imu_staff': 'IMU',
            'finance_staff': 'Finance',
            'hr': 'Human Resources',
            'housekeeping_staff': 'Housekeeping'
        }
        return department_mapping.get(role, 'General')

    def get_designation_for_role(self, role):
        """Get designation based on role"""
        designation_mapping = {
            'scheduling_staff': 'Scheduling Staff',
            'ip_pharmacy_staff': 'Pharmacy Staff',
            'imu_staff': 'IMU Staff',
            'finance_staff': 'Finance Staff',
            'hr': 'HR Staff',
            'housekeeping_staff': 'Housekeeping Staff'
        }
        return designation_mapping.get(role, 'Staff')
