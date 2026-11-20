#!/usr/bin/env python3
"""Nightly backup of the research library. Run as root by library-backup.timer (01:30 UTC). See README.md beside this file.

1. nightly/<date>/  real copies of what cannot be rebuilt: the findings notebook, Maktaba's databases, the code, tests, logs and
                    typed texts. A file that did not change is a hard link to last night's copy, so a night costs only what changed.
2. guard/           hard links to the big files that never change in place (page scans, search index, page copy). No extra disk.
                    They protect against a mistaken delete only. Nothing is ever removed from guard automatically.
3. off-site         the small irreplaceable part goes to the Modal volume (folder /backup), so it survives the loss of this server.
Result of every run: status/backup.json (health.py reads it and alerts when a run failed or is too old).
"""
import os, re, sys, json, time, shutil, sqlite3, hashlib, subprocess, datetime

HOME = os.environ.get("LIB_HOME") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))     # this file sits in <home>/backups
USER = os.environ.get("LIB_USER") or __import__("pwd").getpwuid(os.stat(HOME).st_uid).pw_name
BASE = HOME + "/backups"; NIGHTLY = BASE + "/nightly"; GUARD = BASE + "/guard"; STATUS = BASE + "/status"
KEEP = 14; KEEP_MONTHLY = 6
SQLITE = [("notebook/findings.sqlite3", HOME + "/semsearch/findings/findings.sqlite3", False),
          ("maktaba/library.db", HOME + "/library/library.db", True),          # True = stored compressed (.zst)
          ("maktaba/links.db", HOME + "/library/links.db", False)]
TREES = [("semsearch", HOME + "/semsearch/", ["--max-size=20M", "--exclude=/data/", "--exclude=/data_maktaba/", "--exclude=/pages/pages.sqlite3*",
                                               "--exclude=/venv/", "--exclude=__pycache__/", "--exclude=*.i8", "--exclude=*.npy", "--exclude=/findings/"]),
         ("library", HOME + "/library/", ["--max-size=20M", "--exclude=/ocr/", "--exclude=/cand/", "--exclude=/maktaba-venv/", "--exclude=/incoming/",
                                          "--exclude=/library.db*", "--exclude=/links.db*", "--exclude=__pycache__/"])]
FILES = ["/etc/systemd/system/maktaba.service", "/etc/systemd/system/shamela-sem.service", "/etc/systemd/system/library-backup.service",
         "/etc/systemd/system/library-backup.timer", "/etc/systemd/system/server-health.service", "/etc/systemd/system/server-health.timer",
         BASE + "/backup.py", BASE + "/health.py", BASE + "/health.json", BASE + "/README.md"]
SECRETS = ["/etc/maktaba.env", HOME + "/isync/Caddyfile"]                      # kept root-only, never sent off-site (the Caddyfile can hold access keys)
GUARDED = [("library-ocr", HOME + "/library/ocr/", []), ("library-cand", HOME + "/library/cand/", []), ("library-incoming", HOME + "/library/incoming/", []),
           ("search-index", HOME + "/semsearch/data/", []), ("search-index-maktaba", HOME + "/semsearch/data_maktaba/", []),
           ("page-copy", HOME + "/semsearch/pages/", ["--include=pages.sqlite3", "--exclude=*"])]
MODAL = HOME + "/modal-venv/bin/modal"; VOLUME = "shamela-sem"; REMOTE = "/backup"; OFFSITE_MAX = 300 * 1024 * 1024; KEEP_REMOTE_DB = 2
DAY = re.compile(r"^\d{4}-\d{2}-\d{2}$")
errors = []; notes = []


def now(): return datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")


def sh(cmd, timeout=3600, user=None):
    if user: cmd = ["sudo", "-u", user, "-H"] + cmd
    p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=timeout)
    return p.returncode, p.stdout, p.stderr


def sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""): h.update(b)
    return h.hexdigest()


def tree_bytes(path):
    """(bytes, files) really used by a folder, counting a hard-linked file once."""
    seen = set(); n = 0; files = 0
    for d, _, fs in os.walk(path):
        for f in fs:
            try: st = os.lstat(os.path.join(d, f))
            except OSError: continue
            files += 1
            if st.st_ino not in seen: seen.add(st.st_ino); n += st.st_size
    return n, files


