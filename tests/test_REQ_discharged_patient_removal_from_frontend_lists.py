"""
Regression Test: Discharged Patient Data Removal from Active Frontend Lists

Category: Patient Management / Frontend
Title: Discharged Patient Data Removal from Active Frontend Lists

Rule / Description:
    Discharged patients must no longer appear in active patient search results or
    active prescription and treatment lists. Historical records should remain accessible
    wherever required by the system's record-retention rules.

Inputs / Test Data:
    - Patient A is active and has prescription and treatment records.
    - Patient B has been discharged and has existing prescription and treatment records.

Execution Steps:
    1. Search for Patient A and Patient B in the Active Patients search box.
    2. Check the prescription list.
    3. Check the treatment lists (both draft treatments and scheduled treatments).
    4. Discharge Patient A and refresh the relevant screens.
    5. Verify the updated frontend lists and search results.

Expected Results:
    1. Discharged patients do not appear in active patient search results.
    2. Discharged patients are removed from active prescription and treatment lists (draft and scheduled).
    3. Active patients remain visible in the relevant lists.
    4. Discharge status is reflected consistently after refresh.
    5. Historical patient, prescription, and treatment records are retained in the database
       unless deletion is explicitly required by the system's retention rules.
"""
import pytest
from datetime import date, time
from unittest.mock import patch, MagicMock
from django.test import TestCase, Client
from django.contrib.auth import get_user_model
from django.utils import timezone

from Sheduling.models import (
    PatientSnapshot,
    TherapyAllocation,
    Booking,
    PrescriptionScheduling,
    PrescriptionAllocation,
)
from masters.models import SlotMaster, TherapistGrade, TherapyMaster, TherapistMaster
from Patient.models import TreatmentRoom, RoomName, TherapistBooking
from authentication.models import Module
from MySql_Data_pull.models import Registration, doctor_master, OPMaster


TARGET_DATE = date(2099, 8, 15)
TARGET_DATE_STR = TARGET_DATE.isoformat()
TARGET_DATE_SCHED = date(2099, 8, 16)
TARGET_DATE_SCHED_STR = TARGET_DATE_SCHED.isoformat()


def _ensure_slot(number, slot_time):
    obj, _ = SlotMaster.objects.get_or_create(
        slot_number=number,
        defaults={"slot_time": slot_time, "is_active": True},
    )
    return obj


def _ensure_grade(name, order):
    obj, _ = TherapistGrade.objects.get_or_create(
        name=name,
        defaults={"display_order": order, "is_active": True},
    )
    return obj


def _ensure_therapist(code, name, gender, grade, employee_code, is_bathing=True):
    obj, _ = TherapistMaster.objects.get_or_create(
        therapist_code=code,
        defaults={
            "therapist_name": name,
            "therapist_gender": gender,
            "therapist_grade": grade,
            "employee_code": employee_code,
            "is_bathing_therapist": is_bathing,
            "is_helping_therapist": False,
            "is_active": True,
        },
    )
    return obj


def _ensure_therapy(code, name):
    obj, _ = TherapyMaster.objects.get_or_create(
        therapy_code=code,
        defaults={
            "therapy_name": name,
            "therapy_category": "Medium",
            "therapy_duration": "45",
            "bathing_required": "No",
            "treatment_room_required": "Yes",
            "no_of_senior_therapist": 1,
            "total_no_of_therapist": 1,
            "patient_type": "IP",
            "is_active": True,
        },
    )
    return obj


def _ensure_room(room_no):
    room_name, _ = RoomName.objects.get_or_create(
        name=f"Room {room_no}", defaults={"is_active": True}
    )
    obj, _ = TreatmentRoom.objects.get_or_create(
        room_no=room_no,
        defaults={
            "room_name": room_name,
            "floor": "G",
            "is_active": True,
        },
    )
    return obj


class MockRegistrationRecord:
    """Simulates an external hospital database Registration record."""

    def __init__(self, pat_reg_no, pat_name, pat_status="Y"):
        self.pat_reg_no = int(pat_reg_no) if str(pat_reg_no).isdigit() else pat_reg_no
        self.pat_name = pat_name
        self.pat_status = pat_status
        self.dct_team = "Clinical Team A"
        self.doctcode = "DOC01"
        self.pat_reg_date = timezone.now()


