param(
    [ValidateSet('Instalar','Demo','DemoReal','Testar','Verificar','Broker','Monitorar','Simular','Historico')]
    [string]$Acao = 'Demo',
    [string]$Python = '',
    [string[]]$Argumentos = @()
)

$ErrorActionPreference = 'Stop'
$env:PYTHONUTF8 = '1'
$env:PYTHONDONTWRITEBYTECODE = '1'
$taskLocalVenv = Join-Path $PSScriptRoot 'work\.venv\Scripts\python.exe'
$taskWorkspaceVenv = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..\work\.venv\Scripts\python.exe'))
$taskInterpreter = ''
foreach ($taskCandidate in @($taskLocalVenv, $taskWorkspaceVenv)) {
    if (Test-Path -LiteralPath $taskCandidate) {
        $taskInterpreter = $taskCandidate
        break
    }
}

Push-Location $PSScriptRoot
try {
    if ($Acao -eq 'Instalar') {
        if (-not $taskInterpreter) {
            if (-not $Python) {
                $taskBundledPython = Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
                if (Test-Path -LiteralPath $taskBundledPython) { $Python = $taskBundledPython }
                else { $Python = 'python' }
            }
            & $Python -m venv (Join-Path $PSScriptRoot 'work\.venv')
            if ($LASTEXITCODE -ne 0) { throw 'Falha ao criar o ambiente. Use Python 3.12 ou superior.' }
            $taskInterpreter = $taskLocalVenv
        }
        & $taskInterpreter -m pip install -r requirements.txt
        if ($LASTEXITCODE -ne 0) { throw 'Falha ao instalar as dependencias.' }
        if (-not (Test-Path -LiteralPath '.env')) { Copy-Item -LiteralPath '.env.example' -Destination '.env' }
        Write-Output 'Instalacao concluida. Execute: .\Executar.cmd -Acao Demo'
    }
    else {
        if (-not $taskInterpreter) { throw 'Execute primeiro: .\Executar.cmd -Acao Instalar' }
        if ($Acao -eq 'Testar') {
            & $taskInterpreter -m pytest -q '--junitxml=resultados/testes-automatizados.xml' @Argumentos
        }
        else {
            [string[]]$taskCommand = switch ($Acao) {
                'Demo' { @('demo') }
                'DemoReal' { @('demo','--real') }
                'Verificar' { @('verificar') }
                'Broker' { @('broker') }
                'Monitorar' { @('monitorar') }
                'Simular' { @('simular') }
                'Historico' { @('historico') }
            }
            & $taskInterpreter -m monitoramento @taskCommand @Argumentos
        }
        if ($LASTEXITCODE -ne 0) { throw 'A execucao encontrou um erro; consulte a mensagem acima.' }
    }
}
finally {
    Pop-Location
}
