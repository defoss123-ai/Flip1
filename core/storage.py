import json
from dataclasses import asdict
from pathlib import Path

from core.models import DEFAULT_VISIBLE_COLUMNS, Settings

DATA_DIR = Path("data")
WATCHLIST_PATH = DATA_DIR / "watchlist.json"
SETTINGS_PATH = DATA_DIR / "settings.json"

DEFAULT_WATCHLIST = ["BTCUSDT", "ETHUSDT"]
DEFAULT_SETTINGS = asdict(Settings())


def ensure_data_dir() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    if not WATCHLIST_PATH.exists():
        save_json(WATCHLIST_PATH, DEFAULT_WATCHLIST)
    if not SETTINGS_PATH.exists():
        save_json(SETTINGS_PATH, DEFAULT_SETTINGS)


def load_json(path: Path, default):
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data
    except (json.JSONDecodeError, OSError):
        save_json(path, default)
        return default


def save_json(path: Path, payload) -> None:
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def load_watchlist() -> list[str]:
    ensure_data_dir()
    data = load_json(WATCHLIST_PATH, DEFAULT_WATCHLIST)
    if isinstance(data, list):
        symbols = [str(item).strip().upper() for item in data if str(item).strip()]
        if symbols:
            return symbols

    save_json(WATCHLIST_PATH, DEFAULT_WATCHLIST)
    return DEFAULT_WATCHLIST.copy()


def save_watchlist(wl: list[str]) -> None:
    ensure_data_dir()
    save_json(WATCHLIST_PATH, wl)


def _normalize_pinned_symbols(payload) -> list[str]:
    if not isinstance(payload, list):
        return []
    normalized: list[str] = []
    seen: set[str] = set()
    for item in payload:
        symbol = str(item).strip().upper()
        if not symbol or symbol in seen:
            continue
        seen.add(symbol)
        normalized.append(symbol)
    return normalized


def _normalize_visible_columns(payload) -> list[str]:
    if not isinstance(payload, list):
        payload = DEFAULT_VISIBLE_COLUMNS

    normalized: list[str] = []
    seen: set[str] = set()
    allowed = set(DEFAULT_VISIBLE_COLUMNS)
    for item in payload:
        col = str(item).strip()
        if col not in allowed or col in seen:
            continue
        seen.add(col)
        normalized.append(col)

    if "Symbol" not in normalized:
        normalized.insert(0, "Symbol")

    if not normalized:
        return DEFAULT_VISIBLE_COLUMNS.copy()
    return normalized


def load_settings() -> Settings:
    ensure_data_dir()
    raw_data = load_json(SETTINGS_PATH, DEFAULT_SETTINGS)

    settings_dict = DEFAULT_SETTINGS.copy()
    if isinstance(raw_data, dict):
        settings_dict.update(raw_data)
        settings_dict["entry_mode"] = str(raw_data.get("entry_mode", "mid")).lower()
        if settings_dict["entry_mode"] not in ("mid", "best"):
            settings_dict["entry_mode"] = "mid"
        settings_dict["use_real_binance"] = raw_data.get("use_real_binance", False)
        settings_dict["use_real_mexc"] = raw_data.get("use_real_mexc", False)
        settings_dict["pinned_symbols"] = _normalize_pinned_symbols(raw_data.get("pinned_symbols", []))
        settings_dict["compact_mode"] = bool(raw_data.get("compact_mode", False))
        settings_dict["visible_columns"] = _normalize_visible_columns(raw_data.get("visible_columns", DEFAULT_VISIBLE_COLUMNS))
    else:
        settings_dict["pinned_symbols"] = []
        settings_dict["compact_mode"] = False
        settings_dict["visible_columns"] = DEFAULT_VISIBLE_COLUMNS.copy()

    settings = Settings(**settings_dict)
    save_json(SETTINGS_PATH, asdict(settings))
    return settings


def save_settings(settings) -> None:
    ensure_data_dir()
    if isinstance(settings, Settings):
        payload = asdict(settings)
    else:
        payload = dict(settings)
    payload["pinned_symbols"] = _normalize_pinned_symbols(payload.get("pinned_symbols", []))
    payload["compact_mode"] = bool(payload.get("compact_mode", False))
    payload["visible_columns"] = _normalize_visible_columns(payload.get("visible_columns", DEFAULT_VISIBLE_COLUMNS))
    save_json(SETTINGS_PATH, payload)
