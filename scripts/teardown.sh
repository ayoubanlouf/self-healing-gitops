#!/usr/bin/env bash
set -euo pipefail

CLUSTER_NAME="gitops-cluster"

echo "=== Tearing down background port-forwards ==="
pkill -f "kubectl port-forward" || true

echo "=== Deleting Kind Cluster: ${CLUSTER_NAME} ==="
kind delete cluster --name "${CLUSTER_NAME}"

echo "=== Teardown Complete ==="
