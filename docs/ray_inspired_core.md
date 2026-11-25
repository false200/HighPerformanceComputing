# Ray-inspired core (adapted, not Ray)

We studied Ray Core’s architecture (tasks, actors, object store, GCS, lineage,
resource scheduling — see [Ray key concepts](https://docs.ray.io/en/latest/ray-core/key-concepts.html)
and Moritz et al., OSDI’18) and **ported the ideas** into this consent-driven
desktop grid. We did **not** vendor Ray, copy Ray source, or depend on the Ray package.

## Concept map

| Ray Core idea | Our module | Campus-grid adaptation |
|---------------|------------|-------------------------|
| Task + resource request (`num_cpus`, memory, custom) | `master/resources.py` + `Task.resources` | Logical admission; OpenMP threads still owner-capped |
| ObjectRef to immutable remote value | `master/object_ref.py` | Refs point at local/S3 URIs (no Plasma shm) |
| Lineage reconstruction | `TaskLineage` in GCS + reclaim requeue | Reclaim marks objects lost; checkpoint_ref preferred on retry |
| Global Control Store | `master/gcs.py` | In-memory on single master (class scale) |
| Actor (stateful worker) | `WorkerInfo` + consent/pause | Owner QoS is stronger than Ray actors |
| Bottom-up / spill scheduling | Peer-first → cloud burst | Campus = “local”; AWS burst = spill |
| Autoscaler | `master/burst.py` | Policy-driven VM launch/retire |
| Placement PACK / SPREAD | `Job.placement` | `pack` fills one peer; `spread` balances |
| `max_retries` | `Task.max_retries` → `FAILED` | Same default (3); reclaim counts as retry path |

## What we deliberately kept ours

- Consent popup and join token
- Owner pause / leave / CPU–RAM caps
- Reclaim-as-normal (not only node death)
- OpenMP kernels + checksum merge
- JSON/TCP protocol on `:9100`

## Code entry points

- `master/resources.py` — `ResourceSpec`, `NodeResources`
- `master/object_ref.py` — `ObjectRef`, `TaskLineage`
- `master/gcs.py` — `GlobalControlStore`
- `master/scheduler.py` — resource-aware `assign_next`, retries, GCS hooks
- Config: `scheduling.max_retries`, `scheduling.placement`

## Tests

`tests/test_ray_inspired_core.py` covers admission, GCS refs, lineage on reclaim, max_retries, and pack placement.
