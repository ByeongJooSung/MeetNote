# 휴대폰·다른 기기에서 PC 서비스(전사·발언자 구분)와 PC의 LM Studio·Ollama를 쓰기 위한 https 터널 (Cloudflare 빠른 터널, 무료·계정 불필요)
# 사용:  powershell -ExecutionPolicy Bypass -File server\tunnel.ps1 [-Port 8765]
#  1) 먼저 python diarize.py(PC 서비스)를 켜 두세요. LM Studio도 서버 켜기(Enable CORS, 인터넷에 열리니 API 키 설정 권장).
#  2) 이 스크립트가 알려 주는 https 주소를 앱의 "발언자 구분 → PC 서비스 주소"에, "설정 → AI 엔진 → 서버 주소"에는 주소 뒤에 /llm 을 붙여 넣으세요.
#  주소는 실행할 때마다 바뀝니다. 창을 닫으면 터널도 끝나요.
param([int]$Port = 8765)
if (-not (Get-Command cloudflared -ErrorAction SilentlyContinue)) {
  Write-Host "cloudflared를 설치합니다 (winget)..." -ForegroundColor Yellow
  winget install --id Cloudflare.cloudflared -e --accept-source-agreements --accept-package-agreements
  $env:PATH = [System.Environment]::GetEnvironmentVariable("PATH", "Machine") + ";" + [System.Environment]::GetEnvironmentVariable("PATH", "User")
  if (-not (Get-Command cloudflared -ErrorAction SilentlyContinue)) { Write-Host "cloudflared를 찾지 못했어요. 새 PowerShell 창에서 다시 실행하거나 https://github.com/cloudflare/cloudflared/releases 에서 받아 PATH에 넣어 주세요." -ForegroundColor Red; exit 1 }
}
try { $h = Invoke-RestMethod "http://localhost:$Port/health" -TimeoutSec 3; Write-Host "PC 서비스 확인: whisper=$($h.whisper) llm=$($h.llm)" -ForegroundColor Green }
catch { Write-Host "포트 $Port 에서 PC 서비스가 응답하지 않아요. 먼저 'python diarize.py'를 켜 주세요. (그래도 터널은 만듭니다)" -ForegroundColor Yellow }
Write-Host "https 터널을 만드는 중... (주소가 나오면 휴대폰 앱에 넣으세요)" -ForegroundColor Cyan
cloudflared tunnel --url "http://localhost:$Port" 2>&1 | ForEach-Object {
  $line = "$_"
  if ($line -match "https://[a-z0-9-]+\.trycloudflare\.com") {
    $u = $Matches[0]
    Write-Host ""
    Write-Host "================================================================" -ForegroundColor Green
    Write-Host " PC 서비스 주소(발언자 구분 · 클로바 프록시):  $u" -ForegroundColor Green
    Write-Host " AI 서버 주소(설정 → AI 엔진, LM Studio 대신):  $u/llm" -ForegroundColor Green
    Write-Host " 앱 자체도 이 주소로 열 수 있어요(웹 앱 내장 시):  $u/" -ForegroundColor Green
    Write-Host "================================================================" -ForegroundColor Green
    Write-Host ""
  } elseif ($line -match "error|failed") { Write-Host $line -ForegroundColor Red }
}
