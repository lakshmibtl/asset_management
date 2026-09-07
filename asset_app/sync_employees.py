import requests
from django.db import transaction
from .models import Employee
import logging
import threading
from datetime import timedelta
from django.utils import timezone

logger = logging.getLogger(__name__)

_last_sync_time = None
_sync_lock = threading.Lock()

SYNC_INTERVAL = timedelta(hours=1)


def _needs_sync():
    global _last_sync_time
    if _last_sync_time is None:
        return True
    return timezone.now() - _last_sync_time > SYNC_INTERVAL


def _do_sync():
    global _last_sync_time
    url = "https://hrms.brihaspathi.in/api/locationtracking/employees"
    try:
        response = requests.get(url, timeout=30, verify=False)
        response.raise_for_status()
        data = response.json()

        if isinstance(data, dict):
            for key, val in data.items():
                if isinstance(val, list):
                    data = val
                    break
            else:
                logger.warning("HRMS API: Unrecognized JSON format")
                return

        if not isinstance(data, list):
            logger.warning("HRMS API: Expected a list")
            return

        with transaction.atomic():
            for item in data:
                if not isinstance(item, dict):
                    continue
                item_lower = {k.lower(): v for k, v in item.items()}
                emp_id = str(item_lower.get('empid') or item_lower.get('emp_id') or item_lower.get('employee_id') or item_lower.get('id', '')).strip()
                name = str(item_lower.get('firstname') or item_lower.get('name') or item_lower.get('employee_name') or item_lower.get('full_name') or 'Unknown').strip()
                department = str(item_lower.get('department') or item_lower.get('dept') or item_lower.get('department_name') or 'Unknown').strip()
                branch = str(item_lower.get('branch') or item_lower.get('location') or '').strip()

                if not emp_id or emp_id == 'None':
                    continue

                Employee.objects.update_or_create(
                    employee_id=emp_id,
                    defaults={'name': name, 'department': department, 'branch': branch}
                )

        _last_sync_time = timezone.now()
        logger.info("HRMS employee sync completed successfully")
    except Exception as e:
        logger.error(f"HRMS employee sync failed: {e}")


def sync_employees_from_api():
    if _needs_sync():
        t = threading.Thread(target=_do_sync, daemon=True)
        t.start()
    return True, "Sync started in background."


def sync_employees_immediate():
    _do_sync()
    count = Employee.objects.count()
    return count > 0, f"Sync complete. {count} employees in database."
