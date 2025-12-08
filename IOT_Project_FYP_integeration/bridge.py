import paho.mqtt.client as mqtt
import firebase_admin
from firebase_admin import credentials, db
import cloudinary
import cloudinary.uploader
import base64
import time
import os

# --- CONFIGURATION ---
MQTT_BROKER = "broker.hivemq.com"
MQTT_TOPIC_IMAGE = "eagleeye/camera/image"
# IMPORTANT: Ensure this file exists in the same directory
FIREBASE_KEY_PATH = "serviceAccountKey.json"

# --- CLOUDINARY CONFIG ---
# TODO: Replace with your actual Cloudinary credentials
cloudinary.config( 
  cloud_name = "dsq74osj5", 
  api_key = "454823543384692", 
  api_secret = "UPF9ZrxjhxYrttoVKerx2NeOPes",
  secure = True
)

# TODO: Replace with your actual database URL
DATABASE_URL = 'https://fyproject-2d3f6-default-rtdb.firebaseio.com/'

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
def on_connect(client, userdata, flags, rc):
    if rc == 0:
        print("Bridge Connected to HiveMQ! Listening for intruders...")
        client.subscribe(MQTT_TOPIC_IMAGE)
    else:
        print(f"Failed to connect to HiveMQ, return code {rc}")

def on_message(client, userdata, msg):
    print("Human Detected! Receiving Image Payload...")
    
    # 1. Decode Base64 Image
    try:
        if not msg.payload:
            print("Received empty payload.")
            return

        print(f"Payload received: {len(msg.payload)} bytes")
        
        image_data = base64.b64decode(msg.payload)
        print(f"Decoded data size: {len(image_data)} bytes")

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

        # 3. Upload to Cloudinary (DISABLED)
        # print("Uploading to Cloudinary...")
        # upload_result = cloudinary.uploader.upload(filename, folder="eagleeye_intrusions")
        # public_url = upload_result.get("secure_url")
        # print(f"Image Uploaded: {public_url}")
        
        # 4. Log to Realtime Database (DISABLED)
        # ref = db.reference('alerts')
        # ref.push({
        #     'timestamp': timestamp,
        #     'image_url': public_url,
        #     'type': 'Human Detected'
        # })
        # print("Alert logged to Realtime Database.")
        
        print("Database upload skipped (Local Only Mode).")
        
        # Cleanup (Disabled: User wants to keep local copies)
        # if os.path.exists(filename):
        #    os.remove(filename)
        
    except Exception as e:
        print(f"Error processing image: {e}")
        # Clean up if partial write happened
        if 'filename' in locals() and os.path.exists(filename):
             os.remove(filename)

# --- MAIN LOOP ---
client = mqtt.Client()
client.on_connect = on_connect
client.on_message = on_message

print(f"Connecting to MQTT Broker: {MQTT_BROKER}...")
try:
    client.connect(MQTT_BROKER, 1883, 60)
    client.loop_forever()
except Exception as e:
    print(f"Could not connect to MQTT Broker: {e}")
