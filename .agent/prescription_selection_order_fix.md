# Prescription Item Order - Selection Order Preservation

## Issue
Items in the Select2 dropdown were being displayed in **alphabetical order** instead of **selection order**.

### Example:
**User selects:**
1. AGP Spl Kashayam
2. Abhirumooladi Kashayam  
3. Abhayadi modak
4. Amruthotharam Kashayam

**System displayed (WRONG):**
1. Abhayadi modak (alphabetical)
2. Abhirumooladi Kashayam
3. AGP Spl Kashayam
4. Amruthotharam Kashayam

**System should display (CORRECT):**
1. AGP Spl Kashayam (selection order)
2. Abhirumooladi Kashayam
3. Abhayadi modak
4. Amruthotharam Kashayam

## Root Cause
Select2 by default sorts selected items alphabetically. This is controlled by the `sorter` function.

## Fix Applied

### File: `static/js/updated_dash_prescription_entry.js`
### Lines: 668-672

**Added:**
```javascript
// Prevent Select2 from sorting - maintain selection order
sorter: function(data) {
  return data; // Return data as-is, don't sort
}
```

This tells Select2 to **NOT sort** the data and keep it in the order it was selected.

## How It Works

### Before (Default Select2 Behavior):
1. User selects items in order: A, C, B
2. Select2 sorts them: A, B, C (alphabetical)
3. Items displayed: A, B, C ❌

### After (With sorter function):
1. User selects items in order: A, C, B
2. Select2 keeps order: A, C, B (no sorting)
3. Items displayed: A, C, B ✅

## Testing

### Test 1: Selection Order
1. Clear the form
2. Select items in this order:
   - AGP Spl Kashayam
   - Abhayadi modak
   - Amruthotharam Kashayam
3. Verify they appear in the same order in the selected items box

### Test 2: Edit Group
1. Create a group with items in a specific order
2. Click "Edit" on that group
3. Verify items load in the same order

### Test 3: Add More Items
1. Select 2 items
2. Add a 3rd item
3. Verify the 3rd item appears last, not sorted alphabetically

## Expected Behavior

### ✅ Selection Order Preserved:
- Items appear in the exact order you select them
- First selected = first in list
- Last selected = last in list

### ✅ No Alphabetical Sorting:
- "Z Medicine" selected first appears first
- "A Medicine" selected second appears second

### ✅ Consistent Across Operations:
- Add new items → order preserved
- Edit group → order preserved
- Load prescription → order preserved

## Files Modified

1. **`static/js/updated_dash_prescription_entry.js`**
   - Added `sorter` function to Select2 configuration
   - Returns data as-is without sorting

## Notes

- This change only affects the **display order** of selected items
- Does NOT affect the search results order in the dropdown
- Does NOT affect how items are stored in the database
- Items are stored and displayed in selection order

## Conclusion

The prescription item selection now maintains the **selection order** instead of sorting alphabetically. Users can control the exact order of items by selecting them in the desired sequence.
