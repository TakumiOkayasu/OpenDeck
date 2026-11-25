#Requires -Version 5.1
#Requires -RunAsAdministrator
[CmdletBinding()]
param(
    [ValidateSet('OpenDeckExit', 'PhysicalReconnect')]
    [string] $Scenario = 'OpenDeckExit',
    [string] $OutputDirectory = $env:TEMP
)

$ErrorActionPreference = 'Stop'
$session = 'OpenDeck-USB-' + [guid]::NewGuid().ToString('N')
$folder = Join-Path $OutputDirectory $session
$null = New-Item -ItemType Directory -Path $folder
Write-Host "Capture directory: $folder"

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
        if ($Scenario -eq 'OpenDeckExit') {
            Write-Host 'In the OpenDeck console, press Ctrl+C. Leave USB connected and do not restart OpenDeck.'
        } else {
            Write-Host 'Unplug the N4 Pro, then reconnect it to the same port.'
        }
        $null = Read-Host 'After the device settles, press Enter here to stop recording'
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
Write-Host "Review events.csv and summary.txt alongside markers.txt and the device location in before.json."
