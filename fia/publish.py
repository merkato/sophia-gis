"""Komunikacja z API Sophii (logowanie + publikacja projektu). Bez zależności spoza QGIS."""
from __future__ import annotations

import json
import ssl
import urllib.error
import urllib.request
import uuid


class ApiError(Exception):
    pass


def _ssl_context(verify: bool) -> ssl.SSLContext:
    ctx = ssl.create_default_context()
    if not verify:  # np. lokalny Caddy z certyfikatem wewnętrznym
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    return ctx


def _request(url: str, data: bytes | None, headers: dict, verify: bool, method: str = "POST") -> dict:
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, context=_ssl_context(verify), timeout=300) as resp:
            return json.loads(resp.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:
            detail = json.loads(e.read()).get("detail")
        except Exception:  # noqa: BLE001
            detail = e.reason
        raise ApiError(f"HTTP {e.code}: {detail}") from e
    except urllib.error.URLError as e:
        raise ApiError(f"Brak połączenia z serwerem: {e.reason}") from e


def login(base_url: str, user: str, password: str, verify: bool = True) -> str:
    body = json.dumps({"login": user, "password": password}).encode()
    res = _request(f"{base_url.rstrip('/')}/api/auth/login", body, {"Content-Type": "application/json"}, verify)
    return res["token"]


def publish(base_url: str, token: str, slug: str, title: str, qgz_path: str, portal_json: dict,
            verify: bool = True) -> dict:
    boundary = uuid.uuid4().hex
    parts: list[bytes] = []

    def field(name: str, value: str):
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode())

    field("slug", slug)
    field("title", title)
    field("portal_json", json.dumps(portal_json, ensure_ascii=False, indent=2))
    with open(qgz_path, "rb") as f:
        parts.append(
            f'--{boundary}\r\nContent-Disposition: form-data; name="project_file"; filename="{slug}.qgz"\r\n'
            f"Content-Type: application/zip\r\n\r\n".encode() + f.read() + b"\r\n")
    parts.append(f"--{boundary}--\r\n".encode())
    headers = {"Content-Type": f"multipart/form-data; boundary={boundary}", "Authorization": f"Bearer {token}"}
    return _request(f"{base_url.rstrip('/')}/api/admin/publish", b"".join(parts), headers, verify)
