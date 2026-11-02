from __future__ import annotations

import copy
import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any


class ConfigError(ValueError):
    """An actionable error that never includes secret field values."""


def config_root() -> Path:
    override = os.environ.get("VIDEOCREATE_CONFIG_DIR", "").strip()
    if override:
        return Path(override).expanduser().resolve()
    if os.name == "nt" and os.environ.get("LOCALAPPDATA"):
        return Path(os.environ["LOCALAPPDATA"]) / "VideoCreate"
    xdg = os.environ.get("XDG_CONFIG_HOME", "").strip()
    return (Path(xdg).expanduser() if xdg else Path.home() / ".config") / "VideoCreate"


def user_config_path(explicit: str | Path | None = None) -> Path:
    return Path(explicit).expanduser().resolve() if explicit else config_root() / "videocreate.config.json"


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2, allow_nan=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def load_json(path: Path) -> dict[str, Any]:
    def object_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for name, value in pairs:
            if name in result:
                raise ConfigError("Duplicate JSON property; remove the duplicate before continuing")
            result[name] = value
        return result
    try:
        raw = path.read_text(encoding="utf-8-sig")
        value = json.loads(raw, object_pairs_hook=object_pairs,
                           parse_constant=lambda _: (_ for _ in ()).throw(ConfigError("Non-finite JSON number")))
    except json.JSONDecodeError as error:
        raise ConfigError(f"Invalid JSON at line {error.lineno}, column {error.colno}") from None
    if not isinstance(value, dict):
        raise ConfigError("Configuration root must be an object")
    return value


SECRET_FIELDS = {"api_key", "key", "token", "password", "authorization", "access_token", "refresh_token"}


def redact_config(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: ("***" if v else "") if k.lower() in SECRET_FIELDS or k.lower().endswith("_key")
                else redact_config(v) for k, v in value.items()}
    if isinstance(value, list):
        return [redact_config(item) for item in value]
    return value


def private_store(root: Path | None = None) -> dict[str, str]:
    path = (root or config_root()) / "secrets.dpapi"
    if not path.exists():
        return {}
    if os.name != "nt":
        raise ConfigError("Windows encrypted credentials require the original Windows account")
    from .secrets import unprotect
    try:
        value = json.loads(unprotect(path.read_bytes()).decode("utf-8"))
    except Exception:
        raise ConfigError("Encrypted credential store could not be read by this account") from None
    return value if isinstance(value, dict) else {}


def resolve_key(auth: dict[str, Any], *, store_root: Path | None = None) -> str:
    choices = [field for field in ("api_key", "env", "secret_ref") if field in auth]
    if len(choices) != 1:
        raise ConfigError("auth requires exactly one of api_key, env, secret_ref")
    if choices[0] == "api_key":
        return str(auth["api_key"]).strip()
    if choices[0] == "env":
        return os.environ.get(str(auth["env"]), "").strip()
    value: Any = private_store(store_root)
    # The encrypted payload stays byte-for-byte intact during migration.
    # Only older payloads with no current role fields receive legacy aliases.
    if isinstance(value, dict) and not any(k in value for k in ("sub2api_image_key", "sub2api_video_key", "newapi_video_key")):
        value = {**value,
            "sub2api_image_key": value.get("quickai_image_key") or value.get("sub2api_key") or value.get("quickai_key", ""),
            "sub2api_video_key": value.get("quickai_video_key") or value.get("sub2api_key") or value.get("quickai_key", ""),
            "newapi_video_key": value.get("quickainew_video_key") or value.get("newapi_key") or value.get("quickainew_key", "")}
    elif isinstance(value, dict):
        value = {**value,
            "sub2api_image_key": value.get("sub2api_image_key") or value.get("sub2api_key", ""),
            "sub2api_video_key": value.get("sub2api_video_key") or value.get("sub2api_key", ""),
            "newapi_video_key": value.get("newapi_video_key") or value.get("newapi_key", "")}
    reference = str(auth["secret_ref"])
    if reference.startswith("video_upstream_keys."):
        keys = value.get("video_upstream_keys", {}) if isinstance(value, dict) else {}
        return str(keys.get(reference[len("video_upstream_keys."):], "")).strip() if isinstance(keys, dict) else ""
    for name in reference.split("."):
        value = value.get(name, "") if isinstance(value, dict) else ""
    return str(value).strip() if isinstance(value, str) else ""


def secret_values(config: dict[str, Any]) -> list[str]:
    values: list[str] = []
    for item in config.get("upstreams", {}).values():
        if isinstance(item, dict):
            auth = item.get("auth", {})
            if isinstance(auth, dict):
                try:
                    key = resolve_key(auth)
                except ConfigError:
                    key = ""
                if key:
                    values.append(key)
    return values


def safe_error(error: Exception, secrets: list[str] = ()) -> str:
    message = str(error)
    for value in sorted(secrets, key=len, reverse=True):
        if value:
            message = message.replace(value, "***")
    return re.sub(r"(?i)(bearer\s+)[^\s\"']+", r"\1***", message)


def copied(value: dict[str, Any]) -> dict[str, Any]:
    return copy.deepcopy(value)
