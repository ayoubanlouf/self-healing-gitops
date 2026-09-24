#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
CLUSTER_NAME="gitops-cluster"

echo "=== [1/8] Checking / Creating Kind Cluster: ${CLUSTER_NAME} ==="
if ! kind get clusters | grep -q "^${CLUSTER_NAME}$"; then
  echo "Provisioning new Kind cluster with port mappings..."
  kind create cluster --config "${SCRIPT_DIR}/kind-config.yaml"
else
  echo "Cluster ${CLUSTER_NAME} already exists. Using existing cluster."
fi

kubectl cluster-info --context "kind-${CLUSTER_NAME}"
kubectl wait --for=condition=Ready nodes --all --timeout=60s

echo "=== [2/8] Installing ArgoCD ==="
kubectl create namespace argocd --dry-run=client -o yaml | kubectl apply -f -
kubectl apply -n argocd -f https://raw.githubusercontent.com/argoproj/argo-cd/v2.10.4/manifests/install.yaml

# Disable TLS termination on argocd-server for local dev simplicity
kubectl patch deployment argocd-server -n argocd --type='json' -p='[{"op": "add", "path": "/spec/template/spec/containers/0/args/-", "value": "--insecure"}]' || true

echo "=== [3/8] Installing kube-prometheus-stack ==="
kubectl create namespace monitoring --dry-run=client -o yaml | kubectl apply -f -
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts || true
helm repo update prometheus-community

helm upgrade --install prometheus-stack prometheus-community/kube-prometheus-stack \
  --namespace monitoring \
  --values "${ROOT_DIR}/monitoring/prometheus-values.yaml" \
  --wait --timeout=5m || echo "Prometheus stack installation triggered."

echo "=== [4/8] CRD Race Condition Guard ==="
echo "Waiting for Prometheus and ArgoCD CRDs to establish..."
kubectl wait --for=condition=established --timeout=120s crd/prometheuses.monitoring.coreos.com
kubectl wait --for=condition=established --timeout=120s crd/servicemonitors.monitoring.coreos.com
kubectl wait --for=condition=established --timeout=120s crd/prometheusrules.monitoring.coreos.com
kubectl wait --for=condition=established --timeout=120s crd/applications.argoproj.io
kubectl wait --for=condition=established --timeout=120s crd/applicationsets.argoproj.io

echo "Waiting for ArgoCD server deployment..."
kubectl wait --for=condition=available --timeout=180s deployment/argocd-server -n argocd

echo "=== [5/8] Building & Loading Local Container Images ==="
cd "${ROOT_DIR}"

echo "Building git-server image..."
docker build -t git-server:v1 git-server/

echo "Building app images (v1 and v2)..."
docker build -t app:v1 app/
docker build -t app:v2 --build-arg APP_VERSION=v2.0.0 app/

echo "Building remediator image..."
docker build -t remediator:v1 remediator/

echo "Loading images into Kind cluster..."
kind load docker-image git-server:v1 --name "${CLUSTER_NAME}"
kind load docker-image app:v1 --name "${CLUSTER_NAME}"
kind load docker-image app:v2 --name "${CLUSTER_NAME}"
kind load docker-image remediator:v1 --name "${CLUSTER_NAME}"

echo "=== [6/8] Deploying In-Cluster Git Server & Seeding Repository ==="
kubectl apply -f "${ROOT_DIR}/git-server/manifests/git-server.yaml"
kubectl wait --for=condition=available --timeout=60s deployment/git-server -n gitops

# Initialize and push workspace code to in-cluster git server via port 30080
TMP_GIT_DIR=$(mktemp -d)
cd "${TMP_GIT_DIR}"
git init -b main
GIT_USER_NAME="$(git config user.name 2>/dev/null || echo 'Platform Engineer')"
GIT_USER_EMAIL="$(git config user.email 2>/dev/null || echo 'platform-team@local')"
git config user.name "${GIT_USER_NAME}"
git config user.email "${GIT_USER_EMAIL}"
cp -r "${ROOT_DIR}/charts" .
cp -r "${ROOT_DIR}/gitops" .
cp -r "${ROOT_DIR}/remediator" .
git add .
git commit -m "Initial GitOps repository seed: v1.0.0"

# Allow up to 10 retries for git-server port to respond
MAX_RETRIES=10
for i in $(seq 1 $MAX_RETRIES); do
  if git push --set-upstream "git://127.0.0.1:30080/repo.git" main --force; then
    echo "Git repository seeded successfully."
    break
  fi
  echo "Retrying git push ($i/$MAX_RETRIES)..."
  sleep 3
done
rm -rf "${TMP_GIT_DIR}"

echo "=== [7/8] Configuring ArgoCD Credentials & Secrets ==="
ARGOCD_ADMIN_PASS=$(kubectl -n argocd get secret argocd-initial-admin-secret -o jsonpath="{.data.password}" | base64 -d)
echo "ArgoCD admin password extracted."

kubectl create secret generic remediator-argocd-secret \
  --namespace default \
  --from-literal=password="${ARGOCD_ADMIN_PASS}" \
  --dry-run=client -o yaml | kubectl apply -f -

# Deploy PrometheusRule
kubectl apply -f "${ROOT_DIR}/monitoring/alert-rules.yaml"

echo "=== [8/8] Deploying GitOps Workloads ==="
kubectl apply -f "${ROOT_DIR}/gitops/app-production.yaml"
kubectl apply -f "${ROOT_DIR}/gitops/remediator-application.yaml"

echo "Waiting for production microservice and remediator deployments..."
# Wait for pods
kubectl wait --for=condition=available --timeout=120s deployment/gitops-microservice -n production || true
kubectl wait --for=condition=available --timeout=120s deployment/remediator -n default || true

echo "=== BOOTSTRAP COMPLETE ==="
echo "ArgoCD UI:      http://localhost:8080 (admin / ${ARGOCD_ADMIN_PASS})"
echo "App Production: http://localhost:8000"
echo "Prometheus:     http://localhost:9090"
echo "Alertmanager:   http://localhost:9093"
