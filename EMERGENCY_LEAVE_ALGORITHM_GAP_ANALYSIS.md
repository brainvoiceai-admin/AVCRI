# Emergency Leave Reassignment Algorithm - Gap Analysis

## Overview
This document compares the **Emergency Leave Reassignment Algorithm** (`resheduleMorningandNight.py`) that runs at 5:30 AM with the **Main Reschedule Algorithm** (`reshedule.py`) to identify missing continuity features.

---

## ✅ Features Present in Emergency Leave Algorithm

1. **Basic Previous Therapist Continuity**
   - Checks for previous therapist for same patient
   - Respects therapist grade/level matching
   - Respects gender matching
   - Respects bathing therapist requirements

2. **Bathing Therapist Continuity**
   - Prioritizes previous bathing therapist when needed
   - Validates `is_bathing_therapist` flag

3. **Daily Load Balancing**
   - Respects `max_daily_normal` (5 sessions)
   - Respects `max_daily_overtime_extra` (2 sessions)
   - Uses difficulty-based balancing (Easy/Medium/Hard)

4. **Special Treatment Handling**
   - Handles Dhara & Pizichil (senior tag requirements)
   - Ensures senior therapist is NOT bathing therapist for special treatments

5. **Emergency Leave Filtering**
   - Excludes therapists on emergency leave
   - Excludes therapists on weekly leave
   - Checks slot conflicts

---

## ❌ Missing Features in Emergency Leave Algorithm

### 1. **TherapistContinuityPlan Not Used**
**Main Algorithm:** Uses `TherapistContinuityPlan` model to get pre-planned continuity therapists
```python
continuity_qs = TherapistContinuityPlan.objects.filter(
    date=target_date,
    time_slot=slot_master,
    allocation_id=allocation.id,
    patient_id=patient_id,
)
```

**Emergency Algorithm:** Does NOT use TherapistContinuityPlan at all
- **Impact:** Misses pre-planned continuity assignments
- **Severity:** HIGH

---

### 2. **"From Start of Therapy" Continuity Missing**
**Main Algorithm:** Prioritizes therapists from the **first day of therapy** (`allocation.from_date`)
```python
# Prefers therapists from start of therapy
from_start_qs = TherapistBooking.objects.filter(
    visit_id=allocation.id,
    date__gte=therapy_start_date,  # From first day
    date__lt=target_date,
    time_slot=slot_master,
    status='BOOKED',
).order_by('date', 'created_at')
```

**Emergency Algorithm:** Only checks **previous day** (`order_by('-date').first()`)
```python
prev = (TherapistBooking.objects
    .filter(patient_id=booking.patient_id)
    .exclude(pk=booking.pk)
    .order_by('-date')  # Only previous day
    .first())
```

- **Impact:** May reassign to a temporary replacement instead of original therapist
- **Severity:** HIGH

---

### 3. **No PASS 1 / PASS 2 Logic**
**Main Algorithm:** Uses two-pass system:
- **PASS 1:** Assigns continuity therapists only (from TherapistContinuityPlan or previous day)
- **PASS 2:** Fills remaining slots with new therapists

**Emergency Algorithm:** Single-pass reassignment
- **Impact:** Cannot prioritize continuity therapists before filling remaining slots
- **Severity:** MEDIUM

---

### 4. **Allocation-Specific Continuity Missing**
**Main Algorithm:** Checks continuity within **same allocation** (`visit_id=allocation.id`)
```python
TherapistBooking.objects.filter(
    visit_id=allocation.id,  # Same therapy allocation
    date__gte=therapy_start_date,
    ...
)
```

**Emergency Algorithm:** Only checks by **patient_id** (ignores allocation)
```python
TherapistBooking.objects.filter(
    patient_id=booking.patient_id  # Any therapy for patient
    ...
)
```

- **Impact:** May reassign therapist from different therapy to current therapy
- **Severity:** MEDIUM

---

