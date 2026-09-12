# URL Shortener

A minimal URL shortener API built with FastAPI and PostgreSQL. Clients submit a long URL and receive a short URL; accessing the short URL issues a redirect to the original. The service is configured entirely through environment variables, exposes Prometheus metrics, and is packaged as a stateless, production-oriented Docker container.

## Configuration

All runtime configuration is supplied through environment variables:

| Variable | Required | Description | Example |
| --- | --- | --- | --- |
| `DATABASE_URL` | Yes | PostgreSQL connection string (async driver) | `postgresql+asyncpg://postgres:password@db:5432/url_shortener` |
| `BASE_URL` | Yes | Publicly accessible root URL of the service, no trailing slash | `http://localhost:8000` |
| `LOG_LEVEL` | No | Logging level (`DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL`). Defaults to `INFO`. | `INFO` |

See [`.env.example`](.env.example) for a template. Do not commit a populated `.env` file.

## Docker

The application ships with a `Dockerfile` that uses `python:3.12-slim`, runs as a non-root user, exposes port `8000`, and starts the app with `uvicorn`. The image is stateless and contains no secrets or environment-specific configuration — all configuration is provided at runtime via environment variables.

### Local development database

For local/manual testing you can run PostgreSQL in a container. This keeps your
machine free of a `createdb`/`psql` install and matches the versions used in CI.

```bash
docker run --name url-shortener-postgres \
  -e POSTGRES_USER=url_shortener_dev \
  -e POSTGRES_PASSWORD=url_shortener_dev \
  -e POSTGRES_DB=url_shortener_local \
  -p 5433:5432 \
  -d postgres:14-alpine
```

This maps host port `5433` to the container's `5432`. Use a dedicated
`url_shortener_local` database for manual testing — keep it separate from the
`url_shortener_test` database, whose schema is torn down by the test suite on
every run.

If the container is already running and you only need the extra database:

```bash
docker exec url-shortener-postgres \
  psql -U url_shortener_dev -d postgres \
  -c "CREATE DATABASE url_shortener_local OWNER url_shortener_dev;"
```


### Build the image

```bash
docker build -t url-shortener:latest .
```

### Run the container

Provide the required environment variables at runtime and publish the container port. Use your own values in place of the examples below.

```bash
docker run --rm \
  -e DATABASE_URL="postgresql+asyncpg://url_shortener_dev:url_shortener_dev@host.docker.internal:5433/url_shortener_local" \
  -e BASE_URL="http://localhost:8000" \
  -e LOG_LEVEL="INFO" \
  -p 8000:8000 \
  url-shortener:latest
```

- `-e DATABASE_URL=...` (required) — PostgreSQL connection string. The example values above are placeholders; supply your own credentials and host.
- `-e BASE_URL=...` (required) — the public root URL used to build returned short URLs.
- `-e LOG_LEVEL=...` (optional) — defaults to `INFO` when omitted.
- `-p 8000:8000` — maps the container's exposed port `8000` to the host.

Application logs are written to stdout/stderr, so container runtimes and log aggregators can collect them without extra configuration.

> **Connecting to a database on your host machine:** inside a container, `localhost` refers to the container itself, not your host. If your PostgreSQL runs on the host (e.g. mapped to `localhost:5433`), use `host.docker.internal` as the host in `DATABASE_URL` on Docker Desktop (Windows/macOS):
>
> ```
> DATABASE_URL="postgresql+asyncpg://user:pass@host.docker.internal:5433/url_shortener"
> ```
>
> On plain Linux Docker, add `--add-host=host.docker.internal:host-gateway` to the `docker run` command, or run PostgreSQL in a container on a shared Docker network and use its container name as the host.

### Database migrations

The application container **does not** run database migrations automatically on startup. You must apply migrations separately, before (or independently of) starting the application, so schema changes are explicit and controlled.

Run Alembic migrations against your database using the same image:

```bash
docker run --rm \
  -e DATABASE_URL="postgresql+asyncpg://url_shortener_dev:url_shortener_dev@host.docker.internal:5433/url_shortener_local" \
  url-shortener:latest \
  alembic upgrade head
```

This runs `alembic upgrade head` inside a one-off container and exits. Migrations only require `DATABASE_URL` — `BASE_URL` is not needed to run them. Apply migrations first, then start the application container as shown above. Docker Compose is not required to build or run the service.

## Kubernetes deployment

The `k8s/` directory contains plain Kubernetes manifests to run the full stack —
the stateless URL Shortener application plus its PostgreSQL database — inside a
cluster (targeted at a small homelab). The manifests are deliberately simple:
raw YAML, no Kustomize or Helm, so every resource is explicit and easy to
troubleshoot.

