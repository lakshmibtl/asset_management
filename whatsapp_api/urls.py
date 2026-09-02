from django.urls import path
from .views import send_whatsapp

urlpatterns = [
    path("send-whatsapp/", send_whatsapp, name="send_whatsapp"),
]
