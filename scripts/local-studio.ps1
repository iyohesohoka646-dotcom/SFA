param(
    [ValidateSet('Start', 'Stop')][string]$Action = 'Start',
    [string]$Project = '',
    [string]$WorkspaceHome = '',
    [ValidateRange(0, 65535)][int]$Port = 0,
    [switch]$NoBrowser
)

$ErrorActionPreference = 'Stop'
$env:PYTHONUTF8 = '1'
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
$StudioRoot = Split-Path -Parent $PSScriptRoot
$StudioPython = Join-Path $StudioRoot '.venv\Scripts\python.exe'
if (-not $Project) {
    $StudioProject = $null
} elseif ([System.IO.Path]::IsPathRooted($Project)) {
    $StudioProject = [System.IO.Path]::GetFullPath($Project)
} else {
    $StudioProject = [System.IO.Path]::GetFullPath((Join-Path $StudioRoot $Project))
}

try {
    if (-not (Test-Path -LiteralPath $StudioPython)) {
        if ($Action -eq 'Stop') {
            Write-Host 'No local installation is running.'
            exit 0
        }
        $StudioBootstrap = Get-Command py.exe -ErrorAction SilentlyContinue
        if ($StudioBootstrap) {
            & $StudioBootstrap.Source -3 -m venv (Join-Path $StudioRoot '.venv')
        } else {
            $StudioBootstrap = Get-Command python.exe -ErrorAction Stop
            & $StudioBootstrap.Source -m venv (Join-Path $StudioRoot '.venv')
        }
        if ($LASTEXITCODE -ne 0) { throw 'Python 3.11+ is required to create the local environment.' }
    }
    & $StudioPython -X utf8 -c "import importlib.util,sys; from pathlib import Path; s=importlib.util.find_spec('contract_driven_ai_flow'); expected=Path(sys.argv[1])/'src/contract_driven_ai_flow'; raise SystemExit(0 if s and Path(s.origin).parent.resolve()==expected.resolve() else 1)" $StudioRoot
    if ($LASTEXITCODE -ne 0) {
        Write-Host 'Installing the local Web UI in the project environment...'
        & $StudioPython -X utf8 -m pip install -e $StudioRoot
        if ($LASTEXITCODE -ne 0) { throw 'Local installation failed. The pip error above contains the cause.' }
    }
    $StudioArguments = @('-X', 'utf8', '-m', 'contract_driven_ai_flow', '--json', 'studio', '--no-open')
    if ($StudioProject) {
        $StudioArguments += @('--project', $StudioProject)
    } elseif ($WorkspaceHome) {
        $StudioArguments += @('--home', $WorkspaceHome)
    } else {
        $StudioArguments += '--workspace'
    }
    if ($Action -eq 'Start') {
        if ($Port -gt 0) { $StudioArguments += @('--port', $Port) }
    } else {
        $StudioArguments += '--stop'
    }
    $StudioRaw = & $StudioPython @StudioArguments
    if ($LASTEXITCODE -ne 0) { throw 'Studio failed; inspect the error above and the project .cdaf/studio.log.' }
    $StudioService = ($StudioRaw -join "`n") | ConvertFrom-Json
    if ($Action -eq 'Start') {
        Write-Host ('Local Web UI: ' + $StudioService.url)
        Write-Host ('Log: ' + $StudioService.log)
        Write-Host 'Closing the last browser tab stops the local service. Use cdaf serve for an explicit persistent service.'
        if (-not $NoBrowser) { Start-Process -FilePath $StudioService.url }
    } else {
        Write-Host ('Studio stopped: ' + $StudioService.stopped)
    }
} catch {
    Write-Error $_
    exit 1
}
