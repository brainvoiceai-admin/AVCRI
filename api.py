#!/usr/bin/env python3
"""
get_employees_on_leave_and_save.py

Fetch employee(s) on approved leave for a target date from HRMS and optionally
store/upsert the records into the Django EmergencyLeave model.

Usage:
  python get_employees_on_leave_and_save.py [--settings DJANGO_SETTINGS_MODULE] [--date YYYY-MM-DD] [--no-db]

If --settings is provided it will set DJANGO_SETTINGS_MODULE and call django.setup()
so the script can import your models and write to the DB.
"""

import os
import sys
import json
import argparse
import requests
from datetime import date, datetime
from dotenv import load_dotenv

load_dotenv()

# HRMS config (from environment or .env)
HRMS_API_TOKEN = os.getenv("HRMS_API_TOKEN", "").strip()
HRMS_BASE_URL = os.getenv("HRMS_BASE_URL", "https://avcri.finite-erp.tech").rstrip("/")
HRMS_LEAVE_PATH = os.getenv("HRMS_LEAVE_PATH", "/api/resource/Leave Application")
HEADERS = {"Authorization": f"token {HRMS_API_TOKEN}"} if HRMS_API_TOKEN else {}

# Django placeholders (populated if Django is enabled)
DJANGO_AVAILABLE = False
EmergencyLeave = None
TherapistMaster = None

def try_enable_django(settings_module: str | None) -> bool:
    """Set DJANGO_SETTINGS_MODULE (if provided) and call django.setup(); import models."""
    global DJANGO_AVAILABLE, EmergencyLeave, TherapistMaster
    try:
        import django
        if settings_module:
            os.environ.setdefault("DJANGO_SETTINGS_MODULE", settings_module)
        # If DJANGO_SETTINGS_MODULE is not set, skip enabling
        if not os.environ.get("DJANGO_SETTINGS_MODULE"):
            print("DJANGO_SETTINGS_MODULE not provided and not set in environment; skipping Django setup.")
            return False
        # Try to setup Django
        django.setup()
        # Try to import models
        try:
            from masters.models import EmergencyLeave as _EL, TherapistMaster as _TM
            EmergencyLeave = _EL
            TherapistMaster = _TM
            DJANGO_AVAILABLE = True
            print("Django enabled; masters.models imported successfully.")
            return True
        except Exception as e:
            print("Django setup succeeded but could not import masters.models:", e)
            DJANGO_AVAILABLE = False
            return False
    except Exception as e:
        print("Failed to enable Django:", e)
        DJANGO_AVAILABLE = False
        return False

def enable_django_for_scheduling():
    """
    Enable Django specifically for scheduling operations.
    This function should be called from Django views.
    """
    global DJANGO_AVAILABLE, EmergencyLeave, TherapistMaster
    
    if not DJANGO_AVAILABLE:
        try:
            from masters.models import EmergencyLeave, TherapistMaster
            DJANGO_AVAILABLE = True
            return True
        except Exception as e:
            print(f"Failed to import Django models: {e}")
            return False
    return True

# --- HRMS helpers ---
def _extract_employee_code(rec: dict) -> str | None:
    if not isinstance(rec, dict):
        return None
    for k in ("employee", "employee_id", "emp", "emp_id"):
        v = rec.get(k)
        if v:
            return str(v).strip()
    emp = rec.get("employee")
    if isinstance(emp, dict):
        for sub in ("name", "id", "employee_id", "employee_code", "code"):
            if emp.get(sub):
                return str(emp.get(sub)).strip()
    for k in ("employee_name", "employee_name1", "name"):
        v = rec.get(k)
        if v:
            return str(v).strip()
    return None

def _parse_date_safe(val):
    if not val:
        return None
    if isinstance(val, date):
        return val
    if isinstance(val, str):
        try:
            return datetime.fromisoformat(val[:10]).date()
        except Exception:
            for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%Y/%m/%d"):
                try:
                    return datetime.strptime(val[:10], fmt).date()
                except Exception:
                    continue
    return None

