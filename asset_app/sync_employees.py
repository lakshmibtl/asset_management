import requests
from django.db import transaction
from .models import Employee
import logging

logger = logging.getLogger(__name__)

def sync_employees_from_api():
    # Correct URL without any trailing quotes
    url = "https://hrms.brihaspathi.in/api/locationtracking/employees"
    try:
        response = requests.get(url, timeout=10, verify=False)
        response.raise_for_status()
        data = response.json()
        
        if isinstance(data, dict):
            for key, val in data.items():
                if isinstance(val, list):
                    data = val
                    break
            else:
                return False, "Unrecognized JSON format: Expected a list of employees."
        
        if not isinstance(data, list):
            return False, "Unrecognized JSON format: Expected a list."
        
        created_count = 0
        updated_count = 0
        
        with transaction.atomic():
            for item in data:
                if not isinstance(item, dict):
                    continue
                
                # Convert all keys to lowercase for easier matching
                item_lower = {k.lower(): v for k, v in item.items()}
                    
                emp_id = str(item_lower.get('empid') or item_lower.get('emp_id') or item_lower.get('employee_id') or item_lower.get('id', '')).strip()
                name = str(item_lower.get('firstname') or item_lower.get('name') or item_lower.get('employee_name') or item_lower.get('full_name') or 'Unknown').strip()
                department = str(item_lower.get('department') or item_lower.get('dept') or item_lower.get('department_name') or 'Unknown').strip()
                branch = str(item_lower.get('branch') or item_lower.get('location') or '').strip()
                
                if not emp_id or emp_id == 'None':
                    continue
                    
                employee, created = Employee.objects.update_or_create(
                    employee_id=emp_id,
                    defaults={
                        'name': name,
                        'department': department,
                        'branch': branch
                    }
                )
                if created:
                    created_count += 1
                else:
                    updated_count += 1
                    
        return True, f"Successfully created {created_count} and updated {updated_count} employees from API."
    except requests.exceptions.RequestException as e:
        logger.error(f"Failed to fetch employees from API: {e}")
        return False, f"API Request failed: {e}"
    except Exception as e:
        logger.error(f"Error syncing employees: {e}")
        return False, f"An error occurred: {e}"
