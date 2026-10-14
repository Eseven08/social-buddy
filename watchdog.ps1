# watchdog.ps1 — keeps NapCat (port 3000) and social-buddy (port 8765) alive.
# Usage:
#   powershell -ExecutionPolicy Bypass -File watchdog.ps1 `
#       -NapcatDir "G:\NapCatOneKey\NapCat.52230.Shell" -BotDir "G:\social-buddy"
# Safe to run repeatedly: a second instance exits immediately.

param(
    [Parameter(Mandatory = $true)][string]$NapcatDir,
    [Parameter(Mandatory = $true)][string]$BotDir
)

# Self-guard: only one watchdog per machine.
$me = $PID
$others = Get-CimInstance Win32_Process -Filter "Name='powershell.exe'" |
    Where-Object { $_.CommandLine -match "watchdog.ps1" -and $_.ProcessId -ne $me }
if ($others) { exit }

# Read the bot's QQ number from config.env so NapCat can quick-login.
$qq = ""
if (Test-Path "$BotDir\config.env") {
    $line = Get-Content "$BotDir\config.env" |
        Where-Object { $_ -match "^SOCIAL_BUDDY_QQ_SELF=" } | Select-Object -First 1
    if ($line) {
        $qq = ($line -replace "^SOCIAL_BUDDY_QQ_SELF=", "").Trim()
        $qq = ($qq -split "\s*#")[0].Trim()
    }
}

while ($true) {
    # NapCat up?
    $napcatUp = Get-NetTCPConnection -LocalPort 3000 -State Listen -ErrorAction SilentlyContinue
    if (-not $napcatUp) {
        if ($qq) {
            Start-Process cmd -ArgumentList "/c", "cd /d `"$NapcatDir`" && NapCatWinBootMain.exe $qq > napcat-run.log 2>&1" -WindowStyle Hidden
        } else {
            Start-Process cmd -ArgumentList "/c", "cd /d `"$NapcatDir`" && NapCatWinBootMain.exe > napcat-run.log 2>&1" -WindowStyle Hidden
        }
        Start-Sleep -Seconds 20
    }
    # Bot up?
    $botUp = Get-NetTCPConnection -LocalPort 8765 -State Listen -ErrorAction SilentlyContinue
    if (-not $botUp) {
        Start-Process cmd -ArgumentList "/c", "cd /d `"$BotDir`" && python main.py onebot > onebot-run.log 2>&1" -WindowStyle Hidden
        Start-Sleep -Seconds 5
    }
    Start-Sleep -Seconds 10
}
