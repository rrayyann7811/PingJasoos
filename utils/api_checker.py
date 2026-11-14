import json
import time
from urllib.parse import urlsplit

import requests


ALLOWED_HOSTS = {"jsonplaceholder.typicode.com", "httpbin.org"}
PREVIEW_LIMIT = 500
MAX_RESPONSE_BYTES = 1024 * 1024
READ_CHUNK_BYTES = 8192


def validate_url(url):
    """Return an error message, or None when the URL is allowed."""
    if not isinstance(url, str) or not url.strip():
        return "Please enter a URL."
    if any(character.isspace() for character in url) or "\\" in url:
        return "Enter a valid URL without whitespace or backslashes."
    if not url.startswith(("http://", "https://")):
        return "URL must begin with http:// or https://."
    try:
        parsed = urlsplit(url)
        hostname = parsed.hostname
        port = parsed.port
    except ValueError:
        return "Enter a valid URL and port."
    if not hostname:
        return "URL must include a valid hostname."
    if parsed.username is not None or parsed.password is not None:
        return "URLs with embedded credentials are not allowed."
    if hostname not in ALLOWED_HOSTS:
        return "Hostname is not approved. Use jsonplaceholder.typicode.com or httpbin.org."
    if port is not None and port != (443 if parsed.scheme == "https" else 80):
        return "Only the standard HTTP and HTTPS ports are allowed."
    return None


def check_api(url):
    result = {
        "url": url,
        "status_code": None,
        "response_time_ms": None,
        "success": False,
        "content_type": None,
        "preview": "",
        "error": None,
    }
    result["error"] = validate_url(url)
    if result["error"]:
        return result

    start = time.perf_counter()
    response = None
    try:
        response = requests.get(url, timeout=5, allow_redirects=False, stream=True)
        result["status_code"] = response.status_code
        result["success"] = 200 <= response.status_code < 300
        result["content_type"] = response.headers.get("Content-Type", "")
        if 300 <= response.status_code < 400:
            result["error"] = f"HTTP {response.status_code}: redirect received; not followed."
        elif not result["success"]:
            result["error"] = f"HTTP {response.status_code}: unsuccessful API response."

        body = bytearray()
        oversized = False
        for chunk in response.iter_content(chunk_size=READ_CHUNK_BYTES):
            remaining = MAX_RESPONSE_BYTES - len(body)
            body.extend(chunk[:remaining])
            if len(chunk) > remaining:
                oversized = True
                break

        try:
            text = body.decode(response.encoding or "utf-8", errors="replace")
        except LookupError:
            text = body.decode("utf-8", errors="replace")
        media_type = result["content_type"].split(";", 1)[0].strip().lower()
        message = None
        if oversized:
            message = "Response exceeded the 1 MiB reading limit; preview is partial."
        elif media_type == "application/json" or media_type.endswith("+json"):
            try:
                text = json.dumps(json.loads(text), indent=2, ensure_ascii=False)
            except (ValueError, RecursionError):
                message = "Response declared JSON but could not be parsed."
        result["preview"] = text[:PREVIEW_LIMIT]
        if message:
            result["error"] = f'{result["error"]} {message}' if result["error"] else message
    except requests.Timeout:
        message = "Request timed out after 5 seconds."
        result["error"] = f'{result["error"]} {message}' if result["error"] else message
    except requests.ConnectionError:
        message = "Could not connect to the API."
        result["error"] = f'{result["error"]} {message}' if result["error"] else message
    except requests.RequestException:
        message = "The API request could not be completed."
        result["error"] = f'{result["error"]} {message}' if result["error"] else message
    finally:
        if response is not None:
            response.close()
        result["response_time_ms"] = round((time.perf_counter() - start) * 1000, 2)
    return result
