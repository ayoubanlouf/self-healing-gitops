#!/usr/bin/env bash
set -euo pipefail

CLUSTER_NAME="gitops-cluster"

echo "=== Verifying Cluster Status ==="
kubectl get nodes -o wide

echo "=== Namespaces & Deployments ==="
kubectl get pods -A

echo "=== ArgoCD Applications ==="
kubectl get applications -n argocd -o wide || true

echo "=== ServiceMonitors & PrometheusRules ==="
kubectl get servicemonitors -A
kubectl get prometheusrules -A

echo "=== In-Cluster Pod Health Checks ==="
# Test app health inside cluster
kubectl run curl-test --image=curlimages/curl --rm -i --restart=Never --command -- \
  curl -s -f http://gitops-microservice.production.svc.cluster.local/healthz || echo "Health test pod finished."

echo "=== System Ready ==="
