# Prescription Print Format Correction - Implementation Summary

## Overview
This implementation corrects the prescription and therapy printout to EXACTLY match the required hospital chart format as specified in the requirements.

## Scope
**IMPORTANT**: These changes affect ONLY the prescription print/PDF output. No other parts of the application (UI screens, forms, dashboards, data models, or business logic) are impacted.

## Files Modified

### 1. `/static/js/prescription_pdf_new.js` (NEW FILE)
**Purpose**: Complete rewrite of PDF generation to match exact hospital chart format

**Key Features**:
- **Exact Header**: "THE ARYA VAIDA CHIKITSALAYAM AND RESEARCH INSTITUTE" with date and department info
- **Clean Time Legend**: Professional multi-column layout with all time codes (M, E, ABF, BL, AL, BD, AD, BT, NT)
- **Strict Room Ordering**: 
  1. SUITE – GROUND FLOOR (DS-1 to DS-6, NR-7 to NR-14, NR-28 to NR-33)
  2. FIRST FLOOR (NR-15 to NR-27)
  3. COTTAGES – NEW BLOCK (CT-1 to CT-23)
  4. GENERAL WARD ROOMS (MG, FG, CB rooms)
  5. OP PATIENTS (OP rooms)
- **Prescription Table Structure**:
  - Columns: Time / Usage | Items | Oil Class | Ingredients
  - Medicines grouped with `+` symbol
  - Dosage included at end of group in brackets: `[10 ml]`
  - Example: `Rasnaerandadi Kashayam + Ashtavargam Kashayam — [10 ml]`
- **Separate Therapy Table**:
  - Columns: Therapy Name | Items | Oil Class | Time Slot
  - Therapy name in first column
  - Therapy medicines in Items column
  - Time slot mandatory for therapies
- **Patient Information**: Room, Name, Gender, Age, Doctor displayed once per patient
- **Landscape orientation**: Better fit for table columns

### 2. `/static/js/prescription_scheduling.js` (MODIFIED)
**Changes**: Replaced the old `generatePrescriptionPDF` function with a lightweight wrapper that loads and calls the new PDF generator

**Why**: Keeps the main file clean and allows for easy rollback if needed

### 3. `/templates/dashboards/prescriptions/prescription_scheduling.html` (MODIFIED)
**Changes**: Added script tag to load `prescription_pdf_new.js`

**Location**: Added before the main `prescription_scheduling.js` script

## Technical Implementation Details

### Room Ordering Logic
```javascript
const roomSections = [
    {
        name: 'SUITE – GROUND FLOOR',
        rooms: ['DS-1', 'DS-2', ..., 'NR-33']
    },
    {
        name: 'FIRST FLOOR',
        rooms: ['NR-15', 'NR-15A', ..., 'NR-27']
    },
    // ... etc
];
```

Patients are organized by room number into sections, then printed in the exact order specified.

### Prescription Grouping
Medicines are grouped by allocation ID, with:
- First medicine in group: on its own line
- Subsequent medicines: `+ ` prefix on new line
- Dosage per medicine/group: `[dosage]` appended to the item name

Example output:
```
Rasnaerandadi Kashayam [10 ml]
+ Ashtavargam Kashayam [5 ml]
+ Indukantham Kashayam [15 ml]
```

### Therapy Separation
Therapies are rendered in a completely separate table AFTER prescriptions, with:
- Therapy name in dedicated column
- Items/medicines in Items column
- Time slot in dedicated column
- No mixing with prescription rows

### Data Deduplication
Patients are deduplicated by registration number to prevent duplicates when a patient has both prescriptions and therapies.

## Testing Checklist

### Header & Legend
- [ ] Header shows "THE ARYA VAIDA CHIKITSALAYAM AND RESEARCH INSTITUTE"
- [ ] Date formatted as DD/MM/YYYY
- [ ] "PHYSICIAN / PHARMACY / RESEARCH" appears on header line
- [ ] Time legend displays in clean 3-column layout
- [ ] All 9 time codes present (M, E, ABF, BL, AL, BD, AD, BT, NT)

### Room Ordering
- [ ] SUITE – GROUND FLOOR section appears first
- [ ] FIRST FLOOR section appears second
- [ ] COTTAGES – NEW BLOCK section appears third
- [ ] GENERAL WARD ROOMS section appears fourth
- [ ] OP PATIENTS section appears last
- [ ] Rooms within each section follow specified order
- [ ] No rooms mixed between sections

### Prescription Table
- [ ] Column headers: Time / Usage, Items, Oil Class, Ingredients
- [ ] NO separate Dosage column
- [ ] Medicines grouped with `+` symbol
- [ ] Dosage appears at end in brackets: `[10 ml]`
- [ ] Oil Class and Ingredients align correctly
- [ ] No overlapping text

### Therapy Table
- [ ] Separate table AFTER prescriptions
- [ ] Column headers: Therapy Name, Items, Oil Class, Time Slot
- [ ] Therapy name in first column
- [ ] Therapy medicines in Items column
- [ ] Time slot present for all therapies
- [ ] No mixing with prescription rows

### Patient Information
- [ ] Room number displayed
- [ ] Patient name displayed
- [ ] Gender displayed
- [ ] Age displayed
- [ ] Doctor name displayed
- [ ] Information appears once per patient

### General
- [ ] PDF generates without errors
- [ ] Landscape orientation
- [ ] Clean, professional layout
- [ ] Print-ready output
- [ ] No data loss or corruption

## Rollback Plan

If issues arise, rollback is simple:

1. Remove the script tag from `prescription_scheduling.html`:
   ```html
   <!-- Comment out or remove this line -->
   <!-- <script src="{% static 'js/prescription_pdf_new.js' %}"></script> -->
   ```

2. Restore the old `generatePrescriptionPDF` function in `prescription_scheduling.js` from git history

3. Delete `prescription_pdf_new.js`

## Notes for Future Maintenance

1. **Room List Updates**: If new rooms are added, update the `roomSections` array in `prescription_pdf_new.js`

2. **Time Legend Changes**: Update the `legendItems` array if time codes change

3. **Column Adjustments**: Column positions are defined by X coordinates (e.g., `margin + 35`, `margin + 120`). Adjust these if column widths need to change.

4. **Font Sizes**: Currently using size 8-12. Adjust in the respective sections if needed.

5. **Page Breaks**: The `checkNewPage()` function handles pagination. Adjust `requiredHeight` thresholds if content is being cut off.

## Compliance with Requirements

✅ Exact header format
✅ Clean time legend layout  
✅ Strict section-wise room ordering
✅ Prescription table with correct columns
✅ Medicine grouping with `+` and dosage in Items column
✅ Separate therapy table with correct structure
✅ No impact on other UI/forms/dashboards
✅ Print-only scope (no business logic changes)

## Contact

For questions or issues with this implementation, refer to this document and the inline comments in `prescription_pdf_new.js`.
