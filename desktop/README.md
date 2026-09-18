# MeetNote 데스크톱(exe) 배포

`MeetNote.exe` 하나로 웹 앱 + 발언자 구분 서버가 함께 실행됩니다. 실행하면 `http://localhost:8765/`가 브라우저로 열리고, 전사·발언자 구분이 같은 주소에서 처리돼 별도 설정이 필요 없습니다. 데이터는 PC 밖으로 나가지 않습니다.

## 빌드 (Windows)
```powershell
cd server
.\install.ps1                 # 가상환경 + 의존성
cd ..\desktop
.\build-exe.ps1               # → desktop\dist\MeetNote\MeetNote.exe
```
- `server\ffmpeg` 폴더에 ffmpeg.exe가 있으면 exe에 함께 들어갑니다(없으면 사용자 PC의 PATH에서 찾음).
- 결과물은 `dist\MeetNote` **폴더 전체**입니다(약 1~1.5GB, torch 포함). zip으로 묶어 배포하세요.
- 사용자는 압축을 풀고 `MeetNote.exe`만 실행하면 됩니다. Windows Defender SmartScreen 경고가 뜨면 "추가 정보 → 실행".

## 모델 동봉 (오프라인 배포)
처음 실행 때 Whisper `small`(약 460MB)을 내려받습니다. 인터넷이 없는 PC에 배포하려면 빌드한 PC에서 한 번 실행해 받은 캐시 폴더
`%USERPROFILE%\.cache\huggingface\hub` 를 함께 복사해 두세요(같은 경로).

## 옵션(환경변수 또는 실행 시)
`PORT=8765` 포트, `WHISPER_MODEL=small|medium`, `OPEN_BROWSER=0` 브라우저 자동 열기 끄기, `PRELOAD=0` 시작 시 모델 미리 받지 않기.

## Google 로그인
exe는 `http://localhost:8765` 에서 열리므로 Cloud Console "승인된 JavaScript 원본"에 `http://localhost:8765`를 추가하고 `web/config.js`에 클라이언트 ID를 넣은 뒤 빌드하면 됩니다.

## 크기를 줄이려면
torch(약 800MB)가 대부분입니다. 발언자 구분을 쓰지 않는 배포라면 `server\requirements.txt`에서 torch·resemblyzer·librosa·scipy를 빼고 빌드하면 300MB 안팎으로 줄어듭니다(전사만 동작, 발언자는 1명으로 표시).
