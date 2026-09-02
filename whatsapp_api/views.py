import json
import logging
from django.conf import settings
from django.http import JsonResponse, HttpResponseBadRequest
from django.views.decorators.http import require_POST
from django.views.decorators.csrf import csrf_exempt
import requests
from django.shortcuts import render
from django.views import View
logger = logging.getLogger(__name__)

@csrf_exempt
@require_POST
def send_whatsapp(request):
    """
    Endpoint to forward ticket data to SmartPing (WhatsApp API).
    Accepts JSON body or form-encoded POST.
    """
    try:
        # parse JSON or form-data
        if request.content_type and 'application/json' in request.content_type:
            data = json.loads(request.body.decode('utf-8') or "{}")
        else:
            # covers x-www-form-urlencoded or multipart/form-data
            data = request.POST.dict()

        phone = data.get('phone')
        district = data.get('district')
        college = data.get('college')
        raisedby = data.get('raisedby')
        vendor = data.get('vendor')
        description = data.get('description')
        url = data.get('url')
        name = data.get('name')

        if not phone:
            return HttpResponseBadRequest(json.dumps({
                'ok': False,
                'message': 'Phone number is required.'
            }), content_type='application/json')

        api_url = "https://backend.api-wa.co/campaign/smartping/api/v2"
        api_key = getattr(settings, "SMARTPING_API_KEY", None)

        if not api_key:
            logger.error("SMARTPING_API_KEY missing in Django settings")
            return JsonResponse({
                'ok': False,
                'message': 'SmartPing API_KEY is missing in settings'
            }, status=500)

        logger.info("Using SmartPing API Key (present) and sending to %s", phone)

        payload = {
            "apiKey": api_key,
            "campaignName": "raiseticketforvendor",
            "destination": phone,
            "userName": "BRIHASPATHI TECHNOLOGIES PRIVATE LIMITED",
            "templateParams": [district, college, raisedby, vendor, description],
            "source": "ticket-system",
            "media": {"url": url, "filename": name or "attachment"} if url else {},
            "tags": "",
            "buttons": []
        }

        headers = {"Content-Type": "application/json"}
        resp = requests.post(api_url, json=payload, headers=headers, timeout=30)
        resp.raise_for_status()

        # If SmartPing returns non-json, handle gracefully
        try:
            result = resp.json()
        except ValueError:
            result = resp.text

        return JsonResponse({
            "ok": True,
            "result": result
        })

    except requests.exceptions.RequestException as e:
        logger.exception("SmartPing request failed")
        return JsonResponse({
            "ok": False,
            "message": "Failed to send WhatsApp message",
            "error": str(e)
        }, status=502)
    except Exception as e:
        logger.exception("Unexpected error in send_whatsapp")
        return JsonResponse({
            "ok": False,
            "message": "Internal server error",
            "error": str(e)
        }, status=500) 



# import json
# import logging
# from django.conf import settings
# from django.http import JsonResponse, HttpResponseBadRequest, HttpResponseRedirect
# from django.views.decorators.http import require_POST
# from django.views.decorators.csrf import csrf_exempt
# from django.shortcuts import render
# from django.views import View
# import requests

# logger = logging.getLogger(__name__)

# API_URL = "https://backend.api-wa.co/campaign/smartping/api/v2"

# def forward_to_smartping(api_key, phone, district, college, raisedby, vendor, description, url=None, name=None):
#     """
#     Helper that actually sends the request to SmartPing and returns
#     the parsed response (or raises requests.RequestException).
#     """
#     payload = {
#         "apiKey": api_key,
#         "campaignName": "raiseticketforvendor",
#         "destination": phone,
#         "userName": "BRIHASPATHI TECHNOLOGIES PRIVATE LIMITED",
#         "templateParams": [district, college, raisedby, vendor, description],
#         "source": "ticket-system",
#         "media": {"url": url, "filename": name or "attachment"} if url else {},
#         "tags": "",
#         "buttons": []
#     }

#     headers = {"Content-Type": "application/json"}
#     resp = requests.post(API_URL, json=payload, headers=headers, timeout=30)
#     resp.raise_for_status()
#     # return JSON when available, else text
#     try:
#         return resp.json()
#     except ValueError:
#         return resp.text


# @csrf_exempt
# @require_POST
# def send_whatsapp(request):
#     """
#     Public endpoint to forward ticket data to SmartPing (WhatsApp API).
#     Accepts JSON body or form-encoded POST.
#     Returns JSON response.
#     """
#     try:
#         # parse JSON or form-data
#         if request.content_type and 'application/json' in request.content_type:
#             data = json.loads(request.body.decode('utf-8') or "{}")
#         else:
#             data = request.POST.dict()

