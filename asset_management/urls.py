from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import path, include
from django.shortcuts import redirect
from django.contrib.auth import views as auth_views

from accounts.views import login_user, logout_user
from accounts.password_views import CustomPasswordResetView

urlpatterns = [
    path("", lambda request: redirect("login"), name="home"),
    path("admin/", admin.site.urls),
    path("login/", login_user, name="login"),
    path("logout/", logout_user, name="logout"),
    path("logout/", logout_user, name="logout_user"),
    
    # 🔑 PASSWORD RESET (BUILT-IN)
    path(
        "password-reset/",
        CustomPasswordResetView.as_view(),
        name="password_reset",
    ),
    path(
        "reset/<uidb64>/<token>/",
        auth_views.PasswordResetConfirmView.as_view(
            template_name="registration/password_reset_confirm.html"
        ),
        name="password_reset_confirm",
    ),
    path(
        "reset/done/",
        auth_views.PasswordResetCompleteView.as_view(
            template_name="registration/password_reset_complete.html"
        ),
        name="password_reset_complete",
    ),

    path("super-admin/", include("superadmin_app.urls")),
    path("asset/", include("asset_app.urls")),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
