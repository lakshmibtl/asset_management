from django.shortcuts import render, redirect
from accounts.models import CustomUser
from django.contrib.auth.decorators import login_required


@login_required
def superadmin_dashboard(request):
    return render(request, "superadmin/dashboard.html")


@login_required
def create_admin(request):
    if request.method == "POST":
        username = request.POST["username"]
        email = request.POST["email"]
        role = request.POST["role"]            # asset_admin
        password = request.POST["password"]

        user = CustomUser.objects.create_user(
            username=username,
            
            email=email,
            role=role,
            is_staff=True
        )
        user.set_password(password)
        user.save()

        return redirect("superadmin_dashboard")

    return render(request, "superadmin/create_admin.html")
