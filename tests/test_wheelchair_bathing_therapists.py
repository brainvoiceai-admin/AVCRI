import json
from datetime import date, timedelta, time
from django.test import TestCase, Client
from django.contrib.auth import get_user_model
from masters.models import (
    TherapyMaster,
    TherapistMaster,
    TherapistGrade,
    SlotMaster,
)
from Sheduling.models import (
    PatientSnapshot,
    TherapyAllocation,
    Booking,
    BookingAssignment,
)
from Patient.models import TherapistBooking, TreatmentRoom, RoomName
from final_allocation import (
    allocate_therapists,
    therapist_requirements,
    expand_therapies_for_visit,
)

User = get_user_model()


class TestWheelchairBathingTherapistsAllocation(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="testuser", password="password")

        # Slot master
        self.slot, _ = SlotMaster.objects.get_or_create(
            slot_number=2,
            defaults={"slot_time": time(8, 30), "slot_name": "08:30 AM", "is_active": True}
        )
        self.slot.is_active = True
        self.slot.save()

        self.grade_super_senior, _ = TherapistGrade.objects.get_or_create(name="Super Senior Therapist")
        self.grade_senior, _ = TherapistGrade.objects.get_or_create(name="Senior Therapist")
        self.grade_junior, _ = TherapistGrade.objects.get_or_create(name="Junior Therapist")
        self.grade_trainee, _ = TherapistGrade.objects.get_or_create(name="Trainee Therapist")

        self.room_name, _ = RoomName.objects.get_or_create(name="Test Room A")
        self.room, _ = TreatmentRoom.objects.get_or_create(
            room_no="TR-101",
            defaults={"room_name": self.room_name, "is_active": True, "is_wheelchair_accessible": True}
        )

        self.patient, _ = PatientSnapshot.objects.get_or_create(
            pat_reg_no="PAT-WC-001",
            defaults={"pat_name": "Wheelchair Patient Test", "pat_sex": "Male", "pat_age": 45, "is_wheelchair": True}
        )

    def _create_therapist(self, code, name, grade, is_bathing=True, gender="Male"):
        t, _ = TherapistMaster.objects.get_or_create(
            therapist_code=code,
            defaults={
                "employee_code": f"EMP-{code}",
                "therapist_name": name,
                "therapist_grade": grade,
                "therapist_gender": gender,
                "is_bathing_therapist": is_bathing,
                "is_active": True,
                "is_helping_therapist": False
            }
        )
        t.therapist_grade = grade
        t.therapist_gender = gender
        t.is_bathing_therapist = is_bathing
        t.is_active = True
        t.save()
        return t

    def test_therapist_requirements_with_bathing_count(self):
        """Test therapist_requirements calculation when bathing_therapists_count is set."""
        th1, _ = TherapyMaster.objects.get_or_create(
            therapy_code="TH-TEST-1",
            defaults={
                "therapy_name": "Single Therapist Treatment",
                "no_of_junior_therapist": 1,
                "total_no_of_therapist": 1,
                "bathing_required": "No",
                "treatment_room_required": "Yes"
            }
        )

        alloc = TherapyAllocation(
            therapy_code="TH-TEST-1",
            therapy_name="Single Therapist Treatment",
            is_wheelchair=True,
            bathing_therapists_count=2
        )
        req = therapist_requirements(alloc)
        # Treatment normally requires 1, but bathing therapists required is 2 -> req_total is 2
        self.assertEqual(req["total"], 2)
        self.assertEqual(req["normal_total"], 1)
        self.assertEqual(req["bathing_therapists_count"], 2)

    def test_case1_six_therapists_three_bathing(self):
        """
        Case 1: If a treatment requires 6 therapists and the number of bathing therapists required is 3,
        the system should allocate 6 therapists, of whom 3 will be marked as bathing therapists.
        """
        th6, _ = TherapyMaster.objects.get_or_create(
            therapy_code="TH-TEST-6",
            defaults={
                "therapy_name": "Six Therapist Treatment",
                "no_of_super_senior_therapist": 2,
                "no_of_senior_therapist": 2,
                "no_of_junior_therapist": 2,
                "total_no_of_therapist": 6,
                "bathing_required": "Yes",
                "treatment_room_required": "Yes"
            }
        )

        # Create 2 super senior, 2 senior, 2 junior (3 with is_bathing_therapist=True, 3 with False)
        ss1 = self._create_therapist("T-SS-1", "SS 1", self.grade_super_senior, is_bathing=True)
        ss2 = self._create_therapist("T-SS-2", "SS 2", self.grade_super_senior, is_bathing=False)
        s1 = self._create_therapist("T-S-1", "S 1", self.grade_senior, is_bathing=True)
        s2 = self._create_therapist("T-S-2", "S 2", self.grade_senior, is_bathing=False)
        j1 = self._create_therapist("T-J-1", "J 1", self.grade_junior, is_bathing=True)
        j2 = self._create_therapist("T-J-2", "J 2", self.grade_junior, is_bathing=False)

        target_date = date.today() + timedelta(days=2)
        alloc = TherapyAllocation.objects.create(
            patient=self.patient,
            therapy_code="TH-TEST-6",
            therapy_name="Six Therapist Treatment",
            timeslot=self.slot,
            room=self.room,
            is_wheelchair=True,
            bathing_therapists_count=3,
            from_date=target_date,
            to_date=target_date,
            days=1,
            status="draft"
        )
        booking = Booking.objects.create(
            allocation=alloc,
            date=target_date,
            timeslot=self.slot,
            room=self.room,
            is_wheelchair=True,
            bathing_therapists_count=3,
            status="draft"
        )

        tasks = expand_therapies_for_visit(alloc.id, target_date, create_bookings=True)
        self.assertTrue(bool(tasks) and tasks[0].get("status") in ["BOOKED", "SUCCESS"], f"Failed with {tasks}")

        # Verify exactly 6 therapists were allocated
        assignments = BookingAssignment.objects.filter(booking=booking)
        self.assertEqual(assignments.count(), 6)

        # Verify exactly 3 are marked as bathing in TherapistBooking
        tb_list = TherapistBooking.objects.filter(visit=alloc, date=target_date, status="BOOKED")
        self.assertEqual(tb_list.count(), 6)
        bathing_tb = tb_list.filter(is_bathing=True)
        self.assertEqual(bathing_tb.count(), 3)

    def test_case2_one_normal_therapist_two_bathing(self):
        """
        Case 2: If a treatment normally requires only 1 therapist but the number of bathing therapists required is 2,
        the system should allocate 2 therapists, and both will be marked as bathing therapists.
        """
        th1, _ = TherapyMaster.objects.get_or_create(
            therapy_code="TH-TEST-1B",
            defaults={
                "therapy_name": "One Therapist Treatment",
                "no_of_junior_therapist": 1,
                "total_no_of_therapist": 1,
                "bathing_required": "No",
                "treatment_room_required": "Yes"
            }
        )

        j1 = self._create_therapist("T-J-10", "Junior Bathing 10", self.grade_junior, is_bathing=True)
        j2 = self._create_therapist("T-J-11", "Junior Bathing 11", self.grade_junior, is_bathing=True)

        target_date = date.today() + timedelta(days=3)
        alloc = TherapyAllocation.objects.create(
            patient=self.patient,
            therapy_code="TH-TEST-1B",
            therapy_name="One Therapist Treatment",
            timeslot=self.slot,
            room=self.room,
            is_wheelchair=True,
            bathing_therapists_count=2,
            from_date=target_date,
            to_date=target_date,
            days=1,
            status="draft"
        )
        booking = Booking.objects.create(
            allocation=alloc,
            date=target_date,
            timeslot=self.slot,
            room=self.room,
            is_wheelchair=True,
            bathing_therapists_count=2,
            status="draft"
        )

        tasks = expand_therapies_for_visit(alloc.id, target_date, create_bookings=True)
        self.assertTrue(bool(tasks) and tasks[0].get("status") in ["BOOKED", "SUCCESS"], f"Failed with {tasks}")

        # Verify exactly 2 therapists allocated
        assignments = BookingAssignment.objects.filter(booking=booking)
        self.assertEqual(assignments.count(), 2)

        # Verify BOTH are marked as bathing therapists
        tb_list = TherapistBooking.objects.filter(visit=alloc, date=target_date, status="BOOKED")
        self.assertEqual(tb_list.count(), 2)
        bathing_tb = tb_list.filter(is_bathing=True)
        self.assertEqual(bathing_tb.count(), 2)

    def test_case3_additional_bathing_therapist_grade_assigned_by_availability(self):
        """
        Case 3: In cases where additional bathing therapists are required,
        their grades should be assigned based on therapist availability.
        """
        th_avail, _ = TherapyMaster.objects.get_or_create(
            therapy_code="TH-TEST-AVAIL",
            defaults={
                "therapy_name": "Avail Treatment",
                "no_of_junior_therapist": 1,
                "total_no_of_therapist": 1,
                "bathing_required": "No",
                "treatment_room_required": "Yes"
            }
        )

        # Exactly 1 Junior is available
        j_main = self._create_therapist("T-J-20", "Junior Main", self.grade_junior, is_bathing=True)

        # For the additional therapist, Trainees are available in abundance (high availability)
        tr1 = self._create_therapist("T-TR-1", "Trainee 1", self.grade_trainee, is_bathing=True)
        tr2 = self._create_therapist("T-TR-2", "Trainee 2", self.grade_trainee, is_bathing=True)
        tr3 = self._create_therapist("T-TR-3", "Trainee 3", self.grade_trainee, is_bathing=True)

        target_date = date.today() + timedelta(days=4)
        req = {
            "junior": 1,
            "total": 2,  # 1 normal + 1 additional bathing therapist
            "normal_total": 1,
            "bathing_therapists_count": 2,
            "therapy_name": "Avail Treatment",
            "therapy_code": "TH-TEST-AVAIL"
        }

        allocated = allocate_therapists(
            date=target_date,
            time_slot=self.slot,
            therapy_requirements=req,
            needs_bathing=True,
            patient_gender="Male",
            patient_id=self.patient.pat_reg_no
        )

        # Both therapists should be allocated
        self.assertEqual(len(allocated), 2)
        allocated_codes = [t.therapist_code for t in allocated]
        self.assertIn("T-J-20", allocated_codes)
        # The additional therapist should be a Trainee due to highest availability
        trainee_codes = {"T-TR-1", "T-TR-2", "T-TR-3"}
        self.assertTrue(any(code in trainee_codes for code in allocated_codes))

    def test_api_allocate_and_update_with_bathing_therapists_count(self):
        """Test Add Therapy API and update_therapy API with bathing_therapists_count."""
        client = Client()
        client.force_login(self.user)

        start_date = (date.today() + timedelta(days=5)).isoformat()
        end_date = (date.today() + timedelta(days=6)).isoformat()

        # 1. Allocate action
        payload = {
            "patient_reg_no": self.patient.pat_reg_no,
            "patient_name": self.patient.pat_name,
            "therapy_code": "TH-TEST-1B",
            "therapy_name": "One Therapist Treatment",
            "slot": "08:30",
            "is_wheelchair": True,
            "bathing_therapists_count": 3,
            "from_date": start_date,
            "to_date": end_date,
            "items_groups": []
        }

        resp = client.post(
            "/sheduling/therapy-entry/?action=allocate",
            data=json.dumps(payload),
            content_type="application/json"
        )
        self.assertIn(resp.status_code, [200, 201], f"Error: {resp.status_code} - {resp.content.decode('utf-8')}")
        data = resp.json()
        self.assertEqual(data.get("status"), "ok")

        alloc_id = data.get("allocation_id")
        alloc = TherapyAllocation.objects.get(pk=alloc_id)
        self.assertTrue(alloc.is_wheelchair)
        self.assertEqual(alloc.bathing_therapists_count, 3)

        bookings = Booking.objects.filter(allocation=alloc)
        self.assertTrue(all(b.is_wheelchair for b in bookings))
        self.assertTrue(all(b.bathing_therapists_count == 3 for b in bookings))

        # 2. Verify patient_therapies API returns bathing_therapists_count
        resp_list = client.get(
            f"/sheduling/therapy-entry/?action=patient_therapies&patient_reg_no={self.patient.pat_reg_no}"
        )
        self.assertEqual(resp_list.status_code, 200)
        t_list = resp_list.json()
        saved_item = next(t for t in t_list if t["allocation_id"] == alloc_id)
        self.assertTrue(saved_item["is_wheelchair"])
        self.assertEqual(saved_item["bathing_therapists_count"], 3)

        # 3. Update therapy action
        update_payload = {
            "allocation_id": alloc_id,
            "is_wheelchair": True,
            "bathing_therapists_count": 4,
            "from_date": start_date,
            "to_date": end_date
        }
        resp_update = client.post(
            "/sheduling/therapy-entry/?action=update_therapy",
            data=json.dumps(update_payload),
            content_type="application/json"
        )
        self.assertEqual(resp_update.status_code, 200)
        alloc.refresh_from_db()
        self.assertEqual(alloc.bathing_therapists_count, 4)
        bookings = Booking.objects.filter(allocation=alloc, status="draft")
        self.assertTrue(all(b.bathing_therapists_count == 4 for b in bookings))

    def test_allocation_status_action_marks_all_bathing_therapists(self):
        """
        Verify that action=allocation_status returns is_bathing=True for all allocated bathing therapists,
        allowing the UI (formatStaffNames) to prefix each bathing therapist with '*'.
        """
        th, _ = TherapyMaster.objects.get_or_create(
            therapy_code="TH-STATUS-6T",
            defaults={
                "therapy_name": "Status 6 Therapist Treatment",
                "no_of_junior_therapist": 6,
                "total_no_of_therapist": 6,
                "bathing_required": "Yes",
                "treatment_room_required": "Yes"
            }
        )

        for i in range(1, 7):
            self._create_therapist(f"T-STAT-{i}", f"Status Therapist {i}", self.grade_junior, is_bathing=True)

        target_date = date.today() + timedelta(days=6)
        alloc = TherapyAllocation.objects.create(
            patient=self.patient,
            therapy_code="TH-STATUS-6T",
            therapy_name="Status 6 Therapist Treatment",
            timeslot=self.slot,
            room=self.room,
            is_wheelchair=True,
            bathing_therapists_count=3,
            from_date=target_date,
            to_date=target_date,
            days=1,
            status="draft"
        )
        booking = Booking.objects.create(
            allocation=alloc,
            date=target_date,
            timeslot=self.slot,
            room=self.room,
            is_wheelchair=True,
            bathing_therapists_count=3,
            status="draft"
        )

        tasks = expand_therapies_for_visit(alloc.id, target_date, create_bookings=True)
        self.assertTrue(bool(tasks) and tasks[0].get("status") in ["BOOKED", "SUCCESS"])

        client = Client()
        resp = client.get(f"/sheduling/therapy-entry/?action=allocation_status&allocation_id={alloc.id}")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()

        bookings = data.get("bookings", [])
        self.assertEqual(len(bookings), 1)
        b_data = bookings[0]
        therapists = b_data.get("therapists", [])
        self.assertEqual(len(therapists), 6)

        bathing_list = [t for t in therapists if t.get("is_bathing") is True]
        non_bathing_list = [t for t in therapists if not t.get("is_bathing")]

        # All 3 required bathing therapists must have is_bathing = True
        self.assertEqual(len(bathing_list), 3)
        self.assertEqual(len(non_bathing_list), 3)

