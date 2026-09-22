import re
from django import template
from asset_app.models import Employee

register = template.Library()

@register.filter
def display_name(user):
    """Returns the real employee name for a user (username matches employee_id or name),
    falling back to the username."""
    if not user:
        return ''
    
    # Check if Employee table has this user
    emp = Employee.objects.filter(employee_id__iexact=user.username).first()
    if not emp:
        emp = Employee.objects.filter(name__iexact=user.username).first()
        
    if emp:
        return emp.name
        
    return user.get_full_name() or user.username


@register.filter
def split_resolution(value):
    """Split a resolution_message string into individual history entries.
    Entries are separated by '---'.
    Returns a list of non-empty strings."""
    if not value:
        return []
    raw_parts = re.split(r'\n+\s*---\s*', str(value))
    result = []
    for i, part in enumerate(raw_parts):
        part = part.strip()
        if not part:
            continue
        if i > 0:
            part = '--- ' + part
        result.append(part)
    return result


@register.filter(name='strip')
def strip_whitespace(value):
    """Strip leading/trailing whitespace from a string."""
    if value is None:
        return ''
    return str(value).strip()
