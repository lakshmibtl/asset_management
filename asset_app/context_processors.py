from .models import ReturnRequest, Notification


def pending_return_count(request):
    if not request.user.is_authenticated:
        return {"pending_return_count": 0}
    return {
        "pending_return_count": ReturnRequest.objects.filter(status="Pending").count()
    }


def notifications_processor(request):
    if not request.user.is_authenticated:
        return {"notifications": [], "unread_notifications_count": 0}
    qs = request.user.notifications.all()
    return {
        "notifications": list(qs[:8]),
        "unread_notifications_count": qs.filter(is_read=False).count(),
    }