# Lattice

Consent-based desktop cluster: peers donate CPU, a coordinator schedules work, users upload jobs and get results back.

## Quick start

**Worker (donate compute)**  
`Connect.bat` → enter the gateway IP + join token → consent.

**User (run a job)** — gateway must already be up; workers connected:
```powershell
$env:PYTHONPATH = (Get-Location).Path
$env:HPC_JOIN_TOKEN = (Get-Content .\key\join_token.txt -Raw).Trim()

py -3 -m master.upload_job `
  --master "GATEWAY_IP:9100" `
  --token $env:HPC_JOIN_TOKEN `
  --train test/train.py `
  --dataset test/data.csv `
  --dataset-name data.csv `
  --entrypoint train.py `
  --label-col price_k `
  --epochs 100 `
  --chunks 6 `
  --policy campus_only
```

**Console:** `http://GATEWAY_IP:8080` — peers **and** connected users show on the map; logout removes the user node. Job intake **requires RabbitMQ**; fair least-load scheduling spreads work across workers. Users upload their own code+data (`upload_job`) — no built-in ML kernels.

## Deploy gateway once (AWS)

```powershell
$env:HPC_JOIN_TOKEN = "your-secret"
.\DeployGateway.bat
```

Do not redeploy for each job. Workers `Connect`; users `upload_job`.

## Local host (no AWS)

`Host.bat` on one laptop, then `Connect.bat` / `SubmitJob.bat` on others.

## Tests

```powershell
$env:PYTHONPATH = (Get-Location).Path
py -3 -m pytest tests -q
```

## Docs

- [`docs/architecture.md`](docs/architecture.md) — design  
- [`docs/aws_deployment.md`](docs/aws_deployment.md) — AWS  
- [`examples/logistic_regression/`](examples/logistic_regression/) · [`test/`](test/) — sample user jobs  
