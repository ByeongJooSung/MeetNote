# Windows: MeetNote 앱 + 발언자 구분 서버를 하나의 폴더(exe)로 묶습니다.
# 사용:  desktop 폴더에서  .\build-exe.ps1   → dist\MeetNote\MeetNote.exe
Set-Location $PSScriptRoot
$py = "..\server\.venv\Scripts\python.exe"
if (-not (Test-Path $py)) { Write-Host "먼저 server\install.ps1 로 가상환경을 만들어 주세요." -ForegroundColor Yellow; exit 1 }
& $py -m pip install pyinstaller
$ff = Get-ChildItem ..\server -Recurse -Filter ffmpeg.exe -ErrorAction SilentlyContinue | Select-Object -First 1
if (-not $ff) { Write-Host "server\ffmpeg 폴더에 ffmpeg.exe가 없어요. https://www.gyan.dev/ffmpeg/builds/ essentials zip을 server\ffmpeg 에 풀어 두면 exe에 함께 들어갑니다." -ForegroundColor Yellow }
& $py -m PyInstaller meetnote.spec --noconfirm --clean
if ($LASTEXITCODE -eq 0) {
  Write-Host ""
  Write-Host "완성: dist\MeetNote\MeetNote.exe  (폴더째 배포. 실행하면 브라우저가 http://localhost:8765 로 열립니다)" -ForegroundColor Green
  Write-Host "처음 실행 시 Whisper 모델(약 460MB)을 내려받습니다. 미리 넣으려면 아래 README의 '모델 동봉' 참고."
}
