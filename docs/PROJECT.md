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
   - `POST /jobs` (multipart: audio, lang, num_speakers, vocab) → `{job_id}`; `POST /cloud/clova` (multipart: audio, invoke_url, key, lang, num_speakers, vocab) → 클로바 스피치 응답 그대로; `GET/POST /llm/{path}` → `LLM_BASE/{path}`로 전달(스트리밍 포함, Authorization 통과); `GET /jobs/{id}` → `{state, pct, stage, message, result}`; `DELETE /jobs/{id}` 취소
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
- 헤더: `← 대시보드`(로고 자리, `#backDash`) · 제목 · 마이크 · 새 회의 · 저장 · 내보내기 · 설정 · 로그인. 회의록 작성 화면은 대시보드 아래 2뎁스라서 로고 대신 뒤로가기가 있다.
- **저장하지 않은 내용 확인**(`dirty`/`dirtyAck`): 대시보드로 나갈 때(`goDashboard`)와 다른 .mnote 파일을 열 때만 한 번 묻고, 확인한 뒤에는 내용이 다시 바뀌기 전까지 다시 묻지 않는다. **새 회의 시작에서는 묻지 않는다.** 창 닫기(`beforeunload`)는 브라우저 기본 확인 그대로.

### 3.2 화면 구성
- **왼쪽(60%) 회의록 문서**: 양식 선택, 일시·장소·작성자(·주관), 참석자 표, 본문 편집기, 양식에 따른 실행계획 표·특이사항.
- **대시보드**(`#dashPage`, 전체 화면 페이지, 헤더 왼쪽 "← 대시보드" 버튼 / `dashOpen`·`dashClose`): 앱을 열면(로그인 시 `projPull` 뒤, 게스트도) 한 번 자동으로 열린다(`openDashboard`). 왼쪽 LNB에 프로젝트(모든 / 미분류(개인) / 프로젝트별, 건수·공유 표시)와 새 회의·새 프로젝트·프로젝트 관리·.mnote 열기·설정·Drive 맞추기·새로고침, 오른쪽에 현황 카드(회의록 수·이번 달·프로젝트·마지막 저장), 달력 카드(달력+그날 목록 또는 전체 목록), 최근 작성 회의록 카드(저장순 8건, `renderDashProjs`가 그린다). 목록은 내 `users/{uid}/meetings` + 공유 프로젝트의 `projects/{id}/meetings`를 합친다.
- **좁은 화면(모바일)**: 전사·메모·AI 회의록 패널은 고정 높이 안에서 스크롤하고(`--side-h`), 패널 아래 손잡이(`#sideResize`)를 끌어 높이를 조절한다(브라우저에 기억, 두 번 누르면 기본). 메모 도구 모음은 메모 패널 위쪽에 고정된다.
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

- **녹음 음량 보정**(마이크 설정): Web Audio API로 마이크 → 80Hz 하이패스 → DynamicsCompressor(보통 -30dB/4:1, 강하게 -40dB/8:1) → 증폭(1.6×/2.4×) → tanh 소프트 리미터(최대 0.95) → MediaStreamDestination을 MediaRecorder에 넣는다(`boostedStream`, 설정 `meetnote.micBoost`, 기본 보통). 브라우저 `autoGainControl`도 켠다. 실시간 전사도 보정된 소리를 듣는다. 실측(가짜 마이크): 진폭 3% 구간 RMS 0.003→0.3, 60% 구간 0.41→0.7, 피크 0.97.

