# MeetNote — Claude Code 작업 가이드

녹음과 함께 쓰는 회의록 앱. 상세 문서는 `docs/PROJECT.md`(구조·아키텍처·기능·문제 해결)를 먼저 읽을 것.

## 무엇이 어디에
- `web/index.html` — 앱 본체. HTML+CSS+JS **단일 파일**(프레임워크 없음). 코드는 `/* ---------- 이름 ---------- */` 구분자로 모듈이 나뉜다.
- `web/sw.js` — 서비스 워커. **API 경로(/jobs, /health, /diarize)는 절대 캐시하지 말 것**(과거 버그).
- `web/config.js` — 배포 설정(Google 클라이언트 ID, 로그인 필수).
- `server/diarize.py` — FastAPI 서버: 전사(faster-whisper) + 발언자 구분(pyannote/resemblyzer) + `web/` 정적 서빙.
- `desktop/` — PyInstaller exe 빌드. `android-capacitor/` — APK. `Dockerfile` — 도커.
- `tests/smoke.py` — Playwright 자동 점검(편집기·표·메모 시점·내보내기·저장/불러오기).

## 실행·검증
```powershell
cd web && python serve.py                 # 앱만 http://localhost:8080
cd server && .\install.ps1 ; python diarize.py   # 앱+서버 http://localhost:8765
python -m pip install playwright && python -m playwright install chromium
python tests/smoke.py                     # 수정 후 반드시 실행 (web/ 을 임시 localhost 포트로 띄워 점검)
```
JS 문법은 `node --check`로 확인 가능: `python tests/smoke.py --check-only`.

## 코드 규칙
- 사용자 전역 설정(AI 작성 설정 `draftOpt`, 추가 지시 템플릿 `draftTpls`, 작성자 `authorPref`, 다듬기·AI 엔진·발언자 분석)은 localStorage에 두고 `prefsTouch()`로 계정 DB(Firestore `users/{uid}/settings/prefs`)에 동기화한다. 새 설정을 만들면 `prefsLocal`/`prefsPull`에도 넣을 것. 회의별 정보는 `S`에 둔다(예: 이번 회의의 추가 지시 `S.aiExtra`).
- 버전은 출시 전 `0.x.y`. 사용자에게 보이는 변경을 하면 `APP_VERSION`과 `PATCH_NOTES`(설정 → 버전 정보)를 함께 올린다. 서비스 워커 캐시 이름은 배포 워크플로가 자동으로 바꾼다.
- 상태는 전역 `S` 하나. 파일(.mnote)에 저장될 정보는 반드시 `S`에 둔다. 저장/불러오기(`buildZip`/`openFile`)에 함께 추가한다.
- 편집기 블록은 `data-id`로 추적되며 `trackBlocks(track)`가 시점·편집 기록을 갱신한다(메모 `memoTrack`, 본문 `docTrack`). DOM을 직접 재배치했다면 `trackBlocks(track, {structural:true})`를 호출.
- 외부/파일에서 온 HTML은 `sanitizeHTML`을 거친다. 허용 태그·스타일·클래스·data 속성을 늘릴 때는 `processEl`을 수정.
- AI·분석 관련 실패는 `aiLog(level, msg, data)`에 남기고 사용자에게 **원인 + 해결 방법**을 함께 보여준다(`explainAIError`).
- 내보내기 글꼴은 `EXPORT_FONT`(Noto Sans KR) 하나로 통일한다. 내려받는 파일 이름은 `dlBase()`(회의록 이름_날짜시분초)를 쓴다. 참석자 표기는 `attendeesForExport()`(같은 소속은 직급 최고 1명 + 외 N인)를 거친다.
- 내보내기는 빌더 인터페이스(`B.para`, `B.table`)를 공유한다. 양식은 `TEMPLATES`, 서식 변환은 `hwpxBlock`/`inlineRuns`. HWPX·DOCX·PDF(HTML) 세 빌더에 동시에 반영할 것.
- Claude 아티팩트 안(`inClaude`)에서는 외부 네트워크·마이크·Google 로그인이 막힌다. 해당 기능은 `inClaude`/`framed` 분기로 안내한다.
- UI 문구는 한국어, 존댓말("~해요/~합니다"). 툴팁은 `toolbar tooltips` 섹션의 `T` 맵에 추가.

