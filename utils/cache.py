import os
import json
import time
from typing import Any, Optional

class FileCache:
    def __init__(self, base_dir: str, ttl_seconds: int = 5):
        self.base_dir = base_dir
        self.ttl = ttl_seconds
        os.makedirs(self.base_dir, exist_ok=True)

    def _path(self, key: str) -> str:
        safe = key.replace("/", "_")
        return os.path.join(self.base_dir, f"{safe}.json")

    def get(self, key: str) -> Optional[Any]:
        path = self._path(key)
        if not os.path.exists(path):
            return None
        stat = os.stat(path)
        age = time.time() - stat.st_mtime
        if age > self.ttl:
            return None
        with open(path, "r") as f:
            return json.load(f)

    def set(self, key: str, value: Any):
        path = self._path(key)
        with open(path, "w") as f:
            json.dump(value, f, default=str)