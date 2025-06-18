import sys
import asyncio
import json
import logging
import threading
import time
import random

from bumble.transport import open_transport_or_link
from bumble.device import Device
from bumble.gatt import Service, Characteristic
from bumble.gatt import Service as _s
from bumble.core import AdvertisingData, UUID
from bumble.att import Attribute
from bumble import hci

import pandas as pd 

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)


# BLE disconnection reason map
BLE_REASON_MAP = {
    0x05: "Authentication Failure",
    0x08: "Connection Timeout",
    0x13: "Remote User Terminated Connection",
    0x16: "Connection Terminated by Local Host",
    0x3B: "Unacceptable Connection Interval",
    0x3D: "Connection Failed to be Established"
}

# Virtual Pairing Delegate to handle pairing and security


_s.GENERIC_ACCESS_SERVICE_UUID= 0x1234
_s.GENERIC_ATTRIBUTE_SERVICE_UUID= 0X1235
# Property map for GATT characteristics
PROPERTY_MAP = {
    "broadcast": Characteristic.Properties.BROADCAST,
    "read": Characteristic.Properties.READ,
    "write without response": Characteristic.Properties.WRITE_WITHOUT_RESPONSE,
    "write": Characteristic.Properties.WRITE,
    "notify": Characteristic.Properties.NOTIFY,
    "indicate": Characteristic.Properties.INDICATE,
    "authenticated signed writes": Characteristic.Properties.AUTHENTICATED_SIGNED_WRITES,
    "extended properties": Characteristic.Properties.EXTENDED_PROPERTIES
}

PERMISSION_MAP = {
    "read": Attribute.READABLE,
    "write": Attribute.WRITEABLE
}

