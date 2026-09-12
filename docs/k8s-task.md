# Task: Prepare the URL Shortener repository for Kubernetes deployment

The URL Shortener application is now implemented, tested, and containerized.

I want to transition the project from local Docker execution to Kubernetes in my homelab.

You are the owner of this `url-shortener` repository. Your responsibility is to prepare the repository with the Kubernetes workload manifests required to run the application and its PostgreSQL database.

## Important repository boundary

There are two separate Git repositories:

1. `url-shortener`

   * Application source code
   * Tests
   * Dockerfile
   * Alembic migrations
   * Kubernetes workload manifests

2. `argocd-apps`

   * Argo CD `Application` resources
   * Argo CD-specific GitOps configuration

For this task, **only modify the `url-shortener` repository**.

Do NOT create or modify the Argo CD `Application` resource. That will be handled separately in the `argocd-apps` repository.

---

## Existing application

The application is:

* FastAPI
* PostgreSQL
* SQLAlchemy async
* asyncpg
* Alembic migrations
* Prometheus metrics
* Dockerized
* Stateless application container
* Application configuration supplied through environment variables

The application requires:

```text
DATABASE_URL
BASE_URL
LOG_LEVEL
```

The Docker image currently used is:

```text
magmakomer/url-shortener:1.0.0
```

The application listens on:

```text
8000
```

The application container does NOT automatically run Alembic migrations on startup.

Migrations are intentionally executed separately:

```bash
alembic upgrade head
```

This behavior should remain unchanged.

---

# Objective

Add a Kubernetes deployment structure to this repository that allows the complete application stack to run in Kubernetes:

```text
Kubernetes cluster
│
└── url-shortener namespace
    │
    ├── URL Shortener
    │   ├── Deployment
    │   └── Service
    │
    └── PostgreSQL
        ├── StatefulSet
        ├── Service
        └── PersistentVolumeClaim
```

Database migrations should be represented as a Kubernetes Job and must remain separate from application startup.

---

# Before implementing

First inspect the existing repository carefully.

In particular, verify:

* Dockerfile
* application startup command
* container working directory
* exposed/listening port
* Alembic configuration
* migration directory
* database connection configuration
* SQLAlchemy models
* required environment variables
* whether the application has a health endpoint
* Prometheus metrics endpoint
* PostgreSQL version currently used in local development

Do not assume these details if they can be determined from the repository.

If something is ambiguous, document the assumption rather than modifying application code unnecessarily.

---

# Kubernetes directory

Create a clear Kubernetes directory, preferably:

```text
k8s/
```

Use a simple structure appropriate for a single homelab application.

For example:

```text
k8s/
├── namespace.yaml
├── postgres-secret.yaml
├── postgres-service.yaml
├── postgres-statefulset.yaml
├── app-configmap.yaml
├── app-secret.yaml
├── app-deployment.yaml
├── app-service.yaml
└── migration-job.yaml
```

You may adjust the exact structure if there is a better simple organization, but avoid unnecessary Kustomize/Helm complexity at this stage.

---

# 1. Namespace

Create:

```text
url-shortener
```

namespace.

All application resources should be deployed into this namespace.

---

# 2. PostgreSQL

Deploy PostgreSQL as a Kubernetes StatefulSet.

Use the PostgreSQL version appropriate for this project based on the existing repository/CI configuration.

The PostgreSQL deployment must include:

* StatefulSet
* PostgreSQL container
* PostgreSQL Service
* PersistentVolumeClaim
* database name
* database user
* database password supplied through a Kubernetes Secret

Do NOT use `host.docker.internal`.

The application and PostgreSQL must communicate through Kubernetes networking.

The application should eventually connect to PostgreSQL through its Kubernetes Service, for example:

```text
postgres:5432
```

Do not expose PostgreSQL externally.

The PostgreSQL data must be stored on persistent storage through a PVC.

Use a reasonable storage size for a homelab learning project.

Do not over-engineer PostgreSQL into a production HA cluster.

A single PostgreSQL replica is intentional for this learning project.

---

# 3. Application configuration

Separate configuration from the Deployment where appropriate.

Use a ConfigMap for non-sensitive configuration such as:

```text
BASE_URL
LOG_LEVEL
```

Use a Secret for sensitive database connection information.

Do NOT commit real production/homelab credentials into Git.

If a Secret manifest is required for demonstration, use clearly fake/example credentials and document that real credentials must be supplied separately.

Do not invent a secret-management system such as Vault unless it is actually required.

---

# 4. URL Shortener Deployment

Create a Deployment for:

```text
magmakomer/url-shortener:1.0.0
```

Start with:

```text
replicas: 1
```

The container listens on port:

```text
8000
```

The Deployment should obtain its configuration through ConfigMap/Secret references rather than hardcoding credentials.

Do not add unnecessary infrastructure features yet.

Do not add:

* Redis
* RabbitMQ
* Kafka
* Elasticsearch
* HPA
* service mesh
* ingress controller
* external database
* authentication
* additional application components

