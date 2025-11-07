"""
update_therapist_gender.py

Usage:
    Put this file in your Django project root (where manage.py is).
    Set EXCEL_PATH to the path of your Excel file (with columns 'therapist_code' and 'gender'),
    then run: python update_therapist_gender.py

Notes:
 - By default this WILL update existing TherapistMaster rows only.
 - Set CREATE_MISSING = True to create minimal placeholder records for therapist_codes not found
   (the model has required fields; the script will create placeholders for therapist_name and employee_code).
 - Make a DB backup before running on production.
"""

import os
import sys
import django
import pandas as pd
from collections import defaultdict

# -------- CONFIG: change these ----------
EXCEL_PATH = "C:\\Users\\jaise\\OneDrive\\Desktop\\AVCRI\\therapists_with_gender.xlsx"  # path to your uploaded file
SHEET_NAME = 0  # sheet name or index
THERAPIST_CODE_COL = "therapist_code"
GENDER_COL = "gender"
CREATE_MISSING = False   # set True ONLY if you want the script to create placeholder TherapistMaster rows
DEFAULT_GENDER_IF_MISSING = "Male"  # used when creating placeholders
# ---------------------------------------

# Setup Django environment (assumes settings module is reachable from project root)
# If your settings module lives elsewhere, change the DJANGO_SETTINGS_MODULE accordingly.
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "AVCRI.settings")  # <-- change if your settings module path is different
# Example alternatives:
# os.environ.setdefault("DJANGO_SETTINGS_MODULE", "mysite.settings")
try:
    django.setup()
except Exception as e:
    print("Failed to set up Django. Make sure this script runs from your project root and DJANGO_SETTINGS_MODULE is correct.")
    raise

from masters.models import TherapistMaster  # adjust app name if your model lives elsewhere

# Normalization helper
def normalize_gender(raw):
    if raw is None:
        return None
    if not isinstance(raw, str):
        raw = str(raw)
    s = raw.strip().lower()
    if s in ("m", "male", "man", "male ", "masculine"):
        return "Male"
    if s in ("f", "female", "woman", "female ", "fem"):
        return "Female"
    # common localized terms
    if s in ("male.", "female."):
        return s.rstrip(".").capitalize()
    # heuristic: if looks like single letter
    if len(s) == 1:
        return "Male" if s == "m" else "Female" if s == "f" else None
    # fallback: if contains 'male' or 'female'
    if "male" in s:
        return "Male"
    if "female" in s:
        return "Female"
    return None

