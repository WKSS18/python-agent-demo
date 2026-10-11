# Milvus Project

Minimal Python project connected to the local Milvus Standalone instance.

## Run

Open PowerShell in this directory and run:

```powershell
.\run.ps1
```

The script automatically opens a secure SSH tunnel, runs the program with the
project virtual environment, and closes the tunnel when the program exits.

For development servers or other long-running workflows, you can still keep a
manual tunnel open in a separate terminal:

```powershell
.\start_milvus_tunnel.ps1
```

The default endpoint is `http://127.0.0.1:19530`, forwarded securely to the
Milvus server through SSH. Override it with the `MILVUS_URI` environment
variable when needed.