The application is intentionally simple.

---

# 5. Application Service

Create a Kubernetes Service for the URL Shortener.

It should route:

```text
Service :8000
       ↓
Pod :8000
```

Initially keep this as a simple ClusterIP Service.

Do NOT create a NodePort, LoadBalancer, or Ingress yet.

External exposure will be handled later as a separate learning step.

---

# 6. Database migrations

Create a Kubernetes Job that runs:

```bash
alembic upgrade head
```

using the same application image:

```text
magmakomer/url-shortener:1.0.0
```

The Job must receive the correct `DATABASE_URL`.

Do not modify the application so that migrations execute automatically on startup.

The intended architecture is:

```text
PostgreSQL
     ↑
     │
Migration Job
     │
     └── alembic upgrade head

URL Shortener Deployment
     │
     └── connects to PostgreSQL
```

The migration Job should be safe to understand and operate as a separate Kubernetes workload.

If Argo CD-specific sync ordering is required, keep that concern minimal and document what would eventually be needed. Do not create an Argo CD Application resource in this repository.

---

# 7. Health checks

Inspect the application to determine whether an appropriate health endpoint already exists.

If there is an existing health endpoint, prepare the Deployment for Kubernetes readiness/liveness probes using that endpoint.

Do NOT add a new application endpoint solely for Kubernetes unless there is no reasonable existing mechanism and the change is genuinely necessary.

If no suitable health endpoint exists, document that probes are intentionally deferred rather than inventing application functionality.

---

# 8. Resource requests and limits

For the first version, consider reasonable CPU/memory requests and limits suitable for a small homelab.

Keep them conservative and explain the reasoning in comments or documentation.

Do not pretend these values are production-tuned.

The goal is to introduce the Kubernetes resource-management concept while keeping the values appropriate for a small application.

---

# 9. Secrets and Git

Never commit real passwords.

If the Kubernetes manifests require Secret objects, make the repository safe to publish.

Clearly distinguish:

```text
example/demo credentials
```

from:

```text
real deployment credentials
```

Document how the real Secret should be created.

Do not silently introduce an external secret-management product.

We will address proper GitOps secret management later.

---

# 10. Documentation

Update the repository README with a Kubernetes section explaining:

1. Kubernetes prerequisites
2. Namespace
3. PostgreSQL
4. Persistent storage
5. Application Deployment
6. Services
7. Database migrations
8. How to deploy manually with kubectl
9. How to verify the deployment
10. How to inspect logs
11. How to verify PostgreSQL connectivity
12. How to remove the deployment

The README should explain the architecture rather than simply listing commands.

Include useful commands such as:

```bash
kubectl apply -f k8s/
kubectl get all -n url-shortener
kubectl get pvc -n url-shortener
kubectl get jobs -n url-shortener
kubectl logs ...
```

Also explain that external access is intentionally not configured yet.

---

# 11. Important learning constraint

This is a Kubernetes/DevOps learning project.

Do not over-engineer the solution.

Prefer:

```text
simple
explicit
easy to understand
easy to troubleshoot
```

over:

```text
production platform complexity
```

The application itself is deliberately minimal. The learning objective is Kubernetes, DevOps, observability and GitOps.

Do not modify application functionality unless required to make Kubernetes deployment work.

---

# 12. Validation

Before finishing:

* Validate all YAML
* Verify resource references
* Verify labels/selectors
* Verify namespace references
* Verify Service target ports
* Verify PostgreSQL environment variables
* Verify DATABASE_URL
* Verify the migration command
* Verify the application image
* Verify PVC configuration
* Verify the Deployment configuration

If possible, test the manifests against a Kubernetes cluster.

The expected final architecture should be:

```text
                    url-shortener namespace

              ┌──────────────────────────┐
              │      URL Shortener       │
              │                          │
Client ──────►│ Service :8000            │
              │        │                 │
              │        ▼                 │
              │ Deployment               │
              │        │                 │
              │        ▼                 │
              │      Pod :8000            │
              └────────┬─────────────────┘
                       │
                       │ DATABASE_URL
                       ▼
              ┌──────────────────────────┐
              │       PostgreSQL         │
              │                          │
              │ Service :5432            │
              │        │                 │
              │        ▼                 │
              │ StatefulSet               │
              │        │                 │
              │        ▼                 │
              │ PersistentVolumeClaim     │
              └──────────────────────────┘

              Migration Job
                    │
                    ▼
             alembic upgrade head
```

---

## Expected deliverable

Implement the Kubernetes manifests and documentation in the `url-shortener` repository.

Do NOT implement the Argo CD Application.

After implementation, provide a concise summary of:

1. Files created/changed
2. Kubernetes architecture
3. Any assumptions made
4. How to deploy it manually
5. How migrations are handled
6. Any issues or decisions that should be reviewed before putting this under Argo CD

Do not unnecessarily modify the application code.
