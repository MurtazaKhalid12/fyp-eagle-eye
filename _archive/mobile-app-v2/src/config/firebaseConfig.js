// Firebase - using tree-shakeable modular imports for faster bundling
import { initializeApp } from "firebase/app";
import { getDatabase } from "firebase/database";

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
