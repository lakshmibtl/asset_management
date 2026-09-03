from django.shortcuts import render, redirect
from django.contrib.auth import login, logout
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from accounts.models import CustomUser
from django.contrib.auth.views import PasswordResetView
from django.contrib.auth import get_user_model  
from django.shortcuts import render, redirect
from django.contrib.auth import login, get_user_model
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.contrib.auth.views import PasswordResetView

from accounts.models import CustomUser
# =========================
#        LOGIN
# =========================
def login_user(request):
    if request.method == "POST":
        form = AuthenticationForm(request, data=request.POST)

        if form.is_valid():
            user = form.get_user()
            login(request, user)

            return redirect("/asset/dashboard/")

    else:
        form = AuthenticationForm()

    return render(request, "registration/login.html", {"form": form})

# =========================
#        LOGOUT
# =========================
def logout_user(request):
    logout(request)
    return redirect("/login/")


# =========================
#   SUPERADMIN DASHBOARD
# =========================
@login_required
def superadmin_dashboard(request):
    if request.user.role != "superadmin" and not request.user.is_superuser:
        return redirect("/login/")

    return render(request, "superadmin/dashboard.html")


# =========================
#       CREATE USER
# =========================
@login_required
def create_admin(request):

    if request.user.role != "superadmin" and not request.user.is_superuser:
        return redirect("/login/")

    if request.method == "POST":
        username = request.POST.get("username")
        email = request.POST.get("email")
        role = request.POST.get("role")
        password = request.POST.get("password")

        # 🚨 CHECK USERNAME
        if CustomUser.objects.filter(username=username).exists():
            messages.error(request, "Username already exists! Please choose another.")
            return redirect("/super-admin/create-admin/")

        # 🚨 CHECK EMAIL
        if email and CustomUser.objects.filter(email=email).exists():
            messages.error(request, "Email already exists! Please use another email.")
            return redirect("/super-admin/create-admin/")

        # CREATE USER
        user = CustomUser.objects.create_user(
            username=username,
            email=email,
            role=role,
            is_staff=True if "admin" in role else False
        )
        user.set_password(password)
        user.save()

        messages.success(request, f"{role.replace('_', ' ').title()} created successfully!")
        return redirect("/super-admin/dashboard/")

    return render(request, "superadmin/create_admin.html")




