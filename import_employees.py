import os
import django
import sys
import pandas as pd

# Setup Django environment
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'asset_management.settings')
django.setup()

from asset_app.models import Employee

def import_employees(file_path):
    print(f"Reading {file_path}...")
    try:
        df = pd.read_excel(file_path)
    except Exception as e:
        print(f"Error reading Excel file: {e}")
        return

    print(f"Found columns: {list(df.columns)}")

    df.columns = [str(c).strip().lower().replace(' ', '_') for c in df.columns]
    
    # Try to find the right columns flexibly
    id_col = next((c for c in df.columns if 'id' in c), None)
    name_col = next((c for c in df.columns if 'name' in c), None)
    dept_col = next((c for c in df.columns if 'dept' in c or 'department' in c), None)

    if not all([id_col, name_col, dept_col]):
        print(f"Error: Could not identify necessary columns. Found formatted columns: {df.columns}")
        print(f"Looking for something like ID, Name, Department. Matched: id={id_col}, name={name_col}, dept={dept_col}")
        return

    print(f"Using columns: ID={id_col}, Name={name_col}, Dept={dept_col}")
    
    count = 0
    for index, row in df.iterrows():
        # Handle empty/NaN rows
        if pd.isna(row[id_col]):
            continue
            
        emp_id = str(row[id_col]).strip()
        name = str(row[name_col]).strip() if not pd.isna(row[name_col]) else "Unknown"
        dept = str(row[dept_col]).strip() if not pd.isna(row[dept_col]) else "Unknown"

        if not emp_id or emp_id == 'nan':
            continue

        employee, created = Employee.objects.update_or_create(
            employee_id=emp_id,
            defaults={
                'name': name,
                'department': dept
            }
        )
        if created:
            count += 1
            print(f"Created: {name} ({emp_id})")
        else:
            print(f"Updated: {name} ({emp_id})")

    print(f"Successfully processed {len(df)} rows. Created {count} new employees.")

if __name__ == '__main__':
    file_path = 'asset_app/employee details.xlsx'
    if not os.path.exists(file_path):
        print(f"File not found: {file_path}")
        sys.exit(1)
    import_employees(file_path)
