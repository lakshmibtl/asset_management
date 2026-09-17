import requests
import logging

logger = logging.getLogger(__name__)

API_URL = "https://103.229.250.150/unified/v2/send"
TOKEN = "Bearer eyJhbGciOiJIUzI1NiJ9.eyJpc3MiOiJJbmZpbml0byIsImlhdCI6MTc3NTAxODE5NSwic3ViIjoiQnJpaGFzcGF0aGljYWJ6ZWs0ZnQycmVkIn0.2K30_oHzNN8kactPYCGr0ZugzMWxZMgbO4fFlLfJTQ0"

def send_whatsapp_message(to_number, template_id, template_params):
    import json
    import uuid
    
    template_info = str(template_id)
    if template_params:
        template_info += "~" + "~".join([str(p) for p in template_params])

    payload = {
      "apiver": "1.0",
      "whatsapp": {
        "ver": "2.0",
        "messages": [
          {
            "coding": 1,
            "id": str(uuid.uuid4())[:15],  # Generate a unique ID
            "msgtype": 1,
            "templateid": str(template_id),
            "templateinfo": template_info,
            "addresses": [
              {
                "seq": "1",
                "to": str(to_number),
                "from": "919000552765"
              }
            ]
          }
        ]
      }
    }

    headers = {
        "Authorization": TOKEN,
        "Content-Type": "application/json"
    }

    try:
        response = requests.post(API_URL, json=payload, headers=headers, timeout=10, verify=False)
        result = response.json()
        
        # Log to debug file
        with open("/home/btl/prasuna/New folder 333/New folder 333/asset_management/whatsapp_debug.txt", "w") as f:
            f.write(f"PAYLOAD: {json.dumps(payload)}\n")
            f.write(f"RESPONSE: {response.text}\n")
            
        if result.get("status") != "Error":
            logger.info(f"Successfully sent WhatsApp message to {to_number}. API Response: {response.text}")
            return True, result
        else:
            logger.error(f"Failed API Response: {response.text}")
            return False, result
    except Exception as e:
        logger.error(f"Exception sending WhatsApp message: {str(e)}")
        return False, str(e)
