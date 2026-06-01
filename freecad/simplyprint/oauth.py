"""OAuth 2.0 PKCE authentication flow for SimplyPrint.

Identical handshake to the other SimplyPrint integrations: open the browser to
the authorize endpoint, catch the redirect on a local 127.0.0.1 callback server,
then exchange the code (with PKCE verifier) for access/refresh tokens. Stdlib
only, so it runs unchanged inside FreeCAD's Python.
"""

import hashlib
import json
import secrets
import threading
import webbrowser
from base64 import urlsafe_b64encode
from http.server import HTTPServer, BaseHTTPRequestHandler
from typing import Callable, Optional
from urllib.parse import urlencode, urlparse, parse_qs
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

from . import config
from .api import USER_AGENT

CLIENT_SCOPES = "user.read files.temp_upload"


def _callback_url() -> str:
    return f"http://localhost:{config.callback_port()}/callback"


def _oauth_server_url() -> str:
    return f"https://{config.base_domain()}/panel/oauth2"


def _token_url() -> str:
    return f"https://{config.base_domain()}/api/oauth2/Token"


def _auth_success_redirect() -> str:
    return f"https://{config.base_domain()}/login-success"


class AuthResult:
    """Result of an OAuth authentication attempt."""

    def __init__(
        self,
        success: bool = False,
        access_token: Optional[str] = None,
        refresh_token: Optional[str] = None,
        error: Optional[str] = None,
    ):
        self.success = success
        self.access_token = access_token
        self.refresh_token = refresh_token
        self.error = error

    def to_dict(self) -> dict:
        return {
            "access_token": self.access_token,
            "refresh_token": self.refresh_token,
        }


def _generate_code_verifier() -> str:
    return secrets.token_urlsafe(32)


def _generate_code_challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode()).digest()
    return urlsafe_b64encode(digest).decode().rstrip("=")


def _build_authorization_url(state: str, code_challenge: str) -> str:
    params = {
        "client_id": config.client_id(),
        "redirect_uri": _callback_url(),
        "scope": CLIENT_SCOPES,
        "response_type": "code",
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    }
    return f"{_oauth_server_url()}/authorize?{urlencode(params)}"


def exchange_code_for_tokens(code: str, code_verifier: str) -> AuthResult:
    """Exchange an authorization code for access and refresh tokens."""
    payload = urlencode({
        "grant_type": "authorization_code",
        "client_id": config.client_id(),
        "code": code,
        "redirect_uri": _callback_url(),
        "code_verifier": code_verifier,
    }).encode()

    req = Request(
        _token_url(),
        data=payload,
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": USER_AGENT,
        },
        method="POST",
    )

    try:
        with urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode())
            return AuthResult(
                success=True,
                access_token=data["access_token"],
                refresh_token=data["refresh_token"],
            )
    except HTTPError as exc:
        body = exc.read().decode() if exc.fp else ""
        return AuthResult(success=False, error=f"HTTP {exc.code}: {body}")
    except (URLError, KeyError, json.JSONDecodeError) as exc:
        return AuthResult(success=False, error=str(exc))


def refresh_access_token(current_refresh_token: str) -> AuthResult:
    """Use a refresh token to obtain a new access token."""
    payload = urlencode({
        "grant_type": "refresh_token",
        "client_id": config.client_id(),
        "refresh_token": current_refresh_token,
    }).encode()

    req = Request(
        _token_url(),
        data=payload,
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": USER_AGENT,
        },
        method="POST",
    )

    try:
        with urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode())
            return AuthResult(
                success=True,
                access_token=data["access_token"],
                refresh_token=data["refresh_token"],
            )
    except HTTPError as exc:
        body = exc.read().decode() if exc.fp else ""
        return AuthResult(success=False, error=f"HTTP {exc.code}: {body}")
    except (URLError, KeyError, json.JSONDecodeError) as exc:
        return AuthResult(success=False, error=str(exc))


class OAuthCallbackHandler(BaseHTTPRequestHandler):
    """HTTP request handler that captures the OAuth callback."""

    code: Optional[str] = None
    state: Optional[str] = None

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path != "/callback":
            self.send_response(404)
            self.end_headers()
            return

        params = parse_qs(parsed.query)
        OAuthCallbackHandler.code = params.get("code", [None])[0]
        OAuthCallbackHandler.state = params.get("state", [None])[0]

        self.send_response(302)
        self.send_header("Location", _auth_success_redirect())
        self.end_headers()

        # Shut down from a separate thread so we don't deadlock
        threading.Thread(target=self.server.shutdown, daemon=True).start()

    def log_message(self, format, *args):
        pass  # Silence request logging


last_auth_url: Optional[str] = None


def start_oauth_flow(callback: Callable[[AuthResult], None]) -> None:
    """Start the full OAuth PKCE flow in a background thread.

    Opens the browser for the user to authorize, starts a local server to
    receive the callback, exchanges the code for tokens, then invokes
    *callback* with the result.
    """
    global last_auth_url

    code_verifier = _generate_code_verifier()
    code_challenge = _generate_code_challenge(code_verifier)
    state = secrets.token_urlsafe(16)
    port = config.callback_port()

    def _run():
        global last_auth_url
        OAuthCallbackHandler.code = None
        OAuthCallbackHandler.state = None

        try:
            server = HTTPServer(("127.0.0.1", port), OAuthCallbackHandler)
        except OSError as exc:
            callback(AuthResult(success=False, error=f"Could not start callback server: {exc}"))
            return

        auth_url = _build_authorization_url(state, code_challenge)
        last_auth_url = auth_url
        webbrowser.open(auth_url)

        # Blocks until the handler calls server.shutdown()
        server.serve_forever()
        server.server_close()
        last_auth_url = None

        received_code = OAuthCallbackHandler.code
        received_state = OAuthCallbackHandler.state

        if received_state != state:
            callback(AuthResult(success=False, error="State mismatch – possible CSRF"))
            return

        if not received_code:
            callback(AuthResult(success=False, error="No authorization code received"))
            return

        result = exchange_code_for_tokens(received_code, code_verifier)
        callback(result)

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()
