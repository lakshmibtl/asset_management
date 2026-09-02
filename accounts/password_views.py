from django.contrib.auth.views import PasswordResetView
from django.contrib.auth import get_user_model
from django.contrib import messages
from django.shortcuts import redirect
from django.urls import reverse_lazy

User = get_user_model()

from django.contrib.auth.views import PasswordResetView
from django.contrib.auth import get_user_model
from django.contrib import messages
from django.shortcuts import redirect
from django.urls import reverse_lazy

User = get_user_model()

class CustomPasswordResetView(PasswordResetView):
    template_name = "registration/password_reset_form.html"

    # ✅ stay on SAME page (important for popup)
    success_url = reverse_lazy("password_reset")

    def post(self, request, *args, **kwargs):
        email = request.POST.get("email", "").strip()

        # ❌ empty email
        if not email:
            messages.error(request, "Please enter email.")
            return redirect("password_reset")

        # ❌ email not found
        if not User.objects.filter(email__iexact=email).exists():
            messages.error(request, "❌ Invalid email. Email not found.")
            return redirect("password_reset")

        # ✅ email valid → send mail
        response = super().post(request, *args, **kwargs)

        # ✅ THIS triggers popup
        messages.success(
            request,
            "Password reset link sent"
        )

        return response
