"""
One-shot command to create all NavSections, Modules, Roles and their
module assignments.  Run after a fresh migration on a new machine:

    python manage.py migrate
    python manage.py seed_nav_and_modules
"""

from django.core.management.base import BaseCommand
from django.db import transaction
from authentication.models import NavSection, Module, Role


# ──────────────────────────────────────────────────────
#  1.  NAV SECTIONS  (sidebar headings)
# ──────────────────────────────────────────────────────
SECTIONS = [
    {"name": "therapy_prescription", "display_name": "Therapy & Prescription", "icon": "\U0001f3e5", "order": 0},
    {"name": "scheduling",           "display_name": "Scheduling",             "icon": "\U0001f4c5", "order": 1},
    {"name": "masters",              "display_name": "Masters",                "icon": "\U0001f5c3\ufe0f", "order": 10},
    {"name": "patient_management",   "display_name": "Patient Management",     "icon": "\U0001f465", "order": 20},
    {"name": "dashboards",           "display_name": "Dashboards",             "icon": "\U0001f4ca", "order": 50},
    {"name": "reports",              "display_name": "Reports & Analytics",    "icon": "\U0001f4c8", "order": 60},
    {"name": "administration",       "display_name": "Administration",         "icon": "\u2699\ufe0f", "order": 70},
]

