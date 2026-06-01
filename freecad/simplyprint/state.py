"""Runtime state, token persistence, and a Qt signal bridge.

Network work happens on background threads; FreeCAD/Qt widgets may only be
touched on the main thread. Worker threads therefore report back by emitting Qt
signals on the :class:`_Signals` object (created on the main thread), which Qt
delivers to the panel's slots via a queued connection.

The token-persistence helpers are stdlib-only so they stay importable (and
testable) without FreeCAD or PySide. The Qt bridge is imported lazily.
"""

import json
import os
from typing import Optional

from . import oauth

# ---------------------------------------------------------------------------
# Persistent token storage (per-user, outside the addon folder so it survives
# reinstalls; namespaced per-integration so it never clobbers Blender/Fusion).
# ---------------------------------------------------------------------------

TOKEN_FILENAME = "oauth_freecad.json"


def data_dir() -> str:
    base = os.path.join(os.path.expanduser("~"), ".simplyprint")
    os.makedirs(base, exist_ok=True)
    return base


def token_path() -> str:
    return os.path.join(data_dir(), TOKEN_FILENAME)


def load_tokens() -> Optional[dict]:
    path = token_path()
    if not os.path.isfile(path):
        return None
    try:
        with open(path, "r") as fh:
            return json.load(fh)
    except (OSError, json.JSONDecodeError):
        return None


def save_tokens(tokens: dict) -> None:
    path = token_path()
    with open(path, "w") as fh:
        json.dump(tokens, fh)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def remove_tokens() -> None:
    path = token_path()
    if os.path.isfile(path):
        try:
            os.remove(path)
        except OSError:
            pass


def clear_local_data() -> list:
    """Remove files this addon writes to the user's home dir.

    Leaves user-created files (like .env) untouched. Returns the list of paths
    removed, for reporting. Run before uninstalling to remove all traces.
    """
    removed = []
    base = os.path.join(os.path.expanduser("~"), ".simplyprint")

    path = os.path.join(base, TOKEN_FILENAME)
    if os.path.isfile(path):
        try:
            os.remove(path)
            removed.append(path)
        except OSError:
            pass

    # Remove the directory only if it's now empty — preserves a user-created
    # ~/.simplyprint/.env and tokens belonging to other integrations.
    if os.path.isdir(base):
        try:
            os.rmdir(base)
            removed.append(base)
        except OSError:
            pass

    return removed


# ---------------------------------------------------------------------------
# Runtime state
# ---------------------------------------------------------------------------

class _State:
    tokens: Optional[dict] = None
    user: Optional[dict] = None
    busy: bool = False
    status: str = ""
    progress: float = -1.0  # -1 means indeterminate


state = _State()


def ensure_tokens_loaded() -> None:
    if state.tokens is None:
        state.tokens = load_tokens()


def is_logged_in() -> bool:
    ensure_tokens_loaded()
    return state.tokens is not None and state.user is not None


def has_tokens() -> bool:
    ensure_tokens_loaded()
    return bool(state.tokens and state.tokens.get("access_token"))


def access_token() -> Optional[str]:
    ensure_tokens_loaded()
    if state.tokens:
        return state.tokens.get("access_token")
    return None


def set_tokens(tokens: Optional[dict]) -> None:
    state.tokens = tokens
    if tokens:
        save_tokens(tokens)
    else:
        remove_tokens()


def set_user(user: Optional[dict]) -> None:
    state.user = user


def user_name() -> str:
    if not state.user:
        return "User"
    return state.user.get("name") or state.user.get("username") or "User"


def try_refresh() -> bool:
    """Attempt to refresh the access token. Returns True on success."""
    ensure_tokens_loaded()
    if not state.tokens or not state.tokens.get("refresh_token"):
        return False
    result = oauth.refresh_access_token(state.tokens["refresh_token"])
    if result.success:
        set_tokens(result.to_dict())
        return True
    return False


def logout() -> None:
    set_tokens(None)
    state.user = None
    state.status = "Logged out"


# ---------------------------------------------------------------------------
# Qt signal bridge (lazy – only when running inside FreeCAD GUI)
# ---------------------------------------------------------------------------

_signals = None


def signals():
    """Return the shared signal bridge, creating it on first use.

    Must first be called from the main (GUI) thread so the QObject lives there
    and cross-thread emits are delivered as queued slot calls.
    """
    global _signals
    if _signals is None:
        from PySide import QtCore

        class _Signals(QtCore.QObject):
            auth_changed = QtCore.Signal()           # login state / profile changed
            status_changed = QtCore.Signal(str)      # human-readable status line
            progress_changed = QtCore.Signal(int, int)  # (bytes_sent, total)
            upload_done = QtCore.Signal(bool, str)   # (success, import_url_or_error)

        _signals = _Signals()
    return _signals
