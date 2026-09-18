# 로컬 LLM으로 AI 회의록 만들기 (LM Studio / Ollama)

MeetNote의 화면 위쪽 **⚙ 설정 → AI 엔진**에서 LM Studio, Ollama, 또는 OpenAI 호환 서버를 고르면
회의 메모가 PC 밖으로 나가지 않고 내 컴퓨터의 모델이 초안을 씁니다.
브라우저가 서버에 직접 요청하므로 **CORS 허용**이 핵심입니다.

## LM Studio
1. 모델을 내려받아 로드합니다(한국어는 `Qwen2.5 7B Instruct`, `EXAONE 3.5 7.8B` 추천).
2. 왼쪽 **Developer(</>)** 탭 → **Start Server**. 기본 주소는 `http://localhost:1234`.
3. 같은 화면의 **Settings**에서 **Enable CORS**를 켭니다.
4. MeetNote 엔진을 **LM Studio**로 고르고 **모델 불러오기** → 초안 작성.

## Ollama
```bash
ollama pull qwen2.5:7b
# CORS 허용 후 실행 (터미널을 새로 열어 아래처럼 실행)
OLLAMA_ORIGINS="https://byeongjoosung.github.io" ollama serve   # 내 배포 주소만 허용 (시험용으로만 "*")
```
- Windows: 시스템 환경 변수에 `OLLAMA_ORIGINS` = `https://byeongjoosung.github.io` 추가 후 Ollama 재시작.
- macOS 앱: `launchctl setenv OLLAMA_ORIGINS "https://byeongjoosung.github.io"` 후 재시작.
- MeetNote 엔진을 **Ollama**로 고르고(주소 `http://localhost:11434`) **모델 불러오기**.

## 휴대폰에서 PC의 모델 쓰기
1. 서버를 외부 접속 허용으로 켭니다. Ollama: `OLLAMA_HOST=0.0.0.0 OLLAMA_ORIGINS="*" ollama serve`. LM Studio: Settings → **Serve on Local Network**.
2. MeetNote 서버 주소에 PC의 IP를 넣습니다. 예 `http://192.168.0.10:11434`.
3. **주의**: MeetNote를 https 주소(GitHub Pages 등)로 열었다면 브라우저가 http 서버 호출을 막습니다(혼합 콘텐츠).
   이때는 MeetNote도 같은 PC에서 `python3 web/serve.py`로 http로 띄우고 휴대폰에서 `http://PC-IP:8080`으로 접속하세요.
   (http 접속에서는 마이크가 막히므로 "녹음 파일 붙이기" 방식으로 쓰면 됩니다.)
   APK로 설치한 앱은 `allowMixedContent`가 켜져 있어 `http://PC-IP:11434` 주소를 바로 쓸 수 있습니다.

## 외부에서 접속할 때: 보안 토큰 (선택)
서버를 터널(cloudflared 등)이나 포트 개방으로 인터넷에 열면 주소를 아는 누구나 모델을 쓸 수 있습니다. 서버에 API 키(토큰)를 걸고,
MeetNote **⚙ 설정 → AI 엔진 → 보안 토큰**에 같은 값을 넣으세요. 요청마다 `Authorization: Bearer 토큰`으로 보냅니다.
- LM Studio: Developer → Server Settings에서 인증(API 키) 사용 · vLLM / llama.cpp 서버: `--api-key 값`
- Ollama는 자체 인증이 없어 앞단 프록시(Caddy·nginx)에서 `Authorization` 헤더를 검사하게 합니다.
- 토큰은 기본으로 **그 탭을 닫으면 지워지고**, "이 브라우저에 기억"을 켠 경우에만 브라우저에 저장됩니다. 로그·.mnote 파일에는 남지 않습니다.
- 브라우저가 미리 보내는 확인 요청(OPTIONS, CORS preflight)에는 토큰이 없으므로, 프록시를 쓴다면 OPTIONS는 인증 없이 통과시키세요.

## 모델 고르기 팁
- 7B~8B 크기면 회의록 정리에 충분하고, 8GB VRAM 또는 16GB RAM(맥)이면 돌아갑니다.
- 답이 영어로 나오면 더 큰 모델이거나 한국어 특화 모델(EXAONE, HyperCLOVA X SEED)을 써 보세요.
- `<think>` 태그를 내는 추론 모델(DeepSeek-R1 등)도 지원합니다. 태그 부분은 자동으로 지웁니다.

## 자주 겪는 문제
| 증상 | 원인 / 해결 |
|---|---|
| "서버에 연결할 수 없어요" | 서버가 꺼져 있거나 CORS 미허용. 브라우저 개발자도구(F12) Console에 CORS 오류가 보이면 위 설정 확인 |
| 모델 목록이 비어 있음 | LM Studio에서 모델을 로드하지 않음 / Ollama는 `ollama list`로 확인 |
| 응답이 매우 느림 | 모델이 GPU에 안 올라감. 더 작은 양자화(Q4) 모델 사용 |

## 안 될 때: 로그 보기
**⚙ 설정 → 로그** 탭에 엔진·서버 주소·모델·HTTP 상태·오류 본문이 시간순으로 남습니다.
**복사**를 눌러 붙여 넣어 주시면 원인을 바로 좁힐 수 있어요. 자주 나오는 원인:
- `Failed to fetch` + 서버 로그에 요청 없음 → 서버가 꺼져 있거나 주소/포트가 다름
- `Failed to fetch` 인데 서버 로그에는 요청이 찍힘 → CORS 미허용
- `HTTP 404` → 서버가 `/v1/chat/completions`를 제공하지 않음(Ollama 구버전은 업데이트)
- `HTTP 400 model not loaded` → LM Studio에서 모델을 로드하지 않음
- `no_sample` → Claude 화면 밖에서 열었는데 엔진이 "Claude"로 남아 있음 → 엔진 변경
- `sampling_disabled` / `not_granted` → Claude 아티팩트의 AI 호출이 조직 정책으로 꺼져 있거나 사용자가 거절함
