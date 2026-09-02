from django.urls import path
from accounts.views import superadmin_dashboard, create_admin

urlpatterns = [
    path("dashboard/", superadmin_dashboard, name="superadmin_dashboard"),
      path("create-admin/", create_admin, name="create_admin"),
]
