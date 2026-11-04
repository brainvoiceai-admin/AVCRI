"""
Resolve hospital (therapy_db) patient registration numbers for a doctor code.
Uses raw SQL so matching works when ORM column types differ from SQL Server (e.g. numeric Doctcode).
"""
from django.db import connections
from django.db.models import Q

EXTERNAL_DB_ALIAS = 'therapy_db'

# SQL Server / Django: very large __in lists can fail; chunk OR branches.
PAT_REG_IN_CHUNK_SIZE = 450


def chunked_q_pat_reg_in(reg_nos, lookup, chunk_size=PAT_REG_IN_CHUNK_SIZE):
    """
    Build Q(lookup__in=chunk0) | Q(lookup__in=chunk1) | ...
    lookup examples: 'patient__pat_reg_no', 'allocation__patient__pat_reg_no'
    """
    if not reg_nos:
        return Q(pk__in=[])
    reg_nos = list(reg_nos)
    if len(reg_nos) <= chunk_size:
        return Q(**{f'{lookup}__in': reg_nos})
    q = Q()
    for i in range(0, len(reg_nos), chunk_size):
        q |= Q(**{f'{lookup}__in': reg_nos[i : i + chunk_size]})
    return q


def doctor_code_string_variants(doctor_id):
    s = str(doctor_id).strip() if doctor_id is not None else ''
    if not s:
        return []
    variants = {s, s.strip()}
    if s.isdigit():
        n = int(s)
        variants.add(str(n))
        variants.add(str(n).zfill(3))
        variants.add(str(n).zfill(4))
        variants.add(str(n).zfill(6))
    else:
        # e.g. DOC000156 or DR1011 -> extract numeric component
        import re
        nums = re.findall(r'\d+', s)
        for num in nums:
            n = int(num)
            variants.add(str(n))
            variants.add(num)
            variants.add(str(n).zfill(3))
            variants.add(str(n).zfill(4))
            variants.add(str(n).zfill(6))
    return [x for x in variants if x]


def get_doctor_codes_for_user(user):
    """
    Get all possible doctor code variants for a given user.
    Uses doctor_profile.doctor_id, username, and matches in hospital doctor_master by name.
    """
    if not user or not user.is_authenticated:
        return []

    codes = set()
    # 1. From doctor_profile
    if hasattr(user, 'doctor_profile') and user.doctor_profile and user.doctor_profile.doctor_id:
        raw_id = user.doctor_profile.doctor_id.strip()
        codes.update(doctor_code_string_variants(raw_id))

    # 2. From username
    if getattr(user, 'username', ''):
        codes.update(doctor_code_string_variants(user.username.strip()))

    # 3. From hospital doctor_master by doctor name
    full_name = (user.get_full_name() or user.username or '').strip()
    import re
    core_name = re.sub(r'^(dr\.?|doctor)\s*', '', full_name, flags=re.IGNORECASE).strip()
    if core_name and len(core_name) >= 3:
        try:
            from MySql_Data_pull.models import doctor_master
            q = Q(Doct_Name__icontains=core_name) | Q(Doct_Code__iexact=core_name)
            for w in core_name.split():
                if len(w) >= 4:
                    q |= Q(Doct_Name__icontains=w)
            dms = doctor_master.objects.using(EXTERNAL_DB_ALIAS).filter(q)
            for dm in dms:
                if dm.Doct_Code:
                    codes.update(doctor_code_string_variants(dm.Doct_Code))
        except Exception:
            pass

    return [c for c in codes if c]


import time

_last_hosp_lookup_failure = 0

def pat_reg_nos_for_hospital_doctor(doctor_id_str):
    global _last_hosp_lookup_failure
    if time.time() - _last_hosp_lookup_failure < 30:
        return []
    variants = doctor_code_string_variants(doctor_id_str)
    if not variants:
        return []
    reg_nos = set()

    def _add_rows(rows):
        for row in rows or []:
            if row and row[0] is not None:
                v = str(row[0]).strip()
                if v:
                    reg_nos.add(v)

    try:
        from MySql_Data_pull.models import Treatment
        qs = (
            Treatment.objects.using(EXTERNAL_DB_ALIAS)
            .filter(Treat_Doc_Code__in=variants)
            .values_list('Pat_Reg_No', flat=True)
            .distinct()
        )
        for prn in qs:
            if prn is not None and str(prn).strip():
                reg_nos.add(str(prn).strip())
    except Exception:
        pass

    try:
        ph = ','.join(['%s'] * len(variants))
        sql = f"""
            SELECT DISTINCT LTRIM(RTRIM(CAST(Pat_Reg_No AS NVARCHAR(50))))
            FROM dbo.Treatment
            WHERE Treat_Doc_Code IS NOT NULL
              AND LTRIM(RTRIM(CAST(Treat_Doc_Code AS NVARCHAR(100)))) IN ({ph})
        """
        cursor = connections[EXTERNAL_DB_ALIAS].cursor()
        cursor.execute(sql, variants)
        _add_rows(cursor.fetchall())
    except Exception:
        pass

    try:
        ph = ','.join(['%s'] * len(variants))
        int_variants = [int(v) for v in variants if v.isdigit()]
        if int_variants:
            iph = ','.join(['%s'] * len(int_variants))
            sql = f"""
                SELECT DISTINCT LTRIM(RTRIM(CAST(Pat_Reg_No AS NVARCHAR(50))))
                FROM dbo.Registration
                WHERE Doctcode IS NOT NULL
                  AND (
                        LTRIM(RTRIM(CAST(Doctcode AS NVARCHAR(100)))) IN ({ph})
                     OR Doctcode IN ({iph})
                  )
            """
            cursor = connections[EXTERNAL_DB_ALIAS].cursor()
            cursor.execute(sql, list(variants) + int_variants)
        else:
            sql = f"""
                SELECT DISTINCT LTRIM(RTRIM(CAST(Pat_Reg_No AS NVARCHAR(50))))
                FROM dbo.Registration
                WHERE Doctcode IS NOT NULL
                  AND LTRIM(RTRIM(CAST(Doctcode AS NVARCHAR(100)))) IN ({ph})
            """
            cursor = connections[EXTERNAL_DB_ALIAS].cursor()
            cursor.execute(sql, variants)
        _add_rows(cursor.fetchall())
    except Exception:
        _last_hosp_lookup_failure = time.time()

    return sorted(reg_nos, key=lambda x: (len(x), x))


