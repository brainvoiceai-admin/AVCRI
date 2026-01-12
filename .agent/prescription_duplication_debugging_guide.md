# Prescription Duplication - Debugging Guide

## Current Status

I've added comprehensive fixes and debugging to help identify the exact cause of the duplication issue you're experiencing.

## What I've Fixed

### 1. Double-Click Prevention
Added a flag (`isAddingGroup`) to prevent the "Add Group" button from being clicked multiple times rapidly, which could cause duplicate groups to be created.

### 2. Backend Deduplication
- Added deduplication logic in both `allocate` and `update_prescription` endpoints
- Ensures no duplicate items are saved to the database

### 3. Frontend Deduplication on Load
- When editing a prescription, duplicate items are automatically removed
- Only the first occurrence of each item is kept

### 4. Debug Logging
Added detailed console logging to track the exact flow:

**When Editing a Group:**
```
=== Edit Group Debug ===
Editing group ID: [id]
Group items: [list of items]
itemGroups count before removal: [count]
itemGroups count after removal: [count]
Remaining item codes: [codes]
========================
```

**When Adding a Group:**
```
=== Add Group Debug ===
Items to add: [list]
Current itemGroups count: [count]
All existing item codes: [codes]
editingGroupId: [id or null]
After adding - itemGroups count: [count]
New group ID: [id]
=======================
```

## How to Debug Your Issue

### Step 1: Clear Browser Cache
1. Press `Ctrl + Shift + Delete`
2. Clear cached images and files
3. Reload the page

### Step 2: Open Browser Console
1. Press `F12` to open Developer Tools
2. Go to the "Console" tab
3. Keep it open while testing

### Step 3: Reproduce the Issue
Follow your exact scenario:
1. Create a prescription with p1, p2, p3
2. Click "Edit" on the group
3. **Watch the console** - you should see "Edit Group Debug" messages
4. Remove p2 and p3 from the dropdown
5. Add p4 to the dropdown
6. Click "Add Group"
7. **Watch the console** - you should see "Add Group Debug" messages

### Step 4: Analyze the Console Output

Look for these specific things:

#### A. When you click "Edit":
- `itemGroups count before removal`: Should show 1 (the original group)
- `itemGroups count after removal`: Should show 0 (group removed)
- `Remaining item codes`: Should be empty `[]`

#### B. When you click "Add Group":
- `Items to add`: Should show `["p1 (code)", "p4 (code)"]`
- `Current itemGroups count`: Should be 0
- `All existing item codes`: Should be empty `[]`
- `editingGroupId`: Should show the old group ID
- `After adding - itemGroups count`: Should be 1

#### C. Check for Duplicates:
- If "All existing item codes" shows p1's code, that's the problem!
- If "Items to add" shows p1 twice, that's the problem!
- If you see "Add Group Debug" messages **twice**, that means the button was clicked twice!

### Step 5: Take a Screenshot
1. Reproduce the issue
2. Take a screenshot of the console output
3. Share it with me so I can see exactly what's happening

## Possible Causes

Based on the console output, we can identify:

### Cause 1: Button Clicked Twice
**Symptom**: You see "Add Group Debug" messages twice in a row
**Solution**: Already implemented double-click prevention

### Cause 2: Items Not Cleared from itemGroups
**Symptom**: "All existing item codes" shows p1's code even though itemGroups count is 0
**Solution**: Need to investigate why items are still tracked

### Cause 3: Select2 Returning Duplicate Items
**Symptom**: "Items to add" shows p1 twice
**Solution**: Need to fix Select2 data retrieval

### Cause 4: Group Not Properly Removed
**Symptom**: "itemGroups count after removal" is not 0
**Solution**: Need to fix the filter logic

## What to Share With Me

Please provide:
1. **Console output** from the debug messages
2. **Screenshot** of the issue
3. **Exact steps** you followed
4. **Browser** you're using (Chrome, Firefox, etc.)

## Quick Test

Try this simple test:
1. Create a prescription with just ONE item (p1)
2. Save it
3. Edit the prescription
4. Click "Edit" on the group
5. **Don't change anything** - just click "Add Group" immediately
6. Check if p1 appears twice

If p1 appears twice in this test, it means the issue is with the edit/add flow itself, not with removing/adding items.

## Temporary Workaround

Until we fix the root cause:
1. After editing a group, **refresh the page**
2. Then edit the prescription again
3. This will trigger the deduplication logic and clean up any duplicates

## Files Modified

1. `static/js/updated_dash_prescription_entry.js`:
   - Added double-click prevention
   - Added debug logging
   - Added deduplication on load

2. `Sheduling/views.py`:
   - Added backend deduplication
   - Added server-side logging

## Next Steps

1. **Test with debug logging** and share the console output
2. Based on the output, I can identify the exact cause
3. Implement a targeted fix for the specific issue

The debug logging will tell us exactly what's happening at each step!
