# Windows PowerShell: GitHub 저장소 만들고 올리기 (GitHub CLI 필요: winget install GitHub.cli)
# 사용:  .\publish.ps1 meetnote          (저장소 이름, 기본 public)
param([string]$Name = "meetnote", [string]$Visibility = "public")
Set-Location $PSScriptRoot
if (-not (Get-Command gh -ErrorAction SilentlyContinue)) { Write-Host "GitHub CLI(gh)가 필요해요: winget install GitHub.cli 후 새 창에서 gh auth login" -ForegroundColor Yellow; exit 1 }
gh auth status 2>$null; if ($LASTEXITCODE -ne 0) { gh auth login }
if (-not (Test-Path .git)) { git init -b main }
git add .
git commit -m "MeetNote: 초기 배포" 2>$null | Out-Null
gh repo create $Name --$Visibility --source=. --push
$owner = gh api user -q .login
gh api -X POST "repos/$owner/$Name/pages" -f build_type=workflow 2>$null | Out-Null
Write-Host ""
Write-Host "완료. 1~2분 뒤 https://$owner.github.io/$Name/ 에서 열립니다." -ForegroundColor Green
Write-Host "Google 로그인: Cloud Console '승인된 JavaScript 원본'에 https://$owner.github.io 추가 후 web/config.js에 클라이언트 ID 입력 → git push"
