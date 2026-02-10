# Therapy Change Log Feature - Testing Guide

## Overview
This guide provides step-by-step instructions for testing the newly implemented Therapy Change Log feature.

## Prerequisites
1. Ensure migrations have been run: `python manage.py migrate Sheduling`
2. Access to the Therapy Scheduling page
3. At least one therapy that has been rescheduled (slot or room changed from original)

## Test Scenarios

### Scenario 1: Viewing Change Log for a Rescheduled Therapy

**Steps:**
1. Navigate to Therapy Scheduling screen
2. Click on "Scheduled Therapies" tab
3. Select a date from the date filter (ensure date has scheduled therapies)
4. Look for therapies with purple/lavender background - these are rescheduled therapies

**Expected Results:**
- Rescheduled therapy rows have a purple background (#f3e5f5)
- A blue "📋 Change Log" button appears next to the therapy name in the "Therapy Name" column
- Non-rescheduled therapies do NOT have the Change Log button

**Pass Criteria:**
- ✓ Correct visual highlighting of rescheduled rows
- ✓ Change Log button present only for rescheduled therapies
- ✓ Button is properly styled (blue background, white text, compact size)

### Scenario 2: Opening the Change Log Modal

**Steps:**
1. Identify a rescheduled therapy (purple background)
2. Click the "📋 Change Log" button next to the therapy name
3. Observe the modal that appears

**Expected Results:**
- Modal opens immediately with a loading spinner
- Modal is centered on screen
- Modal has proper dimensions (max-width 800px, responsive)
- Loading message appears: "Loading change log..."

**Pass Criteria:**
- ✓ Modal appears promptly
- ✓ Loading state is visible
- ✓ No console errors

### Scenario 3: Viewing Change Log Data

**Steps:**
1. Open Change Log modal for a rescheduled therapy
2. Wait for data to load
3. Review the displayed information

**Expected Results:**
Modal displays three main sections:

**1. Header Section:**
- Title: "Therapy Change Log"
- Close button (×) in top-right corner

**2. Patient/Therapy Info Section (gray background):**
- Patient name and registration number
  Example: "Sarah Johnson (REG12345)"
- Therapy name
  Example: "Abhyanga"

**3. Change History Section:**
- Section title: "Change History" with subtitle indicating source
  - "(Audit Records)" if history table has data
  - "(Current vs Original)" if comparing allocation to booking
- One or more change entry cards, each showing:
  - Entry number (e.g., "Entry #1")
  - Date (e.g., "Date: 15-02-2026")
  - Rescheduled by and timestamp
    Example: "By: admin 2/10/2026, 10:30:00 AM"
  - Comparison table with three columns:
    * "Field"
    * "Before (Original Entry)"
    * "After (Rescheduled)"

**Comparison Table Rows (may include):**
- **Slot / Time:** 
  - Format: 12-hour time (e.g., "09:00 AM")
  - Shows old vs new time slot
- **Room:**
  - Format: Room number (e.g., "TR-101")
  - Shows old vs new treatment room
- **Therapist(s):**
  - Format: Comma-separated names
  - Shows old vs new therapist assignments
- **Date:**
  - Format: DD-MM-YYYY
  - Shows if therapy was moved to a different date

**Visual Indicators:**
- Changed fields have yellow background (#fef3c7)
- Changed fields have bold text
- Red dot (●) appears next to changed "After" values
- Unchanged fields have normal white/light gray background

**Pass Criteria:**
- ✓ All sections display correctly
- ✓ Patient and therapy information is accurate
- ✓ Change entries are in chronological order (most recent first)
- ✓ Before/After values are correct
- ✓ Changed fields are highlighted in yellow
- ✓ Red dot appears only on changed values
- ✓ Date and time formats are correct
- ✓ User who made the change is indicated

### Scenario 4: Multiple Reschedule Events

**Steps:**
1. Find a therapy that has been rescheduled more than once
2. Open its Change Log

**Expected Results:**
- Multiple entry cards appear (Entry #1, Entry #2, etc.)
- Each entry shows a different reschedule event
- Events are ordered chronologically (most recent first)
- Each entry has its own Before/After comparison table

**Pass Criteria:**
- ✓ Multiple entries display correctly
- ✓ Chronological ordering is correct
- ✓ Each entry shows unique timestamp and user
- ✓ Changes progress logically across entries

### Scenario 5: Therapy with No Reschedule History

**Steps:**
1. Manually test by querying a therapy that is marked as rescheduled but has no `BookingRescheduleHistory` records
2. Open its Change Log

**Expected Results:**
- Modal displays header and patient/therapy info
- Change log section shows comparison between current booking and original allocation
- Message indicates: "(Current vs Original)"
- Only fields that differ between allocation and booking are marked as changed

**Pass Criteria:**
- ✓ Fallback logic works correctly
- ✓ Comparison is accurate
- ✓ Changed fields are properly identified

### Scenario 6: Closing the Modal

**Steps:**
Test all three ways to close the modal:

1. **Close Button (×):**
   - Click the × button in top-right corner
   
2. **Outside Click:**
   - Click anywhere outside the modal (on the dark overlay)

**Expected Results:**
- Modal closes immediately
- No errors in console
- Page returns to normal state
- Background scroll is restored (if applicable)

**Pass Criteria:**
- ✓ Close button works
- ✓ Outside click works
- ✓ Modal is completely removed from DOM
- ✓ No memory leaks or lingering elements

### Scenario 7: Error Handling

**Steps to Simulate Errors:**

**7a. Invalid Allocation ID:**
1. Manually modify button's data-allocation-id to an invalid value
2. Click the Change Log button

**7b. Network Error:**
1. Disconnect network while opening Change Log
2. Click the Change Log button

**Expected Results:**
- Modal opens
- Error message displays:
  - "⚠️ Error Loading Change Log"
  - Specific error message (e.g., "HTTP 404: Not Found")
  - "Close" button to dismiss
- Error is styled in red (#ef4444)
- User can close modal and try again

**Pass Criteria:**
- ✓ Errors are caught gracefully
- ✓ User-friendly error messages
- ✓ Console shows detailed error for debugging
- ✓ Modal can be closed after error
- ✓ No page crashes or freezes

### Scenario 8: Responsive Design

**Steps:**
1. Open Change Log modal on desktop
2. Resize browser window to tablet size (768px wide)
3. Resize to mobile size (375px wide)
4. Test on actual mobile device if available

**Expected Results:**
- Modal width adjusts responsively (90% of screen width)
- Maximum width of 800px on large screens
- Table scrolls horizontally if needed on small screens
- All content remains readable and accessible
- Close button remains accessible

**Pass Criteria:**
- ✓ Modal is fully responsive
- ✓ No horizontal overflow on small screens
- ✓ Text remains legible
- ✓ Touch targets are adequate (44px minimum)

### Scenario 9: Nurse Treatments

**Steps:**
1. Navigate to "Scheduled Therapies" tab
2. Scroll to "Nurse Treatments" section
3. Find a rescheduled nurse treatment (purple background)
4. Click its Change Log button

**Expected Results:**
- Same behavior as therapist treatments
- Modal displays correctly
- Change log shows before/after comparison

**Pass Criteria:**
- ✓ Feature works for nurse treatments
- ✓ No differences in functionality
- ✓ All data displays correctly

### Scenario 10: Integration with Existing Features

**Steps:**
1. Use patient name search while viewing scheduled therapies
2. Verify rescheduled therapies still show Change Log button
3. Change date filter
4. Verify Change Log button updates correctly
5. Export schedule to Excel/PDF
6. Verify no conflicts with Change Log feature

**Expected Results:**
- Change Log feature works seamlessly with all filters
- No interference with existing functionality
- Performance remains good

**Pass Criteria:**
- ✓ Filters work correctly
- ✓ Change Log data updates with date changes
- ✓ No performance degradation
- ✓ Export functions still work

## API Testing

### Direct API Test

**Endpoint:** `GET /sheduling/scheduling/api/therapy-change-log/`

**Test 1: Valid Request**
```bash
curl "http://localhost:8000/sheduling/scheduling/api/therapy-change-log/?allocation_id=123"
```

**Expected Response:**
```json
{
  "allocation_id": 123,
  "patient_name": "John Doe",
  "patient_reg_no": "REG001",
  "therapy_name": "Abhyanga",
  "change_log": [...],
  "has_history_records": true/false
}
```

**Test 2: Missing Allocation ID**
```bash
curl "http://localhost:8000/sheduling/scheduling/api/therapy-change-log/"
```

**Expected Response:**
```json
{
  "error": "allocation_id is required"
}
```
Status Code: 400

**Test 3: Invalid Allocation ID**
```bash
curl "http://localhost:8000/sheduling/scheduling/api/therapy-change-log/?allocation_id=999999"
```

**Expected Response:**
```json
{
  "error": "Allocation not found"
}
```
Status Code: 404

## Database Verification

**Check Migration:**
```bash
python manage.py showmigrations Sheduling
```

**Expected:** Latest migration for `BookingRescheduleHistory` should be applied (marked with [X])

**Check Model in Django Admin:**
1. Navigate to Django Admin
2. Look for "Booking Reschedule Histories" under Sheduling app
3. Verify model is registered and accessible

## Performance Testing

**Test with Large Dataset:**
1. Create therapy with 10+ reschedule events
2. Open Change Log
3. Measure load time

**Expected:**
- Load time < 2 seconds
- No browser lag
- Smooth scrolling in modal

**Pass Criteria:**
- ✓ Loads quickly even with many records
- ✓ No memory leaks with repeated opens/closes
- ✓ Browser remains responsive

## Accessibility Testing

**Screen Reader Test:**
1. Use screen reader (NVDA, JAWS, or VoiceOver)
2. Navigate to Change Log button
3. Activate button
4. Navigate through modal content

**Expected:**
- Button has proper label
- Modal content is accessible
- Table has proper headers
- User can navigate with keyboard

**Pass Criteria:**
- ✓ All content is announced correctly
- ✓ Focus management works properly
- ✓ No accessibility barriers

## Security Testing

**Test SQL Injection:**
- Try passing SQL in allocation_id parameter
- Verify proper escaping and validation

**Test XSS:**
- Try injecting script tags in therapy names or patient names
- Verify `escapeHtml()` function works correctly

**Expected:**
- No SQL injection possible
- No XSS vulnerabilities
- User input is properly sanitized

## Summary Checklist

- [ ] All visual elements display correctly
- [ ] Change Log button appears only for rescheduled therapies
- [ ] Modal opens and closes properly
- [ ] Change log data is accurate
- [ ] Changed fields are properly highlighted
- [ ] Multiple reschedule events display correctly
- [ ] Error handling works gracefully
- [ ] Responsive design works on all screen sizes
- [ ] Works for both therapist and nurse treatments
- [ ] Integration with existing features is seamless
- [ ] API returns correct data
- [ ] Database migration is applied
- [ ] Performance is acceptable
- [ ] Accessibility requirements are met
- [ ] Security is maintained

## Reporting Issues

When reporting issues, please include:
1. Scenario number from this guide
2. Steps to reproduce
3. Expected vs actual behavior
4. Screenshots or screen recording
5. Browser console errors (if any)
6. Browser and version
7. Screen size and device type

## Success Criteria

The feature is considered successfully implemented when:
- ✅ All 10 main scenarios pass
- ✅ API tests return correct responses
- ✅ No critical bugs found
- ✅ Performance is acceptable
- ✅ Accessibility standards are met
- ✅ Security tests pass
- ✅ User feedback is positive