# ──────────────────────────────────────────────────────
#  2.  MODULES  (each row maps to a nav link)
#      section = name of the NavSection from above
# ──────────────────────────────────────────────────────
MODULES = [
    # --- Therapy & Prescription ---
    {"name": "add_therapy",        "display_name": "Add Therapy",        "url_path": "/sheduling/therapy-entry/",        "url_name": "patient_therapy",            "icon": "\U0001f3e5", "order": 2,   "section": "therapy_prescription"},
    {"name": "doctor_patients_therapy", "display_name": "My patients — therapy sessions", "url_path": "/sheduling/doctor-patients-therapy/", "url_name": "doctor_patients_therapy_dashboard", "icon": "\U0001f465", "order": 4,   "section": "therapy_prescription"},
    {"name": "add_prescription",   "display_name": "Add Prescription",   "url_path": "/sheduling/prescriptions/",        "url_name": "prescription_entry_page",    "icon": "\U0001f3e5", "order": 3,   "section": "therapy_prescription"},
    {"name": "ip_pharmacy",        "display_name": "In-Patient Pharmacy","url_path": "/authentication/ip_pharmacy/dashboard/", "url_name": "ip_pharmacy",           "icon": "\U0001f48a", "order": 11,  "section": "therapy_prescription"},

    # --- Scheduling ---
    {"name": "Room availability",               "display_name": "Treatment room availability", "url_path": "/sheduling/room-availability/",          "url_name": "room_availability_dashboard",     "icon": "\U0001f4cb", "order": 0,  "section": "scheduling"},
    {"name": "therapy_schedule",                 "display_name": "My Therapy Schedule",         "url_path": "/authentication/therapist/dashboard/",   "url_name": "therapistdash",                   "icon": "\U0001f5d3\ufe0f", "order": 6,  "section": "scheduling"},
    {"name": "therapy_scheduling",               "display_name": "Therapy Scheduling",          "url_path": "/sheduling/scheduling/",                 "url_name": "scheduling_dashboard",            "icon": "\U0001f4c5", "order": 10, "section": "scheduling"},
    {"name": "therapist_availability",           "display_name": "Therapist Availability",      "url_path": "/sheduling/therapist-availability/",     "url_name": "therapist_availability_dashboard","icon": "\U0001f465", "order": 12, "section": "scheduling"},
    {"name": "therapist_difficulty_dashboard",   "display_name": "Therapist Distribution",      "url_path": "/sheduling/therapist-difficulty/",       "url_name": "therapist_difficulty_dashboard",  "icon": "\U0001f4ca", "order": 45, "section": "scheduling"},
    {"name": "therapy_bulk_excel",               "display_name": "Therapy Bulk Excel",          "url_path": "/sheduling/therapy-bulk-excel/",         "url_name": "therapy_bulk_excel",              "icon": "\U0001f4e5", "order": 46, "section": "scheduling"},
    {"name": "prescription_scheduling",          "display_name": "Prescription Scheduling",     "url_path": "/sheduling/prescription-scheduling/",    "url_name": "prescription_scheduling_dashboard","icon": "\U0001f4cb", "order": 50, "section": "scheduling"},

    # --- Masters ---
    {"name": "prescription_usage_manage",   "display_name": "Prescription Usage Master", "url_path": "/Masters/prescription-usages/",  "url_name": "prescriptionusage_manage",    "icon": "\U0001f48a", "order": 55,  "section": "masters"},
    {"name": "master_management_dashboard", "display_name": "Master Management",         "url_path": "/Masters/dashboard/",            "url_name": "master_management_dashboard", "icon": "\U0001f5c3\ufe0f", "order": 100, "section": "masters"},
    {"name": "therapy_master_manage",       "display_name": "Therapy Master",             "url_path": "/Masters/therapy/",              "url_name": "therapy_master_manage",       "icon": "\U0001f3e5", "order": 101, "section": "masters"},
    {"name": "item_master_manage",          "display_name": "Item Master",                "url_path": "/Masters/items/",                "url_name": "item_master_manage",          "icon": "\U0001f4e6", "order": 102, "section": "masters"},
    {"name": "slot_master_manage",          "display_name": "Slot Master",                "url_path": "/Masters/slots/",                "url_name": "slot_master_manage",          "icon": "\u23f0",     "order": 103, "section": "masters"},
    {"name": "shift_master_manage",        "display_name": "Shift Master",              "url_path": "/Masters/shifts/",              "url_name": "shift_master_manage",      "icon": "\u23f1\ufe0f", "order": 104, "section": "masters"},
    {"name": "therapist_master_manage",     "display_name": "Therapist Master",           "url_path": "/Masters/therapists/",           "url_name": "therapist_master_manage",     "icon": "\U0001f468\u200d\u2695\ufe0f", "order": 104, "section": "masters"},
    {"name": "procured_manage",             "display_name": "Procurement Sources",        "url_path": "/Masters/procured",              "url_name": "procured_manage",             "icon": "\U0001f4cb", "order": 105, "section": "masters"},
    {"name": "oilclass_manage",             "display_name": "Oil Classes",                "url_path": "/Masters/oils/",                 "url_name": "oilclass_manage",             "icon": "\U0001f6e2\ufe0f", "order": 106, "section": "masters"},
    {"name": "usagetype_manage",            "display_name": "Usage Types",                "url_path": "/Masters/usages/",               "url_name": "usagetype_manage",            "icon": "\U0001f4ca", "order": 107, "section": "masters"},
    {"name": "prestime_manage",             "display_name": "Prescription Times",         "url_path": "/Masters/times/",                "url_name": "prestime_manage",             "icon": "\u23f1\ufe0f", "order": 108, "section": "masters"},
    {"name": "prescope_manage",             "display_name": "Prescription Scopes",        "url_path": "/Masters/prescopes/",            "url_name": "prescope_manage",             "icon": "\U0001f4dd", "order": 109, "section": "masters"},
    {"name": "unit_list",                   "display_name": "Unit Numbers",               "url_path": "/Masters/units/",                "url_name": "unit_list",                   "icon": "\U0001f4cf", "order": 110, "section": "masters"},
    {"name": "therapy_group_manage",        "display_name": "Therapy Group Master",       "url_path": "/Masters/therapy-groups/",       "url_name": "therapy_group_manage",        "icon": "\U0001f5c2\ufe0f", "order": 111, "section": "masters"},
    {"name": "item_group_manage",           "display_name": "Item Group Master",          "url_path": "/Masters/item-groups/",          "url_name": "item_group_manage",           "icon": "\U0001f5c2\ufe0f", "order": 112, "section": "masters"},
    {"name": "therapistgrade_manage",       "display_name": "Therapist Grades",           "url_path": "/Masters/therapist-grades/",     "url_name": "therapistgrade_manage",       "icon": "\U0001f393", "order": 113, "section": "masters"},
    {"name": "nursetreatment_manage",       "display_name": "Nurse Treatment Master",     "url_path": "/Masters/nurse-treatments/",     "url_name": "nursetreatment_manage",       "icon": "\U0001f469\u200d\u2695\ufe0f", "order": 114, "section": "masters"},
    {"name": "ingredient_master_manage",    "display_name": "Ingredient Master",          "url_path": "/Masters/ingredients/",          "url_name": "ingredient_master_manage",    "icon": "\U0001f9ea", "order": 115, "section": "masters"},
    {"name": "treatment_room_master_manage","display_name": "Treatment Room Master",      "url_path": "/Masters/treatment-rooms/",      "url_name": "treatment_room_master_manage","icon": "\U0001f6aa", "order": 116, "section": "masters"},
    {"name": "nursemaster_manage",          "display_name": "Nurse Master",               "url_path": "/Masters/nurses/",               "url_name": "nursemaster_manage",          "icon": "\U0001f468\u200d\u2695\ufe0f", "order": 117, "section": "masters"},
    {"name": "roomname_manage",            "display_name": "Room Name Master",            "url_path": "/Masters/room-names/",           "url_name": "roomname_manage",             "icon": "\U0001f6aa", "order": 118, "section": "masters"},
    {"name": "floor_manage",               "display_name": "Floor Master",                "url_path": "/Masters/floors/",               "url_name": "floor_manage",                "icon": "\U0001f3e2", "order": 119, "section": "masters"},
    {"name": "master_tables",              "display_name": "Master Tables",               "url_path": "/Masters/procured",              "url_name": "procured_manage",             "icon": "\U0001f4cb", "order": 18,  "section": "masters"},

    # --- Patient Management ---
    {"name": "patient_lookup",    "display_name": "Patient Lookup",    "url_path": "",                                              "url_name": "patient:patient_lookup",    "icon": "\U0001f50d", "order": 1,  "section": "patient_management"},
    {"name": "patient_profiles",  "display_name": "Patient Profiles",  "url_path": "/authentication/patient_profile/dashboard/",    "url_name": "patient_profile",           "icon": "\U0001f464", "order": 7,  "section": "patient_management"},
    {"name": "patient_feedback",  "display_name": "Patient Feedback",  "url_path": "/authentication/Patient_feedback_review/dashboard/", "url_name": "Patient_feedback_review", "icon": "\U0001f4ac", "order": 10, "section": "patient_management"},

    # --- Dashboards ---
    {"name": "prescriptions_dashboard", "display_name": "Prescriptions Dashboard", "url_path": "/authentication/prescription_dash/dashboard/",     "url_name": "prescription_dash",  "icon": "\U0001f4cb", "order": 8,  "section": "dashboards"},
    {"name": "patient_dashboard",       "display_name": "Patient Dashboard",       "url_path": "/authentication/Patient_dashboard/dashboard/",     "url_name": "patientdash",        "icon": "\U0001f9d1\u200d\u2695\ufe0f", "order": 9,  "section": "dashboards"},
    {"name": "therapist_dashboard",     "display_name": "Therapist Dashboard",     "url_path": "/sheduling/therapist/",                            "url_name": "therapist_dashboard","icon": "\U0001f9d1\u200d\u2695\ufe0f", "order": 11, "section": "dashboards"},
    {"name": "nurse_dashboard",         "display_name": "Nurse Dashboard",         "url_path": "/authentication/nurse_dash/dashboard/",            "url_name": "nurse_dash",         "icon": "\U0001fa7a", "order": 12, "section": "dashboards"},
    {"name": "hr_dashboard",            "display_name": "HR Dashboard",            "url_path": "/authentication/gmhr/dashboard/",                  "url_name": "gmdash",             "icon": "\U0001f465", "order": 13, "section": "dashboards"},
    {"name": "housekeeping",            "display_name": "Housekeeping",            "url_path": "/authentication/housekeepingdash/dashboard/",      "url_name": "housekeepingdash",   "icon": "\U0001f9f9", "order": 14, "section": "dashboards"},
    {"name": "procurement_dashboard",   "display_name": "Procurement Dashboard",   "url_path": "/sheduling/procurement/",                         "url_name": "procurement_dashboard", "icon": "\U0001f4e6", "order": 15, "section": "dashboards"},

    # --- Reports & Analytics ---
    {"name": "reports",           "display_name": "Reports & Analytics", "url_path": "/authentication/Therapy_Report/dashboard/",       "url_name": "Therapy_Report",                "icon": "\U0001f4ca", "order": 4,  "section": "reports"},
    {"name": "demand_prediction", "display_name": "Demand Prediction",   "url_path": "/predictor/dashboard/",                          "url_name": "predictor:prediction_dashboard","icon": "\U0001f4c8", "order": 16, "section": "reports"},
    {"name": "audit_log",        "display_name": "Audit Log",           "url_path": "/authentication/Audit_Log/dashboard/",            "url_name": "Audit_Log",                     "icon": "\U0001f4d1", "order": 17, "section": "reports"},
    {"name": "Therapy_Audit_Log","display_name": "Therapy Audit Log",   "url_path": "/authentication/Therapy_Audit_Log/dashboard/",    "url_name": "Therapy_Audit_Log",             "icon": "\U0001f3e5", "order": 62, "section": "reports"},

    # --- Administration ---
    {"name": "user_management",  "display_name": "User Management",     "url_path": "/authentication/Manage_user/dashboard/",          "url_name": "Manage_user",                   "icon": "\U0001f465", "order": 15, "section": "administration"},
]

