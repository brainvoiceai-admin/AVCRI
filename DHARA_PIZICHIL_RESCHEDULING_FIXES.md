# Dhara & Pizichil Rescheduling Failure Analysis & Fixes

## Issues Found

### 1. **Missing Dhara & Pizichil Special Room Logic in `reshedule.py`**
   - **Problem**: The `allocate_treatment_room()` function in `reshedule.py` did NOT have the special logic to find and reuse previous room assignments for "Dhara & Pizichil" therapies.
   - **Impact**: When rescheduling Dhara & Pizichil, the system wasn't trying to use the patient's previous room, which could cause allocation failures even when rooms are available.
   - **Fix Applied**: Added the Dhara & Pizichil previous room lookup logic to `allocate_treatment_room()` in `reshedule.py`.

### 2. **Missing Parameters for Dhara & Pizichil Logic**
   - **Problem**: When calling `allocate_treatment_room()` from `attempt_allocate_slot()`, the function wasn't passing `therapy_name` and `patient_id` parameters.
   - **Impact**: Even if the logic existed, it couldn't work without these parameters.
   - **Fix Applied**: Updated the function call to pass `therapy_name` and `patient_id`.

### 3. **Insufficient Error Messages**
   - **Problem**: When Dhara & Pizichil failed due to room unavailability, the error message didn't indicate it was a Dhara & Pizichil treatment or mention the previous room.
   - **Impact**: Made debugging difficult - users couldn't tell why it failed.
   - **Fix Applied**: Added specific error messages for Dhara & Pizichil room failures.

## Possible Failure Reasons for Dhara & Pizichil

### Therapist-Related Failures:
1. **Gender Mismatch**: Female patients require female therapists. If no female therapists are available at the slot, allocation fails.
2. **Bathing Therapist Requirement**: Dhara & Pizichil likely requires bathing therapists (`is_bathing_therapist=True`). If no bathing therapists are available, allocation fails.
3. **Therapist Already Booked**: Therapists may be booked at the preferred slot but available at alternate slots.
4. **Therapist on Leave**: Therapists may be on weekly leave or emergency leave.
5. **Grade Requirements**: Therapy may require specific therapist grades (Super Senior, Senior, Junior, Trainee) that aren't available.

### Room-Related Failures:
1. **Previous Room Unavailable**: For Dhara & Pizichil, the system tries to use the previous room. If that room is booked at the new slot, it fails.
2. **Patient Staying Room Rules**: Treatment rooms are assigned based on patient staying room. If assigned rooms are all booked, allocation fails.
3. **Room Already Booked**: The room may be booked at the preferred slot but available at alternate slots.

### Slot-Related Failures:
1. **Preferred Slot Conflicts**: Patient may already have a booking at the preferred slot.
2. **Slot Already Used in Run**: During bulk allocation, the same slot may have been used for another booking in the same run.
3. **Fallback Not Working**: The rescheduling fallback to alternate slots may not be working correctly.

## How Rescheduling Works

1. **Preferred Slot First**: Tries to allocate at the preferred slot (from booking.timeslot or allocation.timeslot).
2. **Fallback to Alternate Slots**: If preferred slot fails with certain reasons (insufficient_therapists_available, no_room_available, etc.), it tries alternate slots based on patient type (OP/IP) and therapy category.
3. **Slot Selection**: For IP patients: ["06:30","08:30","10:00","14:30","16:00"]. For OP patients: ["11:30","17:30"]. Hard/Special therapies exclude OP slots.

## Debugging Tips

When "insufficient_therapists_available" error occurs:

1. **Check Gender Availability**: 
   - Verify if female therapists are available at the slot
   - Check if therapists are filtered by gender correctly

2. **Check Bathing Requirement**:
   - Verify if therapy requires bathing (`bathing_required='yes'` in TherapyMaster)
   - Check if bathing therapists are available

3. **Check Alternate Slots**:
   - The system should try alternate slots automatically
   - Check if therapists are available at other slots
   - Verify the fallback logic is working

4. **Check Previous Room**:
   - For Dhara & Pizichil, check if previous room is available at alternate slots
   - Previous room may be available at one slot but not another

5. **Check Therapist Constraints**:
   - Weekly leave (TherapistLeaveMaster)
   - Emergency leave (EmergencyLeave)
   - Already booked at the slot
   - Grade requirements

## Files Modified

1. **reshedule.py**:
   - Added `therapy_name` and `patient_id` parameters to `allocate_treatment_room()`
   - Added Dhara & Pizichil previous room lookup logic
   - Added better error messages for Dhara & Pizichil failures
   - Updated function call to pass required parameters

## Testing Recommendations

1. Test rescheduling Dhara & Pizichil with:
   - Female patient with female therapists available at alternate slots
   - Previous room available at alternate slot but not preferred slot
   - Bathing therapists available at alternate slots

2. Verify fallback logic:
   - Preferred slot fails → alternate slots are tried
   - Error messages are clear and informative
   - Previous room is used when available

3. Check therapist allocation:
   - Gender matching works correctly
   - Bathing therapist requirement is enforced
   - Alternate slots are checked for therapist availability

