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
