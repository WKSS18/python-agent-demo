$ErrorActionPreference = "Stop"

$python = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
$tunnel = $null

if (-not (Test-Path $python)) {
    throw "Project virtual environment not found: $python"
}

function Test-LocalPort {
    param([int]$Port)

    $client = [System.Net.Sockets.TcpClient]::new()
    try {
        $task = $client.ConnectAsync("127.0.0.1", $Port)
        return $task.Wait(500) -and $client.Connected
    }
    catch {
        return $false
    }
    finally {
        $client.Dispose()
    }
}

try {
    if (-not (Test-LocalPort -Port 19530)) {
        Write-Host "Starting secure Milvus connection..."
        $tunnel = Start-Process -FilePath "ssh.exe" `
            -ArgumentList @(
                "-o", "ExitOnForwardFailure=yes",
                "-N",
                "-L", "19530:127.0.0.1:19530",
                "ubuntu@122.51.39.141"
            ) `
            -WindowStyle Hidden `
            -PassThru

        Start-Sleep -Seconds 2

        if ($tunnel.HasExited -or -not (Test-LocalPort -Port 19530)) {
            throw "Could not establish the SSH tunnel to Milvus."
        }
    }

    & $python (Join-Path $PSScriptRoot "main.py")
    if ($LASTEXITCODE -ne 0) {
        exit $LASTEXITCODE
    }
}
finally {
    if ($null -ne $tunnel -and -not $tunnel.HasExited) {
        Stop-Process -Id $tunnel.Id
    }
}
