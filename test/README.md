# test — user linear regression job (100 epochs)

Act as a **cluster user** (not a worker, not a deployer):

1. Workers already connected to AWS with a join token  
2. You upload `train.py` + `data.csv` to the live gateway  
3. Platform shards training; you get merged weights back  

## Files

| File | Role |
|------|------|
| `train.py` | Linear regression, **100 epochs** |
| `data.csv` | Synthetic house-price features → `price_k` |
| `generate_dataset.py` | Regenerates `data.csv` |
| `results.json` | Filled after a successful user submit |

## Submit (user)

```powershell
py -3 -m master.upload_job `
  --master "<AWS_IP>:9100" `
  --token "<join-token>" `
  --name "test-linreg" `
  --train test/train.py `
  --dataset test/data.csv `
  --dataset-name data.csv `
  --entrypoint train.py `
  --label-col price_k `
  --epochs 100 `
  --lr 0.0005 `
  --chunks 6 `
  --policy campus_only
```
