"""High-level actions: login, logout, fetch user, upload.

These run the slow / network parts on background threads and report progress
back to the UI through the Qt signal bridge in :mod:`state`. Geometry export is
*not* here – it must run on the main thread (see :mod:`panel`).
"""

import os
import shutil
import threading
import webbrowser
from typing import List, Optional

from . import api, oauth, state


def _emit_auth() -> None:
    sig = state.signals()
    sig.status_changed.emit(state.state.status)
    sig.auth_changed.emit()


def restore_session() -> None:
    """On startup: if we have stored tokens, validate them by fetching the user."""
    state.ensure_tokens_loaded()
    if state.has_tokens():
        state.state.busy = True
        state.state.status = "Restoring session…"
        _fetch_user_async()


def start_login() -> None:
    if state.state.busy:
        return
    state.state.busy = True
    state.state.status = "Waiting for browser login…"
    _emit_auth()

    def on_result(result: "oauth.AuthResult") -> None:
        if result.success:
            state.set_tokens(result.to_dict())
            _fetch_user_async()
        else:
            state.state.busy = False
            state.state.status = f"Login failed: {result.error or 'unknown error'}"
            _emit_auth()

    oauth.start_oauth_flow(on_result)


def _fetch_user_async() -> None:
    def work():
        token = state.access_token()
        if not token:
            state.state.busy = False
            state.state.status = "Login failed – no token"
            _emit_auth()
            return

        data = None
        try:
            data = api.get_user(token)
        except Exception:
            if state.try_refresh():
                try:
                    data = api.get_user(state.access_token())
                except Exception as exc:
                    state.state.busy = False
                    state.state.status = f"Could not fetch user info: {exc}"
                    _emit_auth()
                    return
            else:
                state.state.busy = False
                state.state.status = "Could not fetch user info"
                _emit_auth()
                return

        if data and data.get("status"):
            state.set_user(data.get("user", {}))
            state.state.status = f"Signed in as {state.user_name()}"
        else:
            state.set_user(None)
            state.state.status = "Login succeeded but could not load profile"

        state.state.busy = False
        _emit_auth()

    threading.Thread(target=work, daemon=True).start()


def logout() -> None:
    state.logout()
    _emit_auth()


def upload_paths_async(
    paths: List[str],
    cleanup_dir: Optional[str] = None,
    open_browser: bool = True,
) -> None:
    """Upload already-exported files in the background, with progress + cleanup.

    Emits ``progress_changed`` while uploading and ``upload_done(success, url)``
    when finished. Opens the SimplyPrint import URL for each file on success.
    """

    def work():
        sig = state.signals()
        total_files = len(paths)
        try:
            import_urls = []
            for idx, path in enumerate(paths):
                file_name = os.path.basename(path)
                with open(path, "rb") as fh:
                    file_data = fh.read()

                state.state.status = f"Uploading {file_name} ({idx + 1}/{total_files})…"
                sig.status_changed.emit(state.state.status)

                def on_progress(sent, total):
                    sig.progress_changed.emit(int(sent), int(total))

                token = state.access_token()
                try:
                    resp = api.upload_file(file_data, file_name, token, on_progress)
                except Exception:
                    if state.try_refresh():
                        resp = api.upload_file(file_data, file_name, state.access_token(), on_progress)
                    else:
                        raise

                tmp_uuid = resp.get("uuid")
                if not tmp_uuid:
                    state.state.busy = False
                    sig.upload_done.emit(False, f"Upload error: {resp.get('message', 'unknown error')}")
                    return

                import_urls.append(api.make_import_url(tmp_uuid, file_name))

            if open_browser:
                for url in import_urls:
                    webbrowser.open(url)

            state.state.busy = False
            noun = "file" if total_files == 1 else "files"
            state.state.status = f"Sent {total_files} {noun} to SimplyPrint"
            sig.upload_done.emit(True, import_urls[0] if import_urls else "")

        except Exception as exc:
            state.state.busy = False
            sig.upload_done.emit(False, f"Error: {exc}")
        finally:
            if cleanup_dir:
                shutil.rmtree(cleanup_dir, ignore_errors=True)

    threading.Thread(target=work, daemon=True).start()
