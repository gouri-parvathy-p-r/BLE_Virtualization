# device_managers.py (MODIFIED)
import subprocess
import tempfile
import json
import os
import threading
import time

device_process_map = {}
from MQTTJSONmanager import json_manager  # ✅ Shared singleton


import tempfile

device_update_paths = {}  # device_id: temp_file_path

# device_managers.py

 # Global/shared instance

def update_ble_peripheral(data_json):
    print(f"[DEBUG] update_ble_peripheral CALLED with: {data_json}")

    device_id = data_json.get("device_id")
    if not device_id:
        print("[AGENT]  No device_id in data update")
        return

    # Save data to a temp file
    temp_path = json_manager.write_json(device_id, data_json)
    temp_data_path = json_manager.write_json(device_id, data_json)
    json_manager.update_path(temp_data_path)
    print(f'{temp_data_path}')
    # Send update path to BLE Peripheral
    process = device_process_map.get(device_id)
    if process and process.stdin:
        try:
            message = json.dumps({
                "device_id": device_id,
                "update_path": temp_path
            })
            process.stdin.write(message + "\n")
            process.stdin.flush()
            print(f"[AGENT]  Sent path to BLE_Peripheral for device {device_id}")
        except Exception as e:
            print(f"[AGENT]  Failed to send update path: {e}")
    

def start_virtual_device(device_id, device_spec, mqtt, hostname):
    print(f"[{device_id}] 🔧 Inside start_virtual_device()")

    with tempfile.NamedTemporaryFile("w", delete=False, suffix=".json") as f:
        json.dump(device_spec, f, indent=4)
        spec_path = f.name

    update_file_path = f"{device_id}_update.json"
    print(f"[{device_id}]  Launching BLE_Peripheral.py with spec: {spec_path}", flush=True)

    ready = False
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"

    try:
        process = subprocess.Popen(
            ["python", "-u", "BLE_Peripheral.py", spec_path, update_file_path],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            env=env
        )

        device_process_map[device_id] = process

        def log_output():
            nonlocal ready
            for line in process.stdout:
                print(f"[{device_id}] {line.strip()}", flush=True)
                if "BLE_PERIPHERAL_READY" in line:
                    print(f"[{device_id}]  Detected BLE_PERIPHERAL_READY", flush=True)
                    ready = True

        threading.Thread(target=log_output, daemon=True).start()

        for _ in range(100):
            if ready:
                break
            time.sleep(0.1)

        if not ready:
            print(f"[{device_id}]  Timed out waiting for BLE_PERIPHERAL_READY", flush=True)

        return ready

    except Exception as e:
        print(f"[{device_id}]  Error launching subprocess: {e}", flush=True)
        return False
