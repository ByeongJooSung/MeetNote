# Windows: 이 폴더에서  .\install.ps1  실행
if (-not (Test-Path .venv)) { python -m venv .venv }
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
pip install resemblyzer --no-deps
pip uninstall -y typing 2>$null
if (-not (Get-Command ffmpeg -ErrorAction SilentlyContinue)) { Write-Host "ffmpeg가 없어요. 'winget install ffmpeg' 후 PowerShell을 새로 여세요." -ForegroundColor Yellow }
Write-Host "설치 완료. 실행:  python diarize.py" -ForegroundColor Green
