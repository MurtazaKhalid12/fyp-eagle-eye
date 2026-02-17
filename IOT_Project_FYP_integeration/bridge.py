import paho.mqtt.client as mqtt
import firebase_admin
from firebase_admin import credentials, db
import cloudinary
import cloudinary.uploader
import base64
import time
import os
import threading

# --- CONFIGURATION ---
# --- CONFIGURATION ---
from dotenv import load_dotenv
load_dotenv() # Load variables from .env

MQTT_BROKER = "192.168.1.3"
MQTT_TOPIC_IMAGE = "eagleeye/camera/image"
# IMPORTANT: Ensure this file exists in the same directory
FIREBASE_KEY_PATH = "serviceAccountKey.json"

# --- CLOUDINARY CONFIG ---
cloudinary.config( 
  cloud_name = "dsq74osj5", 
  api_key = "454823543384692", 
  api_secret = "UPF9ZrxjhxYrttoVKerx2NeOPes",
  secure = True
)

# Verify Cloudinary config
print(f"Cloudinary configured with cloud_name: {cloudinary.config().cloud_name}")

# Database URL
DATABASE_URL = os.getenv("FIREBASE_DATABASE_URL")

# --- FIREBASE INIT ---
if not os.path.exists(FIREBASE_KEY_PATH):
    print(f"ERROR: {FIREBASE_KEY_PATH} not found. Please place your Firebase private key in this directory.")
    exit(1)

try:
    cred = credentials.Certificate(FIREBASE_KEY_PATH)
    firebase_admin.initialize_app(cred, {
        'databaseURL': DATABASE_URL
    })
    print("Firebase Admin Initialized (Database only).")
except Exception as e:
    print(f"Error initializing Firebase: {e}")
    exit(1)

# --- MQTT CALLBACKS ---
def on_connect(client, userdata, flags, rc, properties):
    if rc == 0:
        print("Bridge Connected to Local Mosquitto! Listening for intruders...")
        client.subscribe("#") # Debugging: Listen to EVERYTHING
    else:
        print(f"Failed to connect to HiveMQ, return code {rc}")

def on_subscribe(client, userdata, mid, reason_code_list, properties):
    print(f"Subscribed to topic! QoS: {reason_code_list[0]}")

# --- GLOBAL STATE ---
IS_ARMED = True # Default to True until Firebase says otherwise

# --- BACKGROUND HEARTBEAT & CONFIG LISTENER ---
def system_monitor():
    global IS_ARMED
    
    # 1. Listen for Arm/Disarm changes
    def on_armed_change(event):
        global IS_ARMED
        if isinstance(event.data, bool):
            IS_ARMED = event.data
            print(f"*** SYSTEM CONFIG CHANGED: Armed = {IS_ARMED} ***")
    
    db.reference('config/armed').listen(on_armed_change)
    
    # 2. Heartbeat Loop
    # 2. Heartbeat & Cleanup Loop
    last_heartbeat = 0
    while True:
        current_time = time.time()
        
        # Heartbeat every 15s
        if current_time - last_heartbeat > 15:
            try:
                db.reference('status/heartbeat').set(int(current_time))
                last_heartbeat = current_time
            except Exception as e:
                print(f"Heartbeat Error: {e}")

        # Cleanup Check every 5s
        try:
            requests = db.reference('deletion_requests').get()
            if requests:
                print(f"Found {len(requests)} deletion requests.")
                for req_key, req_data in requests.items():
                    req_public_id = req_data.get('public_id') if isinstance(req_data, dict) else req_data

                    if req_public_id:
                        print(f"Processing deletion: {req_public_id}...")
                        try:
                            cloudinary.uploader.destroy(req_public_id)
                            print(f"Deleted from Cloudinary: {req_public_id}")
                        except Exception as c_err:
                            print(f"Cloudinary Delete Error: {c_err}")
                    
                    # Remove processed request
                    db.reference(f'deletion_requests/{req_key}').delete()
        except Exception as e:
            print(f"Cleanup Error: {e}")
            
        time.sleep(5)

def on_message(client, userdata, msg):

    print(f"DEBUG: Received message on topic: '{msg.topic}'")
    if msg.topic != MQTT_TOPIC_IMAGE:
        print("Ignored non-image topic.")
        return

    # CHECK ARM STATUS
    if not IS_ARMED:
        print(">>> SYSTEM DISARMED: Ignoring intrusion detected. <<<")
        return

    print("Human Detected! Receiving Image Payload...")
    
    # 1. Process Raw Binary JPEG (No Base64)
    try:
        if not msg.payload:
            print("Received empty payload.")
            return

        print(f"Payload received: {len(msg.payload)} bytes")
        
        image_data = msg.payload  # Already binary JPEG
        print(f"Image data size: {len(image_data)} bytes")

        # Check for JPEG Magic Bytes (FF D8)
        if len(image_data) > 2:
            if image_data[0] == 0xFF and image_data[1] == 0xD8:
                print("Header Check: Valid JPEG Magic Bytes found.")
            else:
                print(f"Header Check: INVALID. Starts with {hex(image_data[0])} {hex(image_data[1])}")
        
        timestamp = int(time.time())
        
        # Ensure 'captures' folder exists
        if not os.path.exists("captures"):
            os.makedirs("captures")
            
        filename = f"captures/intruder_{timestamp}.jpg"
        
        # 2. Save Locally (Permanent)
        with open(filename, "wb") as f:
            f.write(image_data)
        print(f"Image saved locally to {filename} ({os.path.getsize(filename)} bytes)")

        # 3. Upload to Cloudinary
        print("Uploading to Cloudinary...")
        upload_result = cloudinary.uploader.upload(filename, folder="eagleeye_intrusions")
        public_url = upload_result.get("secure_url")
        public_id = upload_result.get("public_id")
        print(f"Image Uploaded: {public_url}")
        
        # 4. Log to Realtime Database
        ref = db.reference('alerts')
        ref.push({
            'timestamp': timestamp,
            'image_url': public_url,
            'public_id': public_id,
            'type': 'Human Detected'
        })
        print("Alert logged to Realtime Database.")
        
        print("Upload complete!")
        
        # Cleanup (Disabled: User wants to keep local copies)
        # if os.path.exists(filename):
        #    os.remove(filename)
        
    except Exception as e:
        print(f"Error processing image: {e}")
        # Clean up if partial write happened
        if 'filename' in locals() and os.path.exists(filename):
             os.remove(filename)

# --- MAIN LOOP ---
client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
client.on_connect = on_connect
client.on_subscribe = on_subscribe
client.on_message = on_message

# Start Monitor Thread
monitor_thread = threading.Thread(target=system_monitor, daemon=True)
monitor_thread.start()

print(f"Connecting to MQTT Broker: {MQTT_BROKER}...")
try:
    client.connect(MQTT_BROKER, 1883, 60)
    client.loop_forever()
except Exception as e:
    print(f"Could not connect to MQTT Broker: {e}")