def fetch_leaves_for_date(target_date: str, test_token: str | None = None) -> list:
    filters = [
        ["workflow_state", "=", "Approved"],
        ["from_date", "<=", target_date],
        ["to_date", ">=", target_date],
    ]
    leave_fields = [
        "name",
        "employee",
        "from_date",
        "to_date",
        "leave_type",
        "half_day",
        "half_day_date",
        "custom_forenoon",
        "custom_afternoon",
        "total_leave_days",
    ]
    params = {
        "fields": json.dumps(leave_fields),
        "filters": json.dumps(filters),
    }
    url = HRMS_BASE_URL.rstrip("/") + HRMS_LEAVE_PATH

    # allow test_token override
    token = test_token if test_token is not None else HRMS_API_TOKEN
    headers = {"Authorization": f"token {token}"} if token else {}

    try:
        resp = requests.get(url, params=params, headers=headers, timeout=20)
        resp.raise_for_status()
    except requests.exceptions.RequestException as e:
        print("HTTP request failed:", e)
        # Try to print response content if available
        if hasattr(e, "response") and e.response is not None:
            try:
                print("Response text:", e.response.text[:2000])
            except Exception:
                pass
        return []

    try:
        j = resp.json()
    except ValueError:
        print("Response not JSON.")
        return []

    data = j.get("data")
    if data is None and isinstance(j, list):
        data = j
    if not data:
        return []
    return data

# --- DB upsert helpers (only active if DJANGO_AVAILABLE True) ---
def upsert_emergency_leave_record(rec: dict):
    """
    Upsert into EmergencyLeave model. Returns (obj, created) or (None, False).
    Requires DJANGO_AVAILABLE True.
    """
    if not DJANGO_AVAILABLE:
        return None, False

    from django.db import transaction

    leave_id = rec.get("name") or rec.get("leave_id") or None
    employee_code = rec.get("employee") or rec.get("employee_code") or rec.get("employee_id")
    if isinstance(employee_code, dict):
        employee_code = employee_code.get("name") or employee_code.get("id") or employee_code.get("code")
    employee_code = str(employee_code).strip() if employee_code else ""

    from_date = _parse_date_safe(rec.get("from_date") or rec.get("from"))
    to_date = _parse_date_safe(rec.get("to_date") or rec.get("to"))
    leave_type = rec.get("leave_type")

    # Extract half-day leave details
    half_day_val = rec.get("half_day")
    total_leave_days = rec.get("total_leave_days")
    try:
        total_leave_days = float(total_leave_days) if total_leave_days is not None else 0.0
    except Exception:
        total_leave_days = 0.0

    is_half_day = bool(half_day_val in (1, "1", True) or total_leave_days == 0.5)
    half_day_date = _parse_date_safe(rec.get("half_day_date")) or (from_date if is_half_day else None)
    custom_forenoon = bool(rec.get("custom_forenoon") in (1, "1", True))
    custom_afternoon = bool(rec.get("custom_afternoon") in (1, "1", True))

    half_day_session = None
    if is_half_day:
        if custom_forenoon and not custom_afternoon:
            half_day_session = "Forenoon"
        elif custom_afternoon and not custom_forenoon:
            half_day_session = "Afternoon"
        elif custom_forenoon and custom_afternoon:
            half_day_session = "Both"
        else:
            # Default when session is unspecified on half-day leave (most common in HRMS)
            half_day_session = "Afternoon"

    if (not employee_code) or not from_date or not to_date:
        if not leave_id:
            return None, False
        defaults = {
            "employee_code": employee_code or "",
            "from_date": from_date or date.today(),
            "to_date": to_date or (from_date or date.today()),
            "leave_type": leave_type,
            "is_half_day": is_half_day,
            "half_day_date": half_day_date,
            "half_day_session": half_day_session,
            "custom_forenoon": custom_forenoon,
            "custom_afternoon": custom_afternoon,
            "raw_payload": rec,
            "status": "partial",
        }
        with transaction.atomic():
            obj, created = EmergencyLeave.objects.update_or_create(leave_id=leave_id, defaults=defaults)
            return obj, created

    therapist = TherapistMaster.objects.filter(employee_code__iexact=employee_code).first()
    defaults = {
        "employee_code": employee_code,
        "from_date": from_date,
        "to_date": to_date,
        "leave_type": leave_type,
        "is_half_day": is_half_day,
        "half_day_date": half_day_date,
        "half_day_session": half_day_session,
        "custom_forenoon": custom_forenoon,
        "custom_afternoon": custom_afternoon,
        "raw_payload": rec,
        "therapist": therapist,
        "status": "processed" if therapist else "unlinked",
    }

    with transaction.atomic():
        if leave_id:
            obj, created = EmergencyLeave.objects.update_or_create(leave_id=leave_id, defaults=defaults)
        else:
            obj, created = EmergencyLeave.objects.get_or_create(
                employee_code=employee_code,
                from_date=from_date,
                to_date=to_date,
                defaults=defaults
            )
    return obj, created

