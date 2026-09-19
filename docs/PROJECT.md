# MeetNote 프로젝트 문서

녹음과 함께 쓰는 회의록 앱. 녹음(또는 녹음 파일)과 메모의 타임라인을 맞추고, 전사·발언자 구분·AI 초안을 거쳐 정형 양식(PDF·한글·Word)으로 내보낸다. 기록은 `.mnote` 한 파일(녹음 + 회의록 + 편집 기록)로 저장된다.

- 버전: 1.0 (2026-09)
- 실행 형태: 웹(GitHub Pages 등 정적 호스팅) · Windows exe(웹 + 분석 서버 동봉) · 도커 · Android APK(Capacitor)

---

## 1. 폴더 구조

```
meetnote/
├─ web/                     앱 본체 (정적 파일, 이 폴더만으로 웹 배포 가능)
│  ├─ index.html            단일 파일 앱 (HTML+CSS+JS, 약 4,700줄)
│  ├─ config.js             배포 설정: Google 클라이언트 ID, 로그인 필수 여부
│  ├─ sw.js                 서비스 워커 (정적 파일만 캐시, API는 캐시하지 않음)
│  ├─ manifest.webmanifest  PWA 설치 정보
│  ├─ icons/                앱 아이콘
│  └─ serve.py              로컬 테스트 서버 (python serve.py → http://localhost:8080)
├─ server/                  발언자 구분·전사 서비스 (Python, FastAPI)
│  ├─ diarize.py            서버 본체: /jobs·/diarize·/health API + web/ 정적 서빙
│  ├─ requirements.txt      의존성 (faster-whisper, resemblyzer, imageio-ffmpeg …)
│  ├─ install.ps1 / .sh     가상환경 생성·설치 스크립트 (Windows / macOS·Linux)
│  └─ README.md             설치·모델·환경변수 안내
├─ desktop/                 Windows exe 빌드 (PyInstaller)
│  ├─ meetnote.spec         빌드 스펙 (web/, ffmpeg, 모델 라이브러리 수집)
│  ├─ build-exe.ps1         빌드 스크립트 → dist\MeetNote\MeetNote.exe
│  ├─ hooks/hook-webrtcvad.py  webrtcvad-wheels용 후크 덮어쓰기
│  └─ README.md
├─ android-capacitor/       Android APK 빌드 (Capacitor)
├─ docs/
│  ├─ PROJECT.md            이 문서
│  ├─ LOCAL-LLM.md          LM Studio / Ollama 연결 방법
│  └─ MNOTE-FORMAT.md       .mnote 파일 구조
├─ .github/workflows/       GitHub Pages 자동 배포, APK 빌드
├─ Dockerfile, render.yaml  도커 / Render 배포
├─ netlify.toml, vercel.json 정적 호스팅 설정
├─ publish.ps1 / .sh        GitHub 저장소 생성 + push + Pages 활성화
└─ README.md                배포·설정 요약
```

---

## 2. 아키텍처

### 2.1 클라이언트 (web/index.html)
프레임워크 없이 순수 HTML/CSS/JS 한 파일. 외부 의존성은 JSZip(.mnote/.hwpx/.docx 압축), Google Fonts, 선택적으로 transformers.js(브라우저 내장 발언자 구분)와 Google Identity Services(로그인)뿐이다.

주요 모듈(코드의 `/* ---------- 이름 ---------- */` 구분자 순서):

