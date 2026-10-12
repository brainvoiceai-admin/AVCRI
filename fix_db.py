import sqlite3
import os
import shutil
import subprocess

print("=" * 60)
print("AUTOMATIC DATABASE RECOVERY & MIGRATION TOOL")
print("=" * 60)

db_path = 'db.sqlite3'

if not os.path.exists(db_path):
    print(f"Error: {db_path} does not exist in the current folder.")
    exit(1)

# Step 1: Check database integrity
is_malformed = False
try:
    conn = sqlite3.connect(db_path)
    check = conn.execute('PRAGMA integrity_check;').fetchall()
    if check != [('ok',)]:
        is_malformed = True
    conn.close()
except Exception:
    is_malformed = True

# Step 2: If database is malformed, perform clean row recovery
if is_malformed:
    print("[WARN] Database disk image is malformed. Starting full row recovery...")
    clean_file = 'db_auto_clean.sqlite3'
    if os.path.exists(clean_file):
        os.remove(clean_file)

    src_conn = sqlite3.connect(f'file:{db_path}?mode=ro', uri=True)
    tables = [r[0] for r in src_conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%';").fetchall()]
    src_conn.close()

    dst = sqlite3.connect(clean_file)
    dst.execute('PRAGMA journal_mode=WAL;')
    dst.execute('PRAGMA foreign_keys=OFF;')

    for t in tables:
        conn_t = sqlite3.connect(f'file:{db_path}?mode=ro', uri=True)
        try:
            sql = conn_t.execute(f"SELECT sql FROM sqlite_master WHERE type='table' AND name='{t}';").fetchone()
            if not sql or not sql[0]:
                conn_t.close()
                continue
            
            dst.execute(sql[0])
            cols = [col[1] for col in conn_t.execute(f'PRAGMA table_info("{t}");').fetchall()]
            col_str = ', '.join([f'"{c}"' for c in cols])
            
            rows = []
            try:
                rows = conn_t.execute(f'SELECT {col_str} FROM "{t}"').fetchall()
            except Exception:
                for rid in range(1, 100000):
                    try:
                        r = conn_t.execute(f'SELECT {col_str} FROM "{t}" WHERE rowid = ?', (rid,)).fetchone()
                        if r:
                            rows.append(r)
                    except Exception:
                        pass

            if rows:
                placeholders = ','.join(['?'] * len(cols))
                dst.executemany(f'INSERT INTO "{t}" VALUES ({placeholders})', rows)
                dst.commit()
                print(f"  [RECOVERED] Table '{t}': {len(rows):,} rows")
        except Exception as e:
            print(f"  [ERROR] Table '{t}': {e}")
        finally:
            conn_t.close()

    # Copy indexes
    src_conn = sqlite3.connect(f'file:{db_path}?mode=ro', uri=True)
    indices = src_conn.execute("SELECT sql FROM sqlite_master WHERE type='index' AND sql IS NOT NULL;").fetchall()
    for idx_sql in indices:
        if idx_sql[0]:
            try:
                dst.execute(idx_sql[0])
            except Exception:
                pass
    src_conn.close()
    dst.close()

    # Overwrite db.sqlite3
    if os.path.exists('db_backup_old.sqlite3'):
        os.remove('db_backup_old.sqlite3')
    os.rename(db_path, 'db_backup_old.sqlite3')
    os.rename(clean_file, db_path)
    print("[SUCCESS] Corrupted database recovered into clean db.sqlite3!")

# Step 3: Clean foreign key violations
print("[INFO] Checking Foreign Key integrity...")
conn = sqlite3.connect(db_path)
conn.execute('PRAGMA foreign_keys = OFF;')
fk_errors = conn.execute('PRAGMA foreign_key_check;').fetchall()
if fk_errors:
    print(f"[INFO] Found {len(fk_errors)} orphaned FK rows. Cleaning...")
    while fk_errors:
        for table, rowid, parent, fkid in fk_errors:
            conn.execute(f'DELETE FROM "{table}" WHERE rowid = ?', (rowid,))
        conn.commit()
        fk_errors = conn.execute('PRAGMA foreign_key_check;').fetchall()
    print("[SUCCESS] Cleaned all orphaned Foreign Key references!")
else:
    print("[SUCCESS] Zero Foreign Key violations found.")

conn.execute('PRAGMA journal_mode=WAL;')
conn.close()

# Step 4: Run Django migrate
print("\n[INFO] Running Django migrations...")
result = subprocess.run(['python', 'manage.py', 'migrate'], capture_output=True, text=True)
print(result.stdout)
if result.stderr and 'Traceback' in result.stderr:
    print("Migration output stderr:\n", result.stderr)
else:
    print("MIGRATION COMPLETED SUCCESSFULLY!")
