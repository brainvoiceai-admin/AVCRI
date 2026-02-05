# Template Syntax Error Fix - 2026-02-04

## Issue
**Error:** `TemplateSyntaxError: Invalid block tag on line 196: 'endwith', expected 'elif', 'else' or 'endif'`

## Root Cause
Multiple `{% with %}` template tags were split across multiple lines in `scheduling.html`. Django template tags MUST be on a single line - they cannot span multiple lines.

## Problematic Pattern
```django
{% with
room_no=booking.allocation.patient.pat_room_no|get_staying_room_display
%}
```

## Correct Pattern
```django
{% with room_no=booking.allocation.patient.pat_room_no|get_staying_room_display %}
```

## Locations Fixed

### 1. Line 193-194 (Failed Schedules tab - Patient Room)
**Before:**
```django
{% with
room_no=booking.allocation.patient.pat_room_no|get_staying_room_display %}
```

**After:**
```django
{% with room_no=booking.allocation.patient.pat_room_no|get_staying_room_display %}
```

### 2. Line 347-349 (Scheduled Therapies - Patient Room)
**Before:**
```django
{% with
room_no=booking.allocation.patient.pat_room_no|get_staying_room_display
%}
```

**After:**
```django
{% with room_no=booking.allocation.patient.pat_room_no|get_staying_room_display %}
```

### 3. Line 359-361 (Therapist Assigned - Therapist Name)
**Before:**
```django
{% with
therapist_name=assignment.therapist.therapist_name|default:assignment.therapist.therapist_code
%}
```

**After:**
```django
{% with therapist_name=assignment.therapist.therapist_name|default:assignment.therapist.therapist_code %}
```

### 4. Line 363-364 (Therapist Assigned - Is Senior)
**Before:**
```django
{% with is_senior=assignment|is_senior_therapist_for_dhara:booking
%}
```

**After:**
```django
{% with is_senior=assignment|is_senior_therapist_for_dhara:booking %}
```

### 5. Line 435-437 (Nurse Schedule - Patient Room)
**Before:**
```django
{% with
room_no=booking.allocation.patient.pat_room_no|get_staying_room_display
%}
```

**After:**
```django
{% with room_no=booking.allocation.patient.pat_room_no|get_staying_room_display %}
```

## Files Modified
- `templates/dashboards/scheduling/scheduling.html` - Fixed 5 multi-line `{% with %}` tags

## Result
✅ All template tags are now on single lines
✅ The scheduling dashboard page should now render without TemplateSyntaxError
✅ No functional changes - only syntax fixes

## Important Rule
**Django Template Tag Requirement:** All Django template tags (`{% %}`) must be written on a single line. Multi-line tags are not supported and will cause TemplateSyntaxError.
