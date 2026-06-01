"""Stdlib-only tests for the SimplyPrint FreeCAD addon.

These cover the parts that don't need FreeCAD or PySide: config cascade, the
HTTP/upload framing, OAuth URL/PKCE construction, and the export helpers'
pure-Python math. Run directly (``python tests/test_core.py``) or via pytest.
"""

import base64
import hashlib
import os
import sys

# Make the addon importable.
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from freecad.simplyprint import api, config, export, oauth  # noqa: E402

# These tests assert the built-in defaults and the override mechanism, so make
# the suite hermetic: ignore any developer .env (e.g. a local
# freecad/simplyprint/.env pointing at test.simplyprint.io) and clear overrides.
config._parse_env_file = lambda *a, **k: {}
config._override.clear()
config.reload()


# --------------------------------------------------------------------- config

def test_config_defaults():
    config.reload()
    assert config.client_id() == "simplyprintfreecad"
    assert config.callback_port() == 21331
    assert config.base_domain() == "simplyprint.io"


def test_config_env_override():
    os.environ["SP_CLIENT_ID"] = "simplyprinttest"
    os.environ["SP_CALLBACK_PORT"] = "12345"
    try:
        config.reload()
        assert config.client_id() == "simplyprinttest"
        assert config.callback_port() == 12345
    finally:
        del os.environ["SP_CLIENT_ID"]
        del os.environ["SP_CALLBACK_PORT"]
        config.reload()


# ------------------------------------------------------------------- multipart

def test_build_multipart_framing():
    body, content_type = api._build_multipart(b"hello world", "thing.stl")
    assert content_type.startswith("multipart/form-data; boundary=")
    boundary = content_type.split("boundary=")[1]
    assert f'filename="thing.stl"'.encode() in body
    assert b"Content-Type: application/octet-stream" in body
    assert b"hello world" in body
    assert body.startswith(f"--{boundary}".encode())
    assert body.rstrip().endswith(f"--{boundary}--".encode())


# ------------------------------------------------------------------- uploads

class _Recorder:
    """Stands in for api._api_request, recording calls and faking responses."""

    def __init__(self):
        self.calls = []
        self._next_id = 1

    def __call__(self, method, endpoint, access_token, data=None, extra_headers=None):
        self.calls.append({"method": method, "endpoint": endpoint, "data": data, "headers": extra_headers})
        if endpoint.startswith("/files/ChunkReceive"):
            cid = self._next_id
            self._next_id += 1
            return {"status": True, "id": cid}
        # /files/TempUpload (single or finalize)
        return {"status": True, "uuid": "fake-uuid-123"}


def test_upload_single():
    rec = _Recorder()
    orig = api._api_request
    api._api_request = rec
    progress = []
    try:
        resp = api.upload_file(b"x" * 1000, "small.stl", "tok", lambda s, t: progress.append((s, t)))
    finally:
        api._api_request = orig

    assert resp["uuid"] == "fake-uuid-123"
    assert len(rec.calls) == 1
    assert rec.calls[0]["endpoint"] == "/files/TempUpload"
    assert rec.calls[0]["headers"]["Content-Type"].startswith("multipart/form-data")
    assert progress[-1] == (1000, 1000)


def test_upload_chunked():
    rec = _Recorder()
    orig_req = api._api_request
    orig_threshold = api.CHUNK_THRESHOLD
    api._api_request = rec
    api.CHUNK_THRESHOLD = 100  # force chunking
    progress = []
    try:
        data = b"y" * 250  # ceil(250/100) = 3 chunks
        resp = api.upload_file(data, "big.3mf", "tok", lambda s, t: progress.append((s, t)))
    finally:
        api._api_request = orig_req
        api.CHUNK_THRESHOLD = orig_threshold

    chunk_calls = [c for c in rec.calls if c["endpoint"].startswith("/files/ChunkReceive")]
    finalize_calls = [c for c in rec.calls if c["endpoint"] == "/files/TempUpload"]

    assert len(chunk_calls) == 3, rec.calls
    assert "i=0" in chunk_calls[0]["endpoint"]
    assert "chunks=3" in chunk_calls[0]["endpoint"]
    assert "totalsize=250" in chunk_calls[0]["endpoint"]
    assert "temp=1" in chunk_calls[0]["endpoint"]
    # subsequent chunks reference the previous chunk id
    assert "id=" in chunk_calls[1]["endpoint"]
    # finalize is a single JSON TempUpload with the last chunk id
    assert len(finalize_calls) == 1
    import json
    body = json.loads(finalize_calls[0]["data"].decode())
    assert "chunkId" in body
    assert resp["uuid"] == "fake-uuid-123"
    assert progress[-1] == (250, 250)


