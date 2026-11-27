# Logistic regression job (user → AWS cluster)

You are a **job submitter**, not a worker and not a deployer.

1. Gateway already running on AWS (`DeployGateway` once).
2. Workers already joined (`Connect.bat`).
3. You submit this job; AWS splits the dataset, workers train shards, master merges the model.

## Files

| Path | Role |
|------|------|
| `data/exam_pass.csv` | Training dataset (1200 rows) |
| `job.yaml` | Job request (kernel, dataset, shards) |
| `generate_dataset.py` | Regenerates the CSV if needed |
| `../../SubmitLogReg.bat` | One-click user submit |

## Features → label

`hours_studied`, `attendance`, `sleep_hours`, `prior_gpa`, `assignments_pct`, `tutoring` → **`passed`**