### 3.5 전사와 발언자 구분
- 녹음 중 브라우저 실시간 전사(Chrome·Edge). 전사 구간은 노트에 넣거나 회의록에 넣을 수 있다.
- **발언자 구분**(전사 탭): 브라우저 내장(transformers.js, 첫 실행 모델 약 90MB) 또는 PC 서비스(정확). 새 회의에 녹음 파일만 붙이면 분석 여부를 먼저 묻고 진행률 창(백그라운드 가능, 취소 가능)으로 진행한다.
- **전사 듣기·고치기·검색**(전사 탭): 글자를 누르면(끌어 고르면) 그 자리부터 재생하고(문단 안 위치는 글자 수 비율로 어림, `segTimeAt`), 행·시각을 누르면 그 문단만 처음부터 끝까지 재생한다(`playSegment`, `segStopAt`). 시각 표시는 발언자 이름과 같은 색. 마우스 우클릭 메뉴(`#segMenu`: 문단 수정·여기서 나누기·듣기·삭제), 터치·펜은 길게 누르면 바로 수정(`startSegEdit`; Enter 저장·Esc 취소). 검색창은 낱말(또는 발언자 이름)이 든 문단만 보여 주고 찾은 곳을 표시한다. 검색창 옆 **바꾸기**로 그 낱말을 전사 전체에서 한꺼번에 교체한다(대소문자 무시, 되돌리기 한 번 `trReplaceBackup`). 재생 중에는 문단 강조(`.seg.now`)에 더해 시각 비율로 어림한 **낱말 위치**를 색으로 표시한다(`paintReadPos`: 읽은 낱말 `.read`, 지금 낱말 `.read-cur`; 검색 중·수정 중에는 끔). 녹음 중 실시간 전사(발언자 모름)는 문단을 짧게 끊는다(0.7초·문장 중간 1.8초, 120자·18초: `canMergeSeg`).
- **전사 파일 가져오기**(전사 탭, 또는 .txt를 화면에 끌어다 놓기): 녹음이 없는 회의에 다른 도구의 전사(.txt)를 올린다. 클로바노트 내보내기를 알아본다 — 음성 기록(참석자+발언)과 AI 요약(주요 주제·다음 할 일·시간대별 요약), 각각 시간 기록 포함/미포함(`parseTranscriptText`). 시간이 없으면 순서만 지키는 가짜 시각을 매기고 `S.trImport.timed=false`로 표시해 화면·프롬프트·내보내기에서 시각을 감춘다(`segTimed()`). 가져온 회의는 녹음·녹음 파일 붙이기가 잠기고 "가져온 전사 지우기"로 되돌린다. 머리말의 제목·일시·길이·참석자는 비어 있는 칸에만 채운다.
- **브라우저 내장 상세**: 인식 모델 등급(`diar.tier`: 자동/정확 `whisper-large-v3-turbo_timestamped`(WebGPU 전용, encoder fp16 + decoder q4 ≈ 1.5GB)/균형 `whisper-small_timestamped`(≈560MB)/빠름 `whisper-base_timestamped`(≈90MB)). 자동은 WebGPU PC → 정확, WebGPU 휴대폰 → 균형, CPU → 균형(휴대폰은 빠름). `resolveTier`가 정하고 GPU 무응답으로 CPU로 바뀌면 다시 정한다. 녹음 중 실시간 전사는 항상 빠름 모델. 순서: ① pyannote-segmentation을 10분 창으로 먼저 돌려 말소리 구간(VAD)과 화자 구간(turns)을 얻고 ② 말소리 조각만 0.4초 무음으로 이어 붙인 26초 안팎의 인식 구간을 만들어(긴 구간은 가장 조용한 지점에서 나눔) Whisper에 넣고 시각은 map으로 원래 위치로 되돌린다(무음·잡음 환청 감소). 분할 실패 시 옛 에너지 기준으로 대체. ③ 발언자는 turns마다 **WeSpeaker 임베딩**(`onnx-community/wespeaker-voxceleb-resnet34-LM`, wasm)으로 단위(최대 8초)마다 특징을 뽑아 pyannote 3.1과 같은 centroid 군집(단위 벡터 유클리드 거리 0.7046, 작은 무리는 가까운 무리에 흡수)으로 녹음 전체에서 화자를 통일한다(`unifySpeakers`). 발언자 수를 지정하면 그 수까지 묶는다.
- **클라우드 API**(세 번째 방식, 선택): 네이버 클로바 스피치(클로바노트와 같은 엔진, 발언자 구분·용어 사전 내장. 브라우저에서 직접 부를 수 없어 PC 서비스의 `/cloud/clova`를 거쳐 보냄), OpenAI `gpt-4o-transcribe-diarize`(브라우저 직접. 25MB 초과 시 12분 WAV 구간으로 나누고 앞 구간의 화자 목소리 샘플을 `known_speaker_references`로 넘겨 같은 사람을 이어 줌), AssemblyAI(올리기→작업→상태 조회, `word_boost`), Deepgram Nova-3(`diarize`+`utterances`). **음성 인식 서버(OpenAI 호환, `whisperapi`)**: PC에 띄운 Whisper 서버(whisper.cpp `whisper-server`, speaches, LocalAI)나 OpenAI whisper-1의 `/v1/audio/transcriptions`(verbose_json, prompt=용어 사전)로 글만 받고, 그 글에 브라우저 내장 발언자 구분을 얹는다(워커 `diarOnly` 모드 → `browserSpeakersFor`). 키는 선택. 코드는 `CLOUD_PROV`/`CLOUD_RUN`/`diarizeCloud`. 키는 세션 저장소(또는 '기억' 체크 시 localStorage `meetnote.cloudKeys`)에만 두고 계정에 동기화하지 않는다. 화자 표시는 서비스마다 달라 나온 순서대로 0,1,2…로 맞춘다.
- 휴대폰에서는 브라우저 내장 '정확' 모델을 균형으로 강제한다(`resolveTier`).
- **회의 용어 사전**(`meetingVocab`): 참석자·발언자 이름, 참고 자료 이름과 자주 나오는 낱말(영문 약어·고유명사 위주, 최대 40개)을 음성 인식 엔진에 힌트로 준다. PC 서비스는 `vocab` 폼 필드 → faster-whisper `hotwords`/`initial_prompt`, 클로바는 `boostings`, AssemblyAI는 `word_boost`, Deepgram은 영어일 때만 `keyterm`. 분석 창의 체크박스로 끌 수 있다.
- 결과는 시간순으로 정렬되고 화자 라벨이 붙는다. **참석자 매핑**에서 화자마다 참석자를 고르거나 이름을 입력하면 전사·AI 초안·내보내기에 반영된다.

