# servir.ps1 - sobe o site e a API local
# O site funciona sem servidor (abre direto no navegador); isto serve para ver tudo junto
# e para consultar o JSON por API.
# Uso: .\servir.ps1 [-Porta 8000] [-Recarregar]
param(
    [int]$Porta = 8000,
    [switch]$Recarregar
)
$ErrorActionPreference = "Stop"

$raiz = $PSScriptRoot
$py = Join-Path $raiz ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) { throw "Ambiente ausente: rode .\preparar.ps1 antes." }

$env:PYTHONPATH = Join-Path $raiz "src"

Write-Host "Site:      http://127.0.0.1:$Porta/"
Write-Host "Dados:     http://127.0.0.1:$Porta/dados"
Write-Host "Saude:     http://127.0.0.1:$Porta/saude"
Write-Host "Documentacao da API: http://127.0.0.1:$Porta/docs"
Write-Host ""

$argumentos = @("-m", "combustivelbr", "servir", "--porta", $Porta)
if ($Recarregar) { $argumentos += "--recarregar" }
& $py @argumentos
