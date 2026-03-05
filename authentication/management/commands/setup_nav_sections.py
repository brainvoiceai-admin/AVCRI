from django.core.management.base import BaseCommand
from django.db import transaction
from django.urls import reverse, NoReverseMatch
from authentication.models import NavSection, Module


# Default sections matching the current sidebar layout
DEFAULT_SECTIONS = [
    {"name": "masters",              "display_name": "Masters",               "icon": "🗃️", "order": 10},
    {"name": "patient_management",   "display_name": "Patient Management",    "icon": "👥", "order": 20},
    {"name": "therapy_prescription", "display_name": "Therapy & Prescription", "icon": "🏥", "order": 30},
    {"name": "scheduling",           "display_name": "Scheduling",            "icon": "📅", "order": 40},
    {"name": "dashboards",           "display_name": "Dashboards",            "icon": "📊", "order": 50},
    {"name": "reports",              "display_name": "Reports & Analytics",   "icon": "📈", "order": 60},
    {"name": "administration",       "display_name": "Administration",        "icon": "⚙️", "order": 70},
]

# Map existing module names → section name + optional url_path override
MODULE_SECTION_MAP = {
    # --- Masters ---
    "master_tables":                 {"section": "masters"},
    "master_management_dashboard":   {"section": "masters"},
    "therapy_master_manage":         {"section": "masters"},
    "item_master_manage":            {"section": "masters"},
    "slot_master_manage":            {"section": "masters"},
    "therapist_master_manage":       {"section": "masters"},
    "procured_manage":               {"section": "masters"},
    "oilclass_manage":               {"section": "masters"},
    "usagetype_manage":              {"section": "masters"},
    "prestime_manage":               {"section": "masters"},
    "prescope_manage":               {"section": "masters"},
    "unit_list":                     {"section": "masters"},
    "prescription_usage_manage":     {"section": "masters"},

    # --- Patient Management ---
    "patient_lookup":                {"section": "patient_management"},
    "patient_profiles":              {"section": "patient_management"},
    "patient_feedback":              {"section": "patient_management"},

    # --- Therapy & Prescription ---
    "add_therapy":                   {"section": "therapy_prescription", "url_path": "/sheduling/therapy-entry/"},
    "add_prescription":              {"section": "therapy_prescription", "url_path": "/sheduling/prescriptions/"},
    "ip_pharmacy":                   {"section": "therapy_prescription"},

    # --- Scheduling ---
    "therapy_scheduling":            {"section": "scheduling",  "url_path": "/sheduling/scheduling/"},
    "therapy_schedule":              {"section": "scheduling"},
    "prescription_scheduling":       {"section": "scheduling",  "url_path": "/sheduling/prescription-scheduling/"},
    "therapist_availability":        {"section": "scheduling",  "url_path": "/sheduling/therapist-availability/"},
    "Room availability":             {"section": "scheduling",  "url_path": "/sheduling/room-availability/"},

    # --- Dashboards ---
    "patient_dashboard":             {"section": "dashboards"},
    "prescriptions_dashboard":       {"section": "dashboards"},
    "nurse_dashboard":               {"section": "dashboards"},
    "hr_dashboard":                  {"section": "dashboards"},
    "housekeeping":                  {"section": "dashboards"},
    "therapist_dashboard":           {"section": "dashboards",  "url_path": "/sheduling/therapist/"},
    "procurement_dashboard":         {"section": "dashboards",  "url_path": "/sheduling/procurement/"},

    # --- Reports & Analytics ---
    "reports":                       {"section": "reports"},
    "audit_log":                     {"section": "reports"},
    "demand_prediction":             {"section": "reports"},

    # --- Administration ---
    "user_management":               {"section": "administration"},
}


def _resolve_url(module):
    """Try to resolve a URL for a module and store it in url_path."""
    if module.url_path:
        return
    try:
        module.url_path = reverse(module.url_name)
        return
    except NoReverseMatch:
        pass
    for prefix in ("authentication:", "sheduling:", "patient:", "predictor:", "masters:"):
        try:
            module.url_path = reverse(f"{prefix}{module.url_name}")
            return
        except NoReverseMatch:
            continue


class Command(BaseCommand):
    help = "Create default NavSections and assign existing modules to them"

    def add_arguments(self, parser):
        parser.add_argument("--force", action="store_true", help="Re-assign even if module already has a section")

    def handle(self, *args, **options):
        force = options["force"]

        with transaction.atomic():
            sections = {}
            for s in DEFAULT_SECTIONS:
                obj, created = NavSection.objects.get_or_create(
                    name=s["name"],
                    defaults={
                        "display_name": s["display_name"],
                        "icon": s["icon"],
                        "order": s["order"],
                    },
                )
                sections[s["name"]] = obj
                status = "Created" if created else "Already exists"
                self.stdout.write(f"  {status}: {obj.display_name}")

            updated = 0
            for module in Module.objects.all():
                mapping = MODULE_SECTION_MAP.get(module.name)
                if mapping:
                    changed = False
                    if force or not module.nav_section_id:
                        module.nav_section = sections[mapping["section"]]
                        changed = True
                    if "url_path" in mapping and not module.url_path:
                        module.url_path = mapping["url_path"]
                        changed = True
                    if not module.url_path:
                        _resolve_url(module)
                        if module.url_path:
                            changed = True
                    if changed:
                        module.save()
                        updated += 1
                        self.stdout.write(f"  Assigned '{module.display_name}' -> [{module.nav_section}] url_path={module.url_path or '(auto)'}")
                else:
                    if not module.url_path:
                        _resolve_url(module)
                        if module.url_path:
                            module.save()
                            self.stdout.write(f"  Resolved URL for '{module.display_name}' -> {module.url_path}")

            self.stdout.write(self.style.SUCCESS(f"\nDone. {len(sections)} sections, {updated} modules updated."))