### 3.6 AI 회의록
- **초안 작성**: 메모(우선)와 전사, 그리고 둘을 시간순으로 합친 타임라인을 근거로 개요·주요 논의·결정 사항·할 일을 작성. **회의록에 넣기**는 마크다운을 편집기 서식(제목·중첩 목록·굵게/기울임·표)으로 바꿔 넣는다(`mdToHtml` → `mdToDocNodes`). 표는 `.tbl-wrap` 표가 되고 머리글 행은 굵게+회색 배경.
- **회의록에 넣기 분기**(`insertDraft`/`splitDraft`): 초안의 `## 할 일`(액션 아이템·실행 계획 등) 절은 표(| 할 일 | 담당 | 기한 |)든 목록(`- [ ] 내용 (담당, 기한)`)이든 파싱해(`parseTodos`) 실행계획 표(`S.meta.actions` {due, who, what}, 산출물 열 없음)에 중복 없이 넣고, `## 추가로 확인할 점`(미결·보류·이슈 등) 절은 특이사항(`S.meta.notes`)에 줄로 넣으며, 나머지가 본문이다. 양식에 실행계획·특이사항 칸이 없으면(기본 양식) 본문에 그대로 둔다. '전사로 회의록 작성'도 같은 경로.
- **작성 옵션**(작성 화면의 버튼): 초안 자료 선택(전사 + 메모 / 전사만 / 메모만, `draftOpt.source`; 녹음 중 자동 작성은 항상 둘 다), 타임라인 시간 표시(문단·행 끝 칩, 끄면 비는 '근거' 열은 자동 제거)와 **추가 지시**(이번 회의에만, `S.aiExtra` → `.mnote`의 `meeting.json.ai.extra`). 추가 지시는 **템플릿**으로 저장·덮어쓰기·이름 변경·삭제할 수 있다(`draftTpls`).
- **지시문 구성**(`buildPrompt`): 전역 AI 작성 설정(설정 → AI 작성: 분량·문체·발언자 표시·표로 정리·포함 항목·공통 지시, `draftOpt`) + 회의별 추가 지시 + 회의 자료. 설정 탭에서 실제로 보낼 지시문을 미리 볼 수 있다.
- **참고 자료**(회의 정보의 참석자 아래, 또는 문서 파일을 화면에 끌어다 놓기): 안건 자료(PDF·docx·pptx·xlsx·hwpx·텍스트·HTML)를 브라우저 안에서 글로 변환해 `S.refs`(`.mnote`의 `refs.json`)에 **글만** 보관한다. 원본 파일은 저장하지 않는다(`extractRef`: Office·HWPX는 JSZip으로 XML에서 글 추출, PDF는 pdf.js를 CDN에서 필요할 때만 받음. `.hwp`·`.doc` 등은 변환 안내). 항목을 누르면 변환된 글과 이름(출처 표시에 쓰임)을 확인·수정할 수 있다.
  - 지원 형식: `.pdf`(글자가 있는 PDF) `.docx` `.pptx` `.xlsx` `.hwpx` `.txt` `.md` `.csv` `.tsv` `.json` `.log` `.html/.htm` `.srt` `.vtt`. 미지원: `.hwp`·`.doc`·`.ppt`·`.xls`(변환 방법 안내), 스캔 PDF·그림 파일(글자 정보 없음). 제한: 회의당 8개, 파일당 40MB, 자료당 20만 자. 화면의 "올릴 수 있는 파일 형식"에 같은 내용을 안내한다.
  - 지시문(`refsRule`): 자료는 용어·수치·배경 확인용. 회의록 내용은 전사·메모에서만 가져오고, 자료에만 있는 내용은 넣지 않으며, 자료에 없는 논의도 빠뜨리지 않는다. 자료로 확인한 줄에는 `(자료: 이름)`을 붙인다 → 미리보기에서는 `.src`, 회의록에 넣으면 파란 글자(`--tc-blue`)로 구분된다.
  - 자료 블록(`refsBlock`): 자료 첫머리는 늘 넣고 나머지는 회의에서 나온 말(전사·메모)과 낱말이 겹치는 대목만 원래 순서대로 고른다. 분량은 엔진에 맞춘다(`refBudget`: 로컬 모델은 학습된 컨텍스트 한도의 약 22%, 그 밖은 16,000자). 내보내는 문서에는 자료 내용이 들어가지 않는다.
