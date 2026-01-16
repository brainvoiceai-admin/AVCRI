# How resheduleMorningandNight.py Algorithm Works

## Current Algorithm Flow

### Step 1: Find Therapists on Emergency Leave
```python
em_therapist_ids, em_emp_codes = get_emergency_leave_sets_for_date(target_date)
```
- Queries `EmergencyLeave` table for leaves overlapping `target_date`
- Gets two sets:
  - `em_therapist_ids`: Therapist PKs on leave (via FK relationship)
  - `em_emp_codes`: Employee codes on leave (for matching by employee_code)

### Step 2: Find Existing Schedules with Affected Therapists
```python
qs = TherapistBooking.objects.filter(date=target_date, status='BOOKED')
```
- Gets all `TherapistBooking` records for the target date with status='BOOKED'
- For each booking, checks if the assigned therapist is on emergency leave:
  ```python
  if (therapist.pk in em_therapist_ids) or (therapist.employee_code in em_emp_codes):
      affected.append(booking)
  ```

### Step 3: For Each Affected Booking - Reassignment Process

#### 3.1: Try Previous Therapist (Same Patient)
- Finds most recent previous therapist for the same patient
- Validates:
  - Same grade level
  - Bathing requirement match
  - Not on emergency leave
  - Not on weekly leave
  - Not already booked at same slot
  - Within daily load limits (max_daily_normal or max_daily_normal + max_daily_overtime_extra)
- If valid → Reassigns immediately

#### 3.2: Find Candidate Pool
- If previous therapist not available, builds candidate pool:
  - Same therapist grade/level
  - Bathing therapist if required
  - Not on emergency leave
  - Not on weekly leave
  - Not already booked at same slot

#### 3.3: Pick Least Loaded Candidate
- From candidates, picks therapist with:
  - Lowest daily booking count
  - Respects max_daily_normal (5) and max_daily_overtime_extra (2) limits
  - Priority: Under normal limit → Under overtime limit

#### 3.4: Reassign or Cancel
- If candidate found → Updates `booking.therapist` to new therapist
- If no candidate → Cancels booking (single or full treatment based on required therapist count)

### Step 4: Update Booking
```python
booking.therapist = pick
booking.is_bathing = True  # if needed
booking.save()
```

## Updated Algorithm (Now Matches reshedule.py Conditions)

**resheduleMorningandNight.py NOW INCLUDES:**
- ✅ Finds existing bookings
- ✅ Checks emergency leave
- ✅ Reassigns therapists
- ✅ **Gender matching** - Patient gender must match therapist gender
- ✅ **Special treatment handling** - Dhara & Pizichil: Senior therapist cannot be bathing therapist
- ✅ **Previous bathing therapist prioritization** - Reuses same bathing therapist for patient
- ✅ **Trainee substitution** - Male Trainee requirements → Junior Therapist
- ✅ **Room allocation checks** - Verifies room availability before reassignment
- ✅ **Therapy requirements from TherapyMaster** - Gets detailed grade breakdown
- ✅ **Patient already booked checks** - Prevents double-booking at same slot
- ✅ **Therapist grade name resolution** - Properly handles FK relationships

## Updated Reassignment Process

### Step 3 (Updated): For Each Affected Booking

#### 3.1: Get Patient and Therapy Information
- Gets patient gender from booking/visit/PatientSnapshot
- Gets therapy requirements from TherapyMaster (grade breakdown)
- Determines if therapy needs bathing (from TherapyMaster, not just booking flag)
- Checks if special treatment (Dhara & Pizichil)

#### 3.2: Check Patient Already Booked
- Verifies patient doesn't already have booking at same date+slot
- Excludes current booking and bookings from same allocation
- If conflict found → Skip reassignment (log as failed)

#### 3.3: Try Previous Therapist (Enhanced)
- **First**: Tries to find previous BATHING therapist if needs_bathing=True
- **Then**: Tries previous therapist for same patient
- Validates:
  - Same grade level (using grade name from FK)
  - Gender match
  - Bathing requirement match
  - Not on emergency leave
  - Not on weekly leave
  - Not already booked at same slot
  - Within daily load limits

#### 3.4: Find Candidate Pool (Enhanced)
- Filters by:
  - Same therapist grade (or Junior if Trainee substitution needed for male patient)
  - Gender match (patient gender = therapist gender)
  - Bathing therapist if required
  - Not on emergency leave
  - Not on weekly leave
  - Not already booked at same slot

#### 3.5: Special Treatment Handling
- If Dhara & Pizichil and needs_bathing:
  - Checks if picked therapist is Senior
  - If Senior → Finds non-senior bathing therapist alternative
  - If no alternative → Fails reassignment

#### 3.6: Room Availability Check
- If therapy needs room (from TherapyMaster):
  - Checks if room is still available
  - Verifies no conflicts with other patients
  - If room unavailable → Fails reassignment

#### 3.7: Reassign or Cancel
- Updates `booking.therapist` to new therapist
- Sets `is_bathing` flag correctly:
  - For special treatments: Senior therapist is NOT marked as bathing
  - For regular treatments: Bathing therapist is marked as bathing
- If no candidate found → Cancels booking (single or full treatment)

## Key Improvements

1. **Gender Matching**: Prevents wrong-gender therapist assignments
2. **Special Treatment Logic**: Ensures senior therapist is not bathing therapist for Dhara & Pizichil
3. **Previous Bathing Therapist**: Maintains consistency by reusing same bathing therapist
4. **Trainee Substitution**: Allows Junior to substitute for Male Trainee requirements
5. **Room Checks**: Prevents room conflicts during reassignment
6. **Patient Booking Checks**: Prevents double-booking patients
7. **Therapy Requirements**: Uses accurate grade breakdown from TherapyMaster