# ──────────────────────────────────────────────────────
#  3.  ROLES  and which module *names* each role gets
# ──────────────────────────────────────────────────────
ROLES = [
    {
        "name": "super_admin",
        "display_name": "Super Admin (IT Department)",
        "modules": [
            "Room availability", "add_therapy", "add_prescription",
            "therapy_schedule", "patient_profiles", "patient_dashboard",
            "therapy_scheduling", "therapist_dashboard", "nurse_dashboard",
            "therapist_availability", "hr_dashboard", "housekeeping",
            "procurement_dashboard", "user_management", "demand_prediction",
            "audit_log", "therapist_difficulty_dashboard", "therapy_bulk_excel",
            "prescription_scheduling", "Therapy_Audit_Log",
            "master_management_dashboard", "therapy_master_manage",
            "item_master_manage", "slot_master_manage", "shift_master_manage", "therapist_master_manage",
            "procured_manage", "oilclass_manage", "usagetype_manage",
            "prestime_manage", "prescope_manage", "unit_list",
            "therapy_group_manage", "item_group_manage", "therapistgrade_manage",
            "nursetreatment_manage", "ingredient_master_manage",
            "treatment_room_master_manage", "nursemaster_manage",
            "prescription_usage_manage", "roomname_manage", "floor_manage",
        ],
    },
    {
        "name": "doctor",
        "display_name": "Doctor",
        "modules": [
            "Room availability", "add_therapy", "add_prescription",
            "doctor_patients_therapy",
            "therapy_master_manage", "item_master_manage",
            "therapist_master_manage", "oilclass_manage",
        ],
    },
    {
        "name": "scheduling_staff",
        "display_name": "Scheduling Staff",
        "modules": [
            "add_therapy", "add_prescription",
            "prescription_scheduling", "therapy_master_manage", "shift_master_manage",
        ],
    },
    {
        "name": "therapist",
        "display_name": "Therapist",
        "modules": [
            "therapy_schedule", "therapist_dashboard", "therapist_availability",
        ],
    },
    {
        "name": "nurse",
        "display_name": "Nurse",
        "modules": [
            "therapy_schedule", "patient_dashboard", "therapist_dashboard",
            "nurse_dashboard", "therapist_availability", "procurement_dashboard",
        ],
    },
    {
        "name": "admin",
        "display_name": "Admin (Administrative GM / Management)",
        "modules": [
            "reports", "patient_profiles", "patient_dashboard",
            "prescription_scheduling",
        ],
    },
    {
        "name": "ip_pharmacy_staff",
        "display_name": "IP Pharmacy Staff",
        "modules": ["prescription_scheduling"],
    },
    {
        "name": "hr",
        "display_name": "HR",
        "modules": ["reports", "hr_dashboard"],
    },
    {
        "name": "housekeeping_staff",
        "display_name": "Housekeeping Staff",
        "modules": ["housekeeping"],
    },
    {
        "name": "patient",
        "display_name": "Patient",
        "modules": ["patient_dashboard"],
    },
    {
        "name": "finance_staff",
        "display_name": "Finance Staff",
        "modules": ["reports"],
    },
    {
        "name": "imu_staff",
        "display_name": "IMU Staff (Instant Medical Unit)",
        "modules": ["therapy_schedule"],
    },
]


