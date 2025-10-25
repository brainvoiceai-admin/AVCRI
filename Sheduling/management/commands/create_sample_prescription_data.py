from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone
from Sheduling.models import PrescriptionScheduling, PrescriptionItem, PrescriptionChangeLog
from Sheduling.models import PatientSnapshot
from authentication.models import CustomUser
from datetime import datetime, timedelta
import random

class Command(BaseCommand):
    help = 'Create sample prescription data for testing'

    def add_arguments(self, parser):
        parser.add_argument(
            '--count',
            type=int,
            default=10,
            help='Number of sample prescriptions to create',
        )

    def handle(self, *args, **options):
        count = options['count']
        
        # Get some patients
        patients = PatientSnapshot.objects.all()[:count]
        if not patients:
            self.stdout.write(
                self.style.ERROR('No patients found. Please create some patients first.')
            )
            return
        
        # Get some doctors
        doctors = CustomUser.objects.filter(role__in=['doctor', 'doctor_admin', 'super_admin'])
        if not doctors:
            self.stdout.write(
                self.style.ERROR('No doctors found. Please create some doctor users first.')
            )
            return
        
        # Sample prescription items
        prescription_items = [
            {'name': 'Paracetamol', 'dose': '500mg', 'time': 'M'},
            {'name': 'Amoxicillin', 'dose': '250mg', 'time': 'ABF'},
            {'name': 'Omeprazole', 'dose': '20mg', 'time': 'BL'},
            {'name': 'Metformin', 'dose': '500mg', 'time': 'AL'},
            {'name': 'Aspirin', 'dose': '75mg', 'time': 'E'},
            {'name': 'Lisinopril', 'dose': '10mg', 'time': 'AD'},
            {'name': 'Atorvastatin', 'dose': '20mg', 'time': 'BT'},
            {'name': 'Kashaya Regimen', 'dose': '15ml', 'time': 'M'},
            {'name': 'Thailam', 'dose': '5ml', 'time': 'M'},
            {'name': 'Murivenna', 'dose': '10ml', 'time': 'AL'},
        ]
        
        created_count = 0
        
        with transaction.atomic():
            for i, patient in enumerate(patients):
                try:
                    # Create prescription for today or yesterday
                    prescription_date = timezone.now().date() - timedelta(days=random.randint(0, 1))
                    
                    # Get a random doctor
                    doctor = random.choice(doctors)
                    
                    # Create prescription scheduling
                    scheduling = PrescriptionScheduling.objects.create(
                        patient=patient,
                        prescription_date=prescription_date,
                        doctor=doctor,
                        status=random.choice(['draft', 'scheduled', 'dispatched']),
                        sent_to='IP Pharmacy' if random.choice([True, False]) else 'Kashaya Room',
                        dispatched_from='IP Pharmacy' if random.choice([True, False]) else 'Kashaya Room',
                        dispatched_at=timezone.now() if random.choice([True, False]) else None
                    )
                    
                    # Create prescription items
                    num_items = random.randint(1, 4)
                    selected_items = random.sample(prescription_items, num_items)
                    
                    for item_data in selected_items:
                        PrescriptionItem.objects.create(
                            prescription_scheduling=scheduling,
                            item_name=item_data['name'],
                            dose=item_data['dose'],
                            quantity=random.randint(1, 10),
                            time=item_data['time'],
                            notes=f'Sample prescription item - {item_data["name"]}'
                        )
                    
                    # Create change log entry
                    PrescriptionChangeLog.objects.create(
                        patient=patient,
                        prescription_date=prescription_date,
                        action='create',
                        changed_by=doctor,
                        description='Sample prescription created for testing',
                        timestamp=timezone.now()
                    )
                    
                    created_count += 1
                    
                except Exception as e:
                    self.stdout.write(
                        self.style.ERROR(f'Error creating prescription for patient {patient.pat_name}: {str(e)}')
                    )
        
        self.stdout.write(
            self.style.SUCCESS(f'Successfully created {created_count} sample prescriptions')
        )
