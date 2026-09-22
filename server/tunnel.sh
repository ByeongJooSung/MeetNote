#!/usr/bin/env bash
# 휴대폰·다른 기기용 https 터널 (Cloudflare 빠른 터널). 먼저 python diarize.py 를 켜 두세요.
# 사용: bash server/tunnel.sh [포트=8765]  → 나오는 https 주소를 앱의 PC 서비스 주소에, AI 서버 주소에는 주소/llm
PORT="${1:-8765}"
if ! command -v cloudflared >/dev/null 2>&1; then
  if command -v brew >/dev/null 2>&1; then brew install cloudflared; else echo "cloudflared가 필요해요: https://github.com/cloudflare/cloudflared/releases"; exit 1; fi
fi
cloudflared tunnel --url "http://localhost:$PORT" 2>&1 | while IFS= read -r line; do
  if [[ "$line" =~ https://[a-z0-9-]+\.trycloudflare\.com ]]; then
    u="${BASH_REMATCH[0]}"
    echo; echo "================================================================"
    echo " PC 서비스 주소(발언자 구분):   $u"
    echo " AI 서버 주소(LM Studio 대신):  $u/llm"
    echo "================================================================"; echo
  fi
done
