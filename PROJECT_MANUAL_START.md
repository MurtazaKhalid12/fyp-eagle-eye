# Project Manual Start Guide

This guide provides step-by-step instructions to manually start the backend services for the EagleEye project (Mosquitto MQTT Broker and Python Bridge).

## Prerequisites
- Ensure **Mosquitto** is installed and added to your system PATH.
- Ensure **Python** is installed with the required dependencies (`paho-mqtt`, `firebase-admin`, `cloudinary`, `python-dotenv`).

---

## 1. Start Mosquitto Broker
The MQTT broker handles local communication between the ESP32 and the computer.

1.  Open a Command Prompt or PowerShell terminal.
2.  Navigate to the project integration directory:
    ```powershell
    cd c:\fyp-eagle-eye\IOT_Project_FYP_integeration
    ```
3.  Start Mosquitto with the local configuration file:
    ```powershell
    mosquitto -c mosquitto.conf -v
    ```
    *   **`-c mosquitto.conf`**: Tells Mosquitto to use the specific config file in this folder (ensure it points to your IP).
    *   **`-v`**: Verbose mode. Displays all logs, connection attempts, and messages in the terminal.

    > **Note:** Keep this terminal open. If you close it, the broker stops.

---

## 2. Start the Python Bridge
The bridge script listens for MQTT messages from the ESP32 and uploads images to Cloudinary/Firebase.

1.  Open a **new** terminal window (do not close the Mosquitto one).
2.  Navigate to the project integration directory:
    ```powershell
    cd c:\fyp-eagle-eye\IOT_Project_FYP_integeration
    ```
3.  Run the bridge script:
    ```powershell
    python bridge.py
    ```

---

## 3. Start the Mobile App (ADB / USB Debugging)
To run the mobile app on a physical Android device connected via USB.

1.  **Connect Device**: Plug in your Android phone and ensure "USB Debugging" is enabled in Developer Options.
2.  **Port Forwarding**:
    Allow your phone to access the development server (Metro) running on your PC's `localhost`.
    ```powershell
    adb reverse tcp:8081 tcp:8081
    ```
    *   If you have other local servers (e.g., a backend API on port 3000), reverse those too: `adb reverse tcp:3000 tcp:3000`.
3.  **Start Expo**:
    Open a new terminal and navigate to the mobile app directory:
    ```powershell
    cd c:\fyp-eagle-eye\mobile-app
    npm run android
    ```

---

## 4. Verification
*   **Mosquitto Terminal:** You should see a log entry similar to:
    > `New client connected from 127.0.0.1 as [ID] (p2, c1, k60).`
*   **Bridge Terminal:** You should see the success message:
    > `[Success] Bridge Connected to Local Mosquitto! Listening for intruders...`

## 5. Troubleshooting
*   **"Mosquitto not found"**: Ensure Mosquitto is in your system's Environment Variables (Path).
*   **Connection Refused**: Check if your firewall is blocking port 1883 or if the IP address in `mosquitto.conf` and `bridge.py` matches your computer's current IP.
