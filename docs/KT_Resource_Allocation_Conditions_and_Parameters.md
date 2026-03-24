# Knowledge Transfer: Resource Allocation — Conditions & Parameters

**Audience:** Product owners, operations, clinical admin, engineering leads, support  
**Scope:** Rules, inputs, and system conditions that drive **therapy scheduling**, **therapist/room/nurse assignment**, and **prescription scheduling** in AVCRI  
**Version:** 1.0 (March 2026)  
**Client handoff (single document):** [`KT_AVCRI_Client_Handbook_Complete.md`](./KT_AVCRI_Client_Handbook_Complete.md) — merges this file + application manual; use **`.html`** with Google Drive → Open with Google Docs.  
**Related:** `COMPREHENSIVE_KT_DOCUMENTATION.md`, `RESCHEDULE_ALGORITHM_EXPLANATION.md`, `DHARA_PIZICHIL_RESCHEDULING_FIXES.md`, [`KT_AVCRI_Full_Application_Manual.md`](./KT_AVCRI_Full_Application_Manual.md) (same content as Part II of the client handbook)

---

## 1. Executive summary

The application allocates **finite resources** (therapists by grade and gender, treatment rooms by slot, nurses for specific treatment types) to **patient therapies** and coordinates **medicine prescriptions** per patient and date. Behaviour is **parameter-driven** from **master data** (therapies, slots, grades, nurse-treatment definitions) and **hard-coded business rules** (IP/OP slot sets, Vasthi 08:30, Lepam slot exclusion, etc.).

**Two parallel domains:**

| Domain | Primary artefacts | Resource focus |
|--------|-------------------|----------------|
| **Therapy scheduling** | `TherapyAllocation`, `Booking`, `BookingAssignment`, `TherapistBooking`, `RoomBooking` | Therapists, rooms, time slots |
| **Prescription scheduling** | `PrescriptionAllocation`, `PrescriptionScheduling`, dispatches | Procurement / dispatch workflow per calendar day |

---

## 2. Stakeholder lens — what each group should know

| Stakeholder | Focus |
|-------------|--------|
| **Clinical / therapy leads** | Which therapies need rooms, bathing therapists, senior tagging, nurse-only flow; slot restrictions by therapy group and category. |
| **Operations / floor** | Draft vs scheduled vs failed bookings; patient “active” definition for lists; zero-therapist therapies may be hidden from some dashboards. |
| **Master data owners** | `TherapyMaster`, `TherapyGroup`, `SlotMaster`, `NurseTreatmentMaster`, therapist grades, room catalogue — incorrect masters directly change allocation outcomes. |
| **IT / integration** | External DBs (`therapy_db`, `iptherapy_db`, `hospital_db`) for registration, treatment, discharge; failures often **fail-open** (patient treated as active) to avoid blocking care. |
| **Engineering** | Core logic in `final_allocation.py`, `reshedule.py`, `allocation_logic.py`, `Sheduling/views.py`, `Patient/views.py`, `Sheduling/nurse_allocation.py`. |

---

## 3. Core parameters (master data)

### 3.1 Therapy master (`TherapyMaster` and related)

| Parameter | Effect on allocation |
|-----------|----------------------|
| **Therapy name / code** | Lookup key; normalized matching tolerates spacing/case variants. |
| **Therapy group** (e.g. name **“Vasthi”**, case-insensitive) | Triggers **08:30-only** scheduling rule (see §4.2). |
| **Therapy code `THEB037`** (Mathra Vasthi) | **Exempt** from Vasthi 08:30-only rule. |
| **Category** (`easy` / `medium` / `hard` / `special`) | Drives **allowed slot sets** with IP/OP (see §4.1). |
| **Counts:** `no_of_super_senior_therapist`, `no_of_senior_therapist`, `no_of_junior_therapist`, `no_of_trainee_therapist`, **`total_no_of_therapist`** | Required therapist mix per session; **zero total** therapies handled differently in UI lists vs unknown therapy fallbacks. |
| **`bathing_required` = Yes** | Pool restricted to **bathing-capable** therapists; special rules for Dhara/Pizhichil senior vs bathing (see §5). |
| **`treatment_room_required` = Yes** | Room must be allocated; room free per date+slot; **unique constraint** on `(room, date, timeslot)` for bookings. |

### 3.2 Slot master (`SlotMaster`)

| Parameter | Effect |
|-----------|--------|
| **`slot_time`** (e.g. 08:30) | Canonical slot for bookings and `TherapistBooking` / `RoomBooking`. |
| **`is_active`** | Inactive slots are not used when resolving 08:30 or other fixed times. |

### 3.3 Nurse treatments (`NurseTreatmentMaster`)

| Parameter | Effect |
|-----------|--------|
| **`treatment_code` / name**, **`is_active`** | If matched, therapy is treated as **nurse treatment**: no therapist slot requirement in the same way; **nurse assignments** per booking/day (`BookingNurseAssignment`). |
| **Nurse count** (from master / allocation) | Drives how many nurses are attached; workload balancing across active nurses. |

### 3.4 Therapist master

