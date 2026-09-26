# Windows: 이 폴더에서  .\install.ps1  실행
# Python 3.11 또는 3.12를 우선 사용 (3.13+ 는 faster-whisper/torch 설치 파일이 없을 수 있음)
$py = $null
foreach ($v in @("3.11", "3.12", "3.10")) {
  if (Get-Command py -ErrorAction SilentlyContinue) { & py -$v --version 2>$null | Out-Null; if ($LASTEXITCODE -eq 0) { $py = "py -$v"; break } }
}
if (-not $py) { $py = "python"; Write-Host "경고: Python 3.11/3.12를 찾지 못해 기본 python을 사용합니다. 설치 실패 시 3.11을 설치하세요." -ForegroundColor Yellow }
Write-Host "사용할 파이썬: $py"
if (-not (Test-Path .venv)) { Invoke-Expression "$py -m venv .venv" }
.\.venv\Scripts\Activate.ps1
python --version
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m pip install resemblyzer --no-deps
python -m pip uninstall -y typing 2>$null
if (-not (Get-Command ffmpeg -ErrorAction SilentlyContinue)) { Write-Host "ffmpeg가 PATH에 없어요. imageio-ffmpeg 동봉본을 자동으로 사용합니다." -ForegroundColor Yellow }
Write-Host "설치 완료. 실행:  python diarize.py" -ForegroundColor Green
