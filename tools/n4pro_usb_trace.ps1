#Requires -Version 7.6
[CmdletBinding(DefaultParameterSetName = 'Run')]
param(
    [ValidateSet('OpenDeckExit', 'PhysicalReconnect')]
    [string] $Scenario = 'OpenDeckExit',
    [Parameter(ParameterSetName = 'Run')]
    [string] $OutputDirectory = $env:TEMP,
    [Parameter(Mandatory, ParameterSetName = 'Capture')]
    [string] $CaptureDirectory
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot

function Invoke-Logman([string[]] $Arguments) {
    & logman.exe @Arguments | Out-Host
    if ($LASTEXITCODE -ne 0) {
        throw "logman $($Arguments[0]) failed ($LASTEXITCODE)."
    }
}

function Save-Devices([string] $Stage) {
    # USB parent nodes from the N4 Pro entries in the pinned SDK's ProductIDs.py.
    $devices = @(Get-PnpDevice -PresentOnly | Where-Object {
        $_.InstanceId -match '^USB\\VID_5548&PID_(1008|1021|1023)\\'
    } | ForEach-Object {
        $paths = Get-PnpDeviceProperty -InstanceId $_.InstanceId -KeyName 'DEVPKEY_Device_LocationPaths'
        [pscustomobject]@{ InstanceId = $_.InstanceId; LocationPaths = $paths.Data }
    })
    ConvertTo-Json -InputObject $devices -Depth 4 |
        Set-Content -LiteralPath (Join-Path $folder "$Stage.json") -Encoding UTF8
    if ($Stage -eq 'before' -and $devices.Count -ne 1) {
        throw "Expected one connected N4 Pro USB parent, found $($devices.Count). See before.json."
    }
}

function Mark([string] $Message) {
    "$([DateTimeOffset]::UtcNow.ToString('o')) $Message" |
        Add-Content -LiteralPath (Join-Path $folder 'markers.txt') -Encoding UTF8
}

function Get-CaptureError {
    $detail = Join-Path $folder 'capture-error.txt'
    if (Test-Path -LiteralPath $detail) { return Get-Content -LiteralPath $detail -Raw }
    return 'The USB capture worker exited unexpectedly.'
}

function Wait-ForSignal([string] $Name, [int] $Seconds, $Process) {
    $path = Join-Path $folder $Name
    $watch = [Diagnostics.Stopwatch]::StartNew()
    while ($true) {
        if ($Process -and $Process.HasExited) { throw (Get-CaptureError) }
        if (Test-Path -LiteralPath $path) { return }
        if ($watch.Elapsed.TotalSeconds -ge $Seconds) { throw "Timed out waiting for $Name." }
        Start-Sleep -Milliseconds 100
    }
}

function Invoke-Capture {
    $session = Split-Path -Leaf $folder
    Save-Devices before
    Mark $Scenario
    Invoke-Logman @('create', 'trace', '-n', $session, '-o', (Join-Path $folder 'usb.etl'))
    try {
        # USBHUB3 covers modern controllers. USBHUB covers the legacy USB stack.
        $enabled = @()
        foreach ($provider in 'Microsoft-Windows-USB-USBHUB3', 'Microsoft-Windows-USB-USBHUB') {
            & logman.exe query providers $provider *> $null
            if ($LASTEXITCODE -ne 0) { continue }
            $arguments = @('update', 'trace', '-n', $session, '-p', $provider)
            if ($provider -eq 'Microsoft-Windows-USB-USBHUB3') { $arguments += 'Default' }
            Invoke-Logman $arguments
            $enabled += $provider
        }
        if (!$enabled) { throw 'No supported USB hub ETW provider is available.' }
        Mark "providers: $($enabled -join ', ')"
        Invoke-Logman @('start', '-n', $session)
        try {
            Mark 'capture started'
            if ($Scenario -eq 'PhysicalReconnect') {
                Write-Host 'Unplug the N4 Pro, then reconnect it to the same port.'
                $null = Read-Host 'After the device settles, press Enter here to stop recording'
            } else {
                Set-Content -LiteralPath (Join-Path $folder 'capture.ready') -Value ''
                Wait-ForSignal 'capture.stop' 120
            }
            Mark 'observation ended'
        } finally {
            Invoke-Logman @('stop', '-n', $session)
        }
    } finally {
        Invoke-Logman @('delete', '-n', $session)
    }

    Save-Devices after
    $etl = @(Get-ChildItem -LiteralPath $folder -Filter '*.etl' -File)
    if ($etl.Count -ne 1) { throw "Expected one ETL in $folder, found $($etl.Count)." }
    Push-Location -LiteralPath $folder
    try {
        & tracerpt.exe $etl[0].FullName -of CSV -o events.csv -summary summary.txt
        if ($LASTEXITCODE -ne 0) { throw "tracerpt failed ($LASTEXITCODE). The ETL is in $folder." }
    } finally {
        Pop-Location
    }
}

function Invoke-ExitExperiment {
    $python = Join-Path $root '.venv\Scripts\python.exe'
    if (!(Test-Path -LiteralPath $python -PathType Leaf)) {
        throw 'Python environment not found. Run the README setup with the device extra first.'
    }
    $shell = Join-Path $PSHOME 'pwsh.exe'
    $arguments = @('-NoProfile', '-File', ('"{0}"' -f $PSCommandPath), '-CaptureDirectory', ('"{0}"' -f $folder))
    # Keep the sample in the caller's session; only Logman and PnP capture need elevation.
    $capture = Start-Process -FilePath $shell -ArgumentList $arguments -Verb RunAs -PassThru
    $stdout = Join-Path $folder 'opendeck-stdout.txt'
    $stderr = Join-Path $folder 'opendeck-stderr.txt'
    try {
        Wait-ForSignal 'capture.ready' 30 $capture
        $sdk = Join-Path $root 'vendor\streamdock-sdk'
        if ((Test-Path -LiteralPath (Join-Path $sdk '.git')) -and (Get-Command git -ErrorAction SilentlyContinue)) {
            $revision = & git -C $sdk rev-parse HEAD
            if ($LASTEXITCODE -eq 0) { Mark "SDK revision: $revision" }
        }
        Mark 'sample starting'
        Write-Host 'Running the live sample. Leave the N4 Pro connected.'
        $sample = Start-Process -FilePath $python -WorkingDirectory $root -NoNewWindow -PassThru `
            -ArgumentList @('examples/async_actions.py', '--live', '--live-seconds', '5') `
            -RedirectStandardOutput $stdout -RedirectStandardError $stderr
        if (!$sample.WaitForExit(60000)) {
            Mark 'sample timed out; exit experiment invalid'
            throw "Sample did not finish (PID $($sample.Id)); not a normal shutdown. See $stderr."
        }
        Mark "sample exited (code $($sample.ExitCode))"
        if ($sample.ExitCode -ne 0) { throw "Live sample failed with code $($sample.ExitCode). See $stderr." }
        Start-Sleep -Seconds 10
    } finally {
        Set-Content -LiteralPath (Join-Path $folder 'capture.stop') -Value ''
        if (!$capture.WaitForExit(30000)) { throw "The USB capture worker did not finish. See $folder." }
        foreach ($signal in 'capture.ready', 'capture.stop') {
            Remove-Item -LiteralPath (Join-Path $folder $signal) -ErrorAction SilentlyContinue
        }
        if ($capture.ExitCode -ne 0) { throw (Get-CaptureError) }
    }
}

if ($PSCmdlet.ParameterSetName -eq 'Capture') {
    $folder = $CaptureDirectory
    try {
        Invoke-Capture
    } catch {
        Set-Content -LiteralPath (Join-Path $folder 'capture-error.txt') -Value $_.ToString() -Encoding UTF8
        throw
    }
    return
}

$session = 'OpenDeck-USB-' + [guid]::NewGuid().ToString('N')
$folder = (New-Item -ItemType Directory -Path (Join-Path $OutputDirectory $session)).FullName
Write-Host "Capture directory: $folder"
if ($Scenario -eq 'PhysicalReconnect') { Invoke-Capture } else { Invoke-ExitExperiment }
Write-Host 'Review events.csv and summary.txt alongside markers.txt and the device location in before.json.'