| Parameter | Effect |
|-----------|--------|
| **Grade** (Super Senior / Senior / Junior / Trainee) | Must satisfy counts from therapy master; **trainee** requirements may be substituted with **junior** under rules in `reshedule.py`. |
| **`therapist_gender`** | Matched to **patient gender** (normalized: non-female → male preference path). |
| **`is_bathing_therapist` / bathing flag** | Required when therapy needs bathing. |
| **`employee_code`** | Used with **emergency leave** matching. |
| **Weekly leave** (`TherapistLeaveMaster` / `TherapistLeave` by weekday) | Therapist excluded for that weekday. |
| **Emergency leave** (`EmergencyLeave` date range) | Therapist excluded for overlapping dates. |

### 3.5 Rooms (`TreatmentRoom`)

| Parameter | Effect |
|-----------|--------|
| **Room number / floor / type** | Room selection and **patient staying-room** mapping (e.g. CT → TRC) in allocation logic. |
| **Booking uniqueness** | One booking per `(room, date, timeslot)` at DB level. |

---

## 4. Time-slot conditions

### 4.1 Patient type: IP vs OP

| Patient type | Default allowed slots (algorithm `get_allowed_slot_values`) |
|--------------|-------------------------------------------------------------|
| **OP** | `11:30`, `17:30` |
| **IP** | `06:30`, `08:30`, `10:00`, `14:30`, `16:00` |
| **Unspecified** | Full general list: `06:30`, `08:30`, `10:00`, `11:30`, `14:30`, `16:00`, `17:30` |

### 4.2 Therapy category interaction

| Category | Condition |
|----------|-----------|
| **`hard` or `special`** | **Removes** OP-only slots `11:30` and `17:30` from the **general** pool (stricter set). |
| **IP + `easy` or `medium`** | **Adds** `11:30` and `17:30` to IP allowed list (IP easy/medium may use OP-preferred slots). |

### 4.3 Named therapy restrictions

| Rule | Condition |
|------|-----------|
| **Lepam** | Name contains **“lepam”** (case-insensitive) → **`06:30` excluded** from allowed slots. |
| **Vasthi group** | Therapy linked to **`TherapyGroup.name`** normalised to **`vasthi`**, except code **`THEB037`** → **only `08:30`** allowed (allocation, reschedule, slot APIs, patient slot picker). |

### 4.4 Patient-facing slot availability (`compute_available_slots_for_date`)

Beyond allowed lists, each candidate slot is checked for:

- **Room:** if therapy needs room → at least one **free** `TreatmentRoom` for that date + `SlotMaster` (no `RoomBooking` with `status='BOOKED'` blocking all rooms).
- **Therapists:** exclude therapists on **weekday leave**; exclude **booked** at that slot (`TherapistBooking` `BOOKED`); if **bathing required** → filter to `is_bathing_therapist`; **grade counts** must be satisfiable from remaining pool.

**OP default candidate list** in this path: `11:30`, `17:30` (then category/Vasthi/Lepam filters apply).

---

## 5. Therapist allocation — key conditions

| Condition | Detail |
|-----------|--------|
| **Leave** | Weekly recurring leave + emergency leave (by therapist id or employee code). |
| **Already booked** | Same therapist cannot be double-booked at same date+slot (`TherapistBooking` / assignment uniqueness). |
| **Gender** | Therapist gender aligned with patient (normalization rules in `reshedule.allocate_therapists`). |
| **Senior tag therapies** | Fixed list of **Dhara / Thakradhara** variants (`is_treatment_requiring_senior_tag`) — **one** non-bathing senior tagged; bathing senior rules for multi-therapist Dhara/Pizhichil. |
| **Daily load / difficulty** | Category-aware balancing (easy/medium/hard counts per therapist day). |
| **Continuity** | `TherapistContinuityPlan` can pre-reserve therapists for date/slot/patient before final run. |
| **Unknown therapy in master** | Some code paths default to requiring **at least one** therapist to avoid “scheduled with zero therapists”; exact default can differ between `final_allocation` vs `reshedule` — treat master data as source of truth. |

---

## 6. Room allocation — key conditions

| Condition | Detail |
|-----------|--------|
| **Therapy needs room** | From master `treatment_room_required == Yes`. |
| **Free room** | No existing `RoomBooking` for same room+date+slot with `BOOKED` (and algorithm fallbacks). |
| **Patient context** | **Staying room** may map to preferred treatment room types (e.g. cottage CT → TRC). |
| **TRC exclusion** | Legacy paths may exclude `TRC*` prefixed rooms from certain fallbacks. |

---

## 7. Nurse allocation — key conditions

| Condition | Detail |
|-----------|--------|
| **Identification** | `is_nurse_treatment(therapy_code, therapy_name)` via `NurseTreatmentMaster`. |
| **Time slot** | Not slot-bound like therapists; **day-level** assignment. |
| **Nurse pool** | `NurseMaster.is_active=True`; round-robin / workload soft balancing. |
| **Uniqueness** | One row per `(nurse, booking)` for assigned status (see model constraints). |

---

## 8. Patient “active” and visibility