def sqlite_copy(src, dst):
    a = sqlite3.connect("file:%s?mode=ro" % src, uri=True, timeout=120); b = sqlite3.connect(dst)
    try:
        with b: a.backup(b)
        return b.execute("PRAGMA integrity_check").fetchone()[0]
    finally: b.close(); a.close()


def export_notebook(db, out):
    con = sqlite3.connect("file:%s?mode=ro" % db, uri=True); con.row_factory = sqlite3.Row
    try:
        rows = [dict(r) for r in con.execute("SELECT * FROM findings ORDER BY id")]
        try: tags = [dict(r) for r in con.execute("SELECT * FROM tags")]
        except sqlite3.Error: tags = []
    finally: con.close()
    with open(out, "w", encoding="utf-8") as f: json.dump({"findings": rows, "tags": tags}, f, ensure_ascii=False, indent=1)
    return len(rows)


def snapshots():
    return sorted(d for d in os.listdir(NIGHTLY) if DAY.match(d) and os.path.isdir(os.path.join(NIGHTLY, d))) if os.path.isdir(NIGHTLY) else []


def make_snapshot(today):
    prev = snapshots(); prev = os.path.join(NIGHTLY, prev[-1]) if prev else None
    work = os.path.join(NIGHTLY, ".work-" + today)
    if os.path.exists(work): shutil.rmtree(work)
    os.makedirs(work); out = {"databases": {}, "trees": {}}
    for rel, src, compress in SQLITE:
        dst = os.path.join(work, rel); os.makedirs(os.path.dirname(dst), exist_ok=True)
        if not os.path.exists(src): errors.append("missing: " + src); continue
        try:
            ok = sqlite_copy(src, dst)
            if ok != "ok": errors.append("%s failed its integrity check: %s" % (rel, ok)); continue
            h = sha(dst); size = os.path.getsize(dst); stored = dst + (".zst" if compress else ""); same = False
            if prev:
                ph = os.path.join(prev, rel + ".sha256"); pf = os.path.join(prev, rel + (".zst" if compress else ""))
                if os.path.exists(ph) and os.path.exists(pf) and open(ph).read().strip() == h:
                    os.remove(dst); os.link(pf, stored); same = True
            if not same and compress:
                c, _, e = sh(["zstd", "-q", "-T2", "-6", "--rm", dst, "-o", stored])
                if c != 0: errors.append("zstd failed on %s: %s" % (rel, e[:200])); continue
            open(dst + ".sha256", "w").write(h + "\n")
            out["databases"][rel] = {"bytes": size, "stored_bytes": os.path.getsize(stored), "sha256": h, "unchanged_since_last_backup": same}
        except Exception as e: errors.append("%s: %r" % (rel, e))
    nb = os.path.join(work, "notebook/findings.sqlite3")
    if os.path.exists(nb):
        try: out["findings"] = export_notebook(nb, os.path.join(work, "notebook/findings.json"))
        except Exception as e: errors.append("notebook export: %r" % e)
    for name, src, opts in TREES:
        dst = os.path.join(work, name) + "/"; cmd = ["rsync", "-a"] + opts
        if prev and os.path.isdir(os.path.join(prev, name)): cmd.append("--link-dest=" + os.path.join(prev, name) + "/")
        c, _, e = sh(cmd + [src, dst])
        if c not in (0, 24): errors.append("rsync %s ended with code %d: %s" % (name, c, e[-300:]))     # 24 = a file vanished while copying
        out["trees"][name] = sum(len(fs) for _, _, fs in os.walk(dst))
    sysd = os.path.join(work, "system"); os.makedirs(sysd)
    for f in FILES:
        if os.path.exists(f): shutil.copy2(f, os.path.join(sysd, f.strip("/").replace("/", "__")))
    sec = os.path.join(work, "secrets"); os.makedirs(sec); os.chmod(sec, 0o700)
    for f in SECRETS:
        if os.path.exists(f):
            d = os.path.join(sec, f.strip("/").replace("/", "__")); shutil.copy2(f, d); os.chmod(d, 0o600)
    final = os.path.join(NIGHTLY, today)
    if os.path.exists(final):
        old = os.path.join(NIGHTLY, ".old-" + today)
        if os.path.exists(old): shutil.rmtree(old)
        os.rename(final, old); os.rename(work, final); shutil.rmtree(old)
    else: os.rename(work, final)
    return final, out