def test_make_import_url():
    config.reload()
    config._override.clear()
    url = api.make_import_url("abc-123", "my part.stl")
    assert url == "https://simplyprint.io/panel?import=tmp:abc-123&filename=my%20part.stl"


def test_base_domain_override_routes_all_urls():
    """Setting the base domain (the GUI 'Server' setting) must route API + OAuth + import URLs."""
    config.reload()
    config._override.clear()
    assert config.base_domain() == "simplyprint.io"
    assert api._base_url() == "https://simplyprint.io/api"

    config.set_base_domain("test.simplyprint.io")
    try:
        assert config.base_domain() == "test.simplyprint.io"
        assert api._base_url() == "https://test.simplyprint.io/api"
        assert oauth._token_url() == "https://test.simplyprint.io/api/oauth2/Token"
        assert oauth._build_authorization_url("s", "c").startswith(
            "https://test.simplyprint.io/panel/oauth2/authorize?"
        )
        assert api.make_import_url("u", "f.stl").startswith(
            "https://test.simplyprint.io/panel?import="
        )
        # A real process env var still wins over the GUI override.
        os.environ["SP_BASE_DOMAIN"] = "envwins.example"
        try:
            assert config.base_domain() == "envwins.example"
        finally:
            del os.environ["SP_BASE_DOMAIN"]
    finally:
        config.set_base_domain(None)  # clear override
    assert config.base_domain() == "simplyprint.io"


# ---------------------------------------------------------------------- oauth

def test_pkce_challenge():
    verifier = "test_verifier_value"
    challenge = oauth._generate_code_challenge(verifier)
    expected = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    assert challenge == expected
    assert "=" not in challenge


def test_authorization_url():
    config.reload()
    url = oauth._build_authorization_url("state123", "chal456")
    assert url.startswith("https://simplyprint.io/panel/oauth2/authorize?")
    assert "client_id=simplyprintfreecad" in url
    assert "code_challenge=chal456" in url
    assert "code_challenge_method=S256" in url
    assert "response_type=code" in url
    assert "state=state123" in url
    assert "21331" in url  # callback port in redirect_uri
    assert "scope=user.read" in url


# --------------------------------------------------------------------- export

def test_deflection_presets():
    assert export.deflection_for("low") == (0.5, 30.0)
    assert export.deflection_for("medium") == (0.1, 20.0)
    assert export.deflection_for("high") == (0.05, 10.0)
    # unknown preset falls back to default
    assert export.deflection_for("nonsense") == export.QUALITY_PRESETS[export.DEFAULT_QUALITY]


def test_deflection_custom_clamps():
    lin, ang = export.deflection_for("custom", custom_linear=0.0, custom_angular=0.0)
    assert lin > 0
    assert ang > 0
    assert export.deflection_for("custom", 0.2, 15.0) == (0.2, 15.0)


def test_sanitize():
    assert export.sanitize("My Part #1") == "My_Part_1"
    assert export.sanitize("") == "model"
    assert export.sanitize("a/b\\c") == "a_b_c"
    assert export.sanitize("keep.dots-and-dash") == "keep.dots-and-dash"


def test_extension_map():
    assert export.EXTENSION_MAP["STL"] == ".stl"
    assert export.EXTENSION_MAP["3MF"] == ".3mf"
    assert export.EXTENSION_MAP["OBJ"] == ".obj"


# ----------------------------------------------------------------------- main

def _run_all():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failures = 0
    for fn in tests:
        try:
            fn()
            print(f"PASS {fn.__name__}")
        except Exception as exc:  # noqa: BLE001
            failures += 1
            print(f"FAIL {fn.__name__}: {exc!r}")
    print(f"\n{len(tests) - failures}/{len(tests)} passed")
    return failures


if __name__ == "__main__":
    sys.exit(1 if _run_all() else 0)
