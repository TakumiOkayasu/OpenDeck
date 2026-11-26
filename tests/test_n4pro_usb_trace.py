import shutil
import subprocess
import sys
from pathlib import Path

import pytest

TOOL = Path(__file__).resolve().parents[1] / "tools" / "n4pro_usb_trace.ps1"
pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows USB ETW")

CONTROLLER_PROBE = r"""
param($Tool, $Output, [int]$ChildCode)
$ErrorActionPreference = 'Stop'
$global:TraceProbeSteps = Join-Path $Output 'steps.txt'
function Read-Host { throw 'The automatic capture must not ask for input' }
function Start-Sleep {
    param([int] $Seconds, [int] $Milliseconds)
    if ($Seconds -gt 0) { Add-Content $global:TraceProbeSteps 'observe' }
}
function Start-Process {
    param($FilePath, [string[]] $ArgumentList, $Verb, $WorkingDirectory,
          $RedirectStandardOutput, $RedirectStandardError, [switch] $PassThru,
          [switch] $NoNewWindow)
    if (!$PassThru) { throw 'The capture must monitor the child process' }
    if ($Verb -eq 'RunAs') {
        if ($FilePath -ne [Environment]::ProcessPath) {
            throw 'The worker must use the same PowerShell executable as the controller'
        }
        if ($ArgumentList -notcontains '-CaptureDirectory') { throw 'Expected worker' }
        if ($ArgumentList -notcontains ('"{0}"' -f [IO.Path]::GetFullPath($Tool))) {
            throw 'Unquoted script path'
        }
        $global:TraceProbeFolder = $ArgumentList[-1].Trim('"')
        Add-Content $global:TraceProbeSteps 'trace start'
        Set-Content (Join-Path $global:TraceProbeFolder 'capture.ready') ''
        $trace = [pscustomobject] @{ ExitCode = 0; HasExited = $false }
        $trace | Add-Member ScriptMethod WaitForExit {
            param($Milliseconds)
            $stop = Join-Path $global:TraceProbeFolder 'capture.stop'
            if (!$Milliseconds -or !(Test-Path -LiteralPath $stop)) {
                throw 'The capture must be told to stop and then joined'
            }
            Add-Content $global:TraceProbeSteps 'trace stop'
            return $true
        }
        return $trace
    }
    if ($Verb -or $ArgumentList -notcontains '--live-seconds' -or
        !(Test-Path (Join-Path $global:TraceProbeFolder 'capture.ready'))) {
        throw 'Expected the ordinary live process after the ETW start'
    }
    if ($FilePath -notlike '*\.venv\Scripts\python.exe') { throw 'Wrong Python' }
    Add-Content $global:TraceProbeSteps 'sample start'
    Set-Content -LiteralPath $RedirectStandardOutput -Value ''
    Set-Content -LiteralPath $RedirectStandardError -Value 'Sample log'
    $sample = [pscustomobject] @{ ExitCode = $ChildCode; Id = 42 }
    $sample | Add-Member ScriptMethod WaitForExit {
        param($Milliseconds)
        if (!$Milliseconds) { throw 'Unbounded sample wait' }
        if ($this.ExitCode -eq 99) {
            Add-Content $global:TraceProbeSteps 'sample timeout'
            return $false
        }
        Add-Content $global:TraceProbeSteps 'sample exit'
        return $true
    }
    return $sample
}
& $Tool -OutputDirectory $Output
"""


@pytest.fixture(scope="module")
def pwsh():
    executable = shutil.which("pwsh.exe")
    if executable is None:
        pytest.skip("PowerShell 7.6 or later is required for USB trace tests")
    version = subprocess.check_output(
        [
            executable,
            "-NoProfile",
            "-Command",
            "$PSVersionTable.PSVersion -ge [version]'7.6'",
        ],
        timeout=10,
    )
    if version.strip() != b"True":
        pytest.skip("PowerShell 7.6 or later is required for USB trace tests")
    return executable


