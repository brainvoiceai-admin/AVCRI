# Windows Task Scheduler Setup for Emergency Leave Reassignment

Reschedule runs **twice per day**:

| Time    | Task              | What it does                                      |
|---------|-------------------|---------------------------------------------------|
| **5:30 AM** | Morning reschedule | Reschedules **today’s** treatments (emergency leave). |
| **8:00 PM** | Night reschedule   | Reschedules **tomorrow’s** treatments (emergency leave). |

Create **two** scheduled tasks (one for each time). Celery Beat uses the same times if you run it instead.

## Quick Setup (Recommended for Testing)

Since Celery Beat requires Redis (which may not be installed), use Windows Task Scheduler instead.

### Step 1: Create Morning Task (5:30 AM – today’s reschedule)

1. Open **Task Scheduler** (`Win + R`, type `taskschd.msc`, press Enter)

2. Click **"Create Basic Task"** (right panel)

3. **General Tab:**
   - Name: `Emergency Leave Reassignment (5:30 AM)`
   - Description: `Runs emergency leave reassignment for today at 5:30 AM`
   - Select: **"Run whether user is logged on or not"**
   - Check: **"Run with highest privileges"**

4. **Trigger Tab:**
   - Click **"New..."**
   - Begin the task: **"On a schedule"**
   - Settings: **"Daily"**
   - Start: **5:30:00 AM**
   - Recur every: **1 days**
   - Click **OK**

5. **Action Tab:**
   - Action: **"Start a program"**
   - Program/script: `C:\Users\jaise\OneDrive\Desktop\git\AVCRI\run_reschedule_morning.bat`
   - OR use Python directly:
     - Program/script: `python` (or full path: `C:\Python\python.exe`)
     - Add arguments: `manage.py reschedule_morning`
     - Start in: `C:\Users\jaise\OneDrive\Desktop\git\AVCRI`

6. **Conditions Tab:**
   - Uncheck: **"Start the task only if the computer is on AC power"** (if you want it to run on battery)
   - Check: **"Wake the computer to run this task"** (optional)

7. **Settings Tab:**
   - Check: **"Allow task to be run on demand"**
   - Check: **"Run task as soon as possible after a scheduled start is missed"**
   - If the task fails, restart every: **10 minutes** (optional)

8. Click **OK** and enter your Windows password if prompted

### Step 2: Create Night Task (8:00 PM – next day’s reschedule)

1. In Task Scheduler, click **"Create Basic Task"** again.

2. **General Tab:**
   - Name: `Emergency Leave Reassignment (8 PM)`
   - Description: `Runs emergency leave reassignment for tomorrow at 8:00 PM`
   - Select: **"Run whether user is logged on or not"**
   - Check: **"Run with highest privileges"**

3. **Trigger Tab:**
   - Begin the task: **"On a schedule"**
   - Settings: **"Daily"**
   - Start: **8:00:00 PM**
   - Recur every: **1 days**
   - Click **OK**

4. **Action Tab:**
   - Action: **"Start a program"**
   - Program/script: `C:\Users\jaise\OneDrive\Desktop\git\AVCRI\run_reschedule_night.bat`
   - OR use Python directly:
     - Program/script: `python` (or full path to `python.exe`)
     - Add arguments: `manage.py reschedule_night`
     - Start in: `C:\Users\jaise\OneDrive\Desktop\git\AVCRI`

5. **Conditions / Settings:** Same as the morning task (optional: wake computer, run on missed start, etc.).

6. Click **OK** and enter your Windows password if prompted.

### Step 3: Test the Tasks

1. Right-click the task → **"Run"**
2. Check the log file or Task Scheduler history (see below)
3. Or run manually: `python manage.py reschedule_morning` or `python manage.py reschedule_night`

---

## How to Know the Task Ran

### 1. Check the log file (easiest)

The batch file writes every run to a **date-named log file**:

- **Folder:** `C:\Users\jaise\OneDrive\Desktop\git\AVCRI\logs\`
- **Morning:** `reschedule_morning_YYYY-MM-DD.log` (after 5:30 AM); **Night:** `reschedule_night_YYYY-MM-DD.log` (after 8:00 PM)

**What to do:**
1. Open the `logs` folder in your AVCRI project.
2. Open the file for **today’s date**.
3. If the task ran, you’ll see:
   - `========== RUN STARTED: ... ==========`
   - Full algorithm output (emergency leave update, reassignment summary, etc.)
   - `========== RUN ENDED: ... ==========`

If the file for today is missing or has no new “RUN STARTED” / “RUN ENDED” lines after the scheduled time, the task did not run (or ran in a different folder).

### 2. Check Task Scheduler history

1. Open **Task Scheduler** (`Win + R` → `taskschd.msc`).
2. In the left panel, select **“Task Scheduler Library”**.
3. Click your task (e.g. “Emergency Leave Reassignment (5:30 AM) or (8 PM)”).
4. In the **“History”** tab (or **“Last Run Result”** in the middle panel):
   - **Last Run Time** – when it last ran.
   - **Last Run Result** – `0x0` means success; other codes mean failure.
   - **History** tab – list of runs (enable it via **View → Show All Task History** if needed).

### 3. Run it yourself once

- Double‑click `run_reschedule_morning.bat` or `run_reschedule_night.bat` in the project folder, or  
- In a command prompt: `cd C:\Users\jaise\OneDrive\Desktop\git\AVCRI` then `python manage.py reschedule_morning`  

Then check today’s log file again; you should see a new run block.

### Step 4: View output

- **Log files:** Morning runs → `logs\\reschedule_morning_YYYY-MM-DD.log`; night runs → `logs\reschedule_night_YYYY-MM-DD.log` (see “How to know the task ran” above).
- **Task Scheduler:** Use the task’s **History** tab and **Last Run Result** to see if it ran and whether it succeeded.

## Alternative: Fix Celery Beat (If You Want to Use It)

### Install Redis for Windows:

1. **Option 1: Use WSL (Windows Subsystem for Linux)**
   ```bash
   wsl
   sudo apt-get install redis-server
   redis-server
   ```

2. **Option 2: Use Memurai (Redis-compatible for Windows)**
   - Download: https://www.memurai.com/
   - Install and start service

3. **Option 3: Use Docker**
   ```bash
   docker run -d -p 6379:6379 redis
   ```

### Install Python Redis Package:
```bash
pip install redis
```

### Then Run Celery Beat:
```bash
celery -A AVCRI beat
```

## Manual Testing (No Scheduler Needed)

Just run the command directly:
```bash
cd C:\Users\jaise\OneDrive\Desktop\git\AVCRI
python manage.py reschedule_morning
```

Or with dry-run (no database changes):
```bash
python manage.py reschedule_morning --dry-run
```

## Expected Output

You should see:
```
================================================================================
================================================================================
🚀 EMERGENCY LEAVE REASSIGNMENT ALGORITHM - STARTING
================================================================================
================================================================================

📅 Starting morning reschedule for date: 2026-02-13
...
```

## Troubleshooting

- **Task doesn't run**: Check Task Scheduler → Task History for errors
- **Python not found**: Use full path to python.exe in Task Scheduler
- **Permission errors**: Run Task Scheduler as Administrator
- **No output visible**: Redirect output to log file (see Step 3)
