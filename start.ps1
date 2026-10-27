param([switch]$Install,[switch]$Reload,[int]$ApiPort=8010,[int]$FrontendPort=5174)
$ErrorActionPreference='Stop'
$project=$PSScriptRoot
foreach($port in @($ApiPort,$FrontendPort)) {
    $listener=[System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Loopback,$port)
    try {$listener.Start()} catch {throw "Port $port is already running. Use the existing server or stop its terminal before restarting."} finally {$listener.Stop()}
}
$venvPython=Join-Path $project '.venv\Scripts\python.exe'
$pythonCommand=Get-Command python -ErrorAction SilentlyContinue
if(!(Test-Path $venvPython)) {
    if(!$pythonCommand){throw 'Install Python 3.12+ and add it to PATH.'}
    & $pythonCommand.Source -m venv (Join-Path $project '.venv')
    if($LASTEXITCODE){throw 'Could not create the project Python environment.'}
}
$pythonExe=$venvPython
& $pythonExe -c 'import sys; assert sys.version_info >= (3,12)'
if($LASTEXITCODE){throw 'Python 3.12+ is required.'}
$env:PYTHONPATH=$project
$requirementsHash=(Get-FileHash (Join-Path $project 'backend\requirements-lock.txt')).Hash
$readyFile=Join-Path $project '.dependencies-ready'
if($Install -or !(Test-Path $readyFile) -or (Get-Content $readyFile -Raw).Trim() -ne $requirementsHash) {
    & $pythonExe -m pip install -r (Join-Path $project 'backend\requirements-lock.txt')
    if($LASTEXITCODE){throw 'Backend dependency installation failed.'}
    Set-Content $readyFile $requirementsHash
}
Push-Location (Join-Path $project 'frontend')
try {
    $webHash=(Get-FileHash package-lock.json).Hash
    $webReady='node_modules/.mediassist-lock-hash'
    if($Install -or !(Test-Path $webReady) -or (Get-Content $webReady -Raw).Trim() -ne $webHash){
        $activeFrontend=Get-CimInstance Win32_Process -Filter "Name='node.exe'" -ErrorAction SilentlyContinue | Where-Object {$_.CommandLine -and $_.CommandLine.Contains((Join-Path $project 'frontend\node_modules'))}
        if($activeFrontend){throw 'Stop this project frontend before installing changed packages. Windows locks its running build tool.'}
        npm.cmd ci
        if($LASTEXITCODE){throw 'Frontend dependency installation failed.'}
        Set-Content $webReady $webHash
    }
}finally{Pop-Location}
$env:MEDIASSIST_API_TARGET="http://127.0.0.1:$ApiPort"
$env:MEDIASSIST_FRONTEND_PORT="$FrontendPort"
$apiArguments=@('-m','uvicorn','backend.main:app','--host','127.0.0.1','--port',"$ApiPort")
if($Reload){$apiArguments+=@('--reload','--reload-dir','backend','--reload-exclude','test_*.py')}
$backend=Start-Process -FilePath $pythonExe -ArgumentList $apiArguments -WorkingDirectory $project -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $project 'backend-output.log') -RedirectStandardError (Join-Path $project 'backend-errors.log')
try {
    $ready=$false
    for($attempt=0;$attempt -lt 30;$attempt++){
        if($backend.HasExited){throw 'API startup failed. Read backend-errors.log.'}
        try{$health=Invoke-RestMethod "http://127.0.0.1:$ApiPort/api/health" -TimeoutSec 2;if($health.app -eq 'mediassist'){$ready=$true;break}}catch{Start-Sleep -Milliseconds 500}
    }
    if(!$ready){throw 'API did not become ready. Read backend-errors.log.'}
    Write-Host "MediAssist: http://127.0.0.1:$FrontendPort | API: http://127.0.0.1:$ApiPort/docs"
    Write-Host 'Keep this terminal open. Press Ctrl+C to stop both services.'
    Push-Location (Join-Path $project 'frontend')
    try{npm.cmd run dev -- --port $FrontendPort}finally{Pop-Location}
}finally{
    # Stop only this launch's child process, including a Windows venv/reload wrapper.
    function Stop-ProjectChildren([int]$ParentId){
        Get-CimInstance Win32_Process -Filter "ParentProcessId=$ParentId" -ErrorAction SilentlyContinue | ForEach-Object {Stop-ProjectChildren $_.ProcessId;Stop-Process -Id $_.ProcessId -ErrorAction SilentlyContinue}
    }
    Stop-ProjectChildren $backend.Id
    Stop-Process -Id $backend.Id -ErrorAction SilentlyContinue
}
