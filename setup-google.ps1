# Saves your Google sign-in credentials into backend/.env (the secret is typed hidden and never shown).
# Get them first: Google Cloud Console -> Google Auth Platform -> Clients -> your Web client.
#
# Usage:  powershell -ExecutionPolicy Bypass -File setup-google.ps1

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$envFile = Join-Path $root "backend\.env"
$lines = [System.Collections.Generic.List[string]]([IO.File]::ReadAllLines($envFile))

function Set-Value([string]$name, [string]$value) {
    for ($i = 0; $i -lt $lines.Count; $i++) {
        if ($lines[$i] -match "^$name=") { $lines[$i] = "$name=$value"; return }
    }
    $lines.Add("$name=$value")
}

Write-Host "Google sign-in setup for Wayfinder" -ForegroundColor Yellow
Write-Host "Copy both values from your Web client at https://console.cloud.google.com/auth/clients`n"

do {
    $id = (Read-Host "Client ID (ends with .apps.googleusercontent.com)").Trim()
    $okId = $id -match '^[0-9]+-[a-z0-9]+\.apps\.googleusercontent\.com$'
    if (-not $okId) { Write-Host "  That doesn't look like a Google client ID - copy the whole value and try again." -ForegroundColor Red }
} until ($okId)

do {
    $secure = Read-Host "Client secret (hidden, usually starts with GOCSPX-)" -AsSecureString
    $secret = [Runtime.InteropServices.Marshal]::PtrToStringAuto([Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)).Trim()
    $okSecret = $secret.Length -ge 20 -and $secret -notmatch '\s'
    if (-not $okSecret) { Write-Host "  That doesn't look like a client secret - try again." -ForegroundColor Red }
} until ($okSecret)

Set-Value "GOOGLE_CLIENT_ID" $id
Set-Value "GOOGLE_CLIENT_SECRET" $secret
[IO.File]::WriteAllLines($envFile, $lines, (New-Object Text.UTF8Encoding($false)))
$hint = if ($secret.StartsWith("GOCSPX-")) { "GOCSPX-..." } else { "(saved)" }
Write-Host "`nSaved to backend\.env  (client ID $($id.Substring(0, [Math]::Min(12, $id.Length)))..., secret $hint)" -ForegroundColor Green
Write-Host "Now tell Claude 'done' - it will restart the backend and test Google sign-in."
