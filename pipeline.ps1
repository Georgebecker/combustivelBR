# pipeline.ps1 - coleta e transforma (bruto -> data/processed + site/data)
# Uso:
#   .\pipeline.ps1                 baixa da fonte publica
#   .\pipeline.ps1 -Amostra        usa tests/fixtures/amostra_precos.csv (sem rede)
#   .\pipeline.ps1 -Url <endereco> baixa de um endereco especifico
#   .\pipeline.ps1 -Uf SC          estreita o recorte para um estado (padrao: todos)
#   .\pipeline.ps1 -SemNoticias    nao busca manchetes novas (mantem as publicadas)
#   .\pipeline.ps1 -Testes         roda os testes antes de publicar (recomendado)
param(
    [switch]$Amostra,
    [string]$Url,
    [string]$Uf,
    [switch]$SemNoticias,
    [switch]$Testes
)
$ErrorActionPreference = "Stop"

$raiz = $PSScriptRoot
$py = Join-Path $raiz ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) { throw "Ambiente ausente: rode .\preparar.ps1 antes." }

# o pacote vive em src/, entao sem isto o 'python -m combustivelbr' nao encontra o modulo
$env:PYTHONPATH = Join-Path $raiz "src"

if ($Testes) {
    Write-Host "Rodando os testes antes de publicar ..."
    & $py -m pytest
    if ($LASTEXITCODE -ne 0) { throw "Os testes falharam: nada foi publicado." }
}

$argumentos = @("-m", "combustivelbr", "pipeline")
if ($Url) { $argumentos += @("--url", $Url) } elseif ($Amostra) { $argumentos += "--amostra" }
if ($Uf) { $argumentos += @("--uf", $Uf) }
if ($SemNoticias) { $argumentos += "--sem-noticias" }

& $py @argumentos
if ($LASTEXITCODE -ne 0) { throw "O pipeline falhou (motivo acima)." }

Write-Host "Pronto: data\processed\dados.json e site\data\dados.json atualizados."
