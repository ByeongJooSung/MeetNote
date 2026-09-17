#!/usr/bin/env bash
# MeetNote 안드로이드 APK 빌드 스크립트
# 필요: Node.js 18+, JDK 17, Android Studio(또는 Android SDK + ANDROID_HOME)
set -e
cd "$(dirname "$0")"
rm -rf www && mkdir www && cp -r ../web/. www/
rm -f www/serve.py
npm install
if [ ! -d android ]; then npx cap add android; echo; echo ">>> AndroidManifest.patch.md대로 권한을 추가한 뒤 이 스크립트를 다시 실행하세요."; exit 0; fi
npx cap sync android
cd android && ./gradlew assembleDebug
echo
echo "APK 완성: android/app/build/outputs/apk/debug/app-debug.apk"
echo "휴대폰에 옮겨 설치하거나: adb install -r app/build/outputs/apk/debug/app-debug.apk"
