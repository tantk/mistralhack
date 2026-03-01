"""
Reverse proxy: tan:8000 → titan:8001 (GPU service)

Tailscale funnel routes https://tan.tail2e1adb.ts.net → localhost:8000
This proxy forwards everything to titan's GPU service.
"""

import asyncio
import httpx

TARGET = "http://192.168.0.105:8001"


async def app(scope, receive, send):
    if scope["type"] == "lifespan":
        msg = await receive()
        await send({"type": "lifespan.startup.complete"})
        msg = await receive()
        await send({"type": "lifespan.shutdown.complete"})
        return

    if scope["type"] != "http":
        return

    method = scope["method"]
    path = scope["path"]
    query = scope["query_string"].decode()
    url = f"{TARGET}{path}"
    if query:
        url += f"?{query}"

    # Collect request headers (skip host)
    headers = {}
    for name, value in scope["headers"]:
        key = name.decode().lower()
        if key != "host":
            headers[key] = value.decode()

    # Read full request body
    body = b""
    while True:
        msg = await receive()
        body += msg.get("body", b"")
        if not msg.get("more_body", False):
            break

    # Forward to titan
    async with httpx.AsyncClient(timeout=httpx.Timeout(300.0)) as client:
        try:
            resp = await client.request(
                method=method,
                url=url,
                headers=headers,
                content=body,
            )

            # Build response headers
            resp_headers = [
                (k.encode(), v.encode())
                for k, v in resp.headers.items()
                if k.lower() not in ("transfer-encoding",)
            ]

            await send({
                "type": "http.response.start",
                "status": resp.status_code,
                "headers": resp_headers,
            })
            await send({
                "type": "http.response.body",
                "body": resp.content,
            })
        except Exception as e:
            import json
            error_body = json.dumps({"error": f"proxy error: {type(e).__name__}: {e}", "target": url}).encode()
            await send({
                "type": "http.response.start",
                "status": 502,
                "headers": [(b"content-type", b"application/json")],
            })
            await send({
                "type": "http.response.body",
                "body": error_body,
            })
