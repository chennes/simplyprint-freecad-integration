"""Configuration loaded from runtime overrides, .env files and env variables.

Lookup order (first found wins for each key):
  1. real environment variables (highest priority)
  2. runtime override via set_override() / set_base_domain() (the GUI setting)
  3. <addon_dir>/.env
  4. ~/.simplyprint/.env
  5. built-in default

Supported keys:
  SP_BASE_DOMAIN   - SimplyPrint backend domain  (default: simplyprint.io)
  SP_CLIENT_ID     - OAuth client ID             (default: simplyprintfreecad)
  SP_CALLBACK_PORT - Local OAuth callback port   (default: 21331)

The backend domain drives every URL: the API is https://<domain>/api, OAuth is
https://<domain>/panel/oauth2, etc. So setting it to "test.simplyprint.io" points
the whole integration at https://test.simplyprint.io/api.
"""

import os
from typing import Dict, Optional

_DEFAULTS: Dict[str, str] = {
    "SP_BASE_DOMAIN": "simplyprint.io",
    "SP_CLIENT_ID": "simplyprintfreecad",
    # Distinct from Cura/Blender (21328) and Fusion (21330) so the integrations
    # can run side by side without fighting over the callback port.
    "SP_CALLBACK_PORT": "21331",
}

_config: Dict[str, str] = {}


def _parse_env_file(filepath: str) -> Dict[str, str]:
    """Parse a simple KEY=VALUE .env file, ignoring comments and blanks."""
    values: Dict[str, str] = {}
    if not os.path.isfile(filepath):
        return values

    with open(filepath, "r") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip("\"'")
            values[key] = value

    return values


def _addon_dir() -> str:
    # simplyprint/ lives one level below the addon root; the .env (if any) sits
    # next to this file so it ships with the addon.
    return os.path.dirname(os.path.abspath(__file__))


# Programmatic overrides set at runtime (e.g. by the GUI "Server" selector).
# These sit above the .env files / defaults but below a real process env var.
_override: Dict[str, str] = {}


def _load() -> Dict[str, str]:
    """Load configuration from the .env files (defaults < home < addon)."""
    merged: Dict[str, str] = dict(_DEFAULTS)

    # ~/.simplyprint/.env  (lowest priority file)
    home_env = os.path.join(os.path.expanduser("~"), ".simplyprint", ".env")
    merged.update(_parse_env_file(home_env))

    # <addon_dir>/.env  (higher priority)
    merged.update(_parse_env_file(os.path.join(_addon_dir(), ".env")))

    return merged


def _ensure_loaded() -> None:
    global _config
    if not _config:
        _config = _load()


def get(key: str, default: Optional[str] = None) -> str:
    """Resolve a config value. Precedence (highest first):

    1. real process environment variable (CI / dev shells)
    2. programmatic override set via :func:`set_override` (the GUI setting)
    3. .env files (addon dir, then ~/.simplyprint)
    4. built-in default
    """
    env_val = os.environ.get(key)
    if env_val is not None:
        return env_val
    if key in _override:
        return _override[key]
    _ensure_loaded()
    return _config.get(key, default if default is not None else _DEFAULTS.get(key, ""))


def set_override(key: str, value: Optional[str]) -> None:
    """Set (or clear, with a falsy value) a runtime override for *key*."""
    if value:
        _override[key] = value
    else:
        _override.pop(key, None)


def set_base_domain(domain: Optional[str]) -> None:
    """Convenience: override the SimplyPrint backend domain at runtime."""
    set_override("SP_BASE_DOMAIN", domain)


def reload() -> None:
    """Force re-read of .env files (does not clear runtime overrides)."""
    global _config
    _config = _load()


# Convenience accessors
def base_domain() -> str:
    return get("SP_BASE_DOMAIN")


def client_id() -> str:
    return get("SP_CLIENT_ID")


def callback_port() -> int:
    return int(get("SP_CALLBACK_PORT"))
