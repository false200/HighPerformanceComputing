# AWS deployment — Master as Gateway

## Does the architecture need to change?

**No redesign of the campus pool.** Your idea (“users connect to a gateway; work goes out and results come back”) is already how this system works:

| Your words | This codebase |
|------------|----------------|
| Gateway on AWS | **Master** process on an EC2 instance |
| Worker nodes | Campus laptops (`Connect.bat`) and/or EC2 burst workers |
| Request through gateway | `JOB_SUBMIT` / `TASK_ASSIGN` via TCP `:9100` |
| Results back through gateway | `TASK_RESULT` → merge on master → you |

You do **not** need a separate API Gateway product for the curriculum demo. A public **EC2 master** *is* the gateway. (Optional later: Network Load Balancer in front of `:9100` for a stable DNS name.)

```text
                    YOU (operator laptop)
                           │ SubmitJob → master:9100
                           ▼
              ┌────────────────────────────┐
              │   AWS  ·  Gateway / Master │
              │   EC2  ·  TCP 9100 (+8080) │
              │   optional S3 checkpoints  │
              └─────────────┬──────────────┘
                 ▲          │ TASK_ASSIGN
                 │          ▼
         REGISTER/RESULT   Campus workers (your 3 laptops)
         HEARTBEAT         Connect.bat → <AWS public IP>
                 │          │
                 │          ▼
                 └──── optional EC2 cloud-burst workers
```

**Why this fits student laptops:** workers only make **outbound** connections to AWS. No inbound ports on home/campus firewalls.

---

## Curriculum deployment (recommended)

### 1. Deploy the gateway (master) on AWS
Use `scripts/aws_deploy_gateway.ps1` (or `.sh`) with AWS CLI configured.

It will roughly:
- create/reuse a security group (ports **9100**, **8080**)
- launch a free-tier-ish instance with user-data that installs deps and runs `python -m master`
- print the **public IP / DNS**

### 2. Point workers at that IP
On each laptop:

```text
Connect.bat  →  enter the AWS public IP
```

Same consent / CPU / RAM caps as before.

### 3. Submit jobs from your PC
```text
SubmitJob.bat   (or)
.\scripts\submit_job.ps1 -Master "<AWS_PUBLIC_IP>:9100"
```

### 4. (Optional) Cloud burst still on AWS
Set in `config/default.yaml` on the **gateway instance**:

```yaml
burst:
  mode: aws
  aws_master_host: "<same public DNS or private IP if same VPC>"
  # ami, sg, subnet filled for worker VMs
storage:
  backend: s3
  s3_bucket: your-bucket
```

Campus peers stay first; EC2 workers join only under burst policy.

---

## What you run where

| Component | Where | How |
|-----------|--------|-----|
| Master / gateway | AWS EC2 | `aws_deploy_gateway` |
| Dashboard | Same EC2 `:8080` | opened by deploy SG |
| Campus workers | Your laptops | `Connect.bat` → AWS IP |
| Job submit | Your laptop | `SubmitJob` → AWS IP |
| Burst workers | AWS EC2 | policy + launch stubs |
| Checkpoints | Local on EC2 or S3 | config `storage` |

---

## Security notes (course / free tier)

- Prefer locking SG ingress for `9100`/`8080` to **your IP** `/32`, not `0.0.0.0/0`, when possible.
- Do not put AWS keys on student worker laptops.
- Stop/terminate the gateway instance when the demo ends to avoid charges.

---

## Mapping to the project PDF

- **Campus-first pool** — unchanged (consent, OpenMP, reclaim).
- **Cloud-burst overflow** — EC2 workers via burst controller.
- **Deploy on AWS** — master/gateway (+ optional S3 + burst VMs) satisfies the curriculum hosting requirement without moving every student laptop into the cloud.
