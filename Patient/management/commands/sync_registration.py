# yourapp/management/commands/sync_registration.py
from django.core.management.base import BaseCommand
from MySql_Data_pull.models import Registration as RemoteRegistration
from Patient.models import LocalRegistration

class Command(BaseCommand):
    help = 'Sync remote Registration to local table'

    def handle(self, *args, **kwargs):
        remote_patients = RemoteRegistration.objects.using('therapy_db').all()
        for r in remote_patients:
            LocalRegistration.objects.update_or_create(
                pat_reg_no=r.pat_reg_no,
                defaults={
                    'pat_prefix': r.pat_prefix,
                    'pat_name': r.pat_name,
                    'doctcode': r.doctcode,
                    'pat_dob': r.pat_dob,
                    'pat_age': r.pat_age,
                    'pat_sex': r.pat_sex,
                    'pat_marital_status': r.pat_marital_status,
                    'pat_occup': r.pat_occup,
                    'pat_add1': r.pat_add1,
                    'pat_add2': r.pat_add2,
                    'pat_add3': r.pat_add3,
                    'pat_add4': r.pat_add4,
                    'pat_add5': r.pat_add5,
                    'pat_add6': r.pat_add6,
                    'pat_ph_no': r.pat_ph_no,
                    'pat_email': r.pat_email,
                    'pat_passport': r.pat_passport,
                    'pat_reg_date': r.pat_reg_date,
                    'pat_visit_date': r.pat_visit_date,
                    'pat_room_no': r.pat_room_no,
                    'pat_room_date': r.pat_room_date,
                    'pat_status': r.pat_status,
                    'pat_user': r.pat_user,
                    'pat_user_date': r.pat_user_date,
                    'dct_team': r.dct_team,
                    'aadharno1': r.aadharno1,
                    'aadharno2': r.aadharno2,
                    'aadharno3': r.aadharno3,
                    'pat_op_reg_no': r.pat_op_reg_no,
                    'imgloc': r.imgloc,
                    'pat_bgroup': r.pat_bgroup,
                    'e_contact_name': r.e_contact_name,
                    'pat_ref_id': r.pat_ref_id,
                    'e_contact_no': r.e_contact_no,
                }
            )
        self.stdout.write(self.style.SUCCESS('Remote Registration synced successfully!'))