class DynamicCharacteristic(Characteristic):
    def __init__(self, uuid, properties, permissions, initial_value, json_file , csv_file):
        self.properties_list = properties
        self.permissions_list = permissions
        self.json_file = json_file  # This should be the path to the JSON file, not a dictionary
        self.uuid_str = uuid
        self.value = initial_value
        self.csv_file = csv_file

        prop_flags = sum(getattr(Characteristic.Properties, prop.upper(), 0) for prop in properties)
        perm_flags = sum(PERMISSION_MAP.get(perm.lower(), 0) for perm in permissions)

        super().__init__(uuid, prop_flags, perm_flags, initial_value)
        
    def read_csv_data(self):
        """Reads the latest value for the characteristic from the CSV file."""
        if self.csv_file:
            try:
                df = pd.read_csv(self.csv_file)

                if self.name in df.columns:
                    latest_value = df[self.name].dropna().iloc[-1]
                    return int(latest_value)  
                else:
                    logger.error(f"Characteristic '{self.name}' not found in CSV columns.")
            except Exception as e:
                logger.error(f"Error reading CSV: {e}")
        return int(self.value)  

    async def read_csv_value(self, connection):
        """Returns the current value from CSV when read."""
        self.value = self.read_csv_data()
        logger.info(f"Read {self.uuid} ({self.name}): {self.value}")
        return bytes([self.value])  

    def load_initial_value_from_csv(self):
            """Loads initial value from CSV based on UUID."""
            if not self.csv_file:
                return None
            try:
                df = pd.read_csv(self.csv_file)
                match = df[df["uuid"] == self.uuid]  
                if not match.empty:
                    val = match.iloc[0]["value"]
                    if isinstance(val, str) and val.startswith("0x"):
                        return bytes.fromhex(val[2:])  
                    return val.encode() if isinstance(val, str) else bytes([int(val)])
            except Exception as e:
                logger.error(f"Error loading initial value for {self.uuid} from CSV: {e}")
            return None
        
    async def write_csv_value(self, connection, value):
        """Handles incoming write requests and logs them dynamically."""
        self.value = value  

        if self.csv_file:
            try:
                df = pd.read_csv(self.csv_file)
                if self.uuid in df["uuid"].values:
                    df.loc[df["uuid"] == self.uuid, "value"] = value.hex()  
                else:
                    new_entry = pd.DataFrame({"uuid": [self.uuid], "value": [value.hex()]})
                    df = pd.concat([df, new_entry], ignore_index=True)
                df.to_csv(self.csv_file, index=False)  
                decoded_value = value.decode('utf-8')
                self.value = decoded_value
                logger.info(f" WRITE to {self.uuid_str}: STRING='{decoded_value}'")
            except Exception as e:
                logger.error(f"Error updating CSV with new value: {e}")



    async def read_value(self, connection):
        """Read updated value from JSON file."""
        self.value = self.read_json_value()
        logger.info(f" Read {self.uuid_str}: {self.value}")
        return bytes(self.value) if isinstance(self.value, int) else self.value

    async def write_value(self, connection, value):
        """Handle app write to this characteristic and update JSON."""
        try:
            logger.info(f"Received write value: {value}")
            # Check if it's a UTF-8 encoded string
            decoded_value = value.decode('utf-8')
            self.value = decoded_value
            #logger.info(f"✍️ WRITE to {self.uuid_str}: STRING='{decoded_value}'")
        except UnicodeDecodeError:
            # Handle if it's not a string (maybe bytes)
            self.value = int.from_bytes(value, byteorder="little")
            logger.info(f"✍️ WRITE to {self.uuid_str}: HEX={hex(self.value)}")

        self.update_readings_json()
        await self.write_csv_value(connection, value)

    def read_json_value(self):
        """Load value from JSON for this characteristic UUID."""
        try:
            with open(self.json_file, "r") as f:
                data = json.load(f)

            for service in data.get("gatt", {}).get("services", []):
                for char in service.get("characteristics", []):
                    if char.get("uuid", "").lower() == self.uuid_str.lower():
                        value_str = char.get("initial_value", "0x00")
                        if isinstance(value_str, str) and value_str.startswith("0x"):
                            return bytes.fromhex(value_str[2:])
                        else:
                            return value_str.encode()

        except Exception as e:
            logger.error(f" Failed to read value from JSON for {self.uuid_str}: {e}")
        return self.value

    def update_readings_json(self):
        """Write current value to JSON for this UUID."""
        try:
            with open(self.json_file, "r") as f:
                data = json.load(f)

            updated = False
            for service in data.get("gatt", {}).get("services", []):
                for char in service.get("characteristics", []):
                    if char.get("uuid", "").lower() == self.uuid_str.lower():
                        char["initial_value"] = (
                            self.value if isinstance(self.value, str) else hex(self.value)
                        )
                        updated = True
                        logger.info(f"📄 JSON Updated: {self.uuid_str} -> {char['initial_value']}")
                        break
                if updated:
                    break

            if updated:
                with open(self.json_file, "w") as f:
                    json.dump(data, f, indent=4)
            else:
                logger.warning(f"⚠️ UUID {self.uuid_str} not found in JSON file!")

        except Exception as e:
            logger.error(f"❌ Failed to update JSON for {self.uuid_str}: {e}")
 

def load_services_from_json(config_file, readings_csv):
    """Load services and characteristics from the device_spec.json and a CSV for readings."""
    try:
        with open(config_file, 'r') as f:
            config = json.load(f)

        logger.info(f"Loaded config from {config_file}")
    except Exception as e:
        logger.error(f" Failed to load config from {config_file}: {e}")
        return []

    try:
        # Load readings from the CSV file
        readings_df = pd.read_csv(readings_csv)
        readings = dict(zip(readings_df['uuid'], readings_df['value']))
        logger.info(f"Loaded readings from {readings_csv}")
    except Exception as e:
        logger.warning(f" Could not load readings CSV: {e}")
        readings = {}

    services = []
    for service_data in config.get("gatt", {}).get("services", []):
        characteristics = []
        for char_data in service_data.get("characteristics", []):
            uuid = char_data["uuid"]
            props = sum(PROPERTY_MAP.get(p.lower(), 0) for p in char_data.get("properties", []))
            perms = sum(PERMISSION_MAP.get(p.lower(), 0) for p in char_data.get("permissions", []))
            
            # Set initial value from CSV or default value
            val = readings.get(uuid, char_data.get("initial_value", "0x00"))
            initial_value = bytes.fromhex(val[2:]) if isinstance(val, str) and val.startswith("0x") else val.encode()

            # Initialize DynamicCharacteristic with correct file path
            char = DynamicCharacteristic(
                uuid,
                properties=[p.lower() for p in char_data.get("properties", [])],
                permissions=[p.lower() for p in char_data.get("permissions", [])],
                initial_value=initial_value,
                json_file=config_file ,
                csv_file = readings_csv # Ensure this is a path, not a dictionary
            )

            characteristics.append(char)

        # Create service with the list of characteristics
        service = Service(service_data["uuid"], characteristics)
        services.append(service)

    return services

 
