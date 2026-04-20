# ⚡ The F.L.A.S.H.

### Fraud Locator And Scam Hunter

**The F.L.A.S.H.** is an Android-based mobile application designed to help users detect and prevent scams across multiple communication channels in real time.

---

## 📌 Overview

The project aims to provide a **comprehensive anti-fraud solution** by integrating message monitoring, email scanning, call identification, and AI-based risk analysis into a single platform.

Users can instantly identify suspicious content, receive warnings, and contribute to a community-driven fraud database.

---

## 🎯 Key Features

### 🔐 User Authentication

* Email & password registration/login
* Google OAuth / Facebook Login
* Password reset with OTP verification
* Biometric login (Fingerprint / Face ID)

### 💬 Message Monitoring

* Monitor messages from platforms (LINE, SMS, WhatsApp, Messenger)
* AI-based scam detection with risk scoring (0–100)
* Risk classification: **High / Medium / Safe**
* Conversation-level threat analysis

### 📧 Email Scanning

* Gmail / Outlook integration (planned)
* Phishing email detection
* Keyword-based search

### 📞 Call Identification

* Detect suspicious incoming calls
* Search phone numbers with risk levels
* Community-based reports and scam classification

### 🌐 Community Reporting

* Quick and detailed scam reporting
* Upload evidence (screenshots, recordings)
* Anonymous reporting option
* Share scam warnings across platforms

### ⚙️ Settings & Personalization

* Monitoring toggles (messages, emails, calls)
* Notification controls
* Security settings (biometric login)
* Account management

---

## 🏗️ System Architecture

The system follows a **Client-Server Architecture**:

* **Frontend**: Android App (Kotlin, Jetpack)
* **Backend**: RESTful API Server (planned)
* **Database**:

  * Local: SQLite (Room)
  * Cloud: Remote database (planned)
* **AI Service**:

  * Risk analysis model (planned)

---

## 🧱 Tech Stack

### 📱 Mobile (Android)

* Kotlin 1.9+
* Android SDK 34
* Android Jetpack Components
* Material Design 3

### 🧰 Libraries

* Retrofit — API communication
* Room — Local database ORM
* BiometricPrompt — Biometric authentication
* Navigation Component — App navigation
* RecyclerView — UI lists

### 🖥️ Development Tools

* Android Studio (Hedgehog 2023.1+)
* Gradle 8.x
* Git + GitHub

---

## 📊 Core Modules

| Module             | Description                 |
| ------------------ | --------------------------- |
| Authentication     | Login, registration, OAuth  |
| Message Monitoring | Detect scam messages        |
| Email Scanner      | Identify phishing emails    |
| Call Detection     | Analyze phone numbers       |
| Reporting System   | Community fraud reporting   |
| Settings           | User preferences & security |

---

## 🔄 Workflow Example

### Message Risk Analysis

1. Capture incoming message
2. Extract content
3. Send to AI model
4. Receive risk score
5. Classify risk level
6. Notify user if high risk
7. Store result locally & sync to cloud

---

## 🔐 Security Considerations

* Password hashing with salt
* HTTPS encrypted API communication
* Secure OAuth token storage (Android Keystore)
* OTP expiration mechanism
* Biometric authentication support

---

## ⚡ Performance Goals

* App launch time < 3 seconds
* Risk analysis response < 2 seconds
* Local database query < 500 ms
* APK size < 50 MB

---

## 📁 Project Structure (Simplified)

```
app/
 ├── ui/                # Activities & Fragments
 ├── data/              # Repository, Room DB, API
 ├── domain/            # Business logic
 ├── utils/             # Helpers
 └── di/                # Dependency Injection (planned)
```

---

## 🚧 Current Status

* ✅ UI implementation completed
* ✅ System architecture defined
* ⏳ Backend API integration (in progress)
* ⏳ AI model integration (planned)
* ⏳ Database integration (in progress)

---

## 🗂️ Version

**v1.0 (April 2026)**
First project report — UI structure completed, requirements defined.

---

## 👥 Team Members

* 施辰勳
* 陳冠禎
* 曾奕晟
* 顏瑋辰

---

## 👨‍🏫 Advisor

**Prof. 李春良**

---

## 📜 License

This project is for academic purposes (Chang Gung University, Department of Computer Science).

---

## 💡 Future Work

* AI model deployment
* Real-time backend integration
* Expanded scam database
* Cross-platform support (iOS)
* Advanced analytics dashboard

---

## 🚀 Vision

To build a **smart, community-driven anti-fraud ecosystem** that protects users from evolving digital scams in real time.