def sample_treatment_doctor_codes(limit=30, sample_regs=5):
    """
    Top doctor codes by distinct patient count in Treatment, with sample Pat_Reg_No.
    Returns list of dicts: treat_doc_code, patient_count, sample_pat_reg_nos (list).
    """
    cursor = connections[EXTERNAL_DB_ALIAS].cursor()
    sql = f"""
        SELECT TOP ({int(limit)})
            LTRIM(RTRIM(CAST(Treat_Doc_Code AS NVARCHAR(100)))) AS doc_code,
            COUNT(DISTINCT Pat_Reg_No) AS prn_cnt
        FROM dbo.Treatment
        WHERE Treat_Doc_Code IS NOT NULL
          AND LTRIM(RTRIM(CAST(Treat_Doc_Code AS NVARCHAR(100)))) <> ''
          AND LTRIM(RTRIM(CAST(Treat_Doc_Code AS NVARCHAR(100)))) <> '0'
        GROUP BY LTRIM(RTRIM(CAST(Treat_Doc_Code AS NVARCHAR(100))))
        ORDER BY COUNT(DISTINCT Pat_Reg_No) DESC
    """
    cursor.execute(sql)
    rows = cursor.fetchall()
    out = []
    for doc_code, prn_cnt in rows:
        dc = (doc_code or '').strip()
        if not dc:
            continue
        samples = []
        try:
            n = max(1, min(int(sample_regs), 50))
            cursor.execute(
                f"""
                SELECT DISTINCT TOP ({n}) LTRIM(RTRIM(CAST(Pat_Reg_No AS NVARCHAR(50))))
                FROM dbo.Treatment
                WHERE LTRIM(RTRIM(CAST(Treat_Doc_Code AS NVARCHAR(100)))) = %s
                """,
                [dc],
            )
            samples = [r[0] for r in cursor.fetchall() if r and r[0]]
        except Exception:
            samples = []
        out.append({
            'treat_doc_code': dc,
            'patient_count': int(prn_cnt or 0),
            'sample_pat_reg_nos': samples,
        })
    return out


def sample_registration_doctcodes(limit=25, sample_regs=5):
    """Top Registration.Doctcode values by row count with sample Pat_Reg_No."""
    cursor = connections[EXTERNAL_DB_ALIAS].cursor()
    sql = f"""
        SELECT TOP ({int(limit)})
            LTRIM(RTRIM(CAST(Doctcode AS NVARCHAR(100)))) AS dc,
            COUNT(*) AS cnt
        FROM dbo.Registration
        WHERE Doctcode IS NOT NULL AND Doctcode <> 0
        GROUP BY LTRIM(RTRIM(CAST(Doctcode AS NVARCHAR(100))))
        ORDER BY COUNT(*) DESC
    """
    cursor.execute(sql)
    rows = cursor.fetchall()
    out = []
    for dc_raw, cnt in rows:
        dc = (dc_raw or '').strip()
        if not dc:
            continue
        samples = []
        try:
            n = max(1, min(int(sample_regs), 50))
            cursor.execute(
                f"""
                SELECT DISTINCT TOP ({n}) LTRIM(RTRIM(CAST(Pat_Reg_No AS NVARCHAR(50))))
                FROM dbo.Registration
                WHERE LTRIM(RTRIM(CAST(Doctcode AS NVARCHAR(100)))) = %s
                """,
                [dc],
            )
            samples = [r[0] for r in cursor.fetchall() if r and r[0]]
        except Exception:
            samples = []
        out.append({
            'doctcode': dc,
            'row_count': int(cnt or 0),
            'sample_pat_reg_nos': samples,
        })
    return out
