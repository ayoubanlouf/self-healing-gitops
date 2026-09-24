#!/usr/bin/env bash
set -euo pipefail

# Kill any existing port-forwards
pkill -f "kubectl port-forward" || true
sleep 1

echo "Starting port-forwards to 0.0.0.0..."
nohup kubectl port-forward --address 0.0.0.0 svc/argocd-server -n argocd 8080:80 > /tmp/pf-argocd.log 2>&1 &
nohup kubectl port-forward --address 0.0.0.0 svc/prometheus-stack-kube-prom-prometheus -n monitoring 9090:9090 > /tmp/pf-prom.log 2>&1 &
nohup kubectl port-forward --address 0.0.0.0 svc/prometheus-stack-kube-prom-alertmanager -n monitoring 9093:9093 > /tmp/pf-alertmanager.log 2>&1 &
nohup kubectl port-forward --address 0.0.0.0 svc/gitops-microservice -n production 8000:80 > /tmp/pf-app.log 2>&1 &

sleep 3
echo "Port-forwards started."