| 모듈 | 역할 |
|---|---|
| state | 회의 상태 `S` (제목, 메타, 참석자, 메모 블록, 본문 블록, 전사, 발언자, AI 초안, 오디오) |
| document editor / formatting / tables / resize | 회의록 본문·메모 공용 편집기: 제목·서식·목록·표(병합·사선·배경·크기), 마크다운 단축 입력, 드래그 이동 |
| mode, gutter, replay | 블록별 시점 기록, 메모 시간 거터, 따라 쓰기 재생 |
| timeline / render loop / audio | 하단 타임라인, 재생 동기화, 현재 위치 강조 |
| microphone / recording / attach & sync | 마이크 권한·장치·테스트, 녹음, 시계 모드, 외부 녹음 파일 붙이기와 싱크 조정 |
| live transcription | 브라우저 Web Speech API 실시간 전사 |
| AI minutes / auto-draft / AI provider / AI log | 회의록 초안 생성, 녹음 중 자동 작성, 엔진 설정(Claude·LM Studio·Ollama·OpenAI 호환·Anthropic 키), 진단 로그 |
| HWPX / DOCX / HTML builder / templates | 내보내기 빌더 3종(같은 인터페이스)과 회의록 양식 정의 |
| meeting meta & attendees | 일시·장소·작성자·주관, 참석자(소속·이름·직급), 실행계획, 특이사항 |
| speaker diarization / mapping / progress / in-browser | 발언자 구분(서버·브라우저), 화자↔참석자 매핑, 진행률 창 |
| .mnote save / open | 저장·불러오기 (ZIP 컨테이너) |
| Google sign-in / splash | 스플래시 → 로그인 페이지 → 앱 |
| file delivery | 브라우저 다운로드 / 모바일 공유 시트 / Capacitor 파일 저장 |

### 2.2 서버 (server/diarize.py)
FastAPI + uvicorn. 역할은 두 가지.
1. **전사 + 발언자 구분 API**
   - `POST /jobs` (multipart: audio, lang, num_speakers) → `{job_id}`; `GET /jobs/{id}` → `{state, pct, stage, message, result}`; `DELETE /jobs/{id}` 취소
   - `POST /diarize` 동기 버전(구버전 호환), `GET /health`
   - 파이프라인: ffmpeg → 16kHz wav → faster-whisper(small, VAD) → 발언자 분리(pyannote 3.1 또는 resemblyzer 임베딩+군집) → 문장에 화자 배정
   - 작업은 한 번에 하나만 실행(작업 잠금), 취소는 문장 경계에서 즉시 반영
2. **웹 앱 정적 서빙**: `web/`가 있으면 같은 주소 `/`에서 앱을 제공하고 브라우저를 자동으로 연다. 앱은 같은 주소의 `/health`를 감지하면 이 서버를 기본 분석 엔진으로 잡는다.

ffmpeg는 PATH → exe 옆 `ffmpeg` 폴더 → `imageio-ffmpeg` 동봉본 순으로 찾는다.

### 2.3 배포 형태
| 형태 | 구성 | 발언자 구분 |
|---|---|---|
| GitHub Pages 등 정적 웹 | `web/`만 | 브라우저 내장(transformers.js) 또는 사용자 PC의 서버(localhost:8765) |
| Windows exe | `desktop/`로 빌드, 웹+서버 동봉 | 서버 내장, 자동 연결 |
| 도커 / Render | `Dockerfile`, 웹+서버 | 서버 내장 |
| Android APK | `android-capacitor/` | 브라우저 내장 또는 PC 서버 주소 지정 |

---

## 3. 기능 가이드 (사용자 관점)

