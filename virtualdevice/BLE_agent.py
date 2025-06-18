import json
import socket
import time
from datetime import datetime  # Optional: for timestamped logs

from mqtt_client import MqttClient
from device_managers import start_virtual_device, update_ble_peripheral



# Load config
with open("config.json") as f:
    config = json.load(f)

AGENT_HOSTNAME = config.get("hostname") or socket.gethostname()
MQTT_BROKER = config["mqtt_broker"]

print(f"[AGENT] Hostname: {AGENT_HOSTNAME}")
print(f"[AGENT] MQTT Broker: {MQTT_BROKER}")
print("[AGENT] Starting main agent loop...")

mqtt = MqttClient(MQTT_BROKER, AGENT_HOSTNAME)
mqtt.connect()

 #  Make sure this import is correct

def on_data_message(client, userdata, msg):
    try:
        payload = msg.payload.decode()
        data = json.loads(payload)
        print(f"[AGENT] Received /data payload: {data}")
        update_ble_peripheral(data)
    except Exception as e:
        print(f"[AGENT]  Error handling data message: {e}")
        
    


def on_spec(client, userdata, msg):
    payload = msg.payload.decode()
    print(f"[AGENT]  Got spec message: {payload}")
    try:
        device_spec = json.loads(payload)
    except Exception as e:
        print(f"[AGENT] Failed to parse spec: {e}")
        return

    device_id = msg.topic.split('/')[-2]
    print(f"[AGENT] Starting /'{device_id}'/deviceready.")
    ready = start_virtual_device(device_id, device_spec, mqtt, AGENT_HOSTNAME)

    if ready:
        deviceready_topic = f"/{AGENT_HOSTNAME}/{device_id}/deviceready"
        print(f"[AGENT] Device '{device_id}' is ready. Publishing deviceready.")
        mqtt.publish(deviceready_topic, "")

        # Subscribe to the data topic for this device now
    # Subscribe to BOTH agent-hosted and backend-hosted data topic
    agent_data_topic = f"/{AGENT_HOSTNAME}/{device_id}/data"
    backend_data_topic = f"/{AGENT_HOSTNAME}/{device_id}/data"
    
    mqtt.subscribe_sync(agent_data_topic, on_data_message)
    mqtt.subscribe_sync(backend_data_topic, on_data_message)  



def handle_startdevice(device_id):
    spec_topic = f"/{AGENT_HOSTNAME}/{device_id}/spec"
    getspec_topic = f"/{AGENT_HOSTNAME}/{device_id}/getspec" 
    data_topic = f"/{AGENT_HOSTNAME}/{device_id}/data"   # Add this line

    print(f"[AGENT] Subscribing to spec topic '{spec_topic}' with callback")
    mqtt.subscribe_sync(spec_topic, on_spec)

    print(f"[AGENT] Requesting spec for device '{device_id}' on topic '{getspec_topic}'")
    mqtt.publish(getspec_topic, "")
    
    # Correctly subscribe to external data topic used in incoming MQTT
    external_data_topic = f"/gppr_doppelio/{device_id}/data"
    print(f"[AGENT] Subscribing to EXTERNAL data topic '{external_data_topic}'")
    mqtt.subscribe_sync(external_data_topic, on_data_message)

    
   
 

def on_startdevice(client, userdata, msg):
    payload = msg.payload.decode()
    print(f"[AGENT] Received /startdevice payload: {payload}")
    try:
        data = json.loads(payload)
        print(f"[AGENT] Decoded JSON: {data}")
    except Exception as e:
        print(f"[AGENT] JSON decode error: {e}")
        return

    for device_id in data.get("start", []):
        print(f"[AGENT] Handling start for device: {device_id}")
        handle_startdevice(device_id)

topic = f"/{AGENT_HOSTNAME}/startdevice"
mqtt.subscribe_sync(topic, on_startdevice)



print("[AGENT] Agent is now running. Press Ctrl+C to stop.")
try:
    while True:
        time.sleep(1)
except KeyboardInterrupt:
    print("[AGENT] Stopping agent...")
    mqtt.disconnect()


