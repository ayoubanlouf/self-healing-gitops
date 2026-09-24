#!/usr/bin/env bash
set -euo pipefail

kubectl -n argocd patch configmap argocd-cmd-params-cm --type merge -p '{"data":{"server.insecure":"true"}}'
kubectl -n argocd rollout restart deployment argocd-server
echo "ArgoCD patched with server.insecure=true"
