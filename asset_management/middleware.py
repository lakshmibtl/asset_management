# core/middleware.py
class DisableClientCacheMiddleware:
    """
    Sets strict no-cache headers for responses when the request user is authenticated.
    Place after AuthenticationMiddleware in settings.MIDDLEWARE.
    """
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)

        # Try to check authenticated status safely
        is_auth = False
        try:
            is_auth = bool(request.user and request.user.is_authenticated)
        except Exception:
            is_auth = False

        if is_auth:
            response["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
            response["Pragma"] = "no-cache"
            response["Expires"] = "0"

        return response
