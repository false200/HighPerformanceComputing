# Logistic regression job (user → AWS cluster)

You are a **job submitter**, not a worker and not a deployer.

1. Gateway already running on AWS (`DeployGateway` once).
2. Workers already joined (`Worker.bat`).
3. You upload this package (`User.bat` or CLI); AWS shards the CSV, peers run *your* `train.py`, coordinator merges shard outputs.

## Files

| Path | Role |
|------|------|
| `data/exam_pass.csv` | Training dataset |
| `train.py` | Your code (`train_shard`) |
| `job.yaml` | Notes for upload_job flags |
| `generate_dataset.py` | Regenerates the CSV if needed |

## Submit

```powershell
$env:PYTHONPATH = Join-Path (Get-Location) "backend"
$env:HPC_JOIN_TOKEN = (Get-Content .\key\join_token.txt -Raw).Trim()
py -3 -m master.upload_job `
  --master "GATEWAY_IP:9100" `
  --token $env:HPC_JOIN_TOKEN `
  --train examples/logistic_regression/train.py `
  --dataset examples/logistic_regression/data/exam_pass.csv `
  --dataset-name data.csv `
  --entrypoint train.py `
  --label-col passed `
  --epochs 40 `
  --policy campus_only
```

## Features → label

`hours_studied`, `attendance`, `sleep_hours`, `prior_gpa`, `assignments_pct`, `tutoring` → **`passed`**
