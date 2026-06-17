# Welcome to your Expo app 👋

This is an [Expo](https://expo.dev) project created with [`create-expo-app`](https://www.npmjs.com/package/create-expo-app).

## Run on Android Device via USB (ADB)
This is the fastest and most stable way to develop.

### 1. Enable Developer Options on Android
1.  Go to **Settings > About Phone**.
2.  Tap **Build Number** 7 times until it says "You are a developer".
3.  Go back to **Settings > System > Developer Options**.
4.  Enable **USB Debugging**.

### 2. Connect & Verify
1.  Plug your phone into the PC via USB.
2.  Tap "Allow USB Debugging" on your phone if prompted.
3.  Run this in your terminal to verify connection:
    ```bash
    adb devices
    ```
    *You should see your device ID listed.*

### 3. Setup Port Forwarding
This allows your phone to access the Expo server running on your PC's `localhost`.
```bash
adb reverse tcp:8081 tcp:8081
```

### 4. Start the App
Run the android script, which auto-detects the connected device:
```bash
npm run android
```
*This will open the Expo Go app on your phone and load the bundle.*

You can start developing by editing the files inside the **app** directory. This project uses [file-based routing](https://docs.expo.dev/router/introduction).

## Get a fresh project

When you're ready, run:

```bash
npm run reset-project
```

This command will move the starter code to the **app-example** directory and create a blank **app** directory where you can start developing.

## Learn more

To learn more about developing your project with Expo, look at the following resources:

- [Expo documentation](https://docs.expo.dev/): Learn fundamentals, or go into advanced topics with our [guides](https://docs.expo.dev/guides).
- [Learn Expo tutorial](https://docs.expo.dev/tutorial/introduction/): Follow a step-by-step tutorial where you'll create a project that runs on Android, iOS, and the web.

## Join the community

Join our community of developers creating universal apps.

- [Expo on GitHub](https://github.com/expo/expo): View our open source platform and contribute.
- [Discord community](https://chat.expo.dev): Chat with Expo users and ask questions.
