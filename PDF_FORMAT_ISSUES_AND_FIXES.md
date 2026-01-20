# PRESCRIPTION PDF - CORRECT FORMAT EXAMPLE

## What You Should See

### PAGE 1 - HEADER (Should appear on FIRST page only)

```
THE ARYA VAIDA CHIKITSALAYAM AND RESEARCH INSTITUTE
PRESCRIPTIONS AS ON 20/01/2026        PHYSICIAN / PHARMACY / RESEARCH
================================================================================

TIME LEGEND:
M  (5.30–5.45)  – Morning            ABF (8.00–8.30) – After Breakfast    BD (6.30–7.00)  – Before Dinner
E  (5.30–6.00)  – Evening            BL (11.00–12.30) – Before Lunch      AD (8.00–8.30)  – After Dinner
                                     AL (12.30–1.30) – After Lunch        BT (8.30–9.00)  – Bed Time
                                                                          NT – A Pinch Now And Then
================================================================================

SUITE – GROUND FLOOR

Room: DS-3              Name: DASARI JAGGARAJU
Gender: Male            Age: 59                Doctor: Vasanthi

Time / Usage          Items                                                    Oil Class    Ingredients
M/E                   Gandharvasthadi Kashayam + Mahamanjistadi kashayam + Sahacharadi Kashayam — [15 ml]    —    —
AB, 8.00 PM           Maharajaprasarini Thailam Caps + Cardostab + Kanchanaragulgulu Vatika — [1,1,1 (Nos)]  —    —
10:00:00, 2.00 PM     Brahmidrakshadi Kashayam + Kallyanakam Kashayam + Dasamoolajeerakadi Kashayam Spl — [15 ml]    —    —
7.00 PM               Sukumara Lehyam + Thrivril Lehyam — [2 (tps)]          —    —
—                     Spl Paneeyam + Abhayaristam — [200 (ml)]                —    —
BT                    Gulguluthikthakam Gritham + Mahakalyanaka Gritham — [1 (tps)]    —    —
```

## ISSUES IN YOUR CURRENT PDF

### ❌ Issue 1: Multiple Dosages Per Row
**Current (WRONG):**
```
Gandharvasthadi Kashayam + Mahamanjistadi kashayam + Sahacharadi Kashayam — [15 ml]
+ Sahacharadi 21 capsules + Maharajaprasarini Thailam Caps + Yashtimadhu Tab — [1,1,1 (Nos)]
```

**Should Be (CORRECT):**
```
Gandharvasthadi Kashayam + Mahamanjistadi kashayam + Sahacharadi Kashayam + Sahacharadi 21 capsules + Maharajaprasarini Thailam Caps + Yashtimadhu Tab — [15 ml]
```

**Rule:** ALL medicines in ONE allocation group should be on ONE row with ONE dosage at the very end.

### ❌ Issue 2: Time Format
**Current (WRONG):**
```
AB, 8.00 PM
10:00:00, 2.00 PM
```

**Should Be (CORRECT):**
```
ABF / Internal
BL, AL / External
```

**Rule:** Use time codes (M, E, ABF, BL, AL, BD, AD, BT, NT) with usage, not clock times.

### ❌ Issue 3: Missing Therapies
Therapies should appear in a SEPARATE table AFTER prescriptions:

```
Therapy Name          Items                                    Oil Class    Time Slot
Dhanyamla Dhara (3)   Dhanyamla Oil — [50 ml]                 Class C      06:30
Virechanam            Castor Oil — [30 ml]                    —            10:00
```

## WHAT I JUST FIXED

✅ **Fixed:** Medicine grouping - Now ALL medicines in an allocation are combined with `+` and ONE dosage at the end
✅ **Kept:** Header and time legend (they were already correct)
✅ **Kept:** Therapy rendering logic (it was already correct)

## REMAINING ISSUES TO CHECK

1. **Is the header showing on your PDF?** 
   - If not, you might be looking at page 2+
   - Scroll to the top of the PDF

2. **Are therapies showing?**
   - Check the console logs as per TESTING_THERAPY_PDF_ISSUE.md
   - Therapies will only show if they exist in the data

3. **Time format**
   - This depends on what's in your database
   - If the database has "AB, 8.00 PM", that's what will print
   - The time codes should be stored as "ABF", "BL", etc. in the database

## NEXT TEST

1. Clear browser cache (Ctrl+Shift+Delete)
2. Refresh the page (Ctrl+F5)
3. Generate PDF again
4. Check if medicines are now grouped correctly with ONE dosage
5. Scroll to top to see header
6. Check console for therapy logs
