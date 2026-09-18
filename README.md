# MeetNote — 녹음과 함께 쓰는 회의록

녹음(또는 시계)에 맞춰 시점이 붙는 회의 메모, 따라 쓰기 재생, 실시간 전사, AI 회의록 초안(Claude · LM Studio · Ollama),
표·서식 편집, `.mnote` 저장, 한글 `.hwpx` 내보내기까지 한 파일(`web/index.html`)로 동작하는 웹 앱입니다.

```
web/                 배포 대상 (정적 파일, 빌드 없음)
  index.html         앱 본체
  config.js          배포 설정(Google 클라이언트 ID, 로그인 필수 여부)
  manifest.webmanifest, sw.js, icons/   PWA(홈 화면 설치·오프라인)
  serve.py           로컬 테스트 서버
android-capacitor/   APK 빌드 설정 (Capacitor)
server/              발언자 구분·전사 파이썬 서비스 (faster-whisper + pyannote/resemblyzer)
docs/LOCAL-LLM.md    LM Studio / Ollama 연결 방법
docs/MNOTE-FORMAT.md .mnote 파일 구조
publish.sh           GitHub 저장소 생성 + Pages 배포 한 번에
.github/workflows/   GitHub Pages 자동 배포, APK 빌드
```

## 1. GitHub에 올리고 자동 배포하기 (10분)

가장 빠른 길: [GitHub CLI](https://cli.github.com)를 설치하고 `gh auth login` 후
```bash
./publish.sh meetnote        # 저장소 생성 → push → Pages 켜기까지 한 번에
```
수동으로 하려면:

```bash
# 1) 이 폴더를 git 저장소로
cd meetnote
git init -b main
git add .
git commit -m "MeetNote 초기 커밋"

# 2) GitHub에서 빈 저장소를 만든 뒤 (예: yourname/meetnote)
git remote add origin https://github.com/yourname/meetnote.git
git push -u origin main
```

3) GitHub 저장소 **Settings → Pages → Build and deployment → Source**를 **GitHub Actions**로 바꿉니다.
4) **Actions** 탭에서 "Deploy to GitHub Pages"가 초록색이 되면 `https://yourname.github.io/meetnote/` 에서 열립니다.
   이후 `web/`을 고쳐 `git push`할 때마다 자동 배포됩니다(서비스 워커 캐시도 자동으로 새 버전).

> GitHub CLI가 있다면 2)는 `gh repo create meetnote --public --source=. --push` 한 줄로 끝납니다.

### 다른 호스팅
- **Netlify**: 저장소 연결 시 `netlify.toml`을 자동 인식(publish = web). 또는 https://app.netlify.com/drop 에 `web` 폴더 드래그.
- **Vercel**: 저장소 import → Output Directory가 `web`으로 잡힙니다(`vercel.json`).
- **Cloudflare Pages**: Build command 없음, Output directory `web`.

## 2. 로컬에서 테스트
```bash
python3 web/serve.py        # http://localhost:8080
```
마이크는 https 또는 localhost에서만 열립니다. 휴대폰 테스트는 배포 주소를 쓰거나 `npx cloudflared tunnel --url http://localhost:8080`.

## 3. 한 번에 배포: exe / 도커
- **Windows exe** (`desktop/`): 웹 앱 + 발언자 구분 서버를 하나로 묶습니다. `server\install.ps1` → `desktop\build-exe.ps1` → `desktop\dist\MeetNote\MeetNote.exe`. 실행하면 브라우저가 열리고 분석 서버가 자동 연결됩니다. 자세한 건 [desktop/README.md](desktop/README.md).
- **도커 / 클라우드**: `Dockerfile` 하나로 웹과 API를 같이 띄웁니다. `docker build -t meetnote . && docker run -p 8765:8765 meetnote` → http://localhost:8765. Render는 저장소 연결 후 Blueprint(`render.yaml`)로 배포됩니다(CPU 인스턴스는 전사가 느립니다).
- 앱은 같은 주소에 `/health`가 있으면 그 서버를 자동으로 씁니다.

## 4. 안드로이드 APK
- 손쉬운 방법: GitHub **Actions → Build Android APK → Run workflow** → 완료 후 Artifacts에서 `meetnote-debug-apk` 내려받기(PC에 아무것도 설치 안 해도 됨).
- 직접 빌드: `android-capacitor/README`(build-apk.sh) 참고. Node 18+, JDK 17, Android SDK 필요.

## 5. Google 로그인 (OAuth)
1. https://console.cloud.google.com → **API 및 서비스 → 사용자 인증 정보 → 사용자 인증 정보 만들기 → OAuth 클라이언트 ID**
   - 처음이면 **OAuth 동의 화면**을 먼저 만듭니다(외부, 앱 이름 MeetNote, 범위는 기본 email/profile).