#Handle Notifications
from bumble.att import ATT_Handle_Value_Notification
async def monitor_and_notify(connection, device):
    attr = next((a for a in device.gatt_server.attributes
                 if hasattr(a, 'uuid') and (a.properties & Characteristic.Properties.NOTIFY)), None)
    print(attr)

    counter = 0
    
    value = bytes([0x01, counter % 256])
    await device.gatt_server.notify_subscriber(
        connection=connection,
        attribute=attr,
        value=value,
        force=True
    )
    logger.info(f"📡 Periodic Notify sent: {value.hex()}")
    counter += 1
    await asyncio.sleep(5)


async def send_handle_value_notification(connection, characteristic_handle, value):
    """
    Send a Handle Value Notification to the client.
    - connection: The active BLE connection.
    - characteristic_handle: The handle of the characteristic for which notification is sent.
    - value: The updated value of the characteristic.
    """
    # Ensure the characteristic handle is valid
    if characteristic_handle is None:
        logger.error(" Invalid characteristic handle.")
        return

    # Create the Handle Value Notification packet
    notification = ATT_Handle_Value_Notification(
        attribute_handle=characteristic_handle,
        value=value
    )

    # Send the notification
    connection.send(notification)
    logger.info(f"📡 Sent Handle Value Notification for handle={characteristic_handle:#04x} with value={value.hex()}")

async def update_characteristic_value(connection, characteristic_handle, new_value):
    """
    Update the characteristic value and send a Handle Value Notification to the client.
    - connection: The active BLE connection.
    - characteristic_handle: The handle of the characteristic.
    - new_value: The new value to be updated.
    """
    # Update the characteristic's value (in the virtual device)
    # Here we assume you are keeping track of the value (e.g., in a dictionary or class property)
    logger.info(f"🔄 Updating characteristic value for handle={characteristic_handle:#04x} to {new_value.hex()}")

    # Send the Handle Value Notification to the client
    await send_handle_value_notification(connection, characteristic_handle, new_value)

# Example function to simulate a value change (e.g., when device name changes)
async def change_device_name(connection, new_device_name):
    device_name_handle = 0x0002  # Example handle for Device Name characteristic (you need to get this from your GATT)
    new_value = new_device_name.encode('utf-8')

    # Trigger the characteristic update and notification
    await update_characteristic_value(connection, device_name_handle, new_value)
    
#from bumble.att import ATT_Notification

import asyncio

async def handle_client(reader, writer):
    addr = writer.get_extra_info('peername')
    print(f"Wi-Fi client connected: {addr}")
    while True:
        data = await reader.read(100)
        if not data:
            break
        print(f"Received: {data.decode()}")
        writer.write(data)
        await writer.drain()
    writer.close()

async def start_wifi_server(port=8888):
    server = await asyncio.start_server(handle_client, '0.0.0.0', port)
    async with server:
        await server.serve_forever()

# Run this server alongside your Bumble BLE device event loop



