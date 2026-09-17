from django.contrib.auth.models import AbstractUser
from django.db import models

class CustomUser(AbstractUser):
    ROLE_CHOICES = [
        ("superadmin", "Super Admin"),
        ("asset_admin", "Asset Admin"),
        ("asset_user", "Asset User"),
        ("manager", "Manager"),
    ]

    role = models.CharField(max_length=50, choices=ROLE_CHOICES, default="asset_user")
    department = models.CharField(max_length=100, blank=True, null=True)

    def __str__(self):
        return self.username

    @property
    def display_name(self):
        if hasattr(self, '_display_name'):
            return self._display_name
        try:
            from asset_app.models import Employee
            emp = Employee.objects.filter(employee_id__iexact=self.username).first()
            if not emp:
                emp = Employee.objects.filter(name__iexact=self.username).first()
            if emp:
                return emp.name
        except Exception:
            pass
        return self.get_full_name() or self.username

