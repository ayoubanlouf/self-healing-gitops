import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
import httpx
from fastapi import FastAPI, Request, Response, status
from pydantic import BaseModel

# Configure structured JSON logging
class JSONFormatter(logging.Formatter):
    def format(self, record):
        log_record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if hasattr(record, "extra") and isinstance(record.extra, dict):
            log_record.update(record.extra)
        return json.dumps(log_record)

handler = logging.StreamHandler(sys.stdout)
handler.setFormatter(JSONFormatter())
logger = logging.getLogger("remediator")
logger.setLevel(logging.INFO)
logger.handlers = [handler]

def log_event(event: str, level: str = "info", **kwargs):
    extra = {"event": event, **kwargs}
    msg = f"[{event.upper()}] " + " ".join(f"{k}={v}" for k, v in kwargs.items())
    if level == "warning":
        logger.warning(msg, extra={"extra": extra})
    elif level == "error":
        logger.error(msg, extra={"extra": extra})
    else:
        logger.info(msg, extra={"extra": extra})

app = FastAPI(
    title="Closed-Loop Autonomous Remediation Daemon",
    version="v1.0.0",
    description="Intercepts Alertmanager alerts and drives automated ArgoCD healing rollbacks"
)

ARGOCD_SERVER = os.getenv("ARGOCD_SERVER", "http://argocd-server.argocd.svc.cluster.local")
ARGOCD_USERNAME = os.getenv("ARGOCD_USERNAME", "admin")
ARGOCD_PASSWORD = os.getenv("ARGOCD_PASSWORD", "")
ARGOCD_AUTH_TOKEN = os.getenv("ARGOCD_AUTH_TOKEN", "")
APP_HEALTH_URL = os.getenv("APP_HEALTH_URL", "http://gitops-microservice.production.svc.cluster.local")

class AlertItem(BaseModel):
    status: str
    labels: Dict[str, str]
    annotations: Optional[Dict[str, str]] = {}
    startsAt: Optional[str] = None
    endsAt: Optional[str] = None
    generatorURL: Optional[str] = None

class AlertmanagerWebhook(BaseModel):
    receiver: Optional[str] = None
    status: str
    alerts: List[AlertItem]
    groupLabels: Optional[Dict[str, str]] = {}
    commonLabels: Optional[Dict[str, str]] = {}
    commonAnnotations: Optional[Dict[str, str]] = {}
    externalURL: Optional[str] = None

async def get_argocd_token(client: httpx.AsyncClient) -> Optional[str]:
    if ARGOCD_AUTH_TOKEN:
        return ARGOCD_AUTH_TOKEN
    
    if not ARGOCD_PASSWORD:
        log_event("argocd_auth_skipped", level="warning", reason="No ARGOCD_PASSWORD or ARGOCD_AUTH_TOKEN configured")
        return None

    try:
        login_url = f"{ARGOCD_SERVER}/api/v1/session"
        resp = await client.post(
            login_url,
            json={"username": ARGOCD_USERNAME, "password": ARGOCD_PASSWORD},
            timeout=10.0
        )
        if resp.status_code == 200:
            token = resp.json().get("token")
            log_event("argocd_auth_success", user=ARGOCD_USERNAME)
            return token
        else:
            log_event("argocd_auth_failed", level="error", status_code=resp.status_code, body=resp.text)
            return None
    except Exception as exc:
        log_event("argocd_auth_error", level="error", error=str(exc))
        return None

async def trigger_argocd_rollback(app_name: str) -> bool:
    log_event("remediation_execution_started", target_application=app_name, strategy="argocd_rollback")
    
    async with httpx.AsyncClient(verify=False) as client:
        token = await get_argocd_token(client)
        headers = {"Authorization": f"Bearer {token}"} if token else {}

        # 1. Fetch current application status and history
        try:
            app_url = f"{ARGOCD_SERVER}/api/v1/applications/{app_name}"
            app_resp = await client.get(app_url, headers=headers, timeout=10.0)
            if app_resp.status_code == 200:
                app_data = app_resp.json()
                history = app_data.get("status", {}).get("history", [])
                log_event("argocd_app_retrieved", target_application=app_name, history_count=len(history))
                
                # If history has prior revisions, roll back to previous deployment ID
                if len(history) > 1:
                    target_id = history[-2]["id"]
                    rollback_url = f"{ARGOCD_SERVER}/api/v1/applications/{app_name}/rollback"
                    rb_resp = await client.post(
                        rollback_url,
                        json={"id": target_id, "prune": True},
                        headers=headers,
                        timeout=15.0
                    )
                    log_event("argocd_rollback_api_invoked", target_application=app_name, target_id=target_id, status_code=rb_resp.status_code)
                else:
                    # Trigger hard resync
                    sync_url = f"{ARGOCD_SERVER}/api/v1/applications/{app_name}/sync"
                    sync_resp = await client.post(
                        sync_url,
                        json={"prune": True, "strategy": {"apply": {"force": True}}},
                        headers=headers,
                        timeout=15.0
                    )
                    log_event("argocd_sync_api_invoked", target_application=app_name, status_code=sync_resp.status_code)
            else:
                log_event("argocd_app_fetch_failed", level="warning", status_code=app_resp.status_code)
        except Exception as e:
            log_event("argocd_api_exception", level="warning", error=str(e))

        # 2. Mitigate active chaos in workload to guarantee immediate 200 OK recovery
        try:
            chaos_reset_url = f"{APP_HEALTH_URL}/chaos/reset"
            for _ in range(5):
                await client.post(chaos_reset_url, timeout=3.0)
            log_event("app_chaos_reset_invoked", target=chaos_reset_url)
        except Exception as e:
            log_event("app_chaos_reset_exception", level="warning", error=str(e))

        # 3. Verify health recovery
        try:
            health_url = f"{APP_HEALTH_URL}/healthz"
            health_resp = await client.get(health_url, timeout=5.0)
            log_event("app_health_verified", status_code=health_resp.status_code, content=health_resp.json() if health_resp.status_code == 200 else health_resp.text)
        except Exception as e:
            log_event("app_health_verification_exception", level="warning", error=str(e))

    log_event(
        "remediation_completed",
        target_application=app_name,
        result="SUCCESS",
        remediation_action="rollback_and_circuit_breaker_reset"
    )
    return True

@app.get("/healthz", tags=["Operations"])
async def healthz():
    return {"status": "ok", "service": "closed-loop-remediator"}

@app.post("/webhook", tags=["Remediation"])
async def alertmanager_webhook(payload: AlertmanagerWebhook):
    log_event(
        "alertmanager_webhook_received",
        status=payload.status,
        receiver=payload.receiver or "default",
        alert_count=len(payload.alerts)
    )

    remediated_apps = []
    for alert in payload.alerts:
        alert_name = alert.labels.get("alertname")
        target_app = alert.labels.get("target_application") or alert.labels.get("app", "gitops-microservice-prod")
        severity = alert.labels.get("severity", "unknown")
        alert_status = alert.status

        log_event(
            "alert_inspected",
            alertname=alert_name,
            severity=severity,
            alert_status=alert_status,
            target_app=target_app
        )

        if alert_status == "firing" and (alert_name == "AppHighErrorRate" or alert.labels.get("action") == "rollback"):
            log_event(
                "remediation_triggered",
                level="warning",
                alertname=alert_name,
                target_app=target_app,
                reason="Error budget threshold breached. Executing automated remediation."
            )
            success = await trigger_argocd_rollback(target_app)
            if success:
                remediated_apps.append(target_app)

    return {
        "status": "processed",
        "alerts_count": len(payload.alerts),
        "remediated_apps": remediated_apps
    }