def prune():
    all_ = snapshots(); keep = set(all_[-KEEP:]) | set([d for d in all_ if d.endswith("-01")][-KEEP_MONTHLY:]); gone = []
    for d in all_:
        if d not in keep: shutil.rmtree(os.path.join(NIGHTLY, d)); gone.append(d)
    for d in os.listdir(NIGHTLY):
        if d.startswith(".work-") or d.startswith(".old-"): shutil.rmtree(os.path.join(NIGHTLY, d), ignore_errors=True)
    return sorted(keep), gone


def guard():
    out = {}
    for name, src, opts in GUARDED:
        if not os.path.isdir(src): notes.append("guard: %s is not there, skipped" % src); continue
        dst = os.path.join(GUARD, name) + "/"; os.makedirs(dst, exist_ok=True)
        c, _, e = sh(["rsync", "-a", "--link-dest=" + src] + opts + [src, dst])
        if c not in (0, 24): errors.append("guard %s: rsync code %d: %s" % (name, c, e[-300:]))
        linked = orphan = stale = 0; nl = 0
        for d, _, fs in os.walk(dst):
            for f in fs:
                g = os.path.join(d, f); live = os.path.join(src, os.path.relpath(g, dst))
                try:
                    sg = os.lstat(g)
                    if not os.path.lexists(live): orphan += sg.st_size
                    elif os.lstat(live).st_ino == sg.st_ino: linked += sg.st_size; nl += 1
                    else: stale += sg.st_size
                except OSError: pass
        out[name] = {"files_linked": nl, "gb_linked": round(linked / 1e9, 2), "gb_only_in_guard": round(orphan / 1e9, 2), "gb_older_version": round(stale / 1e9, 2)}
    return out


def remote_names():
    c, o, _ = sh([MODAL, "volume", "ls", "--json", VOLUME, REMOTE], timeout=300, user=USER)
    if c != 0 or not o.strip(): return []
    try: return sorted(os.path.basename(str(x.get("filename") or x.get("Filename") or "")) for x in json.loads(o))
    except Exception: return []


STATIC = {"search-index": (HOME + "/semsearch/data", "/serve")}      # big sets that do not change: sent to Modal once, by hand


def _sizes(src): return {os.path.relpath(os.path.join(d, f), src): os.path.getsize(os.path.join(d, f)) for d, _, fs in os.walk(src) for f in fs}


def send_static(name):
    """backup.py --send search-index : copy a big unchanging set to Modal and remember what was sent."""
    src, remote = STATIC[name]
    c, _, e = sh([MODAL, "volume", "put", "--force", VOLUME, src, remote], timeout=7200, user=USER)
    if c != 0: print("modal put failed:", e[-300:]); return 1
    os.makedirs(STATUS, exist_ok=True)
    with open(os.path.join(STATUS, "offsite-%s.json" % name), "w") as f: json.dump({"sent_utc": now(), "remote": "modal volume %s:%s" % (VOLUME, remote), "files": _sizes(src)}, f, indent=1)
    print("sent", name, "to", remote); return 0


def static_check():
    """For each set sent once: do the files here still match what was sent (name and size, files over 1 MB)? If not, the run reports it."""
    out = {}; big = lambda d: {k: v for k, v in d.items() if v > 1 << 20}
    for name, (src, remote) in STATIC.items():
        mf = os.path.join(STATUS, "offsite-%s.json" % name)
        if not os.path.exists(mf): continue
        try:
            sent = json.load(open(mf)); same = big(_sizes(src)) == big(sent.get("files", {}))
            out[name] = {"sent_utc": sent.get("sent_utc"), "where": sent.get("remote"), "still_the_same_files": same}
            if not same: errors.append("the %s changed since its copy went to Modal on %s; send it again: sudo python3 backup.py --send %s" % (name, sent.get("sent_utc"), name))
        except Exception as e: notes.append("static check %s: %r" % (name, e))
    return out