@pytest.mark.parametrize("child_code", [0, 3, 99])
def test_controller_captures_around_the_sample_and_always_stops(
    tmp_path, child_code, pwsh
):
    repo = tmp_path / "test repo"
    tools = repo / "tools"
    tools.mkdir(parents=True)
    tool = tools / TOOL.name
    shutil.copyfile(TOOL, tool)
    python = repo / ".venv" / "Scripts" / "python.exe"
    python.parent.mkdir(parents=True)
    python.touch()
    out = tmp_path / "trace output"
    out.mkdir()
    probe = tmp_path / "probe.ps1"
    probe.write_text(CONTROLLER_PROBE, encoding="utf-8")

    result = subprocess.run(
        [pwsh, "-NoProfile", "-File", probe, tool, out, str(child_code)],
        capture_output=True,
        timeout=15,
    )

    assert (result.returncode == 0) == (child_code == 0), result.stderr
    steps = ["trace start", "sample start"]
    if child_code == 99:
        steps.append("sample timeout")
        assert b"PID 42" in result.stderr
        end_marker = "sample timed out; exit experiment invalid"
    else:
        steps.append("sample exit")
        end_marker = f"sample exited (code {child_code})"
        if child_code == 0:
            steps.append("observe")
        else:
            assert b"code 3" in result.stderr
    assert (out / "steps.txt").read_text().splitlines() == [*steps, "trace stop"]
    (folder,) = out.glob("OpenDeck-USB-*")
    markers = (folder / "markers.txt").read_text(encoding="utf-8-sig")
    assert end_marker in markers
    assert not (folder / "capture.ready").exists()
    assert not (folder / "capture.stop").exists()


CAPTURE_PROBE = r"""
param($Tool, $Output, [int]$Manual)
$ErrorActionPreference = 'Stop'
$global:CaptureProbeSteps = Join-Path $Output 'steps.txt'
function Get-PnpDevice {
    param([switch]$PresentOnly)
    [pscustomobject]@{ InstanceId = 'USB\VID_5548&PID_1021\fake' }
}
function Get-PnpDeviceProperty {
    param($InstanceId, $KeyName)
    [pscustomobject]@{ Data = @('USBROOT(0)#USB(1)') }
}
function Read-Host {
    if (!$Manual) { throw 'The ETW worker must not prompt' }
    Add-Content $global:CaptureProbeSteps 'physical reconnect'
}
function logman.exe {
    $global:LASTEXITCODE = 0
    if ($args[0] -eq 'query' -or $args[0] -eq 'update') { return }
    Add-Content $global:CaptureProbeSteps $args[0]
    if ($args[0] -eq 'create') {
        $etl = $args[-1]
        if (!(Test-Path (Join-Path (Split-Path $etl) 'before.json'))) {
            throw 'Missing PnP baseline'
        }
        Set-Content -LiteralPath $etl -Value 'mock ETL'
    }
}
function tracerpt.exe {
    $global:LASTEXITCODE = 0
    Add-Content $global:CaptureProbeSteps 'convert'
    Set-Content -LiteralPath $args[4] -Value 'mock CSV'
    Set-Content -LiteralPath $args[6] -Value 'mock summary'
}
if ($Manual) {
    & $Tool -Scenario PhysicalReconnect -OutputDirectory $Output
} else {
    Set-Content (Join-Path $Output 'capture.stop') ''
    & $Tool -CaptureDirectory $Output
}
"""


@pytest.mark.parametrize("manual", [0, 1])
def test_capture_worker_keeps_the_physical_control_and_converts_etl(
    tmp_path, manual, pwsh
):
    probe = tmp_path / "probe.ps1"
    probe.write_text(CAPTURE_PROBE, encoding="utf-8")

    result = subprocess.run(
        [pwsh, "-NoProfile", "-File", probe, TOOL, tmp_path, str(manual)],
        capture_output=True,
        timeout=15,
    )

    assert result.returncode == 0, result.stderr
    steps = ["create", "start"]
    if manual:
        (folder,) = tmp_path.glob("OpenDeck-USB-*")
        steps.append("physical reconnect")
    else:
        folder = tmp_path
        assert (folder / "capture.ready").exists()
    assert (tmp_path / "steps.txt").read_text().splitlines() == [
        *steps,
        "stop",
        "delete",
        "convert",
    ]
    assert (folder / "before.json").read_bytes() == (folder / "after.json").read_bytes()
    assert all((folder / name).exists() for name in ("events.csv", "summary.txt"))
