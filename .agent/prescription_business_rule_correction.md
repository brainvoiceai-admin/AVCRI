# Prescription Item Selection - Business Rule Correction

## Critical Business Rule Change

### ❌ WRONG (Previous Implementation)
- Medicine could only be added ONCE across the ENTIRE prescription
- If Medicine X was in Group A, it was blocked globally
- "Already added" restriction applied across all groups
- Same medicine could NOT exist in different groups

### ✅ CORRECT (New Implementation)
- Medicine can be added ONCE per GROUP
- Same medicine CAN exist in MULTIPLE groups
- Duplicate restriction is GROUP-SCOPED, not global
- No "already added" restriction across groups

## Example Scenario

### Before (WRONG):
```
Group A: Medicine X, Medicine Y
Group B: Medicine Z  ← Medicine X blocked!
```
**Problem:** User cannot add Medicine X to Group B because it's already in Group A

### After (CORRECT):
```
Group A: Medicine X, Medicine Y
Group B: Medicine X, Medicine Z  ← Medicine X allowed!
```
**Solution:** User can add Medicine X to Group B - it's a different group

## Changes Made

### 1. Frontend - Select2 Dropdown ✅
**File:** `static/js/updated_dash_prescription_entry.js`

**Removed:**
- Global duplicate checking in `processResults`
- Disabled items with "(already added)" text
- `templateResult` function that grayed out items

**Result:**
- All items are always selectable
- No visual indication of "already added"
- Clean dropdown without restrictions

### 2. Frontend - Selection Prevention ✅
**File:** `static/js/updated_dash_prescription_entry.js`

**Removed:**
- `select2:selecting` event handler that prevented selection
- Alert message about items being "already added to prescription"

**Result:**
- Users can freely select any item
- No blocking at selection time

### 3. Frontend - Add Group Validation ✅
**File:** `static/js/updated_dash_prescription_entry.js`
**Lines:** 757-776

**Changed:**
```javascript
// OLD - Checked across ALL groups
const selectedCodes = getAllSelectedItemCodes();
selected.forEach(item => {
  if (selectedCodes.has(item.id)) {
    // Block if in ANY group
  }
});

// NEW - Checks within CURRENT selection only
const selectedItemCodes = new Set();
selected.forEach(item => {
  if (selectedItemCodes.has(item.id)) {
    // Block only if selected TWICE in current group
  } else {
    selectedItemCodes.add(item.id);
  }
});
```

**Result:**
- Only checks for duplicates within the items being added to the current group
- Does NOT check against other groups
- Alert message changed to: "selected multiple times in this group"

### 4. Frontend - Load for Edit ✅
**File:** `static/js/updated_dash_prescription_entry.js`
**Lines:** 1390-1423

**Changed:**
```javascript
// OLD - Deduplicated across ALL groups
const seenItemCodes = new Set();
(p.items_groups || []).forEach(g => {
  const uniqueItems = (g.items || []).filter(item => {
    if (seenItemCodes.has(item.item_code)) {
      return false; // Remove if in ANY previous group
    }
    seenItemCodes.add(item.item_code);
    return true;
  });
});

// NEW - Deduplicate within EACH group only
(p.items_groups || []).forEach(g => {
  const seenInGroup = new Set();
  const uniqueItems = (g.items || []).filter(item => {
    if (seenInGroup.has(item.item_code)) {
      return false; // Remove only if duplicate in THIS group
    }
    seenInGroup.add(item.item_code);
    return true;
  });
});
```

**Result:**
- When loading a prescription for edit, same medicine can exist in different groups
- Only removes duplicates within each individual group

### 5. Backend - Allocate Endpoint ✅
**File:** `Sheduling/views.py`
**Lines:** 2615-2637

**Changed:**
```python
# OLD - Deduplicated across ALL groups
seen_item_codes = set()
for group in items_groups:
    for item in group.get('items', []):
        if item_code in seen_item_codes:
            continue  # Skip if in ANY group
        seen_item_codes.add(item_code)

# NEW - Deduplicate within EACH group only
for group in items_groups:
    seen_in_group = set()
    for item in group.get('items', []):
        if item_code in seen_in_group:
            continue  # Skip only if duplicate in THIS group
        seen_in_group.add(item_code)
```

