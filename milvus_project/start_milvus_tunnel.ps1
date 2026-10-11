$ErrorActionPreference = "Stop"

Write-Host "Opening Milvus tunnel: 127.0.0.1:19530 -> 122.51.39.141:19530"
Write-Host "Keep this window open while using the project. Press Ctrl+C to stop."

ssh -N -L 19530:127.0.0.1:19530 ubuntu@122.51.39.141

