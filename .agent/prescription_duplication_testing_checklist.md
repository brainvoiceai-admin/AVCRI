# Prescription Duplication Fix - Testing Checklist

## Test Environment Setup
- [ ] Clear browser cache
- [ ] Reload the prescription entry page
- [ ] Select a test patient

## Test 1: Add Prescription - Basic Duplicate Prevention
### Steps:
1. Select an item (e.g., "Medicine A")
2. Click "Add Group"
3. Try to select the same item again ("Medicine A")

### Expected Result:
- [ ] Item appears grayed out in dropdown with "(already added)" text
- [ ] Clicking the item shows alert: "Medicine A is already added to this prescription"
- [ ] Item is NOT added to the selection

## Test 2: Add Prescription - Multiple Groups
### Steps:
1. Select "Medicine A" and "Medicine B"
2. Click "Add Group" (Group 1 created)
3. Select "Medicine C"
4. Click "Add Group" (Group 2 created)
5. Try to select "Medicine A" or "Medicine B" again

### Expected Result:
- [ ] Both "Medicine A" and "Medicine B" appear disabled in dropdown
- [ ] Alert prevents selection of either item
- [ ] Only "Medicine C" and other new items can be selected

## Test 3: Add Prescription - Validation on Add Group
### Steps:
1. Select "Medicine A"
2. Click "Add Group" (Group 1 created)
3. Manually select "Medicine A" again (if possible through any means)
4. Try to click "Add Group"

### Expected Result:
- [ ] Alert shows: "The following item(s) are already added to this prescription: Medicine A"
- [ ] Group is NOT created
- [ ] User must remove duplicate before proceeding

## Test 4: Edit Group - Re-select Own Items
### Steps:
1. Create a group with "Medicine A" and "Medicine B"
2. Click "Edit" on that group
3. Try to select "Medicine A" again (should be allowed)
4. Try to select "Medicine C" (new item)
5. Click "Add Group"

### Expected Result:
- [ ] Can re-select "Medicine A" (own item)
- [ ] Can select "Medicine C" (new item)
- [ ] Group is updated successfully
- [ ] No duplicate items in final prescription

## Test 5: Edit Group - Cannot Select Items from Other Groups
### Steps:
1. Create Group 1 with "Medicine A"
2. Create Group 2 with "Medicine B"
3. Click "Edit" on Group 2
4. Try to select "Medicine A" (from Group 1)

### Expected Result:
- [ ] "Medicine A" appears disabled in dropdown
- [ ] Alert prevents selection
- [ ] Only "Medicine B" (own item) and new items can be selected

## Test 6: Edit Prescription - Add New Groups
### Steps:
1. Save a prescription with "Medicine A" and "Medicine B"
2. Click "Edit" on the prescription
3. Try to add a new group with "Medicine A"

### Expected Result:
- [ ] "Medicine A" and "Medicine B" appear disabled
- [ ] Cannot select already-added items
- [ ] Can only add new items to the prescription

## Test 7: Remove Group - State Reset
### Steps:
1. Create Group 1 with "Medicine A"
2. Click "Edit" on Group 1
3. Click "Remove" on Group 1 (while in edit mode)
4. Try to select "Medicine A" again

### Expected Result:
- [ ] "Medicine A" becomes available again
- [ ] Can select and add "Medicine A" to a new group
- [ ] No errors or stale state

## Test 8: Multiple Add/Edit/Remove Operations
### Steps:
1. Add Group 1 with "Medicine A"
2. Add Group 2 with "Medicine B"
3. Edit Group 1, change to "Medicine C"
4. Remove Group 2
5. Add Group 3 with "Medicine B" (now available)

### Expected Result:
- [ ] All operations complete successfully
- [ ] Final prescription has "Medicine C" and "Medicine B"
- [ ] No duplicate items
- [ ] No errors

## Test 9: Switch Patients - State Reset
### Steps:
1. Select Patient 1
2. Add groups with various items
3. Switch to Patient 2
4. Try to add items that were used for Patient 1

### Expected Result:
- [ ] All items are available for Patient 2
- [ ] No items appear as "already added"
- [ ] Clean state for new patient

## Test 10: Form Reset
### Steps:
1. Add several groups with items
2. Click "Clear Form" (if available) or reset the form
3. Try to add items that were previously added

### Expected Result:
- [ ] All items are available again
- [ ] No items appear as "already added"
- [ ] Clean state after reset

## Test 11: Save and Reload
### Steps:
1. Create a prescription with "Medicine A", "Medicine B", "Medicine C"
2. Save the prescription
3. Reload the page
4. Edit the same prescription
5. Try to add "Medicine A" again

### Expected Result:
- [ ] After reload, existing items are tracked correctly
- [ ] Cannot add duplicate items
- [ ] Can add new items only

## Test 12: Visual Feedback
### Steps:
1. Add a group with "Medicine A"
2. Open the item dropdown
3. Observe the appearance of "Medicine A"

### Expected Result:
- [ ] "Medicine A" appears grayed out
- [ ] Text shows "(already added)" suffix
- [ ] Item is clearly distinguishable from available items

## Bug Scenarios (Should NOT Occur)
- [ ] Same item appears multiple times in a prescription
- [ ] Editing a group causes item duplication
- [ ] Adding new groups during edit duplicates existing items
- [ ] Page refresh causes duplicate items
- [ ] Switching between add and edit modes causes duplicates

## Performance Check
- [ ] Dropdown loads quickly even with many items
- [ ] Duplicate checking doesn't cause lag
- [ ] No console errors during any operation
- [ ] Smooth user experience throughout

## Notes:
- Document any unexpected behavior
- Note any edge cases not covered
- Report any console errors or warnings