async def setup_virtual_device(config_file, readings_csv, transport_path, device_id):

    logger.info(f" Loading config: {config_file}")
    with open(config_file, 'r') as f:
        config = json.load(f)

    advertisement_data = config.get("advertisement", {})
   # setup = config.get("setup_complete:,"")
    local_name = advertisement_data.get("local_name", "Virtual_Device")
    flags = advertisement_data.get("flags", 0x06)
    service_uuids = advertisement_data.get("service_uuids", [])
    manufacturer_data = advertisement_data.get("manufacturer_data", [])
   
    irk = config.get("irk", None)
    
    
    async with await open_transport_or_link(transport_path) as hci_transport:
        logger.info("Netsim initialized")

        device = Device.from_config_file_with_hci(config_file, hci_transport.source, hci_transport.sink)
       
   
        await device.power_on()
      
      
        logger.info(" Loading GATT services...")
        services = load_services_from_json(config_file, readings_csv)
        for service in services:
            device.add_service(service)
        logger.info(" GATT services loaded")
        
        @device.on("connection")
        def on_connection(connection):
            global commissioning_connection_established
            commissioning_connection_established = True
            logger.info(" Device connected (BLE)")
            print("COMMISSIONING_DONE", flush=True)
          
        import asyncio

        async def monitor_connection(device):
            while True:
                if not device.connections:
                    await device.start_advertising()
                await asyncio.sleep(1)  # Check every second
        
        # In your main section:
        asyncio.create_task(monitor_connection(device))

        
        @device.on("disconnection")
        def on_disconnection(connection, reason):
            reason_name = hci.HCI_Connection_Termination_Reason.get(reason, "Unknown")
            logger.warning(f"🔌 Disconnected (reason={reason:#04x} - {reason_name})")
            device.start_advertising()
            
            # Only print when commissioning is actually complete
            #if commissioning_is_complete:
             #   print("COMMISSIONING_DONE", flush=True)


        service_uuid_bytes = b''.join(UUID(uuid).to_bytes() for uuid in service_uuids)
        manufacturer_bytes = b''.join(bytes.fromhex(m[2:]) for m in manufacturer_data if isinstance(m, str) and m.startswith("0x"))

        adv_fields = [
            (AdvertisingData.COMPLETE_LIST_OF_16_BIT_SERVICE_CLASS_UUIDS, service_uuid_bytes),
            (AdvertisingData.COMPLETE_LOCAL_NAME, local_name.encode("utf-8"))
        ]

        if sum(len(v) + 2 for _, v in adv_fields) + len(manufacturer_bytes) + 2 <= 31:
            adv_fields.append((AdvertisingData.MANUFACTURER_SPECIFIC_DATA, manufacturer_bytes))

        advertising_data = bytes(AdvertisingData(adv_fields))
        scan_response_data = bytes(AdvertisingData(adv_fields))

  

        setup_status = config.get("setup_complete", "NO")

        if setup_status == "NO":
            logger.info("Device is being set up for the first time.")
            device.advertising_data = advertising_data
            device.scan_response_data = scan_response_data
           
            config["setup_complete"] = "YES"
            with open(config_file, 'w') as f:
                json.dump(config, f, indent=4)
                
        logger.info(f" Advertising raw: {advertising_data.hex()} (len={len(advertising_data)})")
        logger.info(f" Scan response raw: {scan_response_data.hex()} (len={len(scan_response_data)})")

        print(device.advertising_data)
        logger.info(f" Now advertising as '{local_name}'")
        logger.info(" Virtual BLE Peripheral is running...")
        #device.advertising_type = AdvertisingType.UNDIRECTED_CONNECTABLE_SCANNABLE

        
        await device.start_advertising()
        # Just before waiting for event
        #update_file_path = sys.argv[5] if len(sys.argv) > 5 else "data.json"



        
        # Start JSON polling thread
      #   polling_thread = threading.Thread(
      #      target=poll_json_and_update_gatt,
       #     args=(update_file_path, device.gatt_server),
        #    daemon=True
        #)
        #polling_thread.start()

        
        await asyncio.sleep(40) 
        
        await asyncio.Event().wait()
        


if __name__ == '__main__':
    if len(sys.argv) < 5:
        print("Usage: python VirtualDevice.py <device_spec.json> <readings.csv> <usb:0>")
        sys.exit(1)

    asyncio.run(setup_virtual_device(sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]))
