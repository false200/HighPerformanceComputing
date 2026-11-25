# Enterprise operations (lean)

This stack is **enterprise-shaped without enterprise bloat**: thin AWS control plane, authenticated workers, durable object storage, health probes, audit trail.

## Architecture posture

| Plane | Component | Notes |
|-------|-----------|--------|
| Control | Master on AWS EC2 | Schedule, auth, reclaim, burst, metrics |
| Compute | Campus/home workers | OpenMP + owner caps; outbound-only |
| Durability | S3 (optional/local) | Checkpoints/results survive reclaim |
| Overflow | Short-lived EC2 | Policy-driven only |
| Observability | `/health` `:9101` + `audit.jsonl` + metrics CSV | LB-friendly |

**Not included on purpose:** Kubernetes, API Gateway per task, Kafka, service mesh.

## Security

1. Set a strong join token:
   ```powershell
   $env:HPC_JOIN_TOKEN = "long-random-string"
   ```
2. Use `config/enterprise.aws.yaml` on the gateway (`auth.require_token: true`).
3. Prefer SG ingress locked to your IP / campus CIDR for `9100`, `8080`, `9101`.
4. Never commit tokens; use env / SSM Parameter Store.
5. Workers and SubmitJob pass the same token (`Connect.bat` prompts; or `HPC_JOIN_TOKEN`).

## Deploy checklist

- [ ] `aws configure` / IAM can launch EC2 + optional S3
- [ ] Create S3 bucket; instance role with `s3:PutObject`/`GetObject` on that prefix
- [ ] `DeployGateway.bat` (injects token via env into user-data when `HPC_JOIN_TOKEN` is set)
- [ ] Wait for `http://<ip>:9101/health` → `running: true`
- [ ] Workers: `Connect.bat` → public IP + token + resource caps
- [ ] Submit: `SubmitJob.bat` / `submit_job.ps1 -Master <ip>:9100`
- [ ] Confirm `data/logs/audit.jsonl` and metrics on gateway
- [ ] Terminate instance when demo ends

## Failure modes

| Event | Behavior |
|-------|----------|
| Worker offline | Heartbeat timeout → reclaim → requeue |
| Owner leave | Checkpoint + requeue |
| Master blip | Workers reconnect with backoff |
| Bad token | REGISTER / JOB_SUBMIT rejected + audit |
| Pool too small | Burst policy (if `burst.mode=aws`) |

## Rollback

Terminate the gateway instance; local `Host.bat` still works for LAN demos with `config/default.yaml` (open token = empty).
