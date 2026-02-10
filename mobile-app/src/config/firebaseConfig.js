// Import the functions you need from the SDKs you need
import { initializeApp } from "firebase/app";
import { getDatabase } from "firebase/database";

// TODO: Replace the following with your app's Firebase project configuration
// You can get this from the Firebase Console > Project Settings > General > Your apps > Web app
const firebaseConfig = {
    apiKey: "AIzaSyDRUXoPveXHlMq-PqLEV4As7Ag-6NSPSuk",
    authDomain: "fyproject-2d3f6.firebaseapp.com",
    databaseURL: "https://fyproject-2d3f6-default-rtdb.firebaseio.com",
    projectId: "fyproject-2d3f6",
    storageBucket: "fyproject-2d3f6.firebasestorage.app",
    messagingSenderId: "896018763410",
    appId: "1:896018763410:android:abc708573f8390499fe04b"
};

// Initialize Firebase
const app = initializeApp(firebaseConfig);
const database = getDatabase(app);

export { app, database };