## 설계 결정(요약)
- 타임라인 시각은 녹음 시작 기준 초. 메모·본문 문단마다 최초 입력 시점 `t`와 편집 이력 `hist`를 보관해 "따라 쓰기" 재생을 만든다.
- AI 초안의 시각은 문단 **끝**(표는 행의 마지막 칸)에만 칩으로 표시(본문 중간에는 넣지 않음). 작성 옵션에서 끌 수 있다.
- AI 초안은 마크다운으로 받아 `mdToHtml`(미리보기) → `mdToDocNodes`(편집기 블록·표)로 바꿔 넣는다. 본문에 마크다운 기호가 그대로 들어가면 안 된다. 지시문(`buildPrompt`)은 전역 AI 작성 설정(설정 → AI 작성: 분량·문체·발언자·표 정리·항목·공통 지시) + 회의별 추가 지시(작성 화면의 작성 옵션) 순.
- 참고 자료(`S.refs`)는 변환된 글만 보관하고 원본 파일·Blob을 저장하지 않는다. AI에는 참고용으로만 보낸다(`refsRule`/`refsBlock`): 회의록 내용은 전사·메모에서, 자료에 없는 논의도 빠뜨리지 않게, 자료로 확인한 곳은 `(자료: 이름)` 표시. 새 파일 형식은 `extractRef`에 추가.
- 전사 목록은 `renderTranscript`가 그린다(검색 필터·수정 중에는 다시 그리지 않음 `segEdit`). 전사 행의 시각 버튼은 `data-segplay`(문단만 재생)이고 전역 `[data-seek]` 처리와 겹치지 않게 할 것.
- 녹음이 없는 회의는 전사 파일(.txt, 클로바노트 음성 기록·AI 요약)을 가져올 수 있다(`parseTranscriptText`/`importTranscriptFile`, 상태 `S.trImport`). 시간 기록이 없는 파일은 `segTimed()`가 false → 전사 시각을 화면·프롬프트·내보내기에 쓰지 말 것. 가져온 회의는 녹음·녹음 파일 붙이기를 막는다.
- 발언자 구분은 브라우저 내장(transformers.js, 경량)·PC 서비스(정확)·클라우드 API(클로바 스피치는 PC 서비스 프록시 `/cloud/clova` 경유, OpenAI·AssemblyAI·Deepgram은 브라우저 직접) 세 경로. 새 클라우드 서비스는 `CLOUD_PROV`+`CLOUD_RUN`에 추가하고 결과는 `{segments:[{t0,t1,text,spk}]}`로 돌려준다. API 키는 `cloudKeys()`에만 두고 prefs 동기화·로그에 넣지 말 것.
- 음성 인식에는 `meetingVocab()`(참석자·참고 자료 용어)을 힌트로 보낸다. 새 회의에 녹음 파일만 붙이면 분석 여부를 먼저 묻는다.
- 서버 작업은 한 번에 하나(`RUN_LOCK`), 취소는 문장 경계에서 반영, 진행률은 `progress(pct, stage, msg)`.
- exe에서는 OpenMP 충돌 방지 환경변수(`KMP_DUPLICATE_LIB_OK` 등)를 서버가 스스로 설정한다.

## 자주 하는 작업
- 회의록 양식 추가: `TEMPLATES`에 항목 추가(`fields`, `sections`, `render`). `docs/PROJECT.md` 5.3 참고.
- AI 엔진 추가: `PROVIDER_DEF` + `callOpenAI` 호환. 
- 배포: `git push`(Pages 자동), `desktop\build-exe.ps1`(exe).

## 하지 말 것
- `web/index.html`을 여러 파일로 쪼개지 말 것(단일 파일 배포·아티팩트 호환이 요구사항).
- `server/.venv`, `server/ffmpeg*`, `desktop/dist`를 커밋하지 말 것(.gitignore 참고).
- 빌드 산출물·모델 파일을 저장소에 올리지 말 것.
