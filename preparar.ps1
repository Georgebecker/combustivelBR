# preparar.ps1 - cria o ambiente virtual e instala as dependencias do projeto
# Uso: powershell -ExecutionPolicy Bypass -File .\preparar.ps1
$ErrorActionPreference = "Stop"

$raiz = $PSScriptRoot
$venv = Join-Path $raiz ".venv"
$py = Join-Path $venv "Scripts\python.exe"

if (-not (Test-Path $py)) {
    Write-Host "Criando o ambiente virtual em .venv ..."
    python -m venv $venv
    if (-not (Test-Path $py)) { throw "Nao consegui criar o venv: o python esta no PATH?" }
}

Write-Host "Instalando as dependencias de requirements.txt ..."
& $py -m pip install --quiet --disable-pip-version-check --upgrade pip
& $py -m pip install --quiet --disable-pip-version-check -r (Join-Path $raiz "requirements.txt")
if ($LASTEXITCODE -ne 0) { throw "Falha ao instalar as dependencias." }

Write-Host ""
Write-Host "Ambiente pronto. Proximos passos:"
Write-Host "  .\pipeline.ps1 -Amostra    gera os dados a partir da amostra (sem rede)"
Write-Host "  .\pipeline.ps1             baixa da fonte publica"
Write-Host "  .\pipeline.ps1 -Testes     roda os testes antes de publicar"
Write-Host "  .\servir.ps1               sobe o site e a API local"
