# Continuity Matrix Display Format Update

## Changes Made - 2026-02-04

### User Requirements:
1. ✅ **Patient name shown only ONCE** - use rowspan for multiple treatment rows
2. ✅ **Remove background color highlights** - use only text colors (no badges)
3. ✅ **Simple colored text format** - match the old format style

---

## Visual Changes

### Before (Badge Style):
- Patient name repeated on every row
- Therapist names in colored badges/pills with backgrounds:
  - 🟢 Green background + dark green text
  - 🔴 Red background + dark red text  
  - ⚪ Gray background + gray text

### After (Text-Only Style):
- Patient name appears **once** with rowspan
- Therapist names as simple text with colors:
  - **Green text** (`#059669`) - Continuity maintained
  - **Red bold text** (`#dc2626`) - Discontinuity (therapist changed)
  - **Gray italic text** (`#6b7280`) - Therapist on leave

---

## Implementation Details

### Rowspan Logic (Lines 675-683)
```javascript
// Calculate how many rows each patient has
const patientRowCounts = {};
data.rows.forEach(row => {
    const patientId = row.patient.id;
    patientRowCounts[patientId] = (patientRowCounts[patientId] || 0) + 1;
});

// Track which patients already have their name cell rendered
const renderedPatients = new Set();
```

### Patient Cell Rendering (Lines 690-705)
```javascript
// Only render patient cell once per patient
if (!renderedPatients.has(patientId)) {
    const tdPatient = document.createElement('td');
    tdPatient.rowSpan = patientRowCounts[patientId];  // Span multiple rows
    tdPatient.innerHTML = `
        <div style="font-weight:600; color:#1f2937; font-size:14px;">${row.patient.name}</div>
        <div style="font-size:11px; color:#6b7280; margin-top:2px;">${row.patient.reg_no}</div>
    `;
    tr.appendChild(tdPatient);
    renderedPatients.add(patientId);
}
```

### Therapist Display (Lines 719-742)
**Removed:** Badge styling with background colors  
**Added:** Simple div elements with text-only styling

```javascript
const span = document.createElement('div');

// Apply text color based on status (NO background)
if (t.status === 'green') {
    span.style.color = '#059669';      // Green text
    span.style.fontWeight = '500';     // Medium weight
} else if (t.status === 'red') {
    span.style.color = '#dc2626';      // Red text
    span.style.fontWeight = '700';     // Bold for emphasis
} else if (t.status === 'gray') {
    span.style.color = '#6b7280';      // Gray text
    span.style.fontStyle = 'italic';   // Italic style
}
```

---

## Example Output

### Patient with Multiple Treatments:

| Patient | Therapy | Slot | Feb 4 | Feb 5 | Feb 6 |
|---------|---------|------|-------|-------|-------|
| **SELLAMUTHU.P**<br><small>325012026</small> | Podikizhi(1) | 06:00 AM | Maheswari B | Maheswari B | Maheswari B |
| | Podikizhi(1) | 02:00 PM | Babu.M | Babu.M | Babu.M |
| | Abhk LP(1 T) | 09:00 AM | Balaji | Balaji | <span style="color:#dc2626;font-weight:700;">Anoop</span> |

**Note:** The patient name "SELLAMUTHU.P" appears only once and spans 3 rows.

---

## Text Color Legend

| Color | Status | Style | Meaning |
|-------|--------|-------|---------|
| 🟢 **Green** (#059669) | `status: 'green'` | Medium weight | Same therapist (continuity maintained) |
| 🔴 **Red** (#dc2626) | `status: 'red'` | **Bold** | Different therapist (continuity broken) |
| ⚪ **Gray** (#6b7280) | `status: 'gray'` | *Italic* | Reference therapist on leave |

---

## Files Modified
- `templates/dashboards/scheduling/scheduling.html` (Lines 645-761)
  - Added rowspan calculation logic
  - Added patient rendering tracking
  - Removed badge backgrounds
  - Changed to text-only colored display

---

## Benefits
1. ✅ **Cleaner UI** - No distracting background colors
2. ✅ **Better readability** - Patient names easier to scan
3. ✅ **Space efficient** - Rowspan saves vertical space
4. ✅ **Matches old format** - Consistent with user's preferred style
5. ✅ **Better visual hierarchy** - Bold red immediately catches attention for discontinuities

---

## Testing Checklist
- [ ] Patient name appears only once per patient (not repeated)
- [ ] Multiple treatments for same patient show different therapy/slot rows
- [ ] Therapist names display in correct colors:
  - Green for continuity match
  - Red (bold) for discontinuity
  - Gray (italic) for on-leave
- [ ] No background color badges
- [ ] Bathing indicator (*) still shows correctly
- [ ] Rowspan alignment looks correct
