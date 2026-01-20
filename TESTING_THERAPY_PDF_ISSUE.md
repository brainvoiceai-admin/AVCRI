# TESTING PRESCRIPTION PDF WITH THERAPIES

## Issue
Treatments (therapies) are not appearing in the prescription PDF.

## Debug Steps Added

I've added comprehensive debug logging to track therapy data through the PDF generation process.

## How to Test

1. **Open the Prescription Scheduling Dashboard**
   - Navigate to the prescription scheduling page
   - Select a date that has both prescriptions AND therapies scheduled

2. **Open Browser Console**
   - Press F12 to open Developer Tools
   - Go to the "Console" tab

3. **Click "Print to PDF"**
   - Click the "Print to PDF" button
   - Watch the console output

4. **Check Console Logs**

Look for these log messages:

### Initial Data Check
```
[PDF NEW] ========== STARTING PDF GENERATION ==========
[PDF NEW] generatePrescriptionPDF_NEW called with X patients
[PDF NEW] First patient structure: {
    patient_name: "...",
    therapy_items_count: X,    <-- Should be > 0 if therapies exist
    zero_therapist_count: X,   <-- Should be > 0 if zero-therapist therapies exist
    ...
}
```

**KEY QUESTION**: Are `therapy_items_count` and `zero_therapist_count` showing 0 or greater than 0?

### Per-Patient Therapy Check
```
[PDF NEW] Patient: John Doe Room: DS-1
[PDF NEW] - therapyItemsFromDetails: X
[PDF NEW] - therapyItemsFromAPI: X
[PDF NEW] - allTherapyItems: X
[PDF NEW] - zeroTherapistTherapies: X
```

**KEY QUESTION**: Are these counts showing 0 or greater than 0?

### Therapy Rendering
```
[PDF NEW] Rendering therapy: Dhanyamla Dhara Items: ... Time: ...
[PDF NEW] Rendering zero-therapist therapy: ... Items: ... Time: ...
```

**KEY QUESTION**: Are these messages appearing?

## Possible Scenarios

### Scenario 1: therapy_items_count = 0 at the start
**Diagnosis**: Data is not being passed from the main function
**Solution**: Need to check the data fetching in prescription_scheduling.js

### Scenario 2: therapy_items_count > 0 but not rendering
**Diagnosis**: Issue with the rendering logic in prescription_pdf_new.js
**Solution**: Need to check the therapy rendering code

### Scenario 3: No therapies scheduled for the selected date
**Diagnosis**: No therapy data exists for that date
**Solution**: Select a different date or add therapies

## What to Report

Please copy and paste the ENTIRE console output, especially:

1. The initial data structure log
2. All patient therapy count logs
3. Any error messages
4. The date you selected
5. Whether you know for certain that therapies exist for that date

## Quick Check

Before testing, verify therapies exist:
1. Go to the Therapy Scheduling dashboard
2. Select the same date
3. Check if therapies are shown in the "Scheduled Therapies" tab
4. Note down patient names who have therapies

Then test the prescription PDF for those same patients.
