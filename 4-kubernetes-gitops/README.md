# Kubernetes GitOps

Production Kubernetes manifests for MLOps infrastructure using GitOps principles.

## Architecture

```
┌──────────────────────────────────────────────────────────┐
│                    Kubernetes Cluster                     │
│                                                           │
│  ┌─────────────────────────────────────────────────────┐ │
│  │              MLOps Namespace                        │ │
│  │                                                     │ │
│  │  ┌──────────────┐  ┌──────────────┐  ┌──────────┐ │ │
│  │  │   Airflow    │  │   MLflow     │  │  ClearML │ │ │
│  │  │  Scheduler   │  │   Server     │  │  Server  │ │ │
│  │  │  Webserver   │  └──────┬───────┘  └────┬─────┘ │ │
│  │  │  Workers (3) │         │               │       │ │
│  │  └──────┬───────┘         │               │       │ │
│  │         │                 │               │       │ │
│  │  ┌──────▼─────────────────▼───────────────▼─────┐ │ │
│  │  │           PostgreSQL StatefulSet            │ │ │
│  │  │         (mlflow, airflow, clearml DBs)      │ │ │
│  │  └──────────────────┬──────────────────────────┘ │ │
│  │                     │                            │ │
│  │  ┌──────────────────▼──────────────────────────┐ │ │
│  │  │         Redis (Celery Broker)              │ │ │
│  │  └────────────────────────────────────────────┘ │ │
│  └─────────────────────────────────────────────────┘ │
│                                                       │
│  ┌─────────────────────────────────────────────────┐ │
│  │              Ingress (NGINX)                    │ │
│  │  - airflow.mlops.example.com                   │ │
│  │  - mlflow.mlops.example.com                    │ │
│  │  - clearml.mlops.example.com                   │ │
│  └─────────────────────────────────────────────────┘ │
└───────────────────────────────────────────────────────┘
```

## Components

### 1. MLflow Tracking Server ([mlflow-deployment.yaml](mlflow-deployment.yaml))

Production MLflow deployment with:
- **2 replicas** for high availability
- **PostgreSQL backend** for experiment metadata
- **S3 artifact storage** for models and artifacts
- **Resource limits**: 2Gi memory, 2 CPU
- **Health checks**: Liveness and readiness probes
- **Ingress**: TLS-enabled with cert-manager

**Key Features:**
- Persistent experiment tracking
- Model registry integration
- Secrets management for AWS credentials
- Horizontal scalability

### 2. Airflow Deployment ([airflow-deployment.yaml](airflow-deployment.yaml))

Complete Airflow setup with CeleryExecutor:
- **Webserver** (2 replicas): UI and API server
- **Scheduler** (1 replica): DAG scheduling
- **Workers** (3 replicas): Task execution
- **Shared storage**: EFS for DAGs and logs
- **ConfigMap**: Airflow configuration
- **Init containers**: Database readiness checks

**Architecture:**
- CeleryExecutor for distributed task execution
- Redis as message broker
- PostgreSQL for metadata
- PersistentVolumeClaims for shared storage

### 3. PostgreSQL StatefulSet ([postgres-statefulset.yaml](postgres-statefulset.yaml))

Stateful PostgreSQL deployment:
- **StatefulSet** with persistent volumes
- **100Gi gp3 storage** with automatic provisioning
- **Init scripts** for database creation
- **Headless service** for stable network identity
- **Multiple databases**: mlflow, airflow, clearml

**Features:**
- Automatic database initialization
- UUID extension enabled
- Health checks with pg_isready
- Resource management: 4Gi memory, 2 CPU

### 4. Redis Cache ([redis-deployment.yaml](redis-deployment.yaml))

Redis for Celery message broker:
- In-memory caching for ML experiments
- Celery task queue backend
- High-performance message broker

### 5. ClearML Server ([clearml-deployment.yaml](clearml-deployment.yaml))

ClearML experiment tracking and orchestration:
- API server for experiment management
- Web UI for visualization
- Agent management for distributed training

### 6. Namespace and RBAC ([namespace.yaml](namespace.yaml))