2. 애플리케이션 유형 **웹 애플리케이션**, **승인된 JavaScript 원본**에 추가:
   - `https://아이디.github.io` (배포 주소, 경로 없이 원본만)
   - `http://localhost:8080` (로컬 테스트)
   리디렉션 URI는 필요 없습니다(Google Identity Services 사용).
3. 발급된 **클라이언트 ID**를 `web/config.js`의 `googleClientId`에 넣고 push. (파일을 고치지 않고 앱 헤더의 **로그인** 버튼 → 설정 창에 붙여 넣어도 되지만, 그 경우 그 브라우저에서만 적용됩니다.)
4. 배포 주소에서 열면 로그인 화면이 먼저 뜨고, Google 계정으로 로그인하면 앱이 열립니다.
   로그인 정보(이름·이메일·사진)는 브라우저에만 저장되고 서버로 보내지 않습니다.
   `requireLogin: false`로 두면 로그인 없이도 쓸 수 있고 헤더에 계정만 표시됩니다.
   `file://`로 연 경우와 Claude 아티팩트 안에서는 로그인이 꺼집니다.

## 6. AI 회의록 엔진
| 엔진 | 어디서 | 준비 |
|---|---|---|
| Claude | claude.ai 아티팩트 안 | 없음 |
| LM Studio / Ollama | 배포·로컬 어디서나 | [docs/LOCAL-LLM.md](docs/LOCAL-LLM.md) |
| Anthropic API 키 | 배포·로컬 | 키 입력(저장되지 않음) |

## 7. 발언자 구분
전사 탭 → **발언자 구분**, 또는 새 회의에 녹음 파일만 붙였을 때 뜨는 분석 창에서 엔진을 고릅니다.
| 엔진 | 준비 | 특징 |
|---|---|---|
| **브라우저 내장** (기본) | 없음. 처음 한 번 모델 약 90MB 다운로드(이후 캐시) | transformers.js로 Whisper-base + pyannote segmentation 3.0을 브라우저에서 실행. WebGPU(최신 Chrome·Edge) 권장, CPU는 느림. 10분 단위 분석이라 긴 회의는 구간마다 화자 번호가 달라질 수 있음 → 참석자 매핑에서 합치기. 배포 주소(https)나 localhost에서만 동작 |
| **PC 서비스** | `server/` 파이썬 서비스 실행([server/README.md](server/README.md)) | faster-whisper small/medium + pyannote 3.1(또는 경량 군집). 정확도·긴 회의·화자 수 많을 때 유리 |
전사는 타임라인 순으로 정렬되며, **참석자 매핑**에서 화자마다 참석자를 고르거나 이름을 입력할 수 있습니다.
발언자 이름을 누르면 참석자 목록에서 고르거나 직접 입력할 수 있습니다.

## 9. 회의록 양식
회의록 상단 **회의록 양식**(내보내기 창에서도 선택)에서 양식을 고릅니다. 양식은 `web/index.html`의 `TEMPLATES` 객체에 정의되며, PDF·HWPX·DOCX가 같은 정의를 공유합니다.
- **회의록(일시·장소·제목·참석자 / 세부내용 / 실행계획 / 특이사항)** — 기본. 참석자는 소속별로 `[소속] 이름 직급, …` 한 줄씩, 본문 뒤에 실행계획 표(기한·작업수행자·내용·산출물)와 특이사항 칸.
- **기본** — 회의 정보 표, 참석자 표, 회의 내용.
새 양식은 `TEMPLATES`에 `render(B, opts)` 함수를 추가하면 됩니다(`B.para`, `B.table` 두 가지로 그립니다).

## 10. 파일 형식
- `.mnote`: 녹음 + 회의록 본문 + 회의 정보·참석자 + 메모(서식·표·편집 기록) + 전사(발언자) + AI 초안을 ZIP 하나로. 구조는 `docs/MNOTE-FORMAT.md`.
- `.hwpx`: 한컴오피스 한글 2014+에서 열리는 OWPML 문서. 회의 정보 표 + 참석자 표 + 회의 내용(서식·표 유지) + 선택 부록(메모·AI 초안·전사). 문단 끝 시간 표기는 옵션.

## 개발 메모
- 빌드 도구 없음. `web/index.html` 하나에 CSS/JS가 들어 있고 JSZip만 CDN에서 가져옵니다.
- 코드 구조: `<script data-app>` 안이 앱 전체. 주요 섹션 주석: document editor / tables / column-row resize / recording / attach & sync / AI provider / HWPX export / .mnote save-open.
- 변경 후 `web/sw.js`의 `CACHE` 값을 올리면 사용자 브라우저 캐시가 갱신됩니다(Actions 배포는 자동).
