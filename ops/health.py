#!/usr/bin/env python3
"""Server watch: disk, services, backups. Run as root every 10 minutes by server-health.timer. See README.md beside this file.

It writes status/health.json every run. It SENDS a message only when something changes: a new problem, a problem getting worse,
a problem fixed; plus one reminder a day while a problem stays, and one short "all fine" note a week so silence can be trusted.
Messages go to ALERTS.log and, when ~/.config/library-alert.env holds NTFY_URL=..., to the phone through ntfy.
    health.py --show   print the current state         health.py --test   send a test message
Settings (limits, which services to watch): health.json beside this file.
"""
import os, sys, json, time, socket, shutil, subprocess, datetime, urllib.request

BASE = os.path.dirname(os.path.abspath(__file__)); STATUS = BASE + "/status"; LOG = BASE + "/ALERTS.log"; ENV = os.environ.get("ALERT_ENV") or os.path.join(os.path.dirname(BASE), ".config", "library-alert.env")
DEFAULT = {"disk_warn": 85, "disk_critical": 92, "growth_gb_per_hour": 8, "systemd": ["shamela-sem", "maktaba"],
           "containers": [], "http": [["meaning-search", "http://127.0.0.1:8791/health", "\"loaded\":true"]],
           "tcp": [["maktaba connector", "127.0.0.1", 8790]], "backup_max_age_hours": 30, "offsite_max_age_days": 3, "remind_hours": 24,
           "confirm_runs": 2, "heartbeat_weekday": 6, "heartbeat_hour_utc": 7}
RANK = {"warn": 1, "critical": 2}


def cfg():
    c = dict(DEFAULT)
    try: c.update(json.load(open(BASE + "/health.json")))
    except Exception: pass
    return c


def sh(cmd, timeout=20):
    try:
        p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=timeout); return p.returncode, p.stdout.strip()
    except Exception as e: return 99, repr(e)


def load(name, d):
    try: return json.load(open(os.path.join(STATUS, name)))
    except Exception: return d


