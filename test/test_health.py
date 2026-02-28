"""
Health check for all services.

Checks:
  - NUC server (tan): https://tan.tail2e1adb.ts.net or http://192.168.0.121:8000
  - Voxtral transcription (titan): http://192.168.0.105:8080/health
  - GPU diarization (titan): http://192.168.0.105:8001/health
"""
import os
import json
import requests

SERVICES = [
    {
        "name": "NUC Server (tan)",
        "url": os.environ.get("NUC_URL", "https://tan.tail2e1adb.ts.net"),
        "health_path": "/",
        "expect_status": 200,
    },
    {
        "name": "Voxtral Transcription (titan:8080)",
        "url": os.environ.get("VOXTRAL_URL", "http://192.168.0.105:8080"),
        "health_path": "/health",
        "expect_json": True,
    },
    {
        "name": "GPU Diarization (titan:8001)",
        "url": os.environ.get("DIARIZATION_URL", "http://192.168.0.105:8001"),
        "health_path": "/health",
        "expect_json": True,
    },
]


def main():
    print("=" * 60)
    print("Service Health Checks")
    print("=" * 60)
    print()

    all_ok = True
    for svc in SERVICES:
        url = svc["url"].rstrip("/") + svc["health_path"]
        try:
            resp = requests.get(url, timeout=10)
            status = resp.status_code

            if svc.get("expect_json"):
                data = resp.json()
                detail = json.dumps(data, indent=None)
            else:
                detail = f"status={status}"

            ok = status == svc.get("expect_status", 200)
            symbol = "OK" if ok else "WARN"
            print(f"  [{symbol:>4}] {svc['name']:<40} {detail}")

        except requests.ConnectionError:
            print(f"  [FAIL] {svc['name']:<40} Connection refused")
            all_ok = False
        except requests.Timeout:
            print(f"  [FAIL] {svc['name']:<40} Timeout")
            all_ok = False
        except Exception as e:
            print(f"  [FAIL] {svc['name']:<40} {e}")
            all_ok = False

    print()
    if all_ok:
        print("All services are reachable.")
    else:
        print("Some services are unreachable. Check the services above.")


if __name__ == "__main__":
    main()