Complete access control setup:
- MLOps namespace isolation
- ServiceAccounts for each component
- Roles and RoleBindings
- Pod Security Policies

## File Structure

```
4-kubernetes-gitops/
├── README.md                      # This file
├── namespace.yaml                 # Namespace and RBAC
├── postgres-statefulset.yaml      # PostgreSQL database
├── redis-deployment.yaml          # Redis cache/broker
├── mlflow-deployment.yaml         # MLflow tracking server
├── airflow-deployment.yaml        # Airflow (scheduler, webserver, workers)
├── clearml-deployment.yaml        # ClearML experiment tracking
├── network-policy.yaml            # Network isolation policies
├── secrets.yaml.example           # Example secrets (DO NOT COMMIT)
└── kustomization.yaml            # Kustomize configuration
```

## Deployment

### Prerequisites

```bash
# Install kubectl
curl -LO "https://dl.k8s.io/release/$(curl -L -s https://dl.k8s.io/release/stable.txt)/bin/linux/amd64/kubectl"

# Install kustomize
curl -s "https://raw.githubusercontent.com/kubernetes-sigs/kustomize/master/hack/install_kustomize.sh" | bash

# Verify cluster access
kubectl cluster-info
```

### Step 1: Create Namespace and Secrets

```bash
# Create namespace
kubectl apply -f namespace.yaml

# Create secrets (edit with your values first)
cp secrets.yaml.example secrets.yaml
# Edit secrets.yaml with actual credentials
kubectl apply -f secrets.yaml
```

### Step 2: Deploy PostgreSQL

```bash
# Deploy StatefulSet
kubectl apply -f postgres-statefulset.yaml

# Verify deployment
kubectl get statefulset -n mlops
kubectl get pvc -n mlops

# Check logs
kubectl logs -n mlops postgres-0

# Wait for ready
kubectl wait --for=condition=ready pod/postgres-0 -n mlops --timeout=300s
```

### Step 3: Deploy Redis

```bash
kubectl apply -f redis-deployment.yaml

# Verify
kubectl get pods -n mlops -l app=redis
```

### Step 4: Deploy MLflow

```bash
kubectl apply -f mlflow-deployment.yaml

# Check deployment
kubectl get deployment -n mlops mlflow-server
kubectl get svc -n mlops mlflow-service
kubectl get ingress -n mlops mlflow-ingress

# View logs
kubectl logs -n mlops -l app=mlflow --tail=50
```

### Step 5: Deploy Airflow

```bash
# Deploy all Airflow components
kubectl apply -f airflow-deployment.yaml

# Verify all components
kubectl get pods -n mlops -l app=airflow

# Check each component
kubectl get deployment -n mlops airflow-webserver
kubectl get deployment -n mlops airflow-scheduler
kubectl get deployment -n mlops airflow-worker

# Access webserver logs
kubectl logs -n mlops -l app=airflow,component=webserver
```

### Step 6: Deploy ClearML

```bash
kubectl apply -f clearml-deployment.yaml

# Verify
kubectl get pods -n mlops -l app=clearml
```

### Using Kustomize (Recommended)

```bash
# Deploy everything at once
kubectl apply -k .

# View what will be applied
kubectl kustomize . | less

# Delete everything
kubectl delete -k .
```

## Access Services

### Port Forwarding (Development)

```bash
# MLflow
kubectl port-forward -n mlops svc/mlflow-service 5000:80

# Airflow
kubectl port-forward -n mlops svc/airflow-webserver-service 8080:80

# PostgreSQL (for debugging)
kubectl port-forward -n mlops svc/postgres-service 5432:5432
```

### Ingress (Production)

Services are accessible via Ingress:
- **MLflow**: https://mlflow.mlops.example.com
- **Airflow**: https://airflow.mlops.example.com
- **ClearML**: https://clearml.mlops.example.com

## Monitoring

### Pod Status

```bash
# All pods in namespace
kubectl get pods -n mlops -o wide

# Watch for changes
kubectl get pods -n mlops -w

# Describe pod for events
kubectl describe pod <pod-name> -n mlops
```