### 3.1 시작
- 스플래시 → 로그인 페이지 → 회의록 작성 화면. Google 로그인은 `config.js`에 클라이언트 ID가 있는 http(s) 사이트에서 동작하며, 없거나 불가능한 환경(Claude 아티팩트, file://)에서는 **게스트로 시작**할 수 있다. 헤더의 로그인 버튼에서 클라이언트 ID를 직접 설정할 수도 있다(그 브라우저에만 적용).
- 헤더: 마이크 · 새 회의 · 회의록 불러오기(.mnote) · .mnote로 저장 · 내보내기 · 로그인.

### 3.2 화면 구성
- **왼쪽(60%) 회의록 문서**: 양식 선택, 일시·장소·작성자(·주관), 참석자 표, 본문 편집기, 양식에 따른 실행계획 표·특이사항.
- **오른쪽(40%) 탭**: 메모 · 전사 · AI 회의록. 가운데 세로 손잡이로 폭 조절(더블클릭 시 6:4 복원).
- 도구 막대는 마지막으로 누른 편집기(회의록/메모)에 적용되고 오른쪽 끝에 대상이 표시된다. 모든 버튼에 호버 툴팁이 있다.

### 3.3 편집기 (회의록 본문·메모 공통)
- 문단 형식(본문·제목 1~3), 굵게·기울임·밑줄·취소선, 글자 색 8종, 형광펜 7종, 목록, 서식 지우기.
- 입력 단축: `# `/`## `/`### ` 제목, `- ` 글머리표, `1 ` 번호 목록, Tab/Shift+Tab 들여쓰기(번호는 1→a→i, 글머리는 •→◦→▪).
- 표: 격자에서 크기 선택, 행/열 추가·삭제, 셀 병합·풀기, 배경색, 사선(╲ ╱), 열 너비·행 높이 드래그, 크기 초기화, 터치용 칸 선택 모드, Tab 이동·마지막 칸 Tab 행 추가, ↑↓ 같은 열 이동.
- 이동: 문단·표 위에 손잡이(⋮⋮)로 끌어서 옮기기(터치는 길게 누르기), Alt+↑/↓.

### 3.4 녹음과 타임라인
- **녹음 시작**: 마이크 권한 창 → 허용. 마이크 설정 창에서 장치 선택·소리 테스트·권한 해결 안내.
- **시계 모드**: 권한이 막힌 환경(모바일 앱 화면 등)에서는 휴대폰 녹음 앱으로 녹음하고 앱에서는 시계만 켜고 메모 → 끝난 뒤 **녹음 파일 붙이기**(m4a·mp3·wav 등) → **싱크 조정**으로 시점 맞춤.
- 메모·본문의 문단마다 쓰기 시작한 시점이 기록되어 시간 칩을 누르면 그 위치가 재생된다. 하단 타임라인에 메모(점)·전사(막대) 표시.
- **따라 쓰기**(메모 탭·회의 내용 옆 스위치): 재생하면 쓰였던 순서·속도 그대로 다시 써진다.

### 3.5 전사와 발언자 구분
- 녹음 중 브라우저 실시간 전사(Chrome·Edge). 전사 구간은 노트에 넣거나 회의록에 넣을 수 있다.
- **발언자 구분**(전사 탭): 브라우저 내장(transformers.js, 첫 실행 모델 약 90MB) 또는 PC 서비스(정확). 새 회의에 녹음 파일만 붙이면 분석 여부를 먼저 묻고 진행률 창(백그라운드 가능, 취소 가능)으로 진행한다.
- 결과는 시간순으로 정렬되고 화자 라벨이 붙는다. **참석자 매핑**에서 화자마다 참석자를 고르거나 이름을 입력하면 전사·AI 초안·내보내기에 반영된다.

### 3.6 AI 회의록
- **초안 작성**: 메모(우선)와 전사, 그리고 둘을 시간순으로 합친 타임라인을 근거로 개요·주요 논의·결정 사항·할 일을 작성. **회의록에 넣기**는 마크다운을 편집기 서식(제목·중첩 목록·굵게/기울임·표)으로 바꿔 넣는다(`mdToHtml` → `mdToDocNodes`). 표는 `.tbl-wrap` 표가 되고 머리글 행은 굵게+회색 배경.
- **작성 옵션**(작성 화면의 버튼): 타임라인 시간 표시(문단·행 끝 칩, 끄면 비는 '근거' 열은 자동 제거)와 **추가 지시**(이번 회의에만, `S.aiExtra` → `.mnote`의 `meeting.json.ai.extra`). 추가 지시는 **템플릿**으로 저장·덮어쓰기·이름 변경·삭제할 수 있다(`draftTpls`).
- **지시문 구성**(`buildPrompt`): 전역 AI 작성 설정(설정 → AI 작성: 분량·문체·발언자 표시·표로 정리·포함 항목·공통 지시, `draftOpt`) + 회의별 추가 지시 + 회의 자료. 설정 탭에서 실제로 보낼 지시문을 미리 볼 수 있다.
- **자동 작성**(회의 내용 옆): 녹음 중 2·5·10분마다 본문을 갱신. 자동 문단은 왼쪽 선으로 표시되고 통째로 교체되며 직접 쓴 문단은 유지. Claude 아티팩트 엔진 제외.
- **설정**(상단 ⚙ 설정, 탭 구조): 화면(테마·배율), **AI 엔진**, **AI 작성**(모든 회의 공통 지시문), **작성자**(소속·이름 → 새 회의의 작성자 칸 기본값), 로그, 계정·클라우드, **버전 정보**(버전·패치 노트). 실패 시 원인과 해결 안내가 화면에 표시된다.

### 3.7 양식과 내보내기
- **회의록 양식**: 문서 상단 또는 내보내기 창에서 선택. 기본 양식은 "회의록(일시·장소·제목·참석자 / 세부내용 / 실행계획 / 특이사항)". 양식마다 입력칸이 달라진다.
- **내보내기**: PDF(브라우저 인쇄 → PDF로 저장), 한글 HWPX, Word DOCX. 서식·표(병합·배경·사선·크기)가 유지되고, 문단 끝 시간 표기와 부록(메모·AI 초안·전사)은 옵션.
- **저장**: `.mnote로 저장`·`☁ 클라우드 저장` 모두 파일 이름을 한 번 묻는다(기본값 `제목_날짜`, 한 번 정하면 그 회의에 기억). **회의록 불러오기** 창은 카드 목록(검색·정렬)과 달력 보기를 지원한다. `.mnote` 하나에 녹음·회의 정보·참석자·본문(편집 기록 포함)·메모(편집 기록)·전사·AI 초안이 들어간다. 구조는 `docs/MNOTE-FORMAT.md`.

---

## 4. 설정

### 4.1 web/config.js
```js
window.MEETNOTE_CONFIG = {
  googleClientId: "",   // OAuth 클라이언트 ID(웹 애플리케이션). 승인된 JavaScript 원본에 배포 주소 추가
  requireLogin: true    // true: 로그인해야 앱 사용, false: 게스트 허용
};
```

### 4.2 서버 환경변수
| 변수 | 기본 | 설명 |
|---|---|---|
| `PORT` | 8765 | 서비스 포트 |
| `WHISPER_MODEL` | small | tiny·base·small·medium·large-v3 |
| `DEVICE` | cpu | `cuda`(NVIDIA GPU) |
| `HF_TOKEN` | 없음 | 있으면 pyannote 3.1 사용(정확도 향상) |
| `DIARIZER` | auto | `none`이면 전사만 |
| `BEAM_SIZE` | 5 | 낮추면 빠름 |
| `PRELOAD` | 1 | 시작 시 모델 미리 받기 |
| `OPEN_BROWSER` | 1 | 웹 앱 자동 열기 |

### 4.3 설정 저장(localStorage + 계정 DB 동기화)
설정은 브라우저 localStorage에 두고, 로그인 상태면 `prefsTouch()` → `prefsPush()`로 Firestore `users/{uid}/settings/prefs`에 올려 다른 기기에서도 이어 쓴다(`prefsLocal`/`prefsPull`). 동기화 대상: 발언자 분석·AI 엔진·다듬기 옵션, AI 작성 설정(`meetnote.draftOpt`: 분량·문체·표 정리·시간 표시·공통 지시), 추가 지시 템플릿(`meetnote.draftTpls`), 작성자(`meetnote.author`). 보안 토큰·API 키는 올리지 않는다.

기타 키: `meetnote.ai`(AI 엔진), `meetnote.diar`(분석 서버), `meetnote.ailog`(로그), `meetnote.user`(로그인), `meetnote.gclient`(클라이언트 ID), `meetnote.sideW`(패널 폭), `meetnote.micDevice`.

---

## 5. 개발 가이드

### 5.1 로컬 실행
```powershell
cd web && python serve.py            # 앱만: http://localhost:8080
cd server && .\install.ps1 && python diarize.py   # 앱+서버: http://localhost:8765
```

### 5.2 코드 규칙
- 상태는 전역 `S` 하나. 파일에 저장되는 것은 모두 `S`에 있어야 한다.
- 편집기 블록은 `data-id`로 추적되고 `trackBlocks(track)`가 시점·편집 기록을 갱신한다(메모 `memoTrack`, 본문 `docTrack`).
- 사용자 입력 HTML은 `sanitizeHTML`을 거친다(허용 태그·스타일·클래스만 유지).
- 진단은 `aiLog(level, msg, data)`에 남기고 사용자에게는 원인+해결을 함께 보여준다.

### 5.3 양식 추가
`TEMPLATES` 객체에 항목을 추가한다.
```js
myform: {
  name: '표시 이름',
  fields: ['when','place','author'],           // 상단 입력칸
  sections: { actions: true, notes: false },   // 실행계획 표, 특이사항
  render(B, opts) {                            // B.para(runs, pp), B.table({rows, cols, origin}, colW, rowH)
    ...; renderBody(B);                        // 본문은 renderBody로
  }
}
```
같은 `render`가 PDF·HWPX·DOCX에 공통으로 쓰인다. 셀은 `cellSpec(r, c, text, font, {fill, align, rs, cs, d1, d2})`.

### 5.3.1 버전 올리기
출시 전에는 `0.x.y`로 관리한다(기능 추가 = x, 수정 = y). `web/index.html`의 `APP_VERSION`을 올리고 `PATCH_NOTES` 맨 위에 항목을 추가한다(설정 → 버전 정보에 표시). 서비스 워커 캐시 이름은 Pages 배포 워크플로가 커밋마다 자동으로 바꾼다.

### 5.4 AI 엔진 추가
`PROVIDER_DEF`에 항목을 추가하고 `/v1/chat/completions` 호환이면 그대로 동작한다. 다른 API는 `callOpenAI`와 같은 형태(prompt, signal, onText) → 텍스트 반환 함수를 만들어 `runAI`·`runAutoDraft`에서 분기한다.

### 5.5 서버 확장
`run_pipeline(src, lang, n, progress, cancelled)`이 핵심. 진행률은 `progress(pct, stage, message)`로 보고하고, 취소는 `cancelled()`를 확인해 `Cancelled` 예외를 던진다.

### 5.6 배포
- 웹: `git push` → GitHub Actions가 `web/`을 Pages에 배포(서비스 워커 캐시 버전 자동 증가).
- exe: `desktop\build-exe.ps1` → `dist\MeetNote` 폴더 전체 배포.
- 도커: `docker build -t meetnote . && docker run -p 8765:8765 meetnote`.
- APK: `android-capacitor/build-apk.sh` 또는 GitHub Actions "Build Android APK".

---

## 6. 문제 해결

| 증상 | 원인 · 조치 |
|---|---|
| 진행률이 멈춘 것처럼 보임 | 서버 콘솔의 `[transcribe] …` 줄이 늘고 있으면 처리 중(CPU small은 녹음 길이의 0.5~1배). 예전 sw.js가 API를 캐시하던 문제는 v3에서 수정 → F12 → Application → Service Workers → Unregister 후 새로고침 |
| `{"detail":"Not Found"}` | 옛 서버(웹 서빙 없음)가 8765 포트를 점유. 실행 중인 MeetNote 창을 모두 닫고 다시 실행 |
| 발언자가 모두 화자 1 | resemblyzer 미설치(`[diarizer] 사용 불가`). `install.ps1` 재실행 또는 exe 재빌드 |
| ffmpeg 없음 경고 | `server\ffmpeg` 폴더에 ffmpeg.exe 두기 또는 `pip install imageio-ffmpeg` |
| Google 로그인 버튼이 안 뜸 | 클라이언트 ID 미설정, 또는 file://·Claude 화면. 승인된 JavaScript 원본에 현재 주소 추가 |
| AI 초안 실패 | AI 설정 → 로그 확인. `Failed to fetch`는 CORS/서버 꺼짐, `no_sample`은 Claude 밖에서 엔진 미변경 |
| LM Studio `ErrorDeviceLost` | GPU 런타임 크래시. LM Studio 재시작, 런타임을 CUDA/CPU로, GPU Offload 낮추기 |
| exe에서만 발언자 단계 멈춤 | OpenMP 충돌·numba 캐시. 최신 diarize.py는 시작 시 환경변수를 자동 설정. `DIARIZER=none`으로 원인 분리 가능 |
| git push 거부(대용량) | `.venv`·ffmpeg가 커밋됨. `.gitignore` 확인 후 히스토리 재생성(README 참고) |
