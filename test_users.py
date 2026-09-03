import os
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "asset_management.settings")
django.setup()

from django.contrib.auth import get_user_model
User = get_user_model()

users = User.objects.all()
for u in users:
    print(f"User: {u.username}, Role: {u.role}, Pass: {u.password[:10]}")
