# dev-sign.ps1 — WDAC/HVCI workaround for 0Lith development
#
# Required one-time setup (admin PowerShell):
#   $cert = New-SelfSignedCertificate -Subject "CN=0Lith Dev" -CertStoreLocation "Cert:\CurrentUser\My" -KeyUsage DigitalSignature -Type CodeSigningCert -NotAfter (Get-Date).AddYears(5)
#   $cer = Export-Certificate -Cert $cert -FilePath "$env:USERPROFILE\Desktop\0lith-dev.cer"
#   Import-Certificate -FilePath $cer.FullName -CertStoreLocation "Cert:\LocalMachine\Root"
#   Import-Certificate -FilePath $cer.FullName -CertStoreLocation "Cert:\LocalMachine\TrustedPublisher"
#
# Dev workflow:
#   Terminal 1 (from 0lith-desktop/): npm run dev        # Vite HMR
#   Terminal 2 (from 0lith-desktop/): .\scripts\dev-sign.ps1  # Build + sign + run

$EXE          = "$env:USERPROFILE\AppData\Local\olith-build\debug\olith-desktop.exe"
$SRC_TAURI    = (Get-Item "$PSScriptRoot\..\src-tauri").FullName
$CERT_SUBJECT = "CN=0Lith Dev"

# --- Kill existing instance ---
$existing = Get-Process "olith-desktop" -ErrorAction SilentlyContinue
if ($existing) {
    Write-Host "  Stopping existing instance..." -ForegroundColor Yellow
    $existing | Stop-Process -Force
    Start-Sleep -Milliseconds 500
}

# --- Build ---
Write-Host "`n[1/3] Building Rust..." -ForegroundColor Cyan
Push-Location $SRC_TAURI
cargo build
$buildOk = $LASTEXITCODE -eq 0
Pop-Location

if (-not $buildOk) {
    Write-Host "[1/3] Build FAILED" -ForegroundColor Red
    exit 1
}
Write-Host "[1/3] Build OK" -ForegroundColor Green

# --- Sign ---
Write-Host "[2/3] Signing binary..." -ForegroundColor Cyan
$cert = Get-ChildItem "Cert:\CurrentUser\My" |
    Where-Object { $_.Subject -eq $CERT_SUBJECT } |
    Select-Object -First 1

if (-not $cert) {
    Write-Host "[2/3] Certificate '$CERT_SUBJECT' not found. Run the one-time setup first." -ForegroundColor Red
    exit 1
}

$sig = Set-AuthenticodeSignature -FilePath $EXE -Certificate $cert
if ($sig.Status -ne "Valid") {
    Write-Host "[2/3] Signing FAILED: $($sig.StatusMessage)" -ForegroundColor Red
    exit 1
}
Write-Host "[2/3] Signed OK  ($($cert.Thumbprint.Substring(0,8))...)" -ForegroundColor Green

# --- Launch ---
Write-Host "[3/3] Launching 0Lith..." -ForegroundColor Cyan
Start-Process -FilePath $EXE -WorkingDirectory $SRC_TAURI
Write-Host "[3/3] Started.`n" -ForegroundColor Green
Write-Host "  Keep 'npm run dev' running in the other terminal for Svelte HMR." -ForegroundColor DarkGray
