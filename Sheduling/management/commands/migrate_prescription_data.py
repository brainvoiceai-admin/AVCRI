from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone
from Sheduling.models import PrescriptionScheduling, PrescriptionItem, PrescriptionChangeLog
from MySql_Data_pull.models import store_Therapy
from Patient.models import Patient
from authentication.models import CustomUser
from datetime import datetime

class Command(BaseCommand):
    help = 'Migrate existing prescription data to the new scheduling system'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be migrated without actually doing it',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        
        if dry_run:
            self.stdout.write(
                self.style.WARNING('DRY RUN MODE - No data will be migrated')
            )

        # Get all existing prescription data
        prescriptions = store_Therapy.objects.all()
        
        migrated_count = 0
        skipped_count = 0
        
        with transaction.atomic():
            for prescription in prescriptions:
                try:
                    # Get patient
                    patient = Patient.objects.get(id=prescription.patient_id)
                    
                    # Get doctor (use a default user if not found)
                    try:
                        doctor = CustomUser.objects.get(id=prescription.doctor_id)
                    except CustomUser.DoesNotExist:
                        # Use first admin user as default
                        doctor = CustomUser.objects.filter(is_staff=True).first()
                        if not doctor:
                            self.stdout.write(
                                self.style.ERROR(f'No admin user found for prescription {prescription.id}')
                            )
                            skipped_count += 1
                            continue
                    
                    # Parse prescription date
                    try:
                        prescription_date = prescription.prescription_date
                        if isinstance(prescription_date, str):
                            prescription_date = datetime.strptime(prescription_date, '%Y-%m-%d').date()
                    except (ValueError, TypeError):
                        prescription_date = timezone.now().date()
                    
                    if not dry_run:
                        # Create prescription scheduling record
                        scheduling, created = PrescriptionScheduling.objects.get_or_create(
                            patient=patient,
                            prescription_date=prescription_date,
                            defaults={
                                'doctor': doctor,
                                'status': 'draft',
                                'created_at': prescription.created_at or timezone.now(),
                                'updated_at': prescription.updated_at or timezone.now()
                            }
                        )
                        
                        if created:
                            # Create prescription items
                            if prescription.item_name:
                                PrescriptionItem.objects.create(
                                    prescription_scheduling=scheduling,
                                    item_name=prescription.item_name,
                                    dose=prescription.dose or '',
                                    quantity=prescription.quantity or 1,
                                    time=prescription.time or 'M',
                                    notes=prescription.notes or '',
                                    created_at=prescription.created_at or timezone.now(),
                                    updated_at=prescription.updated_at or timezone.now()
                                )
                            
                            # Log the migration
                            PrescriptionChangeLog.objects.create(
                                patient=patient,
                                prescription_date=prescription_date,
                                action='create',
                                changed_by=doctor,
                                description='Migrated from legacy prescription system',
                                timestamp=timezone.now()
                            )
                            
                            migrated_count += 1
                        else:
                            skipped_count += 1
                    else:
                        # Dry run - just count
                        migrated_count += 1
                        
                except Patient.DoesNotExist:
                    self.stdout.write(
                        self.style.WARNING(f'Patient not found for prescription {prescription.id}')
                    )
                    skipped_count += 1
                except Exception as e:
                    self.stdout.write(
                        self.style.ERROR(f'Error migrating prescription {prescription.id}: {str(e)}')
                    )
                    skipped_count += 1

        if dry_run:
            self.stdout.write(
                self.style.SUCCESS(f'DRY RUN: Would migrate {migrated_count} prescriptions, skip {skipped_count}')
            )
        else:
            self.stdout.write(
                self.style.SUCCESS(f'Successfully migrated {migrated_count} prescriptions, skipped {skipped_count}')
            )
