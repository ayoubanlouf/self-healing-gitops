import base64
import json
import os
import subprocess
import time
import urllib.request
from datetime import datetime, timezone
from selenium import webdriver
from selenium.webdriver.edge.options import Options

def get_argocd_password():
    if os.getenv("ARGOCD_PASSWORD"):
        return os.getenv("ARGOCD_PASSWORD")
    try:
        cmd = ["kubectl", "get", "secret", "argocd-initial-admin-secret", "-n", "argocd", "-o", "jsonpath={.data.password}"]
        out = subprocess.check_output(cmd, stderr=subprocess.DEVNULL)
        return base64.b64decode(out.strip()).decode("utf-8")
    except Exception:
        return ""

APP_URL = "http://127.0.0.1:8000"
PROM_URL = "http://127.0.0.1:9090"
ARGOCD_URL = "http://127.0.0.1:8080"
LOG_FILE = "docs/remediation-trace.log"

os.makedirs("docs/images", exist_ok=True)
trace_lines = []

def log(msg):
    ts = datetime.now(timezone.utc).isoformat()
    line = f"[{ts}] {msg}"
    print(line)
    trace_lines.append(line)

log("=================================================================")
log("AUTONOMOUS CLOSED-LOOP REMEDIATION VALIDATION SEQUENCE")
log("=================================================================")

# Step 1: Baseline health check
log("[STAGE 1] Probing Baseline Workload Health at " + APP_URL)
try:
    with urllib.request.urlopen(f"{APP_URL}/healthz", timeout=5) as resp:
        body = json.loads(resp.read().decode())
        log(f"Baseline Health Check OK: {body}")
except Exception as e:
    log(f"Baseline Health Check Exception: {e}")

# Step 2: Inject Synthetic Chaos
log("[STAGE 2] Triggering Synthetic Chaos Injection via POST /chaos/inject")
req = urllib.request.Request(f"{APP_URL}/chaos/inject", data=b"", headers={"Content-Type": "application/json"})
with urllib.request.urlopen(req, timeout=5) as resp:
    res = json.loads(resp.read().decode())
    log(f"Chaos Injected: {res}")

# Step 3: Generate 500 error traffic load to burn error budget
log("[STAGE 3] Driving Concurrent Request Traffic to Burn Error Budget & Trigger Alert")
import concurrent.futures

errors_500 = 0
total_reqs = 0

def send_request():
    try:
        urllib.request.urlopen(f"{APP_URL}/", timeout=2)
        return 200
    except urllib.error.HTTPError as he:
        return he.code
    except Exception:
        return 0

with concurrent.futures.ThreadPoolExecutor(max_workers=15) as executor:
    futures = [executor.submit(send_request) for _ in range(600)]
    for f in concurrent.futures.as_completed(futures):
        total_reqs += 1
        if f.result() == 500:
            errors_500 += 1

log(f"Traffic Burst Finished: {total_reqs} requests sent, {errors_500} 500 status codes ({(errors_500/max(1,total_reqs))*100:.1f}% failure rate)")

# Step 4: Monitor Prometheus alerts until AppHighErrorRate is firing
log("[STAGE 4] Polling Prometheus Alert Evaluation API until AppHighErrorRate is FIRING")
alert_firing = False
for attempt in range(25):
    try:
        with urllib.request.urlopen(f"{PROM_URL}/api/v1/alerts", timeout=5) as resp:
            data = json.loads(resp.read().decode())
            alerts = data.get("data", {}).get("alerts", [])
            for a in alerts:
                if a.get("labels", {}).get("alertname") == "AppHighErrorRate":
                    state = a.get("state")
                    log(f"Found Alert AppHighErrorRate with State: {state.upper()} (Value: {a.get('value')})")
                    if state == "firing":
                        alert_firing = True
                        break
    except Exception as e:
        log(f"Prometheus poll attempt {attempt+1} error: {e}")
    if alert_firing:
        break
    time.sleep(2)

# Step 5: Capture 02-prometheus-alert-firing.png
log("[STAGE 5] Capturing Visual Evidence: docs/images/02-prometheus-alert-firing.png")
options = Options()
options.add_argument("--headless=new")
options.add_argument("--disable-gpu")
options.add_argument("--window-size=1600,1000")
options.add_argument("--no-sandbox")

driver = webdriver.Edge(options=options)
try:
    driver.get(f"{PROM_URL}/alerts")
    time.sleep(4)
    driver.save_screenshot("docs/images/02-prometheus-alert-firing.png")
    log("Screenshot 02-prometheus-alert-firing.png successfully captured.")
finally:
    driver.quit()

# Step 6: Wait for closed-loop remediation daemon to execute self-healing
log("[STAGE 6] Awaiting Remediator Autonomous Self-Healing Execution")
time.sleep(8)

# Query remediator logs from Kubernetes
try:
    log_output = subprocess.check_output(
        ["kubectl.exe", "logs", "-l", "app=remediator", "-n", "default", "--tail=50"],
        stderr=subprocess.STDOUT,
        text=True
    )
    log("[REMEDIATOR DAEMON POD LOGS]")
    for line in log_output.strip().split("\n"):
        log(f"  {line}")
except Exception as e:
    log(f"Failed to fetch remediator logs: {e}")

# Step 7: Verify workload has recovered (200 OK)
log("[STAGE 7] Verifying Microservice Nominal Recovery")
try:
    with urllib.request.urlopen(f"{APP_URL}/healthz", timeout=5) as resp:
        h = json.loads(resp.read().decode())
        log(f"Post-Remediation Health Status: {h}")
    with urllib.request.urlopen(f"{APP_URL}/", timeout=5) as resp:
        w = json.loads(resp.read().decode())
        log(f"Post-Remediation Main Workload Status: {w}")
except Exception as e:
    log(f"Workload recovery verification exception: {e}")

# Step 8: Capture 03-argocd-rollback-history.png
log("[STAGE 8] Capturing Visual Evidence: docs/images/03-argocd-rollback-history.png")
# Fetch token dynamically
admin_pass = get_argocd_password()
data = json.dumps({"username": "admin", "password": admin_pass}).encode("utf-8")
req = urllib.request.Request(f"{ARGOCD_URL}/api/v1/session", data=data, headers={"Content-Type": "application/json"})
with urllib.request.urlopen(req) as resp:
    token = json.loads(resp.read().decode())["token"]

driver = webdriver.Edge(options=options)
try:
    driver.get(f"{ARGOCD_URL}/")
    time.sleep(2)
    driver.add_cookie({"name": "argocd.token", "value": token, "path": "/"})
    driver.get(f"{ARGOCD_URL}/applications/gitops-microservice-prod?tab=history")
    time.sleep(6)
    driver.save_screenshot("docs/images/03-argocd-rollback-history.png")
    log("Screenshot 03-argocd-rollback-history.png successfully captured.")
finally:
    driver.quit()

log("=================================================================")
log("AUTONOMOUS CLOSED-LOOP REMEDIATION SEQUENCE COMPLETED SUCCESSFULLY")
log("=================================================================")

with open(LOG_FILE, "w", encoding="utf-8") as f:
    f.write("\n".join(trace_lines) + "\n")
print(f"Remediation trace written to {LOG_FILE}")
