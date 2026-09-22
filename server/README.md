# MeetNote 발언자 구분 서비스

브라우저에서 보낸 녹음을 받아 **전사 + 발언자 구분** 결과를 돌려주는 로컬 서비스입니다. 데이터는 PC 밖으로 나가지 않습니다.

## 설치
```powershell
# Windows PowerShell (server 폴더에서)
.\install.ps1
python diarize.py            # http://localhost:8765
```
```bash
# macOS / Linux
./install.sh
python diarize.py
```
- ffmpeg 필요: Windows `winget install ffmpeg`, macOS `brew install ffmpeg`, Ubuntu `sudo apt install ffmpeg` (설치 후 터미널 새로 열기)
- PowerShell에서 스크립트 실행이 막히면 `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` 한 번 실행
- 서비스는 시작할 때 Whisper 모델(small 약 460MB)을 미리 내려받아요. 서버 창에 진행률이 보이고 `[preload] 준비 완료`가 뜨면 바로 분석할 수 있습니다. (`PRELOAD=0`이면 첫 분석 요청 때 받습니다)
MeetNote → 전사 탭 → **발언자 구분** → "음성 분석 서비스" → 실행.

## 모델 선택
| 구성 | 정확도 | 준비 | 자원 |
|---|---|---|---|
| faster-whisper `small` + resemblyzer 군집 (기본) | 보통 | 없음 | CPU 가능 |
| faster-whisper `small` + **pyannote 3.1** | 높음 | HF 토큰 + 모델 약관 동의 | CPU 느림, GPU 권장 |
| faster-whisper `medium`/`large-v3` | 전사 정확도 ↑ | `WHISPER_MODEL=medium` | GPU 권장 |
| faster-whisper `large-v3-turbo` | large-v3에 가까운 정확도, 훨씬 빠름 | `WHISPER_MODEL=large-v3-turbo` | GPU 권장(약 1.6GB) |
| 회의 용어 사전 | 참석자 이름·참고 자료 용어를 힌트로 받아 고유명사 인식 ↑ | 앱의 분석 창에서 체크(기본 켜짐) | 서버가 `vocab`을 받아 `hotwords`로 사용 |
| 휴대폰에서 LM Studio 쓰기 | `/llm/*`가 LM Studio·Ollama를 대신 호출(`LLM_BASE`). `tunnel.ps1`로 https 터널을 만들어 앱의 AI 서버 주소에 `터널주소/llm` | `powershell -ExecutionPolicy Bypass -File server	unnel.ps1` | 인터넷에 열리니 LM Studio API 키 권장 |
| 클로바 스피치 프록시 | 앱의 클라우드 API → 네이버 클로바 스피치를 이 서버가 대신 호출(브라우저 CORS 제한) | 앱에서 Invoke URL·Secret Key 입력, 또는 `CLOVA_SPEECH_URL`/`CLOVA_SPEECH_KEY` | 키는 저장하지 않음 |

pyannote 사용: https://huggingface.co/pyannote/speaker-diarization-3.1 과 `pyannote/segmentation-3.0` 약관 동의 → 토큰 발급 →
```bash
pip install pyannote.audio torch
HF_TOKEN=hf_xxx python diarize.py       # Windows PowerShell: $env:HF_TOKEN="hf_xxx"; python diarize.py
```

## 옵션(환경변수)
`WHISPER_MODEL`(tiny/base/small/medium/large-v3/large-v3-turbo), `DEVICE`(auto/cpu/cuda), `COMPUTE`(int8/float16), `PORT`(8765)

## API
- `POST /jobs` (multipart: audio, lang=ko, num_speakers?) → `{job_id}` — 진행률 보고 방식(앱 기본)
- `GET /jobs/{id}` → `{state, pct, stage, message, result?}` · `DELETE /jobs/{id}` 취소
- `POST /diarize` 동기 방식 → `{segments:[{t0,t1,text,spk}]}` · `GET /health`
