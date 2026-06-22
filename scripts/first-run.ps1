<#
.SYNOPSIS
Initialise Urban Data Explorer apres un clone Git.

.DESCRIPTION
Prepare le fichier .env, demarre MySQL et MongoDB avec Docker Compose,
construit l'image du pipeline, telecharge les sources ouvertes puis lance
le traitement Bronze/Silver/Gold et la validation.

.PARAMETER Sources
Liste optionnelle de sources a telecharger, par exemple dvf_2025_paris
ou bruitparif_sig_2024. Si vide, toutes les sources configurees sont prises.

.PARAMETER ForceDownload
Retelecharge les sources meme si les fichiers existent deja localement.

.PARAMETER SkipNoise
Ignore le calcul Bruitparif et utilise des valeurs environnementales neutres.

.PARAMETER SkipValidate
Ignore la validation finale des sorties Gold.

.PARAMETER StartApi
Demarre aussi l'API apres le traitement des donnees.

.EXAMPLE
.\scripts\first-run.ps1

.EXAMPLE
.\scripts\first-run.ps1 -StartApi

.EXAMPLE
.\scripts\first-run.ps1 -Sources dvf_2025_paris bruitparif_sig_2024
#>

[CmdletBinding()]
param(
    [string[]]$Sources = @(),
    [switch]$ForceDownload,
    [switch]$SkipNoise,
    [switch]$SkipValidate,
    [switch]$StartApi
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Resolve-Path (Join-Path $ScriptDir "..")
Set-Location $RepoRoot

function Write-Step {
    param([string]$Message)

    Write-Host ""
    Write-Host "== $Message ==" -ForegroundColor Cyan
}

function Invoke-Compose {
    param(
        [Parameter(Mandatory = $true, ValueFromRemainingArguments = $true)]
        [string[]]$ComposeArgs
    )

    & docker compose @ComposeArgs
    if ($LASTEXITCODE -ne 0) {
        throw "docker compose $($ComposeArgs -join ' ') a echoue avec le code $LASTEXITCODE."
    }
}

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    throw "Docker est requis pour ce script. Installez Docker Desktop puis relancez la commande."
}

& docker info *> $null
if ($LASTEXITCODE -ne 0) {
    throw "Docker ne semble pas demarre. Lancez Docker Desktop puis relancez ce script."
}

if (-not (Test-Path ".env") -and (Test-Path ".env.example")) {
    Write-Step "Creation du fichier .env"
    Copy-Item ".env.example" ".env"
}

Write-Step "Preparation des dossiers de donnees"
New-Item -ItemType Directory -Force -Path `
    "data/bronze/raw", `
    "data/bronze/reference", `
    "data/silver", `
    "data/gold" | Out-Null

Write-Step "Demarrage de MySQL et MongoDB"
try {
    Invoke-Compose up -d --wait mysql mongo
}
catch {
    Write-Warning "L'option docker compose --wait est indisponible ou a echoue. Demarrage standard des bases, puis courte attente."
    Invoke-Compose up -d mysql mongo
    Start-Sleep -Seconds 20
}

Write-Step "Construction de l'image pipeline"
Invoke-Compose --profile tools build pipeline

$PipelineArgs = @("run")
if ($ForceDownload) {
    $PipelineArgs += "--force-download"
}
if ($SkipNoise) {
    $PipelineArgs += "--skip-noise"
}
if ($SkipValidate) {
    $PipelineArgs += "--skip-validate"
}
if ($Sources.Count -gt 0) {
    $PipelineArgs += $Sources
}

Write-Step "Telechargement et traitement des donnees"
$RunArgs = @("--profile", "tools", "run", "--rm", "pipeline", "python", "pipeline/run_imports.py") + $PipelineArgs
Invoke-Compose @RunArgs

if ($StartApi) {
    Write-Step "Demarrage de l'API"
    Invoke-Compose up --build -d api
    Write-Host "API disponible sur http://localhost:8000"
    Write-Host "Frontend servi par l'API sur http://localhost:8000/"
}

Write-Step "Initialisation terminee"
Write-Host "Les datasets Bronze/Silver/Gold sont prets et les sorties ont ete chargees dans MySQL/MongoDB."
