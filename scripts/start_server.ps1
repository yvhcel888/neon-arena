[CmdletBinding()]
param(
    [string]$BindHost = "0.0.0.0",
    [ValidateRange(1, 65535)]
    [int]$TcpPort = 7777,
    [ValidateRange(1, 65535)]
    [int]$ApiPort = 8080,
    [ValidateRange(0, 600000)]
    [int]$TickMs = 15000,
    [ValidateRange(0, 600000)]
    [int]$MinTurnMs = 250,
    [ValidateRange(1, 10000)]
    [int]$TurnLimit = 80,
    [ValidateRange(2, 4)]
    [int]$MinPlayers = 2,
    [ValidateRange(2, 4)]
    [int]$MaxPlayers = 4,
    [ValidateRange(0, 600000)]
    [int]$LobbyWaitMs = 5000,
    [ValidateSet("rotation", "classic", "king", "team", "survival", "bounty")]
    [string]$Mode = "rotation",
    [string]$Python = "python",
    [switch]$NoLogs
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$serverDir = Join-Path $projectRoot "server"
$serverArgs = @(
    "-m", "arena_server",
    "--host", $BindHost,
    "--tcp-port", "$TcpPort",
    "--api-port", "$ApiPort",
    "--tick-ms", "$TickMs",
    "--min-turn-ms", "$MinTurnMs",
    "--turn-limit", "$TurnLimit",
    "--min-players", "$MinPlayers",
    "--max-players", "$MaxPlayers",
    "--lobby-wait-ms", "$LobbyWaitMs",
    "--mode", $Mode
)
if ($NoLogs) { $serverArgs += "--no-logs" }
if ($VerbosePreference -eq "Continue") { $serverArgs += "--verbose" }
if ($MinPlayers -gt $MaxPlayers) {
    throw "MinPlayers must be less than or equal to MaxPlayers."
}
if ($Mode -eq "team" -and $MaxPlayers -lt 4) {
    throw "Team mode requires MaxPlayers=4."
}

Push-Location -LiteralPath $serverDir
try {
    & $Python @serverArgs
    $exitCode = $LASTEXITCODE
}
finally {
    Pop-Location
}
return $exitCode