- **프로젝트**(회의록 양식 옆 선택 + 관리 창): 회의록을 프로젝트로 묶는다(`S.meta.project` = 프로젝트 id, 없어도 됨). 프로젝트 목록은 localStorage `meetnote.projects`에 두고 로그인 시 Firestore `users/{uid}/projects/{id}`(json 필드)에 동기화한다(updatedAt 최신 우선, 규칙에 경로가 없으면 403 → 브라우저에만). 목록 DB(meetings)에도 `project`·`projectName`을 적어 불러오기 창에서 모든 프로젝트/프로젝트 없음/특정 프로젝트로 거르고, 카드의 선택 상자로 바로 지정·변경한다(목록 DB가 파일보다 우선: 클라우드에서 열 때 적용).
  - **역할**: 마스터(`ownerEmail`/`owner` uid) 1명 — 초대·내보내기·초대 담당자 지정(`inviters`, 최대 2명)·마스터 위임(ownerEmail을 바꾸고 owner uid는 비움 → 새 마스터가 다음 저장 때 채움, 규칙이 이를 허용)·이름 변경·삭제. 초대 담당자 — 초대·구성원 내보내기(마스터·다른 담당자는 못 뺌). 구성원 — 보기·나가기. 판정은 `isProjOwner`/`isInviter`.
  - **공유**: 프로젝트 관리의 구성원 칸에서 Google 이메일로 초대(`p.members`, 소유자 `p.owner`/`ownerEmail`). 동기화 위치는 최상위 Firestore `projects/{id}`(memberEmails 배열, `fsQuery` array-contains로 내 것을 당김; 옛 `users/{uid}/projects`는 첫 로그인 때 자동 이전). 프로젝트에 묶인 회의록을 클라우드 저장하면 `projects/{id}/meetings/{mid}`에 기록하고 올린 사람의 Drive 파일을 구성원에게 편집 권한으로 공유(`shareFileWith`, 알림 메일 없음). 불러오기 목록은 내 목록 + 공유 프로젝트 목록을 합친다(`sharedRows`, 공유 배지·올린 사람 표시, 삭제·프로젝트 변경은 올린 사람만). 남의 공유 파일에 쓸 권한이 없으면 내 Drive에 새 파일로 저장하고 안내한다. 소유자만 초대·내보내기·이름 변경·삭제, 구성원은 나가기.
  - **프로젝트 참고 문서**: 파일 → 글(`extractRef`) → AI 요약(`SUM_PROMPT`, ≤ 2,500자) → 통합 참조 문서 `merged`에 AI로 머지(`MERGE_PROMPT`: 기존 통합본 + 새 요약 → 갱신). .md는 요약 없이 그대로 합친다. 문서를 빼거나 "다시 통합"을 누르면 요약들로 처음부터 다시 합친다. AI가 없으면 앞부분·이어 붙이기로 대체하고 나중에 다시 통합할 수 있다. 통합본은 직접 고칠 수 있다.
  - 회의록 작성 시 `projBlock`/`projRule`로 <프로젝트 참고>를 붙인다. 회의에 직접 올린 <참고 자료>(S.refs)가 우선이고 둘이 다르면 참고 자료를 따르도록 지시한다. 분량은 `refBudget`의 60%(회의 자료가 있을 때).