> External access is **intentionally not configured yet.** The application
> Service is a `ClusterIP`, reachable only from inside the cluster. Exposing it
> via NodePort / LoadBalancer / Ingress is a later, separate learning step.

### Architecture

Everything lives in a dedicated `url-shortener` namespace:

```text
                    url-shortener namespace

              ┌──────────────────────────┐
              │      URL Shortener       │
 (in-cluster) │ Service :8000 (ClusterIP)│
 client ─────►│        │                 │
              │        ▼                 │
              │ Deployment (replicas: 1) │
              │        │                 │
              │        ▼                 │
              │      Pod :8000           │
              └────────┬─────────────────┘
                       │ DATABASE_URL (from app-secret)
                       ▼
              ┌──────────────────────────┐
              │        PostgreSQL        │
              │ Service :5432 (headless) │
              │        │                 │
              │        ▼                 │
              │ StatefulSet (replicas: 1)│
              │        │                 │
              │        ▼                 │
              │ PersistentVolumeClaim    │
              └──────────────────────────┘

              Migration Job (run separately)
                    │
                    ▼
             alembic upgrade head
```

- **Application** is stateless, so it runs as a `Deployment`. It reads
  `BASE_URL` / `LOG_LEVEL` from a `ConfigMap` and `DATABASE_URL` from a
  `Secret`. Nothing is hardcoded in the pod spec.
- **PostgreSQL** runs as a single-replica `StatefulSet` with a
  `PersistentVolumeClaim` (via `volumeClaimTemplates`) so its data survives pod
  restarts. It is fronted by a **headless** Service named `postgres`, which the
  app reaches at `postgres:5432` over normal Kubernetes DNS. Postgres is never
  exposed outside the cluster.
- **Migrations** run as a one-off `Job` (`alembic upgrade head`) using the same
  application image. Migrations are **not** run on application startup — they
  stay an explicit, separate operation.

### Manifests

| File | Resource | Purpose |
| --- | --- | --- |
| `k8s/namespace.yaml` | Namespace | Isolates all resources in `url-shortener`. |
| `k8s/postgres-secret.yaml` | Secret | PostgreSQL DB name / user / password (**example creds**). |
| `k8s/postgres-service.yaml` | Service (headless) | Stable in-cluster DNS `postgres:5432`. |
| `k8s/postgres-statefulset.yaml` | StatefulSet + PVC | Single Postgres pod with persistent storage. |
| `k8s/app-configmap.yaml` | ConfigMap | Non-sensitive config: `BASE_URL`, `LOG_LEVEL`. |
| `k8s/app-secret.yaml` | Secret | `DATABASE_URL` (embeds DB password — **example creds**). |
| `k8s/app-deployment.yaml` | Deployment | The URL Shortener app, port 8000, liveness/readiness probes. |
| `k8s/app-service.yaml` | Service (ClusterIP) | Routes `:8000` to the app pods. |
| `k8s/migration-job.yaml` | Job | Runs `alembic upgrade head`. |

### Prerequisites

- A running Kubernetes cluster and `kubectl` configured to talk to it
  (`kubectl cluster-info` should succeed). A local homelab cluster such as k3s,
  kind, minikube, or Docker Desktop Kubernetes is fine.
- A **default StorageClass** in the cluster (so the PVC can be provisioned
  dynamically). Check with `kubectl get storageclass` — one entry should be
  marked `(default)`.
- The application image `magmakomer/url-shortener:1.0.0` must be pullable by the
  cluster nodes (published to a registry the cluster can reach).

### Secrets and Git safety

The `postgres-secret.yaml` and `app-secret.yaml` files in this repo contain
**fake, example credentials only** so the repository is safe to publish. They
share the same user/password/database so `DATABASE_URL` lines up with the
PostgreSQL Secret.

For a real deployment, **do not commit real passwords.** Create the Secrets
out-of-band and keep them out of Git. The user, password, and database must
match between the two Secrets:

```bash
kubectl create secret generic postgres-secret \
  --namespace url-shortener \
  --from-literal=POSTGRES_DB=url_shortener \
  --from-literal=POSTGRES_USER=url_shortener \
  --from-literal=POSTGRES_PASSWORD='<real-strong-password>'

kubectl create secret generic app-secret \
  --namespace url-shortener \
  --from-literal=DATABASE_URL='postgresql+asyncpg://url_shortener:<real-strong-password>@postgres:5432/url_shortener'
```

(Create the namespace first — see below.) Proper GitOps secret management
(Sealed Secrets / SOPS / External Secrets) is intentionally deferred to a later
step.

### Deploy manually with kubectl

