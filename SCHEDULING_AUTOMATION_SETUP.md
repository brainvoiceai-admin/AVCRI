# Scheduling Automation Setup Guide

This guide explains how to set up automatic daily scheduling tasks for therapy rescheduling.

## Overview

Two automated processes run daily:

1. **Morning Reschedule** (5:30 AM):
   - Updates emergency leave data for today's date via `api.py`
   - Runs rescheduling algorithm for today's date
   - Command: `python manage.py reschedule_morning`

2. **Night Reschedule** (8:00 PM):
   - Updates emergency leave data for tomorrow's date via `api.py`
   - Runs rescheduling algorithm for tomorrow's date
   - Command: `python manage.py reschedule_night`

## Setup Options

### Option 1: Using Cron (Linux/Mac)

1. Edit the crontab:
   ```bash
   crontab -e
   ```

2. Add the following lines (adjust paths as needed):
   ```cron
   # Morning reschedule at 5:30 AM daily
   30 5 * * * cd /path/to/AVCRI && /path/to/python manage.py reschedule_morning >> /path/to/logs/reschedule_morning.log 2>&1

   # Night reschedule at 8:00 PM daily
   0 20 * * * cd /path/to/AVCRI && /path/to/python manage.py reschedule_night >> /path/to/logs/reschedule_night.log 2>&1
   ```

3. Replace placeholders:
   - `/path/to/AVCRI` - Your project root directory
   - `/path/to/python` - Path to your Python interpreter (or use `python3`)
   - `/path/to/logs/` - Directory for log files

### Option 2: Using Windows Task Scheduler

1. Open Task Scheduler (`taskschd.msc`)

2. Create a new task for Morning Reschedule:
   - **General Tab:**
     - Name: `Morning Therapy Reschedule`
     - Run whether user is logged on or not
     - Run with highest privileges
   
   - **Triggers Tab:**
     - New Trigger → Daily
     - Start time: 5:30 AM
     - Recur every: 1 days
   
   - **Actions Tab:**
     - Action: Start a program
     - Program/script: `C:\Python\python.exe` (or your Python path)
     - Add arguments: `manage.py reschedule_morning`
     - Start in: `C:\path\to\AVCRI`

3. Create a new task for Night Reschedule:
   - **General Tab:**
     - Name: `Night Therapy Reschedule`
     - Run whether user is logged on or not
     - Run with highest privileges
   
   - **Triggers Tab:**
     - New Trigger → Daily
     - Start time: 8:00 PM
     - Recur every: 1 days
   
   - **Actions Tab:**
     - Action: Start a program
     - Program/script: `C:\Python\python.exe` (or your Python path)
     - Add arguments: `manage.py reschedule_night`
     - Start in: `C:\path\to\AVCRI`

### Option 3: Using Django-Q or Celery (Recommended for Production)

If you're using Django-Q or Celery for task scheduling:

1. **For Django-Q**, add to your `settings.py`:
   ```python
   Q_CLUSTER = {
       'name': 'reschedule_tasks',
       'workers': 1,
       'timeout': 3600,
       'retry': 300,
       'cached': True,
       'orm': 'default',
   }
   ```

2. Create scheduled tasks in Django admin or via management command.

## Manual Testing

Before setting up automatic scheduling, test the commands manually:

```bash
# Test morning reschedule (dry run - no database changes)
python manage.py reschedule_morning --dry-run

# Test night reschedule (dry run - no database changes)
python manage.py reschedule_night --dry-run

# Test with specific date
python manage.py reschedule_morning --date 2024-12-25
python manage.py reschedule_night --date 2024-12-26

# Run actual reschedule (makes database changes)
python manage.py reschedule_morning
python manage.py reschedule_night
```

### Expected Output

You should see:
1. **Step 1**: Emergency leave update status
2. **Step 2**: Rescheduling algorithm results with:
   - Number of bookings checked
   - Number of bookings reassigned
   - Number of bookings cancelled
   - Number of failed operations
   - Example reassignments and cancellations

## Logging

The commands output results to stdout. For cron jobs, redirect output to log files:

```bash
# Morning
python manage.py reschedule_morning >> logs/reschedule_morning_$(date +\%Y-\%m-\%d).log 2>&1

# Night
python manage.py reschedule_night >> logs/reschedule_night_$(date +\%Y-\%m-\%d).log 2>&1
```

## Troubleshooting

### Common Issues

1. **Django not found**: Ensure you're running from the project root and Django is installed
2. **Module import errors**: Check that `resheduleMorningandNight.py` is in the project root
3. **API errors**: Verify HRMS API credentials are set in `.env` file
4. **Permission errors**: Ensure the scheduled task/cron has necessary permissions

### Verification

Check if tasks are running:
- Monitor log files
- Check Django admin for any error notifications
- Verify therapist bookings are being reassigned correctly

## Environment Variables Required

Ensure these are set in your `.env` file:
```
HRMS_API_TOKEN=your_token_here
HRMS_BASE_URL=https://avcri.finite-erp.tech
DJANGO_SETTINGS_MODULE=AVCRI.settings
```

## Notes

- The morning reschedule processes **today's** date
- The night reschedule processes **tomorrow's** date (when run at 8 PM today)
- Both commands update emergency leave data before running the rescheduling algorithm
- Use `--dry-run` flag to test without making database changes

