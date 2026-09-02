# accounts/views.py
from django.shortcuts import render, redirect
from django.contrib.auth import login, logout
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.views.decorators.cache import never_cache
from django.utils.http import url_has_allowed_host_and_scheme
from django.conf import settings

from accounts.models import CustomUser


# =====================================================
# 🔐 LOGIN VIEW WITH ROLE-BASED REDIRECTS
# =====================================================
@never_cache
def login_user(request):
    """
    Login view using Django's AuthenticationForm.
    - Prevents caching via @never_cache
    - Honors safe 'next' parameter when present
    - Redirects based on user.role if no next provided
    """
    next_url = request.POST.get("next") or request.GET.get("next") or ""

    if request.method == "POST":
        form = AuthenticationForm(request, data=request.POST)

        if form.is_valid():
            user = form.get_user()
            login(request, user)

            # If a safe 'next' URL is provided, redirect there
            if next_url and url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}):
                return redirect(next_url)

            # ---- ROLE BASED REDIRECT LOGIC ----
            role = getattr(user, "role", None)
            if role == "superadmin":
                return redirect("/super-admin/")

            if role == "asset_admin":
                return redirect("/asset/")

            if role == "stationery_admin":
                return redirect("/stationery/")

            if role == "asset_user":
                return redirect("/asset/user/")

            if role == "stationery_user":
                return redirect("/stationery/user/")

            return redirect("/")  # fallback

        else:
            # form invalid -> show a message and re-render
            messages.error(request, "Invalid username or password.")
    else:
        form = AuthenticationForm()

    return render(request, "registration/login.html", {"form": form, "next": next_url})


# =====================================================
# 🔐 LOGOUT VIEW
# =====================================================
@never_cache
def logout_user(request):
    """
    Fully logs out the user, destroys session, deletes session cookie,
    and redirects to the login page.
    """
    # Django logout clears authenticated user
    logout(request)

    # Ensure session data is removed server-side
    try:
        request.session.flush()
    except Exception:
        pass

    # Redirect to 'login' view name (adjust if you use namespaced name)
    # Build response first so we can remove cookies
    response = redirect("login")

    # Remove session cookie from client
    try:
        response.delete_cookie(settings.SESSION_COOKIE_NAME)
    except Exception:
        pass

    # Optionally remove CSRF cookie as well
    try:
        response.delete_cookie(getattr(settings, "CSRF_COOKIE_NAME", "csrftoken"))
    except Exception:
        pass

    messages.info(request, "You have been logged out.")
    return response


# =====================================================
# 👑 SUPER ADMIN — CREATE ADMINS
# =====================================================
@never_cache
@login_required
def create_admin(request):
    # Only superadmin allowed
    if getattr(request.user, "role", None) != "superadmin":
        messages.error(request, "You are not authorized!")
        return redirect("/login/")

    if request.method == "POST":
        username = request.POST.get("username")
        email = request.POST.get("email")
        role = request.POST.get("role")
        password = request.POST.get("password")

        # Validation — role must be admin roles
        if role not in ["asset_admin", "stationery_admin"]:
            messages.error(request, "Invalid role selected!")
            return redirect("/create-admin/")

        # Create User
        user = CustomUser.objects.create_user(
            username=username,
            email=email,
            role=role,
            is_staff=True
        )

        # Set password and save (safe even if create_user accepted password earlier)
        if password:
            user.set_password(password)
            user.save()

        messages.success(request, f"{role.replace('_', ' ').title()} created successfully!")
        return redirect("/super-admin/")

    return render(request, "superadmin/create_admin.html")
