#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

echo "Extracting ArgoCD admin password..."
ARGOCD_ADMIN_PASS=$(kubectl -n argocd get secret argocd-initial-admin-secret -o jsonpath="{.data.password}" | base64 -d)
echo "ArgoCD admin password: ${ARGOCD_ADMIN_PASS}"

echo "Creating remediator secret in default namespace..."
kubectl create secret generic remediator-argocd-secret \
  --namespace default \
  --from-literal=password="${ARGOCD_ADMIN_PASS}" \
  --dry-run=client -o yaml | kubectl apply -f -

echo "Deploying Prometheus alert rules..."
kubectl apply -f "${ROOT_DIR}/monitoring/alert-rules.yaml"

echo "Deploying remediator daemon..."
kubectl apply -f "${ROOT_DIR}/remediator/manifests/service.yaml"
kubectl apply -f "${ROOT_DIR}/remediator/manifests/deployment.yaml"

echo "Deploying production namespace..."
kubectl create namespace production --dry-run=client -o yaml | kubectl apply -f -

echo "Applying ArgoCD application manifests..."
kubectl apply -f "${ROOT_DIR}/gitops/app-production.yaml"
kubectl apply -f "${ROOT_DIR}/gitops/remediator-application.yaml"

echo "Waiting for remediator pod..."
kubectl wait --for=condition=available --timeout=120s deployment/remediator -n default

echo "Checking ArgoCD applications status..."
kubectl get applications -n argocd
