param(
    [string]$BindHost = "127.0.0.1",
    [ValidateRange(1, 65535)]
    [int]$TcpPort = 7777,
    [ValidateRange(1, 65535)]
    [int]$ApiPort = 8080,
    [ValidateRange(1, 65535)]
    [int]$ClientPort = 8090,
    [ValidateRange(0, 600000)]
    [int]$TickMs = 15000,
    [ValidateRange(1, 10000)]
    [int]$TurnLimit = 80,
    [ValidateRange(3, 4)]
    [int]$MinPlayers = 3,
    [ValidateRange(2, 4)]
    [int]$MaxPlayers = 4,
    [ValidateRange(0, 600000)]
    [int]$LobbyWaitMs = 1000,
    [ValidateSet("rotation", "classic", "king", "team", "survival", "bounty")]
    [string]$Mode = "rotation",
    [string]$Python = "python",
    [switch]$NoOpen
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$serverDir = Join-Path $projectRoot "server"
$agentsDir = Join-Path $projectRoot "agents"
$clientDir = Join-Path $projectRoot "client"
$apiUrl = "http://${BindHost}:${ApiPort}/api/v1"
$server = $null
$client = $null
$bots = @()

function Quote-CommandLineArgument {
    param([string]$Value)
    if ($Value -match '[\s"]') {
        $escaped = $Value -replace '(\\*)"', '$1$1\"'
        $escaped = $escaped -replace '(\\+)$', '$1$1'
        return '"' + $escaped + '"'
    }
    return $Value
}

function Quote-PowerShellLiteral {
    param([string]$Value)
    return "'" + $Value.Replace("'", "''") + "'"
}

function Get-DescendantProcessIds {
    param([int]$ProcessId, [object[]]$AllProcesses)
    $descendantIds = New-Object System.Collections.ArrayList
    foreach ($candidate in @($AllProcesses | Where-Object {
        $_.ParentProcessId -eq $ProcessId
    })) {
        [void]$descendantIds.Add([int]$candidate.ProcessId)
        foreach ($nestedId in @(Get-DescendantProcessIds `
            -ProcessId ([int]$candidate.ProcessId) -AllProcesses $AllProcesses)) {
            [void]$descendantIds.Add($nestedId)
        }
    }
    return $descendantIds.ToArray()
}

function Wait-ProcessExit {
    param($Process, [int]$TimeoutMilliseconds = 5000)
    if ($null -eq $Process) { return }
    try {
        $Process.Refresh()
        if ($Process.HasExited) { return }
        $exited = $Process.WaitForExit($TimeoutMilliseconds)
        $Process.Refresh()
        if ($exited -and $Process.HasExited) { return }

        # WaitForExit can time out while descendants or their wrappers remain.
        Stop-Process -Id $Process.Id -Force -ErrorAction SilentlyContinue
        $null = $Process.WaitForExit($TimeoutMilliseconds)
        $Process.Refresh()
        if (-not $Process.HasExited) {
            Write-Warning "Process $($Process.Id) did not exit within $TimeoutMilliseconds ms after forced cleanup."
        }
    }
    catch {
        try {
            $Process.Refresh()
            if (-not $Process.HasExited) {
                Write-Warning "Could not wait for process $($Process.Id): $($_.Exception.Message)"
            }
        }
        catch { }
    }
}

function Stop-ProcessTree {
    param($Process)
    if ($null -eq $Process) { return }
    try {
        $processId = [int]$Process.Id
        $allProcesses = @()
        try {
            $allProcesses = @(Get-CimInstance -ClassName Win32_Process -ErrorAction Stop)
        }
        catch { }
        $descendantIds = @(Get-DescendantProcessIds `
            -ProcessId $processId -AllProcesses $allProcesses)

        # Always attempt the tree kill: the root may already have exited while
        # its PowerShell/Python descendants are still running.
        & taskkill /PID $processId /T /F 2>$null | Out-Null
        if ($LASTEXITCODE -ne 0) {
            for ($index = $descendantIds.Count - 1; $index -ge 0; $index--) {
                Stop-Process -Id $descendantIds[$index] -Force -ErrorAction SilentlyContinue
            }
            Stop-Process -Id $processId -Force -ErrorAction SilentlyContinue
        }

        # Verify descendants as well as the wrapper, with bounded waits and a
        # forced-kill retry whenever WaitForExit reports a timeout.
        for ($index = $descendantIds.Count - 1; $index -ge 0; $index--) {
            $descendant = Get-Process -Id $descendantIds[$index] -ErrorAction SilentlyContinue
            if ($null -ne $descendant) {
                Wait-ProcessExit -Process $descendant -TimeoutMilliseconds 5000
            }
        }
        Wait-ProcessExit -Process $Process -TimeoutMilliseconds 5000
    }
    catch {
        Write-Warning "Could not clean process tree for PID $($Process.Id): $($_.Exception.Message)"
    }
}

function Wait-ServerReady {
    param($Process, [string]$Url)
    $deadline = (Get-Date).AddSeconds(15)
    while ((Get-Date) -lt $deadline) {
        $Process.Refresh()
        if ($Process.HasExited) {
            throw "NEON ARENA server exited before becoming ready."
        }
        try {
            $health = Invoke-RestMethod -Uri ($Url + "/health") -TimeoutSec 1
            if ($health.ok) { return }
        }
        catch { }
        Start-Sleep -Milliseconds 100
    }
    throw "NEON ARENA server health check timed out."
}

try {
    if ($MinPlayers -gt $MaxPlayers) {
        throw "MinPlayers must be less than or equal to MaxPlayers."
    }
    if ($Mode -eq "team") {
        if ($MaxPlayers -lt 4) {
            throw "Team mode requires MaxPlayers=4."
        }
        throw "Team mode requires four guaranteed participants. play.ps1 provides two bots plus one human seat, not four guaranteed participants. Use start_server.ps1 -Mode team -MinPlayers 4 and connect four clients."
    }

    $serverArgs = @(
        "-m", "arena_server",
        "--host", $BindHost,
        "--tcp-port", "$TcpPort",
        "--api-port", "$ApiPort",
        "--tick-ms", "$TickMs",
        "--turn-limit", "$TurnLimit",
        "--min-players", "$MinPlayers",
        "--max-players", "$MaxPlayers",
        "--lobby-wait-ms", "$LobbyWaitMs",
        "--mode", $Mode
    )
    $quotedServerArgs = $serverArgs | ForEach-Object {
        Quote-CommandLineArgument $_
    }
    $server = Start-Process -FilePath $Python `
        -ArgumentList $quotedServerArgs -WorkingDirectory $serverDir `
        -PassThru -WindowStyle Hidden
    Wait-ServerReady -Process $server -Url $apiUrl

    $botSpecs = @(
        @{ Name = "Aggressive"; Strategy = "aggressive" },
        @{ Name = "Balanced"; Strategy = "balanced" }
    )
    $hostLiteral = Quote-PowerShellLiteral $BindHost
    foreach ($spec in $botSpecs) {
        $nameLiteral = Quote-PowerShellLiteral $spec.Name
        $strategyLiteral = Quote-PowerShellLiteral $spec.Strategy
        $botCode = "from arena_agent.client import run_agent; from bots.heuristic import HeuristicPolicy; run_agent($hostLiteral, $TcpPort, $nameLiteral, HeuristicPolicy($strategyLiteral), requeue=True, logger=lambda *_: None)"
        $botArgs = @("-c", (Quote-CommandLineArgument $botCode))
        $bots += Start-Process -FilePath $Python `
            -ArgumentList $botArgs -WorkingDirectory $agentsDir `
            -PassThru -WindowStyle Hidden
    }

    $clientArgs = @(
        (Join-Path $clientDir "launcher.py"),
        "--host", "127.0.0.1",
        "--port", "$ClientPort",
        "--server", $apiUrl
    )
    if ($NoOpen) { $clientArgs += "--no-open" }
    $quotedClientArgs = $clientArgs | ForEach-Object {
        Quote-CommandLineArgument $_
    }
    $client = Start-Process -FilePath $Python `
        -ArgumentList $quotedClientArgs -WorkingDirectory $clientDir `
        -PassThru -WindowStyle Hidden

    Write-Host "NEON ARENA play: open http://127.0.0.1:$ClientPort/"
    Write-Host "按 Enter 停止"
    [void](Read-Host)
}
finally {
    Stop-ProcessTree $client
    for ($index = $bots.Count - 1; $index -ge 0; $index--) {
        Stop-ProcessTree $bots[$index]
    }
    Stop-ProcessTree $server
}
