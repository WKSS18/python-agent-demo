param(
    [Parameter(Mandatory = $true)]
    [string]$Destination
)

$ErrorActionPreference = "Stop"
$target = [System.IO.Path]::GetFullPath($Destination)
New-Item -ItemType Directory -Force -Path $target | Out-Null
$stamp = Get-Date -Format "yyyyMMdd-HHmmss"

function Get-EnvValue([string]$Name) {
    $line = Get-Content .env.production | Where-Object { $_ -match "^$([regex]::Escape($Name))=" } | Select-Object -Last 1
    if (-not $line) { throw "Missing $Name in .env.production" }
    return $line.Substring($line.IndexOf('=') + 1).Trim()
}

docker compose --env-file .env.production exec -T mysql `
    sh -c 'mysqldump --single-transaction --routines --triggers -u root -p"$MYSQL_ROOT_PASSWORD" "$MYSQL_DATABASE"' |
    Set-Content -Encoding utf8 -Path (Join-Path $target "mysql-$stamp.sql")

$qdrantKey = Get-EnvValue "QDRANT_API_KEY"
$collection = Get-EnvValue "QDRANT_COLLECTION"
$snapshot = Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:6333/collections/$collection/snapshots" `
    -Headers @{"api-key" = $qdrantKey}
$snapshotName = $snapshot.result.name
Invoke-WebRequest -Uri "http://127.0.0.1:6333/collections/$collection/snapshots/$snapshotName" `
    -Headers @{"api-key" = $qdrantKey} `
    -OutFile (Join-Path $target "qdrant-$stamp.snapshot")

Write-Output "Backup completed: $target"
