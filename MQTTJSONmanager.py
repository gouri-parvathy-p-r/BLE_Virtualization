# MQTTJSONmanager.py

import tempfile
import json

class MQTTJsonManager:
    def __init__(self):
        self.current_json_path = None

    def write_json(self, device_id, data):
        with tempfile.NamedTemporaryFile("w", delete=False, suffix="_update.json") as f:
            json.dump(data, f, indent=4)
            self.current_json_path = f.name
        print(f"[MQTTJsonManager] ✅ JSON written to {self.current_json_path}")
        return self.current_json_path

    def update_path(self, path):
        self.current_json_path = path
        print(f"[MQTTJsonManager] 🔄 Path updated to: {path}")

    def get_current_json_path(self):
        return self.current_json_path

# ✅ Shared instance
json_manager = MQTTJsonManager()
