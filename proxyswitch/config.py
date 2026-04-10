import logging
import sys
from pathlib import Path
from typing import List


APP_NAME = "ProxySwitch"
APP_VERSION = "2.0.0"
DATA_FILE = Path.home() / ".proxyswitch" / "profiles.json"
LOCAL_PROXY_PORT = 18080

PROXY_TYPES = ["HTTP", "HTTPS", "SOCKS5"]

C = {
    "bg": "#0a0d12",
    "panel": "#0f1318",
    "card": "#151b23",
    "card_hover": "#1a2130",
    "card_active": "#0d1f35",
    "border": "#21262d",
    "border_act": "#388bfd",
    "accent": "#58a6ff",
    "accent2": "#79c0ff",
    "accent_dim": "#0d2147",
    "green": "#3fb950",
    "green_dim": "#0f2d1a",
    "red": "#f85149",
    "red_dim": "#3a0f0d",
    "yellow": "#e3b341",
    "yellow_dim": "#2e2005",
    "text": "#cdd9e5",
    "text_muted": "#768390",
    "text_dim": "#444c56",
}

S_IDLE = "idle"
S_OK = "ok"
S_FAIL = "fail"
S_TESTING = "testing"

TYPE_BADGE = {
    "HTTP": (C["accent"], C["accent_dim"]),
    "HTTPS": (C["green"], C["green_dim"]),
    "SOCKS5": (C["yellow"], C["yellow_dim"]),
}
S_DOT = {S_IDLE: C["text_dim"], S_OK: C["green"], S_FAIL: C["red"], S_TESTING: C["yellow"]}


def setup_logger() -> logging.Logger:
    log_dir = Path.home() / ".proxyswitch"
    log_handlers: List[logging.Handler] = []
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        log_handlers.append(logging.FileHandler(log_dir / "debug.log"))
    except Exception:
        log_handlers.append(logging.StreamHandler(sys.stderr))

    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=log_handlers,
    )
    return logging.getLogger(__name__)


logger = setup_logger()
