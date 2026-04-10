import json
import time
from typing import Any, Dict, List, Optional

from .config import DATA_FILE, logger


class ProfileStore:
    def __init__(self) -> None:
        try:
            DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            logger.error(f"Could not create data directory: {e}")
        self.profiles: List[Dict[str, Any]] = []
        self.active_id: Optional[str] = None
        self.load()

    def load(self) -> None:
        if DATA_FILE.exists():
            try:
                data = json.loads(DATA_FILE.read_text("utf-8"))
                self.profiles = data.get("profiles", [])
                self.active_id = data.get("active_id")
                logger.debug(f"Loaded {len(self.profiles)} profiles")
            except Exception as e:
                logger.error(f"Error loading profiles: {e}")

    def save(self) -> None:
        try:
            DATA_FILE.write_text(
                json.dumps({"profiles": self.profiles, "active_id": self.active_id}, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            logger.debug(f"Saved {len(self.profiles)} profiles")
        except Exception as e:
            logger.error(f"Error saving profiles: {e}")

    def add(self, p: Dict[str, Any]) -> Dict[str, Any]:
        p["id"] = str(int(time.time() * 1000))
        p.setdefault("rules", [])
        self.profiles.append(p)
        self.save()
        return p

    def update(self, pid: str, p: Dict[str, Any]) -> None:
        for i, pr in enumerate(self.profiles):
            if pr["id"] == pid:
                p["id"] = pid
                self.profiles[i] = p
        self.save()

    def delete(self, pid: str) -> None:
        self.profiles = [p for p in self.profiles if p["id"] != pid]
        if self.active_id == pid:
            self.active_id = None
        self.save()

    def get(self, pid: str) -> Optional[Dict[str, Any]]:
        return next((p for p in self.profiles if p["id"] == pid), None)

    def set_active(self, pid: Optional[str]) -> None:
        self.active_id = pid
        self.save()
