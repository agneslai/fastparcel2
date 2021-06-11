importScripts("https://www.gstatic.com/firebasejs/8.2.1/firebase-app.js");
importScripts("https://www.gstatic.com/firebasejs/8.2.1/firebase-messaging.js")

firebase.initializeApp({
    apiKey: "AIzaSyCEb6SDLKIy_iFKRv42_GcYLkQK1b1culI",
    authDomain: "fastparcel-ad5d0.firebaseapp.com",
    projectId: "fastparcel-ad5d0",
    storageBucket: "fastparcel-ad5d0.appspot.com",
    messagingSenderId: "1067918440460",
    appId: "1:1067918440460:web:a9ced16acf1142534b1629"
});

const messaging = firebase.messaging();