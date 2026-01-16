# Comparison: reshedule.py vs resheduleMorningandNight.py

## Missing Conditions/Features in resheduleMorningandNight.py

### 1. **Gender Matching** ❌ MISSING
**In reshedule.py:**
- Patient gender (`pat_sex`) is checked against therapist gender (`therapist_gender`)
- Therapists are filtered by gender match (Male/Female)
- Lines 584-601, 629-642, 692-694, 716-719, 1048-1051

**In resheduleMorningandNight.py:**
- No gender matching logic
- Therapists are selected without considering patient gender

**Impact:** May assign wrong-gender therapists to patients

---

### 2. **Special Treatment Handling (Dhara & Pizichil)** ❌ MISSING
**In reshedule.py:**
- `is_treatment_requiring_senior_tag()` function checks for special treatments
- Senior therapist identified and marked
- Senior therapist should NOT be bathing therapist
- Alternative senior therapist search if needed
- Lines 18-84, 1006-1111

**In resheduleMorningandNight.py:**
- No special treatment detection
- No senior tag logic
- No senior therapist exclusion from bathing

**Impact:** May assign senior therapist as bathing therapist for Dhara & Pizichil treatments

---

### 3. **Trainee → Junior Substitution** ❌ MISSING
**In reshedule.py:**
- For Male Trainee requirements, substitutes with Junior Therapist
- Lines 677-688

**In resheduleMorningandNight.py:**
- No trainee substitution logic
- Only matches exact grade requirements

**Impact:** May fail to allocate when trainee needed but junior available

---

### 4. **Previous Bathing Therapist Prioritization** ❌ MISSING
**In reshedule.py:**
- Finds most recent bathing therapist for same patient
- Prioritizes previous bathing therapist in allocation
- Lines 840-901, 1114-1117

**In resheduleMorningandNight.py:**
- Only checks previous therapist (not specifically bathing therapist)
- No prioritization of previous bathing therapist

**Impact:** May assign different bathing therapist each time, reducing consistency

---

### 5. **Room Allocation Logic** ❌ MISSING
**In reshedule.py:**
- Complex room allocation based on patient staying room
- `get_treatment_rooms_for_staying_room()` with rules for DS, NR, MG, CB, FG, CT rooms
- OP patient handling with CT room logic
- Dhara & Pizichil previous room preference
- Lines 260-539, 1170-1291

**In resheduleMorningandNight.py:**
- **NO ROOM ALLOCATION AT ALL**
- Only handles therapist reassignment
- Does not check or allocate rooms

**Impact:** Room conflicts not handled during rescheduling

---

### 6. **Therapy Requirements from TherapyMaster** ❌ MISSING
**In reshedule.py:**
- `therapist_requirements()` gets detailed requirements from TherapyMaster
- Returns super_senior, senior, junior, trainee counts
- Lines 127-140

**In resheduleMorningandNight.py:**
- Uses simple `get_required_therapist_count_for_booking()` 
- Only returns total count, not grade breakdown
- Lines 168-187

**Impact:** May not respect exact grade requirements (e.g., 1 senior + 2 junior)

---

### 7. **Patient Already Booked Checks** ❌ MISSING
**In reshedule.py:**
- Checks if patient already has booking at same date+slot
- Excludes bookings from same allocation (allows rescheduling)
- Lines 749-808

**In resheduleMorningandNight.py:**
- No patient booking conflict check
- May reassign to slot where patient already has another booking

**Impact:** Double-booking patients at same time slot

---

### 8. **OP/IP Patient Type Awareness** ❌ MISSING
**In reshedule.py:**
- Detects OP vs IP patients
- Different slot rules for OP (11:30, 17:30) vs IP (06:30, 08:30, 10:00, 14:30, 16:00)
- OP patient room allocation logic
- Lines 543-579, 1473-1481

**In resheduleMorningandNight.py:**
- No patient type detection
- No OP/IP specific logic

**Impact:** May assign wrong slots or rooms for OP patients

---

### 9. **Slot Allocation Logic** ❌ MISSING
**In reshedule.py:**
- `get_allowed_slot_values()` returns allowed slots based on patient type and therapy category
- OP/IP aware slot selection
- Hard/special therapies exclude OP slots
- Easy/medium IP therapies can use OP slots
- Lines 543-579

**In resheduleMorningandNight.py:**
- Uses existing booking's time_slot
- No slot allocation or validation

**Impact:** May keep bookings at inappropriate slots for patient type

---

### 10. **Bathing Therapist Unavailable Handling** ❌ MISSING
**In reshedule.py:**
- Fails allocation if bathing therapist required but unavailable
- Detailed error messages
- Lines 1120-1156

**In resheduleMorningandNight.py:**
- Only checks `is_bathing_therapist` flag
- No failure handling if no bathing therapist available

**Impact:** May assign non-bathing therapist when bathing required

---

### 11. **BookingAssignment Creation** ❌ MISSING
**In reshedule.py:**
- Creates BookingAssignment records for UI visibility
- Links therapists to bookings properly
- Lines 1343-1381

**In resheduleMorningandNight.py:**
- Only updates TherapistBooking
- No BookingAssignment creation

**Impact:** UI may not show therapist assignments correctly

---

### 12. **Therapy Needs Room/Bath Checks** ❌ MISSING
**In reshedule.py:**
- `therapy_needs_room()` checks TherapyMaster.treatment_room_required
- `therapy_needs_bath()` checks TherapyMaster.bathing_required
- Lines 108-116

**In resheduleMorningandNight.py:**
- Uses `is_bathing` from booking (may be incorrect)
- No room requirement check

**Impact:** May not allocate room when needed, or allocate when not needed

---

### 13. **Full Treatment Cancellation Logic** ⚠️ PARTIAL
**In reshedule.py:**
- Complex logic for when to cancel full treatment vs single booking
- Considers required therapist count vs assigned count
- Lines 201-209, 452-479

**In resheduleMorningandNight.py:**
- Has `should_cancel_full_treatment()` but simpler logic
- Lines 201-209

**Impact:** May cancel incorrectly or not cancel when should

---

### 14. **Therapist Grade Name Resolution** ❌ MISSING
**In reshedule.py:**
- `get_therapist_grade_name()` gets grade name from TherapistGrade FK
- Handles FK relationship properly
- Lines 118-125

**In resheduleMorningandNight.py:**
- Directly compares `therapist_grade` objects
- May not work correctly with FK relationships
- Line 324

**Impact:** Grade matching may fail

---

### 15. **CT Room Handling for OP Patients** ❌ MISSING
**In reshedule.py:**
- Special logic for OP patients with CT staying rooms
- Maps CT-1 → TRC-1, CT-2 → TRC-2, etc.
- Lines 425-450

**In resheduleMorningandNight.py:**
- No OP patient handling
- No CT room logic

**Impact:** OP patients with CT rooms won't get proper treatment rooms

---

## Summary

**Critical Missing Features:**
1. Gender matching
2. Room allocation (completely missing)
3. Special treatment handling (Dhara & Pizichil)
4. Patient already booked checks
5. OP/IP patient type awareness
6. Therapy requirements from TherapyMaster (grade breakdown)

**Important Missing Features:**
7. Previous bathing therapist prioritization
8. Trainee → Junior substitution
9. Slot allocation logic
10. BookingAssignment creation
11. CT room handling for OP patients

**Recommendation:** The `resheduleMorningandNight.py` algorithm needs significant updates to match the logic in `reshedule.py`, especially for gender matching, room allocation, and special treatment handling.

