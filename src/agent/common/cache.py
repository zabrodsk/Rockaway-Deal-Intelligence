from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, Optional, TypeVar

T = TypeVar("T")

# #region agent log
def _debug_log(msg: str, data: dict) -> None:
    import json as _j
    _agent_dir = Path(__file__).resolve().parent.parent
    p = _agent_dir.parent.parent / ".cursor" / "debug-7ee34a.log"
    try:
        with p.open("a", encoding="utf-8") as f:
            f.write(_j.dumps({"sessionId": "7ee34a", "location": "cache.py", "message": msg, "data": data, "timestamp": __import__("time").time() * 1000}) + "\n")
    except Exception:
        pass
# #endregion

_CACHE_PATH: Path = Path(__file__).resolve().parent.parent / ".cache"
# #region agent log
try:
    _CACHE_PATH.mkdir(parents=True, exist_ok=True)
    _debug_log("cache init", {"_CACHE_PATH": str(_CACHE_PATH), "exists": _CACHE_PATH.exists(), "is_dir": _CACHE_PATH.is_dir(), "hypothesisId": "H1"})
except Exception as e:
    _debug_log("cache init FAILED", {"_CACHE_PATH": str(_CACHE_PATH), "error": str(e), "hypothesisId": "H2"})
    raise
# #endregion

logger = logging.getLogger(__name__)


def _load_cache(cache_name: str) -> Dict[str, Any]:
    """Load the on-disk cache file (returns empty dict if missing/corrupted)."""
    if not (_CACHE_PATH / cache_name).exists():
        return {}
    try:
        with (_CACHE_PATH / cache_name).open("r", encoding="utf-8") as fp:
            return json.load(fp)
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Could not load cache (%s). Re-creating.", exc)
        return {}


def _save_cache(cache: Dict[str, Any], cache_name: str) -> None:
    """Persist the cache dict to disk (overwrites previous file)."""
    full_path = _CACHE_PATH / cache_name
    # #region agent log
    _debug_log("_save_cache before open", {"full_path": str(full_path), "_CACHE_PATH_exists": _CACHE_PATH.exists(), "_CACHE_PATH_is_dir": _CACHE_PATH.is_dir(), "hypothesisId": "H3"})
    try:
    # #endregion
        with full_path.open("w", encoding="utf-8") as fp:
            json.dump(cache, fp, ensure_ascii=False, indent=2)
    # #region agent log
    except OSError as e:
        _debug_log("_save_cache open FAILED", {"full_path": str(full_path), "errno": getattr(e, "errno", None), "error": str(e), "hypothesisId": "H3"})
        raise
    # #endregion


def get(key: str, cache_name: str) -> Optional[T]:
    """Return cached value for *key* if present, else None."""
    return _load_cache(cache_name).get(key)


def set(key: str, val: Any, cache_name: str) -> None:
    """Store *value* under *key* in the on-disk cache."""
    cache = _load_cache(cache_name)
    cache[key] = val
    _save_cache(cache, cache_name)


if __name__ == "__main__":
    set("test", "test", "test")
    print(get("test", "test"))