### 5. **Bathing Continuity from Start Missing**
**Main Algorithm:** For bathing therapists, prioritizes **first-day bathing therapist** from start of therapy
```python
# BATHING CONTINUITY: Start from START OF THERAPY
prev_bath_bookings_qs = TherapistBooking.objects.filter(
    patient_id=patient_id,
    visit_id=allocation.id,  # Same allocation
    time_slot=slot_master,
    date__lt=target_date,
    is_bathing=True,
    status='BOOKED'
).filter(date__gte=therapy_start_date)  # From start
.order_by('date', 'created_at')  # First available wins
```

**Emergency Algorithm:** Only checks most recent bathing therapist
```python
def find_previous_bathing_therapist_for_patient(booking, target_date, ...):
    # Only checks most recent, not from start
    prev_bath = (TherapistBooking.objects
        .filter(patient_id=booking.patient_id, is_bathing=True, ...)
        .order_by('-date')  # Most recent only
        .first())
```

- **Impact:** May use temporary bathing therapist instead of original
- **Severity:** HIGH

---

### 6. **Complete Therapist Group Continuity Missing**
**Main Algorithm:** Can assign **entire previous therapist group** together for continuity
```python
# Found complete previous therapist group - assign together
previous_therapist_group = [...]  # All therapists from previous day
```

**Emergency Algorithm:** Only reassigns **one therapist at a time**
- **Impact:** May break therapist group continuity
- **Severity:** MEDIUM

---

### 7. **Room Booking Continuity Not Handled**
**Main Algorithm:** Handles room reassignment with continuity preferences
**Emergency Algorithm:** Does NOT handle room bookings at all
- **Impact:** Room continuity not maintained during emergency reassignment
- **Severity:** LOW (if room continuity is important)

---

### 8. **No Continuity Result Tracking**
**Main Algorithm:** Returns detailed continuity assignment results
```python
result = {
    'assigned_therapists': [...],
    'bath_assigned': ...,
    'senior_therapist': ...,
    'success': True
}
```

**Emergency Algorithm:** Only tracks reassignment summary
- **Impact:** Cannot track which therapists were assigned for continuity vs new
- **Severity:** LOW

---

## Summary Table

| Feature | Main Algorithm | Emergency Algorithm | Severity |
|---------|---------------|---------------------|----------|
| TherapistContinuityPlan | ✅ Yes | ❌ No | HIGH |
| From Start of Therapy | ✅ Yes | ❌ No | HIGH |
| Bathing from Start | ✅ Yes | ❌ No | HIGH |
| PASS 1/PASS 2 | ✅ Yes | ❌ No | MEDIUM |
| Allocation-Specific | ✅ Yes | ❌ No | MEDIUM |
| Complete Group | ✅ Yes | ❌ No | MEDIUM |
| Room Continuity | ✅ Yes | ❌ No | LOW |
| Previous Day Only | ✅ Yes | ✅ Yes | - |
| Grade Matching | ✅ Yes | ✅ Yes | - |
| Gender Matching | ✅ Yes | ✅ Yes | - |
| Daily Load Limits | ✅ Yes | ✅ Yes | - |
| Special Treatments | ✅ Yes | ✅ Yes | - |

---

## Recommendations

### Priority 1 (HIGH): Add Missing Continuity Features
1. **Use TherapistContinuityPlan** - Check for pre-planned continuity assignments
2. **Add "From Start of Therapy" Logic** - Prioritize first-day therapists
3. **Add Bathing Continuity from Start** - Use original bathing therapist when available

### Priority 2 (MEDIUM): Improve Continuity Logic
4. **Add PASS 1/PASS 2 Logic** - Separate continuity assignment from new assignments
5. **Add Allocation-Specific Continuity** - Check continuity within same therapy allocation
6. **Add Complete Group Continuity** - Reassign entire therapist group when possible

### Priority 3 (LOW): Enhancements
7. **Add Room Continuity** - Handle room reassignment with continuity
8. **Add Continuity Tracking** - Track which assignments are continuity vs new

---

## Implementation Notes

The emergency leave algorithm should be enhanced to match the main reschedule algorithm's continuity logic, especially:
- Using `TherapistContinuityPlan` model
- Checking `allocation.from_date` for "from start" continuity
- Using `visit_id=allocation.id` for allocation-specific continuity
- Implementing two-pass logic for better continuity prioritization
