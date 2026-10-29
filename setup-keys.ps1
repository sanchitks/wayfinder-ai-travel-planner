# Interactive API key setup for Wayfinder.
# Prompts for each key (input is hidden), writes backend/.env, then verifies every key.
# Press Enter at any prompt to keep the current value (or leave it blank).
#
# Usage:  powershell -ExecutionPolicy Bypass -File setup-keys.ps1

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$backend = Join-Path $root "backend"
$envFile = Join-Path $backend ".env"
$template = Join-Path $backend ".env.example"

if (-not (Test-Path $envFile)) { Copy-Item $template $envFile }
$lines = [System.Collections.Generic.List[string]]([IO.File]::ReadAllLines($envFile))

function Get-Current([string]$name) {
    foreach ($l in $lines) { if ($l -match "^$name=(.*)$") { return $Matches[1] } }
    return ""
}

function Set-Value([string]$name, [string]$value) {
    for ($i = 0; $i -lt $lines.Count; $i++) {
        if ($lines[$i] -match "^$name=") { $lines[$i] = "$name=$value"; return }
    }
    $lines.Add("$name=$value")
}

function Ask([string]$name, [string]$what, [string]$where, [switch]$Visible) {
    $current = Get-Current $name
    $state = if ($current) { "currently SET - Enter keeps it" } else { "currently empty - Enter skips" }
    Write-Host ""
    Write-Host "$name" -ForegroundColor Cyan -NoNewline
    Write-Host "  ($state)"
    Write-Host "  $what"
    Write-Host "  Get it: $where" -ForegroundColor DarkGray
    if ($Visible) {
        $value = Read-Host "  Value"
    } else {
        $secure = Read-Host "  Paste key (hidden)" -AsSecureString
        $value = [Runtime.InteropServices.Marshal]::PtrToStringAuto([Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure))
    }
    $value = $value.Trim()
    if ($value) { Set-Value $name $value; Write-Host "  saved" -ForegroundColor Green }
}

Write-Host "Wayfinder API key setup - see KEYS.md for step-by-step sign-up instructions." -ForegroundColor Yellow
Write-Host "Every key is optional; anything left empty falls back to sample data."

Ask "OPENROUTER_API_KEY" "Claude Opus 5.5 via OpenRouter - the AI brain of all agents (needs prepaid credits)." "https://openrouter.ai/settings/keys"
if (-not (Get-Current "OPENROUTER_API_KEY")) {
    Ask "ANTHROPIC_API_KEY" "Alternative: Claude API directly (only used if no OpenRouter key)." "https://platform.claude.com/settings/keys"
}
Ask "IGNAV_API_KEY" "Live flight fares in INR + airline booking links (1,000 free requests)." "https://ignav.com"
Ask "GOOGLE_PLACES_API_KEY" "Real sights, temples and restaurants (Places API (New); free monthly usage, needs billing)." "https://console.cloud.google.com/google/maps-apis/credentials"
Ask "GOOGLE_CLIENT_ID" "Google sign-in: OAuth Web client ID (free; see KEYS.md for the redirect URI to register)." "https://console.cloud.google.com/auth/clients" -Visible
if (Get-Current "GOOGLE_CLIENT_ID") {
    Ask "GOOGLE_CLIENT_SECRET" "Google sign-in: the same client's secret." "https://console.cloud.google.com/auth/clients"
}
Ask "RAPIDAPI_KEY" "One key for Skyscanner flights + Booking.com hotels (subscribe to both free Basic plans)." "https://rapidapi.com/apiheya/api/sky-scrapper  and  https://rapidapi.com/DataCrawler/api/booking-com15"
$yelp = Read-Host "`nDo you have a Yelp Places API key (optional, paid after trial)? [y/N]"
if ($yelp -match '^[yY]') { Ask "YELP_API_KEY" "Extra restaurant reviews (thin coverage in India)." "https://www.yelp.com/developers/v3/manage_app" }

[IO.File]::WriteAllLines($envFile, $lines, (New-Object Text.UTF8Encoding($false)))
Write-Host "`nWrote $envFile" -ForegroundColor Green

$python = Join-Path $backend ".venv\Scripts\python.exe"
if (Test-Path $python) {
    Write-Host "Verifying keys...`n"
    Push-Location $backend
    & $python -W ignore check_keys.py
    Pop-Location
} else {
    Write-Host "Run start.ps1 once to create the Python environment, then: cd backend; .venv\Scripts\python check_keys.py"
}
