import sys
import requests

API_URL = "https://103.229.250.150/unified/v2/send"
TOKEN = "Bearer eyJhbGciOiJIUzI1NiJ9.eyJpc3MiOiJJbmZpbml0byIsImlhdCI6MTc3NTAxODE5NSwic3ViIjoiQnJpaGFzcGF0aGljYWJ6ZWs0ZnQycmVkIn0.2K30_oHzNN8kactPYCGr0ZugzMWxZMgbO4fFlLfJTQ0"

payload = {
    "apiver": "1.0",
    "whatsapp": {
        "ver": "2.0",
        "dlr": {
            "url": ""
        },
        "messages": [
            {
                "coding": "1",
                "msgtype": "3",
                "templateid": "1802469",
                "templateinfo": "1802469~TKT-001~LP-001~Testing Issue~Prasuna~IT Support~High",
                "property": {
                    "to": ["919908076556"]
                }
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
    with open("api_test_output.txt", "w") as f:
        f.write(f"STATUS CODE: {response.status_code}\n")
        f.write(f"RESPONSE TEXT: {response.text}\n")
except Exception as e:
    with open("api_test_output.txt", "w") as f:
        f.write(f"ERROR: {str(e)}\n")
