"""
List patient registration numbers grouped by doctor code from hospital therapy_db
(Treatment.Treat_Doc_Code and Registration.Doctcode). Use this to pick the correct Doctor ID
for DoctorProfile so "My patients — therapy" can match rows.

Examples:
  python manage.py list_hospital_doctor_patient_regs
  python manage.py list_hospital_doctor_patient_regs --doctor-id 1011
  python manage.py list_hospital_doctor_patient_regs --registration --limit 15
"""
from django.core.management.base import BaseCommand

from Sheduling.hospital_doctor_lookup import (
    EXTERNAL_DB_ALIAS,
    pat_reg_nos_for_hospital_doctor,
    sample_registration_doctcodes,
    sample_treatment_doctor_codes,
)


class Command(BaseCommand):
    help = (
        'Print doctor codes from dbo.Treatment / dbo.Registration with sample Pat_Reg_No. '
        'Optional --doctor-id tests the same lookup used by the doctor therapy dashboard.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--doctor-id',
            type=str,
            default='',
            help='If set, print how many pat reg nos match this code (dashboard logic).',
        )
        parser.add_argument(
            '--limit',
            type=int,
            default=30,
            help='How many top doctor codes to show from Treatment (default 30).',
        )
        parser.add_argument(
            '--registration',
            action='store_true',
            help='Also list top Registration.Doctcode values with sample Pat_Reg_No.',
        )
        parser.add_argument(
            '--samples',
            type=int,
            default=5,
            help='Sample Pat_Reg_No per doctor code (default 5).',
        )

    def handle(self, *args, **options):
        doctor_id = (options.get('doctor_id') or '').strip()
        limit = max(1, min(int(options.get('limit') or 30), 200))
        sample_n = max(1, min(int(options.get('samples') or 5), 50))
        do_reg = options.get('registration')

        self.stdout.write(self.style.NOTICE(f'Using database alias: {EXTERNAL_DB_ALIAS}'))

        if doctor_id:
            found = pat_reg_nos_for_hospital_doctor(doctor_id)
            self.stdout.write(self.style.SUCCESS(f'\nDoctor ID "{doctor_id}" -> {len(found)} distinct Pat_Reg_No (Treatment + Registration).'))
            preview = sorted(found)[:40]
            for p in preview:
                self.stdout.write(f'  {p}')
            if len(found) > 40:
                self.stdout.write(f'  ... and {len(found) - 40} more')
            if not found:
                self.stdout.write(
                    self.style.WARNING(
                        'No rows matched. Set DoctorProfile.doctor_id to one of the Treat_Doc_Code / '
                        'Doctcode values printed below (not the auto DOC000123 id unless it exists in hospital data).'
                    )
                )

        try:
            self.stdout.write(self.style.NOTICE('\n--- dbo.Treatment: top Treat_Doc_Code by distinct Pat_Reg_No ---'))
            for row in sample_treatment_doctor_codes(limit=limit, sample_regs=sample_n):
                codes = ', '.join(str(x) for x in row['sample_pat_reg_nos'])
                self.stdout.write(
                    f"  Treat_Doc_Code={row['treat_doc_code']!r}  patients={row['patient_count']}  "
                    f'sample Pat_Reg_No: {codes or "(none)"}'
                )
        except Exception as exc:
            self.stdout.write(self.style.ERROR(f'Treatment sample failed: {exc}'))

        if do_reg:
            try:
                self.stdout.write(self.style.NOTICE('\n--- dbo.Registration: top Doctcode by row count ---'))
                for row in sample_registration_doctcodes(limit=min(limit, 40), sample_regs=sample_n):
                    codes = ', '.join(str(x) for x in row['sample_pat_reg_nos'])
                    self.stdout.write(
                        f"  Doctcode={row['doctcode']!r}  rows={row['row_count']}  "
                        f'sample Pat_Reg_No: {codes or "(none)"}'
                    )
            except Exception as exc:
                self.stdout.write(self.style.ERROR(f'Registration sample failed: {exc}'))

        self.stdout.write('')
