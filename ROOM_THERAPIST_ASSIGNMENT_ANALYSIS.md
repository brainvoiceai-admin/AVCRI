# Room and Therapist Assignment Analysis

## Summary
This document shows exactly where room numbers and therapists are assigned during therapy scheduling and identifies the issue where therapists are NOT being saved to the Booking model.

---

## Room Assignment

### ✅ Location: `final_allocation.py` (Lines 445-513)

**Room Allocation:**
```python
# Line 446: Check if room is needed and get existing or allocate new
room_candidate = getattr(booking, 'room', None)
if needs_room_flag and not room_candidate:
    room_candidate = allocate_treatment_room(target_date, canonical_slot, None)
```

**Room Assignment & Saving:**
```python
# Line 511-513: Room IS being assigned and saved to Booking model
booking.room = room_candidate or booking.room
booking.status = 'scheduled'
booking.save(update_fields=['timeslot','room','status','updated_at'])
```

**Room Booking Creation:**
```python
# Lines 475-478: RoomBooking is created in Patient app
if needs_room_flag and create_bookings:
    rb_obj, rb_created = create_room_booking_safe(room_candidate, target_date, canonical_slot, therapy_name, patient_id, None)
```

**✅ STATUS: Room assignment IS working correctly**
- Room is assigned to `Booking.room` (Sheduling app)
- `RoomBooking` is created in Patient app
- Room is saved to database

---

## Therapist Assignment

### ⚠️ Location: `final_allocation.py` (Lines 406-491)

**Therapist Allocation:**
```python
# Lines 406-408: Therapists are allocated
if therapy_req and req_total > 0:
    candidate_therapists = allocate_therapists(target_date, canonical_slot, therapy_req, None, needs_bath_flag)
```

**Therapist Selection:**
```python
# Lines 433-444: Therapists are selected and bathting therapist identified
assigned_therapists = candidate_therapists[:req_total]
bath_assigned = None
if needs_bath_flag and assigned_therapists:
    bath_assigned = next((t for t in assigned_therapists if getattr(t, 'is_bathing_therapist', False)), None)
    if not bath_assigned:
        bath_assigned = assigned_therapists[0]
```

**Therapist Booking Creation (Patient App):**
```python
# Lines 483-491: TherapistBooking records ARE created in Patient app
for t in assigned_therapists:
    is_bath_for_t = (t == bath_assigned)
    if create_bookings:
        tb_obj, tb_created = create_therapist_booking_safe(t, target_date, canonical_slot, therapy_name, patient_id, None, is_bathing=is_bath_for_t)
        if not tb_created:
            raise RuntimeError(f"therapist_already_booked:{getattr(t,'therapist_code',str(t))}")
        tb_objs.append(tb_obj)
```

**❌ MISSING: BookingAssignment Creation (Sheduling App)**
```python
# THIS CODE IS MISSING in final_allocation.py:
# Should create BookingAssignment records like in Sheduling/views.py line 695:
# 
# for t in assigned_therapists:
#     from Patient.models import Therapist
#     therapist_obj = Therapist.objects.get(therapist_code=t.therapist_code)
#     BookingAssignment.objects.create(
#         booking=booking,
#         booking_item=None,
#         therapist=therapist_obj,
#         role=getattr(t, 'therapist_grade', ''),
#         assigned_for='booking',
#         status='assigned'
#     )
```

**❌ STATUS: Therapist assignment is PARTIALLY working**
- ✅ Therapists ARE allocated
- ✅ `TherapistBooking` records ARE created in Patient app
- ❌ `BookingAssignment` records are NOT created in Sheduling app
- ❌ Therapists are NOT linked to the Booking model
- ❌ Cannot query `booking.assignments.all()` or `booking.therapists` - returns empty

---

## Comparison with Working Code

### In `Sheduling/views.py` (Line 678-697) - Working Example:
```python
b = Booking.objects.create(allocation=alloc, date=single_date, timeslot=timeslot_obj, room=room_obj, status=booking_status)
# ... create items ...

assigns = []
for t in therapists:  # therapists is list of TherapistMaster objects
    a = BookingAssignment.objects.create(
        booking=b, 
        booking_item=None, 
        therapist=t,  # Direct assignment works if 't' is Therapist object
        role=getattr(t,'therapist_grade',''), 
        assigned_for='booking', 
        status='assigned'
    )
    assigns.append(getattr(t,'therapist_code',''))
```

### In `final_allocation.py` - Missing BookingAssignment:
```python
# Lines 509-515: Only room is saved, therapists are NOT linked
booking.timeslot = getattr(booking, 'timeslot', None) or canonical_slot
booking.room = room_candidate or booking.room
booking.status = 'scheduled'
booking.save(update_fields=['timeslot','room','status','updated_at'])
# ❌ NO BookingAssignment.objects.create() here!
```

---

## The Problem

1. **Room**: ✅ Assigned and saved correctly
2. **Therapists**: 
   - ✅ Allocated correctly
   - ✅ Saved to `Patient.TherapistBooking`
   - ❌ NOT saved to `Sheduling.BookingAssignment`
   - ❌ Cannot access therapists via `booking.assignments.all()`
   - ❌ Therapists not visible in Booking queries

---

## Fix Required

Add BookingAssignment creation in `final_allocation.py` after line 491:

```python
# After creating TherapistBooking records, also create BookingAssignment
from Sheduling.models import BookingAssignment
from Patient.models import Therapist

for t in assigned_therapists:
    try:
        # Get Therapist object from Patient app (therapist_code is PK)
        therapist_obj = Therapist.objects.get(therapist_code=t.therapist_code)
        BookingAssignment.objects.create(
            booking=booking,
            booking_item=None,
            therapist=therapist_obj,
            role=getattr(t, 'therapist_grade', ''),
            assigned_for='booking',
            status='assigned'
        )
    except Therapist.DoesNotExist:
        # Therapist might not exist in Patient.Therapist yet - log or create
        pass
```

---

## Files to Modify

1. **`final_allocation.py`** - Add BookingAssignment creation (after line 491)
2. Ensure `Patient.models.Therapist` records exist for all `masters.models.TherapistMaster` therapists