- **자동 작성**(회의 내용 옆): 녹음 중 2·5·10분마다 본문을 갱신. 자동 문단은 왼쪽 선으로 표시되고 통째로 교체되며 직접 쓴 문단은 유지. Claude 아티팩트 엔진 제외.
- **설정**(상단 ⚙ 설정, 탭 구조): 화면(테마·배율), **AI 엔진**, **AI 작성**(모든 회의 공통 지시문), **작성자**(소속·이름 → 새 회의의 작성자 칸 기본값), 로그, 계정·클라우드, **버전 정보**(버전·패치 노트). 실패 시 원인과 해결 안내가 화면에 표시된다.

### 3.7 양식과 내보내기
- **회의록 양식**: 문서 상단 또는 내보내기 창에서 선택. 기본 양식은 "회의록(일시·장소·제목·참석자 / 세부내용 / 실행계획 / 특이사항)". 양식마다 입력칸이 달라진다.
- **참석자**: 직접 입력하거나 **캡처 이미지에서 읽기**(참석자 영역에서 Ctrl+V도 가능)로 명단 캡처를 AI가 읽어 소속·이름·직급을 채운다(`scanAttendees`). 이미지를 읽는 엔진이 필요하다: Anthropic API 키 또는 LM Studio·Ollama의 비전 모델. 설정의 작성자(소속·이름·직급)는 새 회의의 작성자 칸과 참석자에 자동으로 들어간다.
- **내보내기 표기**: 작성자 칸은 소속 다음 줄에 이름(`authorLines`). 같은 소속 참석자가 둘 이상이면 직급이 가장 높은 1명 + "외 N인"(`attendeesForExport`, 직급 서열 `TITLE_RANK`, 내보내기 창에서 끌 수 있음). 글꼴은 세 형식 모두 Noto Sans KR(`EXPORT_FONT`; 한글·Word는 여는 PC에 글꼴이 없으면 대체 글꼴). 내려받는 파일 이름은 `회의록 이름_YYYYMMDD_HHMMSS`(`dlBase`; 회의록 이름 = 저장할 때 정한 이름·클라우드 파일 이름).
- **내보내기**: PDF(브라우저 인쇄 → PDF로 저장), 한글 HWPX, Word DOCX. 서식·표(병합·배경·사선·크기)가 유지되고, 문단 끝 시간 표기와 부록(메모·AI 초안·전사)은 옵션.
- **저장**: 헤더의 `저장`(Ctrl+S, `saveAny`)을 누르면 먼저 **클라우드 / .mnote 파일 / 둘 다** 중 어디에 저장할지 고른다(`#saveDlg`, `chooseSaveHow`; 마지막 선택은 `meetnote.saveHow`에 기억, 로그인 전에는 .mnote만 고를 수 있음). 그다음 파일 이름을 한 번 묻는다(기본값 `제목_날짜`, 한 번 정하면 그 회의에 기억). "둘 다"는 같은 zip을 먼저 내려받은 뒤 Drive에 올린다(`cloudSave({ alsoLocal })`). **회의록 불러오기** 창은 카드 목록(검색·정렬)과 달력 보기(기본)를 지원한다. 달력 아래 목록은 카드 5개 높이만 보이고 안에서 스크롤한다. `.mnote` 하나에 녹음·회의 정보·참석자·본문(편집 기록 포함)·메모(편집 기록)·전사·AI 초안이 들어간다. 구조는 `docs/MNOTE-FORMAT.md`.

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
| `WHISPER_MODEL` | small | tiny·base·small·medium·large-v3·**large-v3-turbo**(GPU 권장, 빠르고 정확) |
| `DEVICE` | cpu | `cuda`(NVIDIA GPU) |
| `HF_TOKEN` | 없음 | 있으면 pyannote 3.1 사용(정확도 향상) |
| `DIARIZER` | auto | `none`이면 전사만 |
| `BEAM_SIZE` | 5 | 낮추면 빠름 |
| `PRELOAD` | 1 | 시작 시 모델 미리 받기 |
| `OPEN_BROWSER` | 1 | 웹 앱 자동 열기 |
| `CLOVA_SPEECH_URL` / `CLOVA_SPEECH_KEY` | 없음 | 클로바 스피치 프록시 기본값(브라우저에서 보낸 값이 우선) |
| `CLOUD_TIMEOUT` | 1800 | 클로바 스피치 동기 인식 대기(초) |
| `LLM_BASE` | http://localhost:1234 | `/llm/*` 프록시가 대신 부를 로컬 LLM 서버(Ollama면 http://localhost:11434) |

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

### 5.3.2 휴대폰에서 PC의 LM Studio·Ollama 쓰기
배포 앱은 https라 브라우저가 http LAN 주소를 부르지 못한다(혼합 콘텐츠, iPhone·Android 공통). 해법: PC 서비스가 LLM을 대신 부르는 `/llm` 프록시 + `server/tunnel.ps1`(`tunnel.sh`)로 만든 Cloudflare 빠른 터널(https). 앱에서는 PC 서비스 주소 = 터널 주소, AI 서버 주소 = `터널 주소/llm`. 설정 → AI 엔진의 "휴대폰·다른 기기에서…" 상자가 이 순서를 안내하고 PC 서비스 주소가 https면 한 번에 채워 준다(`renderPhoneHelp`). 인터넷에 열리므로 LM Studio API 키(보안 토큰)를 켜 둘 것.

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