| Check | Source | Used for |
|-------|--------|----------|
| **IP active** | `Registration` (`therapy_db`): `pat_status == 'Y'` | `is_patient_active`, room search cross-checks, draft therapy list filtering. |
| **OP active** | `Treatment` (`iptherapy_db`): `Status == 'ON'` | Same helper; padded reg no variants tried. |
| **Room search (Treatment row)** | `Pat_DoD` null or ≥ today, `DOA` ≤ today | “In hospital” for room tab. |
| **Errors / DB down** | Helper often **fail-open → active** | Avoids blocking scheduling if SQL Server link fails. |

**Stakeholder note:** If external DB is unstable, logs may show ODBC errors; behaviour may **include** patients or **skip** checks unpredictably until connectivity is restored.

---

## 9. Booking & therapy allocation lifecycle (status vocabulary)

### 9.1 `TherapyAllocation.status`

`draft` → `allocated` → `cancelled` / `failed` (as implemented in workflows).

### 9.2 `Booking.status` (per day)

Examples used in code/comments: **`draft`**, **`scheduled`**, **`failed`**, **`cancelled`**, **`completed`**, partially cancelled variants.  
**`failure_reason`** stores machine-oriented reasons (e.g. insufficient therapists, slot issues).

### 9.3 `BookingItem.status`

`scheduled` / `cancelled` / `completed` — procurement and completion granularity.

### 9.4 Dashboard / API filters

- **Zero-therapist** non-nurse therapies may be **hidden** from **scheduled/failed** therapy lists (still may appear for **allocated/prescription** views).  
- **Draft** therapy list may **exclude inactive patients** using `is_patient_active`.

---

## 10. Prescription (medicine) scheduling — parameters

| Entity | Status / meaning |
|--------|------------------|
| **`PrescriptionAllocation`** | Header for a prescription period; `draft` / `active` / `cancelled` / `failed`; cancellation date ranges for partial OFF. |
| **`PrescriptionScheduling`** | Per **patient + calendar date**: `draft`, `scheduled`, `dispatched`, `cancelled`, `failed`, etc. |
| **Toggle OFF/ON** | Changes allocation + syncs scheduling rows by rules (not auto-cancelled from external discharge in current build — bulk discharge auto-cancel was **removed** from prescription refresh). |
| **Procurement** | `sent_to` / department routing from allocation metadata; final schedule run may flip days to `scheduled`. |

---

## 11. Hard constraints (integrity)

| Constraint | Business meaning |
|------------|-------------------|
| **Unique `(room, date, timeslot)` on `Booking`** | One concurrent booking per room per slot. |
| **Unique `(therapist, booking_date, booking_timeslot)` on `BookingAssignment`** | No double therapist assignment at same time. |
| **Nurse `(nurse, booking)` unique** | No duplicate nurse on same booking. |

---

## 12. External systems & databases

| Database (alias) | Typical content |
|------------------|-----------------|
| **`therapy_db`** | `Registration`, `Patient_Discharge`, etc. |
| **`iptherapy_db`** | `Treatment` (OP/IP therapy rows, room, DoD, status). |
| **`hospital_db`** | OP registration (`OPMaster`), etc. |
| **Django default DB** | Allocations, bookings, snapshots, masters, sessions. |

---

## 13. Operational parameters (for configuration discussions)

| Topic | Question for stakeholders |
|-------|---------------------------|
| **Slot grid** | Should general slots change (e.g. add 09:00)? Requires `SlotMaster` + code list sync in `get_allowed_slot_values` / patient UI. |
| **Vasthi rule** | Confirmed: **Therapy group name** `Vasthi` + **THEB037** exemption — any new Vasthi-like therapies must be grouped correctly in masters. |
| **Senior-tag list** | New Dhara variants require code update in `is_treatment_requiring_senior_tag`. |
| **Nurse treatments** | New nurse-only procedures must be added to `NurseTreatmentMaster`. |
| **SQLite vs production DB** | Dev `database is locked` / session errors: use proper DB for concurrent use. |

---

## 14. Traceability — main code anchors

| Topic | Primary modules |
|-------|-----------------|
| Slot rules | `reshedule.py` → `get_allowed_slot_values`, `is_group_vasthi_0830_only` |
| Patient slot API | `Patient/views.py` → `compute_available_slots_for_date` |
| Therapist assign | `reshedule.py` → `allocate_therapists`; `allocation_logic.py`; `final_allocation.py` |
| Room assign | `reshedule.py` → `allocate_treatment_room` |
| Nurse assign | `Sheduling/nurse_allocation.py` |
| Therapy create / API | `Sheduling/views.py` → `allocate_therapy`, `therapy_entry`, `get_therapy_data_api` |
| Patient active | `final_allocation.py` → `is_patient_active` |
| Room search API | `authentication/views.py` → `search_patients_by_room` |

---

## 15. Document maintenance

- When **business rules change**, update **this document** and the **master data** sections in `COMPREHENSIVE_KT_DOCUMENTATION.md` if applicable.  
- For **algorithm step-by-step** (e.g. emergency leave reassignment), keep `RESCHEDULE_ALGORITHM_EXPLANATION.md` aligned.

---

*End of KT — Conditions & Parameters for Resource Allocation*
