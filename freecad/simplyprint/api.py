"""SimplyPrint API client – handles authenticated requests and file uploads.

Stdlib-only (urllib) so it works inside FreeCAD's bundled Python without extra
dependencies. Shared upload protocol with the Blender / Cura / Fusion / Onshape
integrations: multipart POST to /files/TempUpload, chunked above ~99 MB.
"""

import json
import math
import uuid
from typing import Callable, Dict, Optional, Tuple
from urllib.parse import quote
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError  # noqa: F401  (re-exported for callers)

from . import config

USER_AGENT = "SimplyPrint FreeCAD Plugin"
CHUNK_THRESHOLD = 98_995_000  # ~99 MB


def _base_url() -> str:
    return f"https://{config.base_domain()}/api"


def _auth_headers(access_token: str) -> Dict[str, str]:
    return {
        "Authorization": f"Bearer {access_token}",
        "User-Agent": USER_AGENT,
    }


def _api_request(
    method: str,
    endpoint: str,
    access_token: str,
    data: Optional[bytes] = None,
    extra_headers: Optional[Dict[str, str]] = None,
) -> dict:
    """Perform an authenticated API request and return the parsed JSON."""
    url = f"{_base_url()}/{endpoint.lstrip('/')}"
    headers = _auth_headers(access_token)
    if extra_headers:
        headers.update(extra_headers)

    req = Request(url, data=data, headers=headers, method=method.upper())
    with urlopen(req, timeout=120) as resp:
        return json.loads(resp.read().decode())


def get_user(access_token: str) -> dict:
    """Fetch the authenticated user's profile."""
    return _api_request("GET", "/account/GetUser", access_token)


def _build_multipart(file_data: bytes, file_name: str) -> Tuple[bytes, str]:
    """Build a multipart/form-data body with a single file field."""
    boundary = uuid.uuid4().hex
    lines = [
        f"--{boundary}".encode(),
        f'Content-Disposition: form-data; name="file"; filename="{file_name}"'.encode(),
        b"Content-Type: application/octet-stream",
        b"",
        file_data,
        f"--{boundary}--".encode(),
        b"",
    ]
    body = b"\r\n".join(lines)
    content_type = f"multipart/form-data; boundary={boundary}"
    return body, content_type


def upload_file(
    file_data: bytes,
    file_name: str,
    access_token: str,
    on_progress: Optional[Callable[[int, int], None]] = None,
) -> dict:
    """Upload a file to SimplyPrint's temporary storage.

    Automatically uses chunked upload for files larger than ~99 MB.
    Returns the parsed API response (contains ``uuid`` on success).
    """
    file_size = len(file_data)
    if file_size > CHUNK_THRESHOLD:
        return _upload_chunked(file_data, file_name, file_size, access_token, on_progress)
    return _upload_single(file_data, file_name, file_size, access_token, on_progress)


def _upload_single(
    file_data: bytes,
    file_name: str,
    file_size: int,
    access_token: str,
    on_progress: Optional[Callable[[int, int], None]] = None,
) -> dict:
    body, content_type = _build_multipart(file_data, file_name)
    if on_progress:
        on_progress(0, file_size)

    result = _api_request(
        "POST",
        "/files/TempUpload",
        access_token,
        data=body,
        extra_headers={"Content-Type": content_type},
    )

    if on_progress:
        on_progress(file_size, file_size)

    return result


def _upload_chunked(
    file_data: bytes,
    file_name: str,
    file_size: int,
    access_token: str,
    on_progress: Optional[Callable[[int, int], None]] = None,
) -> dict:
    chunk_count = math.ceil(file_size / CHUNK_THRESHOLD)
    max_chunk = math.ceil(file_size / chunk_count)
    chunks = [file_data[i * max_chunk:(i + 1) * max_chunk] for i in range(chunk_count)]

    bytes_sent = 0
    chunk_id: Optional[int] = None

    for i, chunk in enumerate(chunks):
        body, content_type = _build_multipart(chunk, file_name)

        params = f"i={i}"
        if i == 0:
            params += f"&filename={quote(file_name)}&chunks={chunk_count}&totalsize={file_size}&temp=1"
        else:
            params += f"&id={chunk_id}&temp=1"

        resp = _api_request(
            "POST",
            f"/files/ChunkReceive?{params}",
            access_token,
            data=body,
            extra_headers={"Content-Type": content_type},
        )

        if resp.get("id"):
            chunk_id = resp["id"]

        bytes_sent += len(chunk)
        if on_progress:
            on_progress(bytes_sent, file_size)

        if not resp.get("status"):
            return resp

    # Finalize chunked upload
    result = _api_request(
        "POST",
        "/files/TempUpload",
        access_token,
        data=json.dumps({"chunkId": chunk_id}).encode(),
        extra_headers={"Content-Type": "application/json"},
    )

    if on_progress:
        on_progress(file_size, file_size)

    return result


def make_import_url(tmp_uuid: str, file_name: str) -> str:
    """Build the SimplyPrint panel URL that imports an uploaded temp file."""
    return f"https://{config.base_domain()}/panel?import=tmp:{tmp_uuid}&filename={quote(file_name)}"


def make_panel_url() -> str:
    """Return the base SimplyPrint panel URL."""
    return f"https://{config.base_domain()}/panel"
