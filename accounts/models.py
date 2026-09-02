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