#         # map expected fields
#         phone = data.get('phone')
#         district = data.get('district') or data.get('category')  # accept category as district fallback
#         college = data.get('college')
#         raisedby = data.get('raisedby') or data.get('request_by') or request.user.get_full_name() if request.user.is_authenticated else data.get('request_by')
#         vendor = data.get('vendor') or data.get('item_name')
#         description = data.get('description') or data.get('notes') or f"Stationery request by {raisedby}"
#         url = data.get('url')
#         name = data.get('name')

#         if not phone:
#             return HttpResponseBadRequest(json.dumps({
#                 'ok': False,
#                 'message': 'Phone number is required.'
#             }), content_type='application/json')

#         api_key = getattr(settings, "SMARTPING_API_KEY", None)
#         if not api_key:
#             logger.error("SMARTPING_API_KEY missing in Django settings")
#             return JsonResponse({
#                 'ok': False,
#                 'message': 'SmartPing API_KEY is missing in settings'
#             }, status=500)

#         result = forward_to_smartping(api_key, phone, district, college, raisedby, vendor, description, url, name)

#         return JsonResponse({
#             "ok": True,
#             "result": result
#         })
#     except requests.exceptions.RequestException as e:
#         logger.exception("SmartPing request failed")
#         return JsonResponse({
#             "ok": False,
#             "message": "Failed to send WhatsApp message",
#             "error": str(e)
#         }, status=502)
#     except Exception as e:
#         logger.exception("Unexpected error in send_whatsapp")
#         return JsonResponse({
#             "ok": False,
#             "message": "Internal server error",
#             "error": str(e)
#         }, status=500)


# class StationeryRequestView(View):
#     """
#     Renders the stationery request form and accepts form POST.
#     On POST, reuses forward_to_smartping to send the WhatsApp.
#     """

#     template_name = "stationery_app/request_form.html"  # change if your template path differs

#     def get_default_phone(self, request):
#         # Priority: logged-in user's profile phone -> settings.DEFAULT_PHONE -> empty
#         default = ""
#         try:
#             if request.user.is_authenticated:
#                 # adjust to your user profile structure
#                 profile_phone = getattr(request.user, "phone", None) or getattr(getattr(request.user, "profile", None), "phone", None)
#                 if profile_phone:
#                     return profile_phone
#         except Exception:
#             logger.debug("No user phone available")

#         return getattr(settings, "DEFAULT_PHONE", "")

#     def get(self, request):
#         context = {
#             "default_phone": self.get_default_phone(request),
#             # pass categories if your template expects it
#             "CATEGORY_ITEMS": getattr(settings, "CATEGORY_ITEMS", {}),
#         }
#         return render(request, self.template_name, context)

#     def post(self, request):
#         # read form fields (coming from your template)
#         phone = request.POST.get("phone")
#         category = request.POST.get("category")
#         item_name = request.POST.get("item_name")
#         request_by = request.POST.get("request_by")
#         quantity = request.POST.get("quantity")
#         request_date = request.POST.get("request_date")

#         if not phone:
#             # re-render form with an error
#             context = {"default_phone": self.get_default_phone(request), "error": "Phone is required.", "CATEGORY_ITEMS": getattr(settings, "CATEGORY_ITEMS", {})}
#             return render(request, self.template_name, context, status=400)

#         # Build reasonable SmartPing fields
#         district = category
#         college = getattr(settings, "DEFAULT_COLLEGE", "ABC College")
#         raisedby = request_by or (request.user.get_full_name() if request.user.is_authenticated else "")
#         vendor = item_name
#         description = f"Request: {item_name} x {quantity} needed by {request_date}"

#         api_key = getattr(settings, "SMARTPING_API_KEY", None)
#         if not api_key:
#             logger.error("SMARTPING_API_KEY missing in Django settings")
#             context = {"default_phone": self.get_default_phone(request), "error": "SmartPing API key not configured.", "CATEGORY_ITEMS": getattr(settings, "CATEGORY_ITEMS", {})}
#             return render(request, self.template_name, context, status=500)

#         try:
#             result = forward_to_smartping(api_key, phone, district, college, raisedby, vendor, description)
#             # On success you can redirect to a success page or re-render with message
#             context = {"default_phone": self.get_default_phone(request), "success": "Request submitted and WhatsApp sent.", "result": result, "CATEGORY_ITEMS": getattr(settings, "CATEGORY_ITEMS", {})}
#             return render(request, self.template_name, context)
#         except requests.exceptions.RequestException as e:
#             logger.exception("SmartPing call failed from stationery form")
#             context = {"default_phone": self.get_default_phone(request), "error": f"Failed to send WhatsApp: {e}", "CATEGORY_ITEMS": getattr(settings, "CATEGORY_ITEMS", {})}
#             return render(request, self.template_name, context, status=502)