def save(name, obj):
    os.makedirs(STATUS, exist_ok=True); tmp = os.path.join(STATUS, name + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f: json.dump(obj, f, ensure_ascii=False, indent=1)
    os.replace(tmp, os.path.join(STATUS, name))


def ntfy_url():
    try:
        for line in open(ENV):
            if line.strip().startswith("NTFY_URL="): return line.strip().split("=", 1)[1].strip().strip('"') or None
    except Exception: pass
    return None


def send(title, body, priority="default", tags="computer"):
    """Log always; push when ntfy is set up. Returns 'pushed', 'push failed: ...' or 'logged only'."""
    how = "logged only"; url = None if os.environ.get("HEALTH_NO_PUSH") else ntfy_url()     # HEALTH_NO_PUSH=1: for trying things out
    if url:
        try:
            r = urllib.request.Request(url, data=body.encode("utf-8"), headers={"Title": title, "Priority": priority, "Tags": tags})
            urllib.request.urlopen(r, timeout=20).read(); how = "pushed"
        except Exception as e: how = "push failed: %r" % (e,)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write("%s UTC | %s | %s | %s\n" % (datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M"), how[:80], title, body.replace("\n", " / ")))
    return how


def check(c):
    """-> (facts, problems). problems: {key: (severity, message, needs_confirming)}"""
    P = {}; F = {}; now = int(time.time())
    du = shutil.disk_usage("/"); pct = 100.0 * du.used / (du.used + du.free); free = du.free / 1e9     # same figure as df shows
    F["disk_percent"] = round(pct, 1); F["disk_free_gb"] = round(free, 1)
    if pct >= c["disk_critical"]: P["disk"] = ("critical", "Disk is %.0f%% full, only %.0f GB free. Things start to break near 100%%." % (pct, free), False)
    elif pct >= c["disk_warn"]: P["disk"] = ("warn", "Disk is %.0f%% full, %.0f GB free." % (pct, free), False)
    hist = [h for h in load("disk_history.json", []) if now - h[0] <= 4500] + [[now, du.used]]; save("disk_history.json", hist)
    old = [h for h in hist if 3000 <= now - h[0] <= 4500]
    if old:
        grew = (du.used - old[0][1]) / 1e9; F["disk_growth_gb_last_hour"] = round(grew, 1)
        if grew >= c["growth_gb_per_hour"]: P["growth"] = ("warn", "Disk use grew by %.0f GB in the last hour. Something is writing fast." % grew, False)
    F["services"] = {}
    for s in c["systemd"]:
        code, out = sh(["systemctl", "is-active", s]); F["services"][s] = out
        if out != "active": P["svc:" + s] = ("critical", "Service %s is %s." % (s, out or "not running"), True)
    for name in c["containers"]:
        code, out = sh(["docker", "inspect", "-f", "{{.State.Status}} {{if .State.Health}}{{.State.Health.Status}}{{end}}", name]); F["services"][name] = out if code == 0 else "missing"
        if code != 0: P["ctr:" + name] = ("critical", "Container %s is missing." % name, True)
        elif not out.startswith("running"): P["ctr:" + name] = ("critical", "Container %s is %s." % (name, out), True)
        elif "unhealthy" in out: P["ctr:" + name] = ("warn", "Container %s runs but reports unhealthy." % name, True)
    for name, url, must in c["http"]:
        try: body = urllib.request.urlopen(url, timeout=10).read().decode("utf-8", "replace"); ok = must in body.replace(" ", "")
        except Exception: ok = False
        F["services"][name] = "ok" if ok else "not answering"
        if not ok: P["http:" + name] = ("critical", "The %s does not answer." % name, True)
    for name, host, port in c["tcp"]:
        try: socket.create_connection((host, port), timeout=5).close(); ok = True
        except Exception: ok = False
        F["services"][name] = "ok" if ok else "not answering"
        if not ok: P["tcp:" + name] = ("critical", "The %s does not answer." % name, True)
    b = load("backup.json", None)
    if b is None: F["backup"] = "no backup has run yet"
    else:
        age = (now - int(b.get("finished_epoch") or 0)) / 3600.0; F["backup"] = {"finished_utc": b.get("finished_utc"), "ok": b.get("ok"), "age_hours": round(age, 1)}
        if not b.get("ok"): P["backup"] = ("warn", "Last night's backup had errors: %s" % "; ".join(b.get("errors") or ["unknown"])[:300], False)
        elif age > c["backup_max_age_hours"]: P["backup"] = ("warn", "No backup for %.0f hours." % age, False)
        off = b.get("offsite_ok_epoch")
        if off is None or (now - int(off)) / 86400.0 > c["offsite_max_age_days"]:
            why = (b.get("offsite") or {}).get("why") or ""
            P["offsite"] = ("warn", "The copy outside the server has not worked for %s. %s" % ("%.0f days" % ((now - int(off)) / 86400.0) if off else "any run yet", why[:200]), False)
        orphan = sum((g.get("gb_only_in_guard") or 0) + (g.get("gb_older_version") or 0) for g in (b.get("guard") or {}).values()); F["guard_extra_gb"] = round(orphan, 1)
    return F, P


def main():
    c = cfg(); now = int(time.time())
    if "--test" in sys.argv:
        print(send("Test from your server", "If you read this on your phone, alerts work.", "default", "white_check_mark")); return 0
    F, P = check(c); st = load("health_state.json", {"problems": {}, "pending": {}, "last_sent": 0, "heartbeat_week": ""})
    pending = {}; live = {}
    for k, (sev, msg, confirm) in P.items():
        n = int(st.get("pending", {}).get(k, 0)) + 1; pending[k] = n
        if not confirm or n >= c["confirm_runs"] or k in st.get("problems", {}): live[k] = {"sev": sev, "msg": msg, "since": st.get("problems", {}).get(k, {}).get("since", now)}
    was = st.get("problems", {}); new = [k for k in live if k not in was]; worse = [k for k in live if k in was and RANK[live[k]["sev"]] > RANK[was[k]["sev"]]]
    fixed = [k for k in was if k not in live]; sent = None
    if new or worse:
        crit = any(live[k]["sev"] == "critical" for k in live)
        sent = send("Server PROBLEM" if crit else "Server warning", "\n".join(live[k]["msg"] for k in sorted(live)), "urgent" if crit else "high", "rotating_light" if crit else "warning")
    elif fixed:
        body = "Fixed: " + " ".join(was[k]["msg"] for k in fixed) + ("\nStill open: " + " ".join(live[k]["msg"] for k in sorted(live)) if live else "")
        sent = send("Server: all clear" if not live else "Server: partly fixed", body, "default", "white_check_mark")
    elif live and now - int(st.get("last_sent") or 0) >= c["remind_hours"] * 3600:
        sent = send("Server: still open", "\n".join(live[k]["msg"] for k in sorted(live)), "default", "warning")
    t = datetime.datetime.utcnow(); week = t.strftime("%G-%V")
    if not live and sent is None and t.weekday() == c["heartbeat_weekday"] and t.hour >= c["heartbeat_hour_utc"] and st.get("heartbeat_week") != week:
        bk = F.get("backup"); bk = ("last backup %s UTC, fine" % bk.get("finished_utc")) if isinstance(bk, dict) else str(bk)
        send("Server weekly check: fine", "Disk %s%% full, %s GB free. %s." % (F["disk_percent"], F["disk_free_gb"], bk), "low", "white_check_mark"); st["heartbeat_week"] = week
    st["problems"] = live; st["pending"] = pending
    if sent is not None: st["last_sent"] = now
    save("health_state.json", st)
    F["checked_utc"] = t.strftime("%Y-%m-%d %H:%M:%S"); F["problems"] = {k: v["msg"] for k, v in live.items()}; F["waiting_to_confirm"] = [k for k in pending if k not in live]
    F["phone_push"] = "set up" if ntfy_url() else "not set up (messages go to ALERTS.log only)"; save("health.json", F)
    if "--show" in sys.argv: print(json.dumps(F, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