def main():
    # Read excel
    try:
        df = pd.read_excel(EXCEL_PATH, sheet_name=SHEET_NAME, dtype=str)
    except Exception as e:
        print(f"Error reading Excel file at {EXCEL_PATH}: {e}")
        sys.exit(1)

    required_cols = {THERAPIST_CODE_COL, GENDER_COL}
    if not required_cols.issubset(set(df.columns.str.lower())):
        # try case-insensitive column matching
        col_map = {c.lower(): c for c in df.columns}
        if not required_cols.issubset(set(col_map.keys())):
            print(f"Excel must contain columns: {', '.join(required_cols)} (case-insensitive). Found: {list(df.columns)}")
            sys.exit(1)
        # remap to canonical column names
        df = df.rename(columns={col_map[c]: c for c in col_map if col_map[c].lower() in required_cols})

    # Normalize column names to match config
    # If columns had different cases, ensure we access via the canonical lowercase names
    if THERAPIST_CODE_COL not in df.columns:
        # find the matching column ignoring case
        for c in df.columns:
            if c.lower() == THERAPIST_CODE_COL:
                df = df.rename(columns={c: THERAPIST_CODE_COL})
                break
    if GENDER_COL not in df.columns:
        for c in df.columns:
            if c.lower() == GENDER_COL:
                df = df.rename(columns={c: GENDER_COL})
                break

    # Trim whitespace
    df[THERAPIST_CODE_COL] = df[THERAPIST_CODE_COL].astype(str).str.strip()
    df[GENDER_COL] = df[GENDER_COL].astype(str).str.strip()

    report_rows = []
    stats = defaultdict(int)

    for idx, row in df.iterrows():
        code = (row.get(THERAPIST_CODE_COL) or "").strip()
        raw_gender = row.get(GENDER_COL, "")
        normalized = normalize_gender(raw_gender)

        if not code:
            stats["skipped_empty_code"] += 1
            report_rows.append({"therapist_code": "", "input_gender": raw_gender, "normalized_gender": normalized, "status": "skipped_empty_code", "note": "Empty therapist_code"})
            continue

        try:
            tm = TherapistMaster.objects.filter(therapist_code=code).first()
        except Exception as e:
            stats["lookup_error"] += 1
            report_rows.append({"therapist_code": code, "input_gender": raw_gender, "normalized_gender": normalized, "status": "lookup_error", "note": str(e)})
            continue

        if tm:
            if normalized is None:
                # if we couldn't normalize, skip and log
                stats["invalid_gender_value"] += 1
                report_rows.append({"therapist_code": code, "input_gender": raw_gender, "normalized_gender": None, "status": "invalid_gender_value", "note": "Could not normalize input gender"})
                continue

            try:
                prev = tm.therapist_gender
                tm.therapist_gender = normalized
                tm.save(update_fields=["therapist_gender", "updated_at"] if hasattr(tm, "updated_at") else ["therapist_gender"])
                stats["updated"] += 1
                report_rows.append({"therapist_code": code, "input_gender": raw_gender, "normalized_gender": normalized, "status": "updated", "note": f"was: {prev}"})
            except Exception as e:
                stats["save_error"] += 1
                report_rows.append({"therapist_code": code, "input_gender": raw_gender, "normalized_gender": normalized, "status": "save_error", "note": str(e)})
        else:
            # missing record
            stats["missing"] += 1
            note = "Not found in DB"
            if CREATE_MISSING:
                try:
                    # Create a minimal placeholder. WARNING: adjust fields as per your validations.
                    placeholder_name = row.get("therapist_name") or f"Placeholder {code}"
                    # employee_code must be unique; generate a temporary one
                    tmp_emp_code = f"AUTO-{code}"
                    new_gender = normalized if normalized else DEFAULT_GENDER_IF_MISSING
                    new_tm = TherapistMaster.objects.create(
                        therapist_code=code,
                        therapist_name=placeholder_name,
                        therapist_grade="Unknown",
                        employee_code=tmp_emp_code,
                        therapist_gender=new_gender,
                        is_active=True,
                    )
                    stats["created"] += 1
                    note = f"Created placeholder with gender {new_gender}"
                    report_rows.append({"therapist_code": code, "input_gender": raw_gender, "normalized_gender": new_gender, "status": "created", "note": note})
                except Exception as e:
                    stats["create_error"] += 1
                    report_rows.append({"therapist_code": code, "input_gender": raw_gender, "normalized_gender": normalized, "status": "create_error", "note": str(e)})
            else:
                report_rows.append({"therapist_code": code, "input_gender": raw_gender, "normalized_gender": normalized, "status": "missing", "note": note})

    # Save report
    report_df = pd.DataFrame(report_rows)
    REPORT_PATH = "gender_update_report.csv"
    report_df.to_csv(REPORT_PATH, index=False)

    # Print summary
    print("=== Gender update finished ===")
    print(f"Total rows processed: {len(df)}")
    print("Counts:")
    for k, v in stats.items():
        print(f"  {k}: {v}")
    print(f"Report saved to: {REPORT_PATH}")
    if stats.get("missing", 0) > 0 and not CREATE_MISSING:
        print("Note: Some therapist_code values were not found in DB. To create placeholder records for missing codes, set CREATE_MISSING = True in this script and re-run (careful on production).")
    print("Finished.")

if __name__ == "__main__":
    main()

