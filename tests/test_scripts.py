"""PowerShell 5.1 orchestration contract tests using mocked child processes."""

from __future__ import annotations

import json
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = ROOT / "scripts"
POWERSHELL = shutil.which("powershell") or shutil.which("pwsh")


def ps_literal(value):
    return "'" + str(value).replace("'", "''") + "'"


def powershell_json(source, timeout=30):
    """Run UTF-16 PowerShell source and return its marked JSON result."""
    encoded = source.encode("utf-16-le")
    import base64
    command = base64.b64encode(encoded).decode("ascii")
    proc = subprocess.run(
        [POWERSHELL, "-NoLogo", "-NoProfile", "-NonInteractive",
         "-ExecutionPolicy", "Bypass", "-EncodedCommand", command],
        cwd=str(ROOT), capture_output=True, text=True, timeout=timeout,
        encoding="utf-8", errors="replace",
    )
    if proc.returncode != 0:
        raise AssertionError(
            f"PowerShell exited {proc.returncode}\nstdout:\n{proc.stdout}"
            f"\nstderr:\n{proc.stderr}",
        )
    for line in proc.stdout.splitlines():
        if line.startswith("__RESULT__"):
            return json.loads(line[len("__RESULT__"):])
    raise AssertionError(f"PowerShell returned no result marker:\n{proc.stdout}")


MOCK_PROCESSES = r"""
$ErrorActionPreference = 'Stop'
$global:Processes = New-Object System.Collections.ArrayList
$global:TaskKills = New-Object System.Collections.ArrayList
$global:NextProcessId = 4100
function global:Start-Process {
    param(
        [string]$FilePath,
        [object[]]$ArgumentList,
        [string]$WorkingDirectory,
        [switch]$PassThru,
        [string]$WindowStyle
    )
    $global:NextProcessId += 1
    $global:Processes.Add([pscustomobject]@{
        FilePath = $FilePath
        ArgumentList = @($ArgumentList)
        WorkingDirectory = $WorkingDirectory
        WindowStyle = $WindowStyle
        Id = $global:NextProcessId
    }) | Out-Null
    if (-not $PassThru) { return }
    $process = New-Object psobject
    $process | Add-Member NoteProperty Id $global:NextProcessId
    $process | Add-Member NoteProperty HasExited $false
    $process | Add-Member ScriptMethod Refresh {}
    $process | Add-Member ScriptMethod WaitForExit {
        param($Milliseconds)
        $this.HasExited = $true
        return $true
    }
    return $process
}
function global:Invoke-RestMethod {
    param([string]$Uri, [int]$TimeoutSec)
    return [pscustomobject]@{ ok = $true }
}
function global:Start-Sleep { param([int]$Milliseconds) }
function global:Read-Host { param([string]$Prompt) return '' }
function global:Get-CimInstance { param([string]$ClassName) }
function global:Get-Process { param([int]$Id) }
function global:taskkill {
    $global:TaskKills.Add(@($args)) | Out-Null
    $target = $global:Processes | Where-Object { $_.Id -eq [int]$args[1] }
    if ($null -ne $target) { $target.HasExited = $true }
    $global:LASTEXITCODE = 0
}
function global:Stop-Process { param([int]$Id, [switch]$Force) }
"""


