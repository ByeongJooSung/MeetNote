# AndroidManifest.xml에 추가할 내용

`npx cap add android` 뒤 `android/app/src/main/AndroidManifest.xml`을 열어
`<manifest>` 바로 안쪽(`<application>` 위)에 아래 권한을 추가하세요.

```xml
<uses-permission android:name="android.permission.RECORD_AUDIO" />
<uses-permission android:name="android.permission.MODIFY_AUDIO_SETTINGS" />
<uses-permission android:name="android.permission.INTERNET" />
```

Capacitor의 WebView는 앱에 RECORD_AUDIO 권한이 있으면 페이지의 마이크 요청
(getUserMedia)이 올 때 안드로이드 권한 창을 띄우고, 허용되면 웹페이지에 넘겨줍니다.
따로 자바 코드를 쓸 필요는 없습니다.

## .mnote 파일을 앱으로 열기 (선택)

`<activity ...>` 안에 아래 intent-filter를 넣으면 파일 관리자에서 .mnote를 눌렀을 때
MeetNote가 후보로 뜹니다. (앱에서 파일 내용을 읽으려면 추가 플러그인 코드가 필요하니
우선은 앱 안의 "열기" 버튼으로 파일을 고르는 방식을 권합니다.)

```xml
<intent-filter>
  <action android:name="android.intent.action.VIEW" />
  <category android:name="android.intent.category.DEFAULT" />
  <category android:name="android.intent.category.BROWSABLE" />
  <data android:scheme="content" android:mimeType="*/*" android:pathPattern=".*\\.mnote" />
</intent-filter>
```