class MockRegistrationQS:
    """Mock QuerySet for Registration.objects.using('therapy_db')."""

    def __init__(self, records):
        self.records = list(records)

    def filter(self, *args, **kwargs):
        res = self.records
        status = kwargs.get("pat_status")
        require_y = False
        query_text = None

        # Inspect Q objects for pat_status='Y' and icontains query
        for arg in args:
            s = str(arg)
            if "pat_status" in s and "Y" in s:
                require_y = True
            for child in getattr(arg, "children", []):
                cs = str(child)
                if "pat_status" in cs and "Y" in cs:
                    require_y = True
                if hasattr(child, "children"):
                    for sub in child.children:
                        if isinstance(sub, tuple) and len(sub) == 2 and "icontains" in sub[0]:
                            query_text = str(sub[1]).lower()

        if require_y or status == "Y":
            res = [r for r in res if (r.pat_status or "").strip().upper() == "Y"]

        in_list = kwargs.get("pat_reg_no__in")
        if in_list is not None:
            in_set = {str(x) for x in in_list}
            res = [r for r in res if str(r.pat_reg_no) in in_set]

        single_no = kwargs.get("pat_reg_no")
        if single_no is not None:
            res = [r for r in res if str(r.pat_reg_no) == str(single_no)]

        if query_text:
            res = [
                r
                for r in res
                if query_text in str(r.pat_reg_no).lower()
                or query_text in str(r.pat_name).lower()
            ]

        return MockRegistrationQS(res)

    def first(self):
        return self.records[0] if self.records else None

    def values(self, *fields):
        return [{f: getattr(r, f, None) for f in fields} for r in self.records]

    def __iter__(self):
        return iter(self.records)

    def __len__(self):
        return len(self.records)

    def __getitem__(self, item):
        if isinstance(item, slice):
            return MockRegistrationQS(self.records[item])
        return self.records[item]