### Logs

```bash
# View logs
kubectl logs -n mlops <pod-name>

# Follow logs
kubectl logs -n mlops <pod-name> -f

# Previous container logs (if crashed)
kubectl logs -n mlops <pod-name> --previous

# All pods with label
kubectl logs -n mlops -l app=airflow --tail=100
```

### Resource Usage

```bash
# CPU and memory usage
kubectl top pods -n mlops

# Node resources
kubectl top nodes

# Persistent volumes
kubectl get pv
kubectl get pvc -n mlops
```

## Troubleshooting

### Common Issues

**PostgreSQL not ready:**
```bash
# Check pod status
kubectl describe pod postgres-0 -n mlops

# Check PVC
kubectl get pvc -n mlops

# Check init logs
kubectl logs postgres-0 -n mlops
```

**Airflow pods CrashLoopBackOff:**
```bash
# Check if DB is ready
kubectl exec -n mlops postgres-0 -- psql -U postgres -c "\l"

# Check airflow logs
kubectl logs -n mlops <airflow-pod> --previous

# Reinitialize database
kubectl exec -n mlops <airflow-pod> -- airflow db init
```

**MLflow connection errors:**
```bash
# Verify secrets
kubectl get secret -n mlops mlflow-secrets -o yaml

# Test DB connection
kubectl exec -n mlops postgres-0 -- psql -U mlflow -d mlflow -c "SELECT 1"

# Check S3 access
kubectl logs -n mlops -l app=mlflow | grep -i s3
```

### Debugging Commands

```bash
# Execute commands in pod
kubectl exec -it -n mlops <pod-name> -- /bin/bash

# Copy files from pod
kubectl cp mlops/<pod-name>:/path/to/file ./local-file

# Check service endpoints
kubectl get endpoints -n mlops

# Describe ingress
kubectl describe ingress -n mlops
```

## Scaling

### Manual Scaling

```bash
# Scale Airflow workers
kubectl scale deployment -n mlops airflow-worker --replicas=5

# Scale MLflow
kubectl scale deployment -n mlops mlflow-server --replicas=3
```

### Horizontal Pod Autoscaler

```yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: airflow-worker-hpa
  namespace: mlops
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: airflow-worker
  minReplicas: 2
  maxReplicas: 10
  metrics:
  - type: Resource
    resource:
      name: cpu
      target:
        type: Utilization
        averageUtilization: 70
```

## Backup and Recovery

### PostgreSQL Backup

```bash
# Backup all databases
kubectl exec -n mlops postgres-0 -- pg_dumpall -U postgres > backup.sql

# Backup specific database
kubectl exec -n mlops postgres-0 -- pg_dump -U postgres mlflow > mlflow-backup.sql

# Restore
kubectl exec -i -n mlops postgres-0 -- psql -U postgres < backup.sql
```

### Volume Snapshots

```yaml
apiVersion: snapshot.storage.k8s.io/v1
kind: VolumeSnapshot
metadata:
  name: postgres-snapshot
  namespace: mlops
spec:
  volumeSnapshotClassName: csi-aws-vss
  source:
    persistentVolumeClaimName: postgres-data-postgres-0
```

## Security Best Practices

1. **Secrets Management**: Use external secrets operator (AWS Secrets Manager, Vault)
2. **Network Policies**: Restrict pod-to-pod communication
3. **RBAC**: Minimum privilege access
4. **Pod Security**: Use Pod Security Standards
5. **Image Security**: Scan images for vulnerabilities
6. **TLS**: Enable TLS for all ingress endpoints

## Technologies

- **Kubernetes**: Container orchestration (v1.28+)
- **Kustomize**: Configuration management
- **Cert-Manager**: TLS certificate automation
- **NGINX Ingress**: Ingress controller
- **EFS CSI Driver**: Shared storage for Airflow
- **EBS CSI Driver**: Block storage for PostgreSQL
- **PostgreSQL**: Relational database
- **Redis**: In-memory cache and message broker