**Result:**
- Backend allows same medicine in different groups
- Only removes duplicates within each group

### 6. Backend - Update Endpoint ✅
**File:** `Sheduling/views.py`
**Lines:** 2912-2935

**Same change as allocate endpoint**

## Validation Rules

### ✅ ALLOWED:
1. **Same medicine in different groups:**
   - Group A: Medicine X
   - Group B: Medicine X ← Allowed!

2. **Multiple groups with overlapping medicines:**
   - Group A: Medicine X, Medicine Y
   - Group B: Medicine X, Medicine Z ← Allowed!

3. **Any combination across groups:**
   - No restrictions between groups

### ❌ PREVENTED:
1. **Duplicate within the same group:**
   - Group A: Medicine X, Medicine X ← Blocked!
   - Alert: "selected multiple times in this group"

2. **Selecting the same item twice in dropdown:**
   - User selects Medicine X twice before clicking "Add Group" ← Blocked!

## User Experience

### Adding New Prescription:
1. Select items for Group A → Click "Add Group" ✅
2. Select items for Group B (can include items from Group A) → Click "Add Group" ✅
3. No restrictions, no "already added" messages

### Editing Prescription:
1. Click "Edit" on a group
2. Items load correctly (even if they exist in other groups)
3. Can modify items freely
4. Can add new groups with overlapping medicines

### Dropdown Behavior:
- All items always available
- No disabled items
- No "(already added)" text
- Clean, unrestricted selection

## Testing Checklist

### Test 1: Same Medicine in Different Groups
- [ ] Add Group A with Medicine X
- [ ] Add Group B with Medicine X
- [ ] Verify both groups exist
- [ ] Verify Medicine X appears in both groups

### Test 2: Edit Group with Overlapping Medicine
- [ ] Create Group A: Medicine X, Medicine Y
- [ ] Create Group B: Medicine Z
- [ ] Edit Group B
- [ ] Add Medicine X to Group B
- [ ] Verify Medicine X now in both groups

### Test 3: Duplicate Within Group
- [ ] Select Medicine X twice in dropdown
- [ ] Click "Add Group"
- [ ] Verify alert: "selected multiple times in this group"
- [ ] Verify group NOT created

### Test 4: Load Prescription with Overlapping Items
- [ ] Create prescription with overlapping medicines in different groups
- [ ] Save prescription
- [ ] Reload page
- [ ] Edit prescription
- [ ] Verify all groups load correctly
- [ ] Verify overlapping medicines preserved

### Test 5: Dropdown Always Available
- [ ] Add Group A with Medicine X
- [ ] Open dropdown again
- [ ] Verify Medicine X is NOT disabled
- [ ] Verify NO "(already added)" text
- [ ] Can select Medicine X again for Group B

## Files Modified

1. **`static/js/updated_dash_prescription_entry.js`**
   - Removed global duplicate checking from Select2
   - Removed select2:selecting event handler
   - Changed Add Group validation to group-scoped
   - Changed loadPrescriptionForEdit to group-scoped deduplication

2. **`Sheduling/views.py`**
   - Changed allocate endpoint to group-scoped deduplication
   - Changed update_prescription endpoint to group-scoped deduplication

## Migration Notes

### Existing Data:
- Prescriptions saved with the old logic (global uniqueness) will load correctly
- If historical data has duplicates across groups, they will be preserved
- If historical data has duplicates within a group, they will be removed on load

### No Breaking Changes:
- UI layout unchanged
- API endpoints unchanged
- Database schema unchanged
- Only validation logic changed

## Conclusion

The prescription item selection now correctly implements the business rule:
- **One medicine per group** (enforced)
- **Same medicine allowed across different groups** (enabled)
- **No incorrect global restrictions** (removed)
- **Clean and predictable behavior** (achieved)

This aligns with the actual business requirement where different groups may need the same medicine with different dosages, times, or other parameters.
