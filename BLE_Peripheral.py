import sys
import os
import json
import subprocess

# Force stdout to be line-buffered and unbuffered env
sys.stdout.reconfigure(line_buffering=True)
os.environ["PYTHONUNBUFFERED"] = "1"

#print("BLE_PERIPHERAL_READY", flush=True)

DEVICE_SPEC_PATH = sys.argv[1] 

import threading
import time

device_id = sys.argv[2] 

device_id = sys.argv[2]  # Initial fallback

try:
    with open(DEVICE_SPEC_PATH, "r") as f:
        spec = json.load(f)
        device_id_from_spec = spec.get("device_id")
        if device_id_from_spec:
            device_id = device_id_from_spec
except Exception as e:
    print(f" Failed to read device_id from spec: {e}")

update_file = f"data.json"  # ← MUST be outside the try-except


# Global variable to store the update path
current_update_path = "data.json"

def handle_stdin_updates():
    for line in sys.stdin:
        try:
            print("[BLE_Peripheral] 🛰️ Received raw stdin:", line.strip())
            update = json.loads(line.strip())
            device_id = update.get("device_id")
            update_path = update.get("update_path")
            if not device_id or not update_path:
                print("[BLE_Peripheral] ❌ Missing device_id or update_path")
                continue

            # ✅ Confirm file path received
            print(f"[BLE_Peripheral] Update path received: {update_path}")

            with open(f"{device_id}_update_path.txt", "w") as f:
                f.write(update_path)
            print(f"[BLE_Peripheral] ✅ Saved update path for {device_id}")

        except Exception as e:
            print(f"[BLE_Peripheral] ❌ Error parsing stdin update: {e}")


def apply_updates_from_file(device_spec_path, update_file):
    try:
        with open(update_file, "r") as f:
            updates = json.load(f)
        with open(device_spec_path, "r") as f:
            spec = json.load(f)

        changed = False
        for service in spec.get("gatt", {}).get("services", []):
            for char in service.get("characteristics", []):
                uuid = char.get("uuid")
                for service_uuid, chars in updates.items():
                    if uuid in chars:
                        new_value = chars[uuid]
                        if char.get("initial_value") != new_value:
                            print(f"[dev123]  Updating {uuid} to {new_value}")
                            char["initial_value"] = new_value
                            changed = True
        if changed:
            with open(device_spec_path, "w") as f:
                json.dump(spec, f, indent=4)
            print("[dev123] ✅ Updated spec with new values.")
    except Exception as e:
        print(f"[dev123] ❌ Error applying updates: {e}")

def start_update_loop(device_spec_path, update_file, interval=1):
    def loop():
        while True:
            apply_updates_from_file(device_spec_path, update_file)
            time.sleep(interval)
    threading.Thread(target=loop, daemon=True).start()

def read_setup_status():
    try:
        with open(DEVICE_SPEC_PATH, "r") as f:
            data = json.load(f)
        return data.get("setup_complete", "NO").upper()
    except Exception:
        return "NO"
    
def read_yes_status():
    try:
        with open(DEVICE_SPEC_PATH, "r") as f:
            data = json.load(f)
        return data.get("setup_complete", "YES").upper()
    except Exception:
        return "YES"

def set_setup_status(status):
    try:
        with open(DEVICE_SPEC_PATH, "r") as f:
            data = json.load(f)
        data["setup_complete"] = status.upper()
        with open(DEVICE_SPEC_PATH, "w") as f:
            json.dump(data, f, indent=4)
    except Exception as e:
        print(f"❌ Failed to update setup status: {e}")
        
def set_value_status(status):
    try:
        with open(DEVICE_SPEC_PATH, "r") as f:
            data = json.load(f)

        services = data.get("gatt", {}).get("services", [])
        for service in services:
            for characteristic in service.get("characteristics", []):
                characteristic["initial_value"] = status.upper()

        with open(DEVICE_SPEC_PATH, "w") as f:
            json.dump(data, f, indent=4)

        print("✅ All characteristic initial values reset.")
    except Exception as e:
        print(f"❌ Failed to reset initial values: {e}")



setup_status = read_setup_status()

if len(sys.argv) > 2 and sys.argv[2] == "--reset":
    print(" Resetting device to commissioning mode...")
    set_setup_status("NO")
    set_value_status("0x00")
    print("✅ Device reset complete. Ready for commissioning.")

setup_status = read_setup_status()

if setup_status == "NO":
    print("Starting commissioning mode...")
    update_file = f"{device_id}_update.json"
    commissioning_process = subprocess.Popen(

    ["python", "VirtualDevice.py", DEVICE_SPEC_PATH, "Readings2.csv", "android-netsim", device_id],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True
    )
    os.environ['PYTHONUNBUFFERED'] = "1"
    print("BLE_PERIPHERAL_READY", flush=True)

    for line in commissioning_process.stdout:
        print("[DEVICE]", line.strip())
        if "Disconnected from" in line or "reason:" in line:  # <- Bumble log disconnection pattern
            print(" COMMISSIONING DONE (via disconnect log)")
            commissioning_process.terminate()
            commissioning_process.wait()
            set_setup_status("YES")
            break


print(" Starting normal mode...")


normal_process = subprocess.Popen( ["python", "VirtualDevice.py", DEVICE_SPEC_PATH, "Readings2.csv", "android-netsim", device_id])
normal_process.wait()

setup_status_yes = read_yes_status()
print("YES YES YES YES YES ")

if setup_status_yes == "YES":
    print(" DISCONNECTED (via disconnect log)")
    for line in normal_process.stdout:
        if "DISCONNECTION:" in line or "reason=" in line:  # <- Bumble log disconnection pattern
            print(" DISCONNECTED (via disconnect log)")
            normal_process.terminate()
           
            normal_process1 = subprocess.Popen( ["python", "VirtualDevice.py", DEVICE_SPEC_PATH, "Readings2.csv", "usb:0", device_id])
            normal_process1.wait()
            