@pytest.mark.django_db(transaction=True)
class TestREQDischargedPatientDataRemoval(TestCase):
    """
    Test suite for Discharged Patient Data Removal from Active Frontend Lists.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        # Ensure authentication modules exist
        Module.objects.get_or_create(
            name="therapy_scheduling",
            defaults={"display_name": "Therapy Scheduling", "is_active": True},
        )
        Module.objects.get_or_create(
            name="prescription_scheduling",
            defaults={"display_name": "Prescription Scheduling", "is_active": True},
        )

        User = get_user_model()
        cls.user, _ = User.objects.get_or_create(
            username="test_discharge_admin",
            defaults={
                "email": "admin@example.com",
                "role": "super_admin",
                "is_staff": True,
                "is_superuser": True,
            },
        )
        if cls.user.role != "super_admin" or not cls.user.is_superuser:
            cls.user.role = "super_admin"
            cls.user.is_superuser = True
            cls.user.save()

        cls.slot = _ensure_slot(1, time(6, 30))
        cls.slot_sched = _ensure_slot(2, time(8, 30))
        cls.senior_grade = _ensure_grade("Senior", 1)
        cls.therapist_a = _ensure_therapist(
            "TH_DISCH_A", "Therapist Alpha", "Male", cls.senior_grade, "EMP_DA"
        )
        cls.therapist_b = _ensure_therapist(
            "TH_DISCH_B", "Therapist Beta", "Male", cls.senior_grade, "EMP_DB"
        )
        cls.room_a = _ensure_room("ROOM_DISCH_A")
        cls.room_b = _ensure_room("ROOM_DISCH_B")
        cls.therapy = _ensure_therapy("T_DISCH_01", "Therapy Discharge Verification")

    def test_discharged_patient_data_removal_from_active_frontend_lists(self):
        """
        Scenario:
            1. Search for Patient A and Patient B in Active Patients search box.
            2. Check the prescription list for target date.
            3. Check the treatment list for target date.
            4. Discharge Patient A and refresh relevant screens.
            5. Verify updated frontend lists and search results, and database retention.
        """
        # --- Arrange: Patient A (Active) & Patient B (Discharged) ---
        reg_no_a = "100001"
        reg_no_b = "100002"

        pat_a = PatientSnapshot.objects.create(
            pat_reg_no=reg_no_a,
            pat_name="Patient Active Alpha",
            pat_room_no="101",
            pat_sex="Male",
            pat_age="40",
        )
        pat_b = PatientSnapshot.objects.create(
            pat_reg_no=reg_no_b,
            pat_name="Patient Discharged Beta",
            pat_room_no="102",
            pat_sex="Female",
            pat_age="42",
        )

        # Prescription records in database
        ps_a = PrescriptionScheduling.objects.create(
            patient=pat_a,
            prescription_date=TARGET_DATE,
            doctor=self.user,
            status="draft",
        )
        ps_b = PrescriptionScheduling.objects.create(
            patient=pat_b,
            prescription_date=TARGET_DATE,
            doctor=self.user,
            status="draft",
        )
        PrescriptionAllocation.objects.create(
            patient=pat_a,
            prescription_name="Ayurvedic Kashayam A",
            from_date=TARGET_DATE,
            to_date=TARGET_DATE,
            days=1,
            status="draft",
        )
        PrescriptionAllocation.objects.create(
            patient=pat_b,
            prescription_name="Ayurvedic Kashayam B",
            from_date=TARGET_DATE,
            to_date=TARGET_DATE,
            days=1,
            status="draft",
        )

        # Scheduled Prescription records in database
        ps_a_sched = PrescriptionScheduling.objects.create(
            patient=pat_a,
            prescription_date=TARGET_DATE_SCHED,
            doctor=self.user,
            status="scheduled",
        )
        ps_b_sched = PrescriptionScheduling.objects.create(
            patient=pat_b,
            prescription_date=TARGET_DATE_SCHED,
            doctor=self.user,
            status="scheduled",
        )
        PrescriptionAllocation.objects.create(
            patient=pat_a,
            prescription_name="Ayurvedic Kashayam A Sched",
            from_date=TARGET_DATE_SCHED,
            to_date=TARGET_DATE_SCHED,
            days=1,
            status="scheduled",
        )
        PrescriptionAllocation.objects.create(
            patient=pat_b,
            prescription_name="Ayurvedic Kashayam B Sched",
            from_date=TARGET_DATE_SCHED,
            to_date=TARGET_DATE_SCHED,
            days=1,
            status="scheduled",
        )

        # Treatment records in database
        alloc_a = TherapyAllocation.objects.create(
            patient=pat_a,
            therapy_code=self.therapy.therapy_code,
            therapy_name=self.therapy.therapy_name,
            from_date=TARGET_DATE,
            to_date=TARGET_DATE,
            days=1,
            timeslot=self.slot,
            room=self.room_a,
            status="draft",
        )
        alloc_b = TherapyAllocation.objects.create(
            patient=pat_b,
            therapy_code=self.therapy.therapy_code,
            therapy_name=self.therapy.therapy_name,
            from_date=TARGET_DATE,
            to_date=TARGET_DATE,
            days=1,
            timeslot=self.slot,
            room=self.room_b,
            status="draft",
        )
        bk_a = Booking.objects.create(
            allocation=alloc_a,
            date=TARGET_DATE,
            timeslot=self.slot,
            room=self.room_a,
            status="draft",
        )
        bk_b = Booking.objects.create(
            allocation=alloc_b,
            date=TARGET_DATE,
            timeslot=self.slot,
            room=self.room_b,
            status="draft",
        )

        # Scheduled Treatment records in database
        alloc_a_sched = TherapyAllocation.objects.create(
            patient=pat_a,
            therapy_code=self.therapy.therapy_code,
            therapy_name=self.therapy.therapy_name,
            from_date=TARGET_DATE,
            to_date=TARGET_DATE,
            days=1,
            timeslot=self.slot_sched,
            room=self.room_a,
            status="scheduled",
        )
        alloc_b_sched = TherapyAllocation.objects.create(
            patient=pat_b,
            therapy_code=self.therapy.therapy_code,
            therapy_name=self.therapy.therapy_name,
            from_date=TARGET_DATE,
            to_date=TARGET_DATE,
            days=1,
            timeslot=self.slot_sched,
            room=self.room_b,
            status="scheduled",
        )
        bk_a_sched = Booking.objects.create(
            allocation=alloc_a_sched,
            date=TARGET_DATE,
            timeslot=self.slot_sched,
            room=self.room_a,
            status="scheduled",
        )
        bk_b_sched = Booking.objects.create(
            allocation=alloc_b_sched,
            date=TARGET_DATE,
            timeslot=self.slot_sched,
            room=self.room_b,
            status="scheduled",
        )
        tb_a = TherapistBooking.objects.create(
            therapist=self.therapist_a,
            patient_id=pat_a.id,
            visit=alloc_a_sched,
            therapy=self.therapy,
            date=TARGET_DATE,
            time_slot=self.slot_sched,
            status="BOOKED",
        )
        tb_b = TherapistBooking.objects.create(
            therapist=self.therapist_b,
            patient_id=pat_b.id,
            visit=alloc_b_sched,
            therapy=self.therapy,
            date=TARGET_DATE,
            time_slot=self.slot_sched,
            status="BOOKED",
        )

        # Hospital Registration status store: Patient A is active ('Y'), Patient B is discharged ('D')
        mock_hospital_store = {
            reg_no_a: MockRegistrationRecord(reg_no_a, "Patient Active Alpha", "Y"),
            reg_no_b: MockRegistrationRecord(reg_no_b, "Patient Discharged Beta", "D"),
        }

        def fake_using(db_name):
            return MockRegistrationQS(mock_hospital_store.values())

        client = Client()
        client.force_login(self.user)

        with patch.object(Registration.objects, "using", side_effect=fake_using), \
             patch.object(OPMaster.objects, "using", return_value=MagicMock(filter=lambda *a, **k: MagicMock(values=lambda *f: []))), \
             patch.object(doctor_master.objects, "using", return_value=MagicMock(filter=lambda **k: [])):

            # --- Step 1: Search for Patient A and Patient B in Active Patients search box ---
            resp_search_1 = client.get("/search-patients/?q=Patient")
            assert resp_search_1.status_code == 200
            search_results_1 = [p["pat_reg_no"] for p in resp_search_1.json()]

            # Active Patient A appears; Discharged Patient B is excluded
            assert reg_no_a in search_results_1, f"Active Patient A ({reg_no_a}) should be in search results"
            assert reg_no_b not in search_results_1, f"Discharged Patient B ({reg_no_b}) must NOT appear in search results"

            # --- Step 2: Check the prescription lists (draft & scheduled) ---
            # 2a. Draft prescriptions
            resp_presc_1 = client.get(
                f"/sheduling/prescription/api/prescription-data/?date={TARGET_DATE_STR}&status=draft"
            )
            assert resp_presc_1.status_code == 200
            presc_data_1 = resp_presc_1.json().get("data", [])
            presc_regs_1 = [
                p.get("registration_no") or p.get("patient_id_display")
                for p in presc_data_1
            ]

            # Active Patient A appears; Discharged Patient B is excluded
            assert reg_no_a in presc_regs_1, f"Active Patient A ({reg_no_a}) should be in active prescription list"
            assert reg_no_b not in presc_regs_1, f"Discharged Patient B ({reg_no_b}) must NOT appear in active prescription list"

            # 2b. Scheduled prescriptions
            resp_presc_sched_1 = client.get(
                f"/sheduling/prescription/api/prescription-data/?date={TARGET_DATE_SCHED_STR}&status=scheduled"
            )
            assert resp_presc_sched_1.status_code == 200
            presc_sched_data_1 = resp_presc_sched_1.json().get("data", [])
            presc_sched_regs_1 = [
                p.get("registration_no") or p.get("patient_id_display")
                for p in presc_sched_data_1
            ]

            assert reg_no_a in presc_sched_regs_1, f"Active Patient A ({reg_no_a}) should be in active scheduled prescription list"
            assert reg_no_b not in presc_sched_regs_1, f"Discharged Patient B ({reg_no_b}) must NOT appear in scheduled prescription list"

            # --- Step 3: Check the treatment lists (draft treatments & scheduled treatments) ---
            # 3a. Draft treatments
            resp_therapy_draft_1 = client.get(
                f"/sheduling/scheduling/api/therapy-data/?date={TARGET_DATE_STR}&status=draft"
            )
            assert resp_therapy_draft_1.status_code == 200
            therapy_draft_1 = resp_therapy_draft_1.json().get("data", [])
            therapy_draft_regs_1 = [item.get("patient_reg_no") for item in therapy_draft_1]

            # Active Patient A appears; Discharged Patient B is excluded
            assert reg_no_a in therapy_draft_regs_1, f"Active Patient A ({reg_no_a}) should be in active draft treatment list"
            assert reg_no_b not in therapy_draft_regs_1, f"Discharged Patient B ({reg_no_b}) must NOT appear in draft treatment list"

            # 3b. Scheduled treatments
            resp_therapy_sched_1 = client.get(
                f"/sheduling/scheduling/api/therapy-data/?date={TARGET_DATE_STR}&status=scheduled"
            )
            assert resp_therapy_sched_1.status_code == 200
            therapy_sched_1 = resp_therapy_sched_1.json().get("data", [])
            therapy_sched_regs_1 = [item.get("patient_reg_no") for item in therapy_sched_1]

            # Active Patient A appears; Discharged Patient B is excluded
            assert reg_no_a in therapy_sched_regs_1, f"Active Patient A ({reg_no_a}) should be in active scheduled treatment list"
            assert reg_no_b not in therapy_sched_regs_1, f"Discharged Patient B ({reg_no_b}) must NOT appear in scheduled treatment list"

            # --- Step 4: Discharge Patient A and refresh relevant screens ---
            mock_hospital_store[reg_no_a].pat_status = "D"

            # Refresh Active Patients search box
            resp_search_2 = client.get("/search-patients/?q=Patient")
            assert resp_search_2.status_code == 200
            search_results_2 = [p["pat_reg_no"] for p in resp_search_2.json()]

            # Refresh Draft Prescription list
            resp_presc_2 = client.get(
                f"/sheduling/prescription/api/prescription-data/?date={TARGET_DATE_STR}&status=draft"
            )
            assert resp_presc_2.status_code == 200
            presc_data_2 = resp_presc_2.json().get("data", [])
            presc_regs_2 = [
                p.get("registration_no") or p.get("patient_id_display")
                for p in presc_data_2
            ]

            # Refresh Scheduled Prescription list
            resp_presc_sched_2 = client.get(
                f"/sheduling/prescription/api/prescription-data/?date={TARGET_DATE_SCHED_STR}&status=scheduled"
            )
            assert resp_presc_sched_2.status_code == 200
            presc_sched_data_2 = resp_presc_sched_2.json().get("data", [])
            presc_sched_regs_2 = [
                p.get("registration_no") or p.get("patient_id_display")
                for p in presc_sched_data_2
            ]

            # Refresh Draft Treatment list
            resp_therapy_draft_2 = client.get(
                f"/sheduling/scheduling/api/therapy-data/?date={TARGET_DATE_STR}&status=draft"
            )
            assert resp_therapy_draft_2.status_code == 200
            therapy_draft_2 = resp_therapy_draft_2.json().get("data", [])
            therapy_draft_regs_2 = [item.get("patient_reg_no") for item in therapy_draft_2]

            # Refresh Scheduled Treatment list
            resp_therapy_sched_2 = client.get(
                f"/sheduling/scheduling/api/therapy-data/?date={TARGET_DATE_STR}&status=scheduled"
            )
            assert resp_therapy_sched_2.status_code == 200
            therapy_sched_2 = resp_therapy_sched_2.json().get("data", [])
            therapy_sched_regs_2 = [item.get("patient_reg_no") for item in therapy_sched_2]

            # --- Step 5: Verify updated frontend lists and search results ---
            # 1. Discharged patients do not appear in active patient search results
            assert reg_no_a not in search_results_2, f"Newly discharged Patient A ({reg_no_a}) must NOT appear in search results"
            assert reg_no_b not in search_results_2, f"Discharged Patient B ({reg_no_b}) must NOT appear in search results"

            # 2. Discharged patients are removed from active prescription lists (draft and scheduled)
            assert reg_no_a not in presc_regs_2, f"Newly discharged Patient A ({reg_no_a}) must be removed from draft prescription list"
            assert reg_no_b not in presc_regs_2, f"Discharged Patient B ({reg_no_b}) must NOT appear in draft prescription list"

            assert reg_no_a not in presc_sched_regs_2, f"Newly discharged Patient A ({reg_no_a}) must be removed from scheduled prescription list"
            assert reg_no_b not in presc_sched_regs_2, f"Discharged Patient B ({reg_no_b}) must NOT appear in scheduled prescription list"

            # 3. Discharged patients are removed from active treatment lists (draft and scheduled)
            assert reg_no_a not in therapy_draft_regs_2, f"Newly discharged Patient A ({reg_no_a}) must be removed from draft treatment list"
            assert reg_no_b not in therapy_draft_regs_2, f"Discharged Patient B ({reg_no_b}) must NOT appear in draft treatment list"

            assert reg_no_a not in therapy_sched_regs_2, f"Newly discharged Patient A ({reg_no_a}) must be removed from scheduled treatment list"
            assert reg_no_b not in therapy_sched_regs_2, f"Discharged Patient B ({reg_no_b}) must NOT appear in scheduled treatment list"

            # 4. Discharge status is reflected consistently across all screens
            assert len(search_results_2) == 0, "No discharged patients should be present in active search"
            assert len(presc_regs_2) == 0, "No discharged patients should be present in active draft prescription list"
            assert len(presc_sched_regs_2) == 0, "No discharged patients should be present in active scheduled prescription list"
            assert len(therapy_draft_regs_2) == 0, "No discharged patients should be present in active draft treatment list"
            assert len(therapy_sched_regs_2) == 0, "No discharged patients should be present in active scheduled treatment list"

        # 5. Historical patient, prescription, and treatment records are retained in database
        assert PatientSnapshot.objects.filter(pat_reg_no=reg_no_a).exists(), "Historical Patient A snapshot must be retained in DB"
        assert PatientSnapshot.objects.filter(pat_reg_no=reg_no_b).exists(), "Historical Patient B snapshot must be retained in DB"

        assert PrescriptionScheduling.objects.filter(id=ps_a.id).exists(), "Historical draft PrescriptionScheduling for Patient A must be retained in DB"
        assert PrescriptionScheduling.objects.filter(id=ps_b.id).exists(), "Historical draft PrescriptionScheduling for Patient B must be retained in DB"
        assert PrescriptionScheduling.objects.filter(id=ps_a_sched.id).exists(), "Historical scheduled PrescriptionScheduling for Patient A must be retained in DB"
        assert PrescriptionScheduling.objects.filter(id=ps_b_sched.id).exists(), "Historical scheduled PrescriptionScheduling for Patient B must be retained in DB"

        assert PrescriptionAllocation.objects.filter(patient=pat_a).exists(), "Historical PrescriptionAllocation for Patient A must be retained in DB"
        assert PrescriptionAllocation.objects.filter(patient=pat_b).exists(), "Historical PrescriptionAllocation for Patient B must be retained in DB"

        assert TherapyAllocation.objects.filter(patient=pat_a, status="draft").exists(), "Historical draft TherapyAllocation for Patient A must be retained in DB"
        assert TherapyAllocation.objects.filter(patient=pat_b, status="draft").exists(), "Historical draft TherapyAllocation for Patient B must be retained in DB"
        assert TherapyAllocation.objects.filter(patient=pat_a, status="scheduled").exists(), "Historical scheduled TherapyAllocation for Patient A must be retained in DB"
        assert TherapyAllocation.objects.filter(patient=pat_b, status="scheduled").exists(), "Historical scheduled TherapyAllocation for Patient B must be retained in DB"

        assert Booking.objects.filter(allocation=alloc_a).exists(), "Historical draft Booking for Patient A must be retained in DB"
        assert Booking.objects.filter(allocation=alloc_b).exists(), "Historical draft Booking for Patient B must be retained in DB"
        assert Booking.objects.filter(allocation=alloc_a_sched).exists(), "Historical scheduled Booking for Patient A must be retained in DB"
        assert Booking.objects.filter(allocation=alloc_b_sched).exists(), "Historical scheduled Booking for Patient B must be retained in DB"

        assert TherapistBooking.objects.filter(id=tb_a.id).exists(), "Historical TherapistBooking for Patient A must be retained in DB"
        assert TherapistBooking.objects.filter(id=tb_b.id).exists(), "Historical TherapistBooking for Patient B must be retained in DB"