def get_employees_on_leave_and_save(target_date: str, save_to_db: bool = True, test_token: str | None = None) -> list:
    """
    Fetch leaves, optionally save/upsert, and return unique employee identifiers list.
    """
    rows = fetch_leaves_for_date(target_date, test_token=test_token)
    employees = []
    processed = []
    created = 0
    updated = 0
    skipped = 0

    for rec in rows:
        emp = _extract_employee_code(rec)
        if emp:
            employees.append(emp)
        if save_to_db:
            obj, was_created = upsert_emergency_leave_record(rec)
            if obj is None:
                skipped += 1
            else:
                processed.append((obj.pk if hasattr(obj, "pk") else None, was_created))
                if was_created:
                    created += 1
                else:
                    updated += 1

    employees = sorted(set(employees))

    if save_to_db:
        if DJANGO_AVAILABLE:
            print(f"DB upsert summary: processed={len(processed)}, created={created}, updated={updated}, skipped={skipped}")
        else:
            print("DJANGO not available/configured — skipped DB writes.")

    return employees

# --- CLI / entrypoint ---
def parse_args(argv):
    p = argparse.ArgumentParser(description="Fetch employees on leave and optionally save to EmergencyLeave model.")
    p.add_argument("--settings", type=str, help="Django settings module, e.g. AVCRI.settings")
    p.add_argument("--date", "-d", type=str, help="Target date YYYY-MM-DD (overrides TEST_DATE/.env)")
    p.add_argument("--no-db", action="store_true", help="Do not attempt DB writes even if Django is enabled")
    p.add_argument("--test-token", type=str, help="Temporarily override HRMS token for testing")
    return p.parse_args(argv[1:])

if __name__ == "__main__":
    args = parse_args(sys.argv)

    # If --settings provided, attempt to enable Django
    if args.settings:
        try_enable_django(args.settings)
    else:
        # If an env var already present, try enabling automatically
        if os.environ.get("DJANGO_SETTINGS_MODULE"):
            try_enable_django(None)

    # Determine target date: precedence CLI --date > TEST_DATE env > today
    if args.date:
        tgt = args.date.strip()
    else:
        tgt = os.getenv("TEST_DATE", "").strip() or date.today().isoformat()

    try:
        tgt_parsed = datetime.fromisoformat(tgt[:10]).date().isoformat()
    except Exception:
        print("Invalid date format, expected YYYY-MM-DD. Using today instead.")
        tgt_parsed = date.today().isoformat()

    save_flag = not args.no_db
    if save_flag and not DJANGO_AVAILABLE:
        print("DB writes requested but Django not enabled/importable — DB writes will be skipped.")
        save_flag = False

    print(f"Fetching leaves for: {tgt_parsed} (save_to_db={save_flag})")
    emp_list = get_employees_on_leave_and_save(tgt_parsed, save_to_db=save_flag, test_token=args.test_token)

    if emp_list:
        print("Employees on leave:")
        for e in emp_list:
            print(" -", e)
    else:
        print("No employee identifiers found for that date.")