@unittest.skipUnless(POWERSHELL, "Windows PowerShell is not available")
class PowerShellScriptTests(unittest.TestCase):
    max_message_length = 8192

    def script_path(self, name):
        path = SCRIPTS_DIR / name
        self.assertTrue(path.is_file(), f"missing orchestration script: {path}")
        return path

    @staticmethod
    def arguments(process):
        return [str(arg).strip('"') for arg in process["ArgumentList"]]

    def test_scripts_parse_and_use_script_root_with_finally(self):
        for name in ("start_server.ps1", "demo.ps1", "play.ps1"):
            path = self.script_path(name)
            source = path.read_text(encoding="utf-8-sig")
            self.assertIn("$PSScriptRoot", source, name)
            self.assertTrue(
                path.read_bytes().startswith(b"\xef\xbb\xbf"),
                f"PowerShell 5.1 requires a UTF-8 BOM for non-ASCII text: {name}",
            )
            self.assertNotIn("??", source, name)
            self.assertNotIn("?.", source, name)
            self.assertNotIn("ForEach-Object -Parallel", source, name)
            parser_source = f"""
$tokens = $null
$errors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile(
    {ps_literal(path)}, [ref]$tokens, [ref]$errors)
$finallyCount = @($ast.FindAll({{
    param($node)
    $node -is [System.Management.Automation.Language.TryStatementAst] -and
        $null -ne $node.Finally
}}, $true)).Count
'__RESULT__' + ([pscustomobject]@{{
    errors = @($errors | ForEach-Object {{ $_.Message }})
    finallyCount = $finallyCount
}} | ConvertTo-Json -Compress -Depth 4)
"""
            result = powershell_json(parser_source)
            self.assertEqual(result["errors"], [], name)
            self.assertGreaterEqual(result["finallyCount"], 1, name)

    def test_start_server_forwards_rotation_mode_and_restores_location(self):
        path = self.script_path("start_server.ps1")
        source = f"""
$ErrorActionPreference = 'Stop'
$global:PythonCalls = New-Object System.Collections.ArrayList
function global:python {{
    $global:PythonCalls.Add(@($args)) | Out-Null
    $global:LASTEXITCODE = 0
}}
$before = (Get-Location).Path
. {ps_literal(path)} -BindHost '127.0.0.1' -TcpPort 17101 -ApiPort 18101 `
    -TickMs 900 -TurnLimit 7 -Mode 'king' -NoLogs -Verbose
$after = (Get-Location).Path
'__RESULT__' + ([pscustomobject]@{{
    before = $before
    after = $after
    calls = @($global:PythonCalls)
}} | ConvertTo-Json -Compress -Depth 6)
"""
        result = powershell_json(source)
        self.assertEqual(result["before"], result["after"])
        self.assertEqual(len(result["calls"]), 1)
        args = [str(arg) for arg in result["calls"][0]]
        self.assertEqual(args[:2], ["-m", "arena_server"])
        expected = {
            "--host": "127.0.0.1",
            "--tcp-port": "17101",
            "--api-port": "18101",
            "--tick-ms": "900",
            "--turn-limit": "7",
            "--mode": "king",
        }
        for flag, value in expected.items():
            self.assertIn(flag, args)
            self.assertEqual(args[args.index(flag) + 1], value)
        self.assertIn("--no-logs", args)
        self.assertIn("--verbose", args)

    def run_demo(self, extra_arguments=""):
        path = self.script_path("demo.ps1")
        source = MOCK_PROCESSES + f"""
$before = (Get-Location).Path
. {ps_literal(path)} -TcpPort 17201 -ApiPort 18201 {extra_arguments}
$after = (Get-Location).Path
'__RESULT__' + ([pscustomobject]@{{
    before = $before
    after = $after
    processes = @($global:Processes)
    kills = @($global:TaskKills)
}} | ConvertTo-Json -Compress -Depth 8)
"""
        return powershell_json(source)

    def test_demo_defaults_to_rotation_with_three_bots_and_spectator(self):
        result = self.run_demo()
        self.assertEqual(result["before"], result["after"])
        processes = result["processes"]
        servers = [p for p in processes
                   if p["WorkingDirectory"].replace("\\", "/").endswith("/server")]
        self.assertEqual(len(servers), 1)
        server_args = self.arguments(servers[0])
        self.assertEqual(server_args[server_args.index("--mode") + 1], "rotation")
        self.assertEqual(server_args[server_args.index("--min-players") + 1], "2")
        self.assertEqual(server_args[server_args.index("--max-players") + 1], "4")
        self.assertIn("127.0.0.1", server_args)

        bots = [p for p in processes
                if p["WorkingDirectory"].replace("\\", "/").endswith("/agents")
                and "tools.spectator" not in " ".join(self.arguments(p))]
        self.assertEqual(len(bots), 3)
        bot_commands = [" ".join(self.arguments(p)) for p in bots]
        for strategy in ("aggressive", "collector", "balanced"):
            self.assertTrue(
                any(strategy in command for command in bot_commands), strategy,
            )
        self.assertTrue(all("requeue=True" in command for command in bot_commands))

        spectators = [p for p in processes
                      if "tools.spectator" in " ".join(self.arguments(p))]
        self.assertEqual(len(spectators), 1)
        self.assertEqual(Path(spectators[0]["FilePath"]).name.lower(),
                         "powershell.exe")
        self.assertEqual(len(result["kills"]), len(processes))
        self.assertEqual(int(result["kills"][-1][1]), servers[0]["Id"])

    def test_demo_supports_no_spectator_open_client_and_explicit_mode(self):
        result = self.run_demo("-NoSpectator -OpenClient -Mode king")
        commands = [" ".join(self.arguments(p)) for p in result["processes"]]
        self.assertFalse(any("tools.spectator" in command for command in commands))
        client = [p for p in result["processes"]
                  if "launcher.py" in " ".join(self.arguments(p))]
        self.assertEqual(len(client), 1)
        server = next(p for p in result["processes"]
                      if p["WorkingDirectory"].replace("\\", "/").endswith("/server"))
        server_args = self.arguments(server)
        self.assertEqual(server_args[server_args.index("--mode") + 1], "king")
        self.assertEqual(len(result["kills"]), len(result["processes"]))

    def test_play_defaults_to_rotation_two_requeue_bots_and_launcher(self):
        path = self.script_path("play.ps1")
        source = MOCK_PROCESSES + f"""
$before = (Get-Location).Path
. {ps_literal(path)} -TcpPort 17301 -ApiPort 18301 -ClientPort 19301
$after = (Get-Location).Path
'__RESULT__' + ([pscustomobject]@{{
    before = $before
    after = $after
    processes = @($global:Processes)
    kills = @($global:TaskKills)
}} | ConvertTo-Json -Compress -Depth 8)
"""
        result = powershell_json(source)
        self.assertEqual(result["before"], result["after"])
        processes = result["processes"]
        server = next(p for p in processes
                      if p["WorkingDirectory"].replace("\\", "/").endswith("/server"))
        server_args = self.arguments(server)
        self.assertEqual(server_args[server_args.index("--mode") + 1], "rotation")
        self.assertEqual(server_args[server_args.index("--min-players") + 1], "3")
        self.assertEqual(server_args[server_args.index("--max-players") + 1], "4")

        bots = [p for p in processes
                if "HeuristicPolicy" in " ".join(self.arguments(p))]
        self.assertEqual(len(bots), 2)
        self.assertTrue(all(
            "requeue=True" in " ".join(self.arguments(p)) for p in bots
        ))
        launcher = [p for p in processes
                    if "launcher.py" in " ".join(self.arguments(p))]
        self.assertEqual(len(launcher), 1)
        launcher_args = self.arguments(launcher[0])
        self.assertNotIn("--no-open", launcher_args)
        self.assertEqual(launcher_args[launcher_args.index("--port") + 1], "19301")
        self.assertEqual(len(result["kills"]), len(processes))
        self.assertEqual(int(result["kills"][-1][1]), server["Id"])

    def test_team_mode_fails_fast_without_four_guaranteed_participants(self):
        for name in ("demo.ps1", "play.ps1"):
            path = self.script_path(name)
            source = MOCK_PROCESSES + f"""
$result = [ordered]@{{
    error = ''
    processes = @($global:Processes)
    kills = @($global:TaskKills)
}}
try {{
    . {ps_literal(path)} -Mode team
}}
catch {{
    $result.error = $_.Exception.Message
}}
'__RESULT__' + ($result | ConvertTo-Json -Compress -Depth 6)
"""
            result = powershell_json(source)
            self.assertIn("four guaranteed participants", result["error"], name)
            self.assertIn("Team mode", result["error"], name)
            self.assertEqual(result["processes"], [], name)
            self.assertEqual(result["kills"], [], name)

    def test_cleanup_handles_exited_root_descendants_and_wait_timeout(self):
        for name in ("demo.ps1", "play.ps1"):
            path = self.script_path(name)
            source = f"""
$ErrorActionPreference = 'Stop'
$tokens = $null
$errors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile(
    {ps_literal(path)}, [ref]$tokens, [ref]$errors)
$functions = @($ast.FindAll({{
    param($node)
    $node -is [System.Management.Automation.Language.FunctionDefinitionAst]
}}, $true))
foreach ($function in $functions) {{
    Invoke-Expression $function.Extent.Text
}}
$global:ProcessObjects = @{{}}
$global:WaitCalls = New-Object System.Collections.ArrayList
$global:ForceKills = New-Object System.Collections.ArrayList
$global:TaskKills = New-Object System.Collections.ArrayList
foreach ($processId in @(4100, 4200, 4300)) {{
    $process = New-Object psobject
    $process | Add-Member NoteProperty Id $processId
    $process | Add-Member NoteProperty HasExited ($processId -eq 4100)
    $process | Add-Member NoteProperty WaitAttempts 0
    $process | Add-Member ScriptMethod Refresh {{}}
    $process | Add-Member ScriptMethod WaitForExit {{
        param($Milliseconds)
        $global:WaitCalls.Add([pscustomobject]@{{
            Id = $this.Id
            Milliseconds = $Milliseconds
        }}) | Out-Null
        $this.WaitAttempts += 1
        if ($this.WaitAttempts -eq 1) {{ return $false }}
        $this.HasExited = $true
        return $true
    }}
    $global:ProcessObjects[$processId] = $process
}}
function global:Get-CimInstance {{
    param([string]$ClassName)
    return @(
        [pscustomobject]@{{ ProcessId = 4100; ParentProcessId = 0 }},
        [pscustomobject]@{{ ProcessId = 4200; ParentProcessId = 4100 }},
        [pscustomobject]@{{ ProcessId = 4300; ParentProcessId = 4200 }}
    )
}}
function global:Get-Process {{
    param([int]$Id)
    return $global:ProcessObjects[$Id]
}}
function global:taskkill {{
    $global:TaskKills.Add(@($args)) | Out-Null
    $global:LASTEXITCODE = 128
}}
function global:Stop-Process {{
    param([int]$Id, [switch]$Force)
    $global:ForceKills.Add($Id) | Out-Null
}}
Stop-ProcessTree -Process $global:ProcessObjects[4100]
'__RESULT__' + ([pscustomobject]@{{
    forceKills = @($global:ForceKills)
    waitCalls = @($global:WaitCalls)
    taskKills = @($global:TaskKills)
    childExited = $global:ProcessObjects[4200].HasExited
    grandchildExited = $global:ProcessObjects[4300].HasExited
}} | ConvertTo-Json -Compress -Depth 6)
"""
            result = powershell_json(source)
            self.assertEqual(len(result["taskKills"]), 1, name)
            self.assertIn(4200, result["forceKills"], name)
            self.assertIn(4300, result["forceKills"], name)
            self.assertTrue(result["childExited"], name)
            self.assertTrue(result["grandchildExited"], name)
            waits_by_id = {}
            for call in result["waitCalls"]:
                waits_by_id.setdefault(call["Id"], []).append(
                    call["Milliseconds"],
                )
            self.assertEqual(waits_by_id.get(4200), [5000, 5000], name)
            self.assertEqual(waits_by_id.get(4300), [5000, 5000], name)


if __name__ == "__main__":
    unittest.main()