def offsite(snap, today, dbs):
    """The small irreplaceable part goes to the Modal volume. No secrets. library.db is sent only when it changed."""
    if not os.path.exists(MODAL): return {"ok": False, "why": "modal CLI not found"}
    tar = os.path.join(STATUS, "small-%s.tar.zst" % today); res = {}
    try:
        c, _, e = sh(["tar", "--zstd", "-C", snap, "-cf", tar, "--exclude=semsearch/proto", "--exclude=semsearch/mk", "--exclude=semsearch/backup",
                      "--exclude=semsearch/new*", "--exclude=*.log", "notebook", "semsearch", "library/maktaba", "library/books.json", "maktaba/links.db", "system"])
        if c != 0: return {"ok": False, "why": "tar: " + e[-200:]}
        size = os.path.getsize(tar); res["small_archive_mb"] = round(size / 1e6, 1)
        if size > OFFSITE_MAX: return dict(res, ok=False, why="the small archive is over the %d MB cap; not sent" % (OFFSITE_MAX >> 20))
        shutil.chown(tar, USER)
        c, _, e = sh([MODAL, "volume", "put", "--force", VOLUME, tar, "%s/small-%s.tar.zst" % (REMOTE, today)], timeout=1500, user=USER)
        if c != 0: return dict(res, ok=False, why="modal put: " + e[-300:])
        names = remote_names(); lib = dbs.get("maktaba/library.db"); zst = os.path.join(snap, "maktaba/library.db.zst")
        if lib and os.path.exists(zst):
            tail = "library-db-%s.zst" % lib["sha256"][:12]
            if not any(n.endswith(tail) for n in names):
                c, _, e = sh([MODAL, "volume", "put", "--force", VOLUME, zst, "%s/%s_%s" % (REMOTE, today, tail)], timeout=3000, user=USER)
                if c != 0: return dict(res, ok=False, why="modal put library.db: " + e[-300:])
                res["library_db_sent_mb"] = round(os.path.getsize(zst) / 1e6, 1); names.append("%s_%s" % (today, tail))
        small = sorted(n for n in names if n.startswith("small-")); libs = sorted(n for n in names if "_library-db-" in n)
        for n in small[:-KEEP] + libs[:-KEEP_REMOTE_DB]:
            sh([MODAL, "volume", "rm", VOLUME, "%s/%s" % (REMOTE, n)], timeout=300, user=USER)
        return dict(res, ok=True, on_modal={"small": len(small[-KEEP:]), "library_db": len(libs[-KEEP_REMOTE_DB:])})
    finally:
        try: os.remove(tar)
        except OSError: pass


def main():
    t0 = time.time(); today = datetime.datetime.utcnow().strftime("%Y-%m-%d"); os.makedirs(NIGHTLY, exist_ok=True); os.makedirs(STATUS, exist_ok=True)
    prev = {}
    try: prev = json.load(open(os.path.join(STATUS, "backup.json")))
    except Exception: pass
    st = {"started_utc": now(), "ok": False}
    try:
        snap, out = make_snapshot(today); st.update(out); st["snapshot"] = snap
        was = prev.get("findings")
        if isinstance(was, int) and isinstance(out.get("findings"), int) and out["findings"] < was:
            errors.append("the notebook has FEWER findings than at the last backup (%d, was %d); older copies are in nightly/" % (out["findings"], was))
        st["kept"], st["removed"] = prune()
        st["guard"] = guard()
        st["sent_once"] = static_check()
        if "--no-offsite" in sys.argv: st["offsite"] = {"ok": None, "why": "skipped by --no-offsite"}
        else:
            try: st["offsite"] = offsite(snap, today, out.get("databases", {}))
            except Exception as e: st["offsite"] = {"ok": False, "why": repr(e)[:300]}
        if st["offsite"].get("ok"): st["offsite_ok_utc"] = now(); st["offsite_ok_epoch"] = int(time.time())
        else:
            for k in ("offsite_ok_utc", "offsite_ok_epoch"):
                if prev.get(k): st[k] = prev[k]
        b, f = tree_bytes(NIGHTLY); st["nightly_gb_on_disk"] = round(b / 1e9, 2); st["nightly_files"] = f
    except Exception as e: errors.append("backup stopped: %r" % e)
    st["errors"] = errors; st["notes"] = notes; st["ok"] = not errors; st["seconds"] = round(time.time() - t0)
    st["finished_utc"] = now(); st["finished_epoch"] = int(time.time())
    tmp = os.path.join(STATUS, "backup.json.tmp")
    with open(tmp, "w", encoding="utf-8") as f: json.dump(st, f, ensure_ascii=False, indent=1)
    os.replace(tmp, os.path.join(STATUS, "backup.json"))
    print(json.dumps({k: st[k] for k in ("ok", "errors", "seconds", "findings", "nightly_gb_on_disk", "offsite") if k in st}, ensure_ascii=False))
    return 0 if st["ok"] else 1


if __name__ == "__main__":
    if "--send" in sys.argv: sys.exit(send_static(sys.argv[sys.argv.index("--send") + 1]))
    sys.exit(main())
