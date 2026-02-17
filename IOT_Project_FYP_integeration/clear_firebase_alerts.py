import firebase_admin
from firebase_admin import credentials, db
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Configuration
FIREBASE_KEY_PATH = "serviceAccountKey.json"
DATABASE_URL = os.getenv("FIREBASE_DATABASE_URL")

if not os.path.exists(FIREBASE_KEY_PATH):
    print(f"ERROR: {FIREBASE_KEY_PATH} not found.")
    exit(1)

if not DATABASE_URL:
    print("ERROR: FIREBASE_DATABASE_URL not found in .env")
    exit(1)

try:
    cred = credentials.Certificate(FIREBASE_KEY_PATH)
    firebase_admin.initialize_app(cred, {
        'databaseURL': DATABASE_URL
    })
    print("Firebase Admin Initialized.")
    
    # Delete the alerts node
    print("Deleting 'alerts' node from Firebase Realtime Database...")
    db.reference('alerts').delete()
    print("Successfully deleted all alerts.")
    
except Exception as e:
    print(f"Error: {e}")