class Command(BaseCommand):
    help = (
        "Seed NavSections, Modules, and Role-module assignments. "
        "Safe to run multiple times — uses get_or_create everywhere."
    )

    def handle(self, *args, **options):
        with transaction.atomic():
            # ── Step 1: NavSections ──
            section_map = {}
            for s in SECTIONS:
                obj, created = NavSection.objects.get_or_create(
                    name=s["name"],
                    defaults={
                        "display_name": s["display_name"],
                        "icon": s["icon"],
                        "order": s["order"],
                    },
                )
                section_map[s["name"]] = obj
                tag = "Created" if created else "Exists "
                self.stdout.write(f"  [{tag}] Section: {obj.display_name}")

            # ── Step 2: Modules ──
            module_map = {}
            for m in MODULES:
                obj, created = Module.objects.get_or_create(
                    name=m["name"],
                    defaults={
                        "display_name": m["display_name"],
                        "url_path": m["url_path"],
                        "url_name": m["url_name"],
                        "icon": m["icon"],
                        "order": m["order"],
                        "nav_section": section_map[m["section"]],
                        "is_active": True,
                    },
                )
                module_map[m["name"]] = obj
                if created:
                    self.stdout.write(f"  [Created] Module: {obj.display_name} -> {m['section']}")
                else:
                    # Update nav_section if it was missing
                    if not obj.nav_section_id:
                        obj.nav_section = section_map[m["section"]]
                        obj.save(update_fields=["nav_section"])
                        self.stdout.write(f"  [Updated] Module: {obj.display_name} -> {m['section']}")
                    # Update url_path if it was empty
                    if not obj.url_path and m["url_path"]:
                        obj.url_path = m["url_path"]
                        obj.save(update_fields=["url_path"])

            # ── Step 3: Roles + module assignments ──
            for r in ROLES:
                role_obj, created = Role.objects.get_or_create(
                    name=r["name"],
                    defaults={
                        "display_name": r["display_name"],
                        "is_active": True,
                    },
                )
                tag = "Created" if created else "Exists "
                self.stdout.write(f"  [{tag}] Role: {role_obj.display_name}")

                # Gather module objects for this role
                mod_objs = []
                for mod_name in r["modules"]:
                    mod = module_map.get(mod_name)
                    if not mod:
                        try:
                            mod = Module.objects.get(name=mod_name)
                        except Module.DoesNotExist:
                            self.stdout.write(
                                self.style.WARNING(f"    Module '{mod_name}' not found, skipping")
                            )
                            continue
                    mod_objs.append(mod)

                # Add modules (doesn't remove existing ones, only adds missing)
                existing_ids = set(role_obj.modules.values_list("id", flat=True))
                to_add = [m for m in mod_objs if m.id not in existing_ids]
                if to_add:
                    role_obj.modules.add(*to_add)
                    self.stdout.write(f"    + Added {len(to_add)} module(s)")

        self.stdout.write(self.style.SUCCESS(
            f"\nDone! {len(SECTIONS)} sections, {len(MODULES)} modules, {len(ROLES)} roles seeded."
        ))