`kubectl apply -f k8s/` applies every manifest. Because `apply` does not
guarantee ordering, PostgreSQL may still be starting when the migration Job
first runs; the Job's `backoffLimit` lets it retry until Postgres is ready. If
you prefer a clean, explicit order:

```bash
# 1. Namespace first
kubectl apply -f k8s/namespace.yaml

# 2. Config + secrets
kubectl apply -f k8s/postgres-secret.yaml
kubectl apply -f k8s/app-configmap.yaml
kubectl apply -f k8s/app-secret.yaml

# 3. PostgreSQL, then wait until it is ready
kubectl apply -f k8s/postgres-service.yaml
kubectl apply -f k8s/postgres-statefulset.yaml
kubectl rollout status statefulset/postgres -n url-shortener

# 4. Run migrations and wait for completion
kubectl apply -f k8s/migration-job.yaml
kubectl wait --for=condition=complete job/db-migrate -n url-shortener --timeout=120s

# 5. Application + Service
kubectl apply -f k8s/app-deployment.yaml
kubectl apply -f k8s/app-service.yaml
```

Or simply:

```bash
kubectl apply -f k8s/
```

### Verify the deployment

```bash
# Everything in the namespace
kubectl get all -n url-shortener

# Persistent volume claim for PostgreSQL
kubectl get pvc -n url-shortener

# Migration Job status (should show 1/1 completions)
kubectl get jobs -n url-shortener

# Wait for the app rollout to finish
kubectl rollout status deployment/url-shortener -n url-shortener
```

Since there is no external route yet, reach the app from your workstation with
a port-forward, then hit the health/metrics endpoints:

```bash
kubectl port-forward -n url-shortener svc/url-shortener 8000:8000
# in another terminal:
curl http://localhost:8000/health   # {"status":"ok"}
curl http://localhost:8000/ready    # {"status":"ready"} once the DB is reachable
curl http://localhost:8000/metrics  # Prometheus metrics
```

### Inspect logs

```bash
# Application logs (stdout/stderr)
kubectl logs -n url-shortener deployment/url-shortener -f

# Migration Job logs (what alembic did)
kubectl logs -n url-shortener job/db-migrate

# PostgreSQL logs
kubectl logs -n url-shortener statefulset/postgres
```

### Verify PostgreSQL connectivity

```bash
# Is Postgres accepting connections? (uses credentials from the Secret)
kubectl exec -n url-shortener postgres-0 -- \
  pg_isready -U url_shortener -d url_shortener

# Open a psql shell inside the Postgres pod and confirm the schema
kubectl exec -it -n url-shortener postgres-0 -- \
  psql -U url_shortener -d url_shortener -c '\dt'
# After migrations you should see the "urls" table.
```

You can also confirm the app itself sees the database via its readiness probe,
which runs `SELECT 1`: a `200 {"status":"ready"}` from `/ready` (see the
port-forward above) means the app connected successfully.

### Re-running migrations

`alembic upgrade head` is idempotent, but a completed Job's name is immutable.
To apply a newly added migration, delete the old Job and re-apply:

```bash
kubectl delete job db-migrate -n url-shortener
kubectl apply -f k8s/migration-job.yaml
```

### Remove the deployment

```bash
# Remove all resources defined by the manifests
kubectl delete -f k8s/

# Note: kubectl delete -f does NOT remove the PVC created by the StatefulSet's
# volumeClaimTemplates. To also delete the PostgreSQL data volume:
kubectl delete pvc -n url-shortener -l app.kubernetes.io/name=postgres

# Or remove everything including the namespace (deletes the PVC too):
kubectl delete namespace url-shortener
```

### Resource requests and limits

Each workload sets conservative CPU/memory requests and limits (app: 50m/128Mi
request, 250m/256Mi limit; Postgres: 100m/256Mi request, 500m/512Mi limit).
These are starting values chosen to introduce the resource-management concept
on a small homelab — **they are not production-tuned.** Adjust them based on
observed usage.

### Notes before putting this under Argo CD

- **No Argo CD `Application` resource is included here** — that belongs in the
  separate `argocd-apps` repository and is out of scope for this repo.
- **Sync ordering:** the migration Job should run before the app rolls out.
  Under Argo CD this is typically expressed with sync-wave / hook annotations on
  the Job (e.g. `argocd.argoproj.io/hook: PreSync` and
  `argocd.argoproj.io/hook-delete-policy: BeforeHookCreation`), which also
  solves the "immutable completed Job" re-run problem automatically. These
  annotations are intentionally omitted from the plain manifests here.
- **Secrets:** replace the example Secrets with a real secret-management
  approach (Sealed Secrets / SOPS / External Secrets) before syncing from Git.
- **Image availability:** ensure `magmakomer/url-shortener:1.0.0` is reachable
  from the cluster's nodes.
