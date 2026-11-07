#!/usr/bin/env python3
"""The whole wall display, Mac to screen, against a simulated Pi. Needs Docker.

    python3 apps/wall/sim/test_connection.py            WALL_SIM_RELEASE=trixie picks the Debian release. WALL_SIM_SHOTS=<folder> saves pictures.

Real here: the Mac-side code and the `theseus wall` command, the ssh client, a TCP connection, an SSH server, Linux users and sudo, the real
pi/install.sh with real packages, systemd services and timers, the forced command, the page in real Chromium, and the kiosk in real cage.
Faked here: the hardware. Docker stands in for the Pi, cage draws to a headless output instead of HDMI, and `cec-ctl` is a recording stand-in with a
placeholder /dev/cec0, so no TV is told anything. This says nothing about a real Pi's graphics, a real TV's HDMI behavior, Wi-Fi or `.local` names.
"""
import datetime as dt
import json
import os
import plistlib
import re
import shutil
import socket
import stat
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
RELEASE = os.environ.get("WALL_SIM_RELEASE", "bookworm")
IMAGE = f"theseus-wall-sim:{RELEASE}"
NAME = f"theseus-wall-sim-{RELEASE}-{os.getpid()}"
HOST = "theseus-wall.local"
SHOTS = os.environ.get("WALL_SIM_SHOTS")

MASTER = """# List
## 🔥 NOW
- [ ] Renew the business license · #Work · due 11/5 · id:a1
  a private note under this item
- [ ] Send the signed lease back · #Home · id:a2
- [ ] Ask about the raise · #Payroll · id:a3
- [ ] Email someone@example.com about the plan · #Work · id:a4
- [ ] Order furnace filters · #Home · id:a5

## 💬 COMMUNICATIONS
- [ ] COMMS-CANARY reply to someone · #Work · id:b1

## ⏭ NEXT
- [ ] Compare insurance quotes · #Money · id:c1

## 🗓 LATER
- [ ] Refinish the deck · #Home · id:d1

## ⏳ WAITING ON
- [ ] WAITING-CANARY a named person · #Work · id:e1

## ✅ DONE
- [x] DONE-CANARY old thing · #Work · id:f1
"""

results = []


def check(name, passed, detail=""):
    results.append((name, bool(passed), detail))
    print(("ok    " if passed else "FAIL  ") + name + (f"   [{detail}]" if detail and not passed else ""), flush=True)
    return passed


def section(name):
    print(f"\n== {name}", flush=True)


def run(*args, timeout=120, check_rc=False, **kw):
    p = subprocess.run(args, capture_output=True, text=True, timeout=timeout, **kw)
    if check_rc and p.returncode:
        raise RuntimeError(f"{' '.join(args)}\n{p.stdout}\n{p.stderr}")
    return p


def pi(*args, user=None, timeout=120):
    base = ["docker", "exec"] + (["-u", user] if user else []) + [NAME]
    return run(*base, *args, timeout=timeout)


def pi_sh(script, user=None, timeout=120):
    return pi("bash", "-c", script, user=user, timeout=timeout)


class Sim:
    def __init__(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="wall-sim-"))
        self.ws = self.tmp / "ws"
        (self.ws / "data").mkdir(parents=True)
        (self.ws / "data/master.md").write_text(MASTER)
        (self.ws / "data/today.md").write_text("TODAY-CANARY someone is waiting on you\n")
        (self.ws / "config.json").write_text(json.dumps({"wall": {"titles": False, "private_categories": ["#Payroll"]},
                                                         "schedule": {"groups": [{"days": ["mon", "tue", "wed", "thu", "fri", "sat", "sun"], "wake": "06:00", "bed": "23:00"}], "flex_hours": 1}}))
        (self.ws / "data/wall-views.json").write_text(json.dumps({"active_hours": "always", **self.start_views()}))
        self.bin = self.tmp / "bin"
        self.bin.mkdir()
        self.admin_key = self.tmp / "admin"
        run("ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(self.admin_key), check_rc=True)
        self.port = free_port()
        self.write_shim(self.port)

    @staticmethod
    def start_views():
        sys.path.insert(0, str(ROOT / "engine/tools"))
        sys.dont_write_bytecode = True
        import wall
        return wall.start_views()

    def write_shim(self, port):
        """Only reaches the simulated Pi's port: wall.py always uses port 22 and a .local name. Everything else is the real ssh."""
        shim = self.bin / "ssh"
        shim.write_text(f"""#!/bin/bash
args=(); key=(-i "{self.admin_key}" -o IdentitiesOnly=yes)
for a in "$@"; do
  [[ "$a" == -i ]] && key=()
  args+=("${{a/@{HOST}/@127.0.0.1}}")
done
exec /usr/bin/ssh -F /dev/null -p {port} -o LogLevel=ERROR "${{key[@]}}" "${{args[@]}}"
""")
        shim.chmod(0o755)

    def theseus(self, *args, timeout=120, stdin=""):
        env = {**os.environ, "THESEUS_HOME": str(self.ws), "PATH": f"{self.bin}:{os.environ['PATH']}", "PYTHONDONTWRITEBYTECODE": "1"}
        return subprocess.run([sys.executable, str(ROOT / "engine/tools/cli.py"), *args], capture_output=True, text=True, timeout=timeout, env=env, input=stdin)

    def wall_ssh(self, *args, stdin=None, timeout=30):
        """Using the delivery key directly, to see what it can and can't do."""
        return subprocess.run([str(self.bin / "ssh"), "-i", str(self.ws / ".wall/id_ed25519"), "-o", "IdentitiesOnly=yes", "-o", "BatchMode=yes", "-o", "ConnectTimeout=5",
                               "-o", f"UserKnownHostsFile={self.ws / '.wall/known_hosts'}", "-o", "StrictHostKeyChecking=yes", *args],
                              capture_output=True, input=stdin, timeout=timeout)

    def state(self):
        try:
            return json.loads((self.ws / "data/wall-state.json").read_text())
        except OSError:
            return {}

    def age_heartbeat(self):
        s = self.state()
        s["last_sent"] = s.get("last_sent", time.time()) - 301
        (self.ws / "data/wall-state.json").write_text(json.dumps(s))

    def list_edit(self, old, new):
        path = self.ws / "data/master.md"
        path.write_text(path.read_text().replace(old, new))


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def start_pi(port):
    run("docker", "run", "-d", "--name", NAME, "--hostname", "theseus-wall", "--privileged", "--cgroupns=host", "-v", "/sys/fs/cgroup:/sys/fs/cgroup:rw",
        "--tmpfs", "/run", "--tmpfs", "/run/lock", "-p", f"127.0.0.1:{port}:22", IMAGE, check_rc=True)
    wait_for_pi()


def wait_for_pi():
    for _ in range(90):
        p = pi("systemctl", "is-system-running")
        if p.stdout.strip() in ("running", "degraded"):
            return
        time.sleep(1)
    raise RuntimeError("the simulated Pi didn't finish starting")


def page(query="", shot=None):
    """What real Chromium on the simulated Pi draws from the page its own server serves."""
    profile = f"/tmp/cr-{time.time_ns()}"
    args = ["chromium", "--headless=new", "--no-sandbox", "--disable-gpu", f"--user-data-dir={profile}", "--virtual-time-budget=8000", "--window-size=1920,1080"]
    url = f"http://127.0.0.1:8737/{query}"
    if shot:
        pi("timeout", "90", *args, f"--screenshot=/home/kiosk/{shot}.png", url, user="kiosk", timeout=120)
        save_picture(f"/home/kiosk/{shot}.png", f"{RELEASE}-{shot}.png")
    p = pi("timeout", "90", *args, "--dump-dom", url, user="kiosk", timeout=120)
    pi("rm", "-rf", profile)
    return p.stdout


def save_picture(path, name):
    """Read through the container, because some releases mount their own /tmp, which `docker cp` can't see."""
    if SHOTS:
        p = subprocess.run(["docker", "exec", NAME, "cat", path], capture_output=True)
        if p.returncode == 0:
            (Path(SHOTS) / name).write_bytes(p.stdout)


def text_of(dom):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", re.sub(r"<(script|style)[\s\S]*?</\1>", " ", dom)))


def now_on_pi(minutes=0):
    out = pi("date", "+%Y-%m-%dT%H:%M:%S").stdout.strip()
    return (dt.datetime.fromisoformat(out) + dt.timedelta(minutes=minutes)).isoformat(timespec="seconds")


def wait_until(test, seconds):
    end = time.time() + seconds
    while time.time() < end:
        if test():
            return True
        time.sleep(1)
    return False


def on_pi_json():
    p = pi("cat", "/run/theseus-wall/wall.json")
    return json.loads(p.stdout) if p.returncode == 0 else None


def scenario(sim):
    section("First connect")
    p = sim.theseus("wall", "status")
    check("before setup it says it's off", p.returncode == 0 and "is off" in p.stdout, p.stdout)
    p = sim.theseus("wall", "show")
    check("`wall show` works with no Pi at all", p.returncode == 0 and json.loads(p.stdout)["mode"] == "counts", p.stderr)
    t = time.time()
    p = sim.theseus("wall", "setup", HOST, "--user", "pi", "--no-agent")
    check("setup with the Pi off fails and says what to check", p.returncode != 0 and "ssh pi@" in p.stderr, p.stderr)
    check("and fails quickly", time.time() - t < 30, f"{time.time() - t:.0f}s")
    check("and turns nothing on", json.loads((sim.ws / "config.json").read_text())["wall"].get("enabled") is not True)

    start_pi(sim.port)
    pi_sh(f"mkdir -p /home/pi/.ssh && echo '{(sim.tmp / 'admin.pub').read_text().strip()}' > /home/pi/.ssh/authorized_keys && chown -R pi:pi /home/pi/.ssh && chmod 700 /home/pi/.ssh && chmod 600 /home/pi/.ssh/authorized_keys")
    p = sim.theseus("wall", "setup", HOST, "--user", "pi", "--no-agent", timeout=1200)
    if not check("setup runs the real installer on Debian and succeeds", p.returncode == 0, (p.stdout + p.stderr)[-1500:]):
        return False
    sim.install_output = p.stdout
    check("with nobody to answer, titles stay off", json.loads((sim.ws / "config.json").read_text())["wall"]["titles"] is False)
    snap = on_pi_json()
    check("a first list arrives, without titles", snap and snap["mode"] == "counts" and "Renew" not in json.dumps(snap), str(snap)[:200])
    check("the delivery key's folder is private", stat.S_IMODE((sim.ws / ".wall").stat().st_mode) == 0o700)

    section("What the installer built")
    for unit in ("theseus-wall-web.service", "theseus-wall-power.timer"):
        check(f"{unit} is running", pi("systemctl", "is-active", unit).stdout.strip() == "active")
    check("both accounts exist", pi("id", "wall").returncode == 0 and pi("id", "kiosk").returncode == 0)
    check("the list lives in memory", "tmpfs" in pi("findmnt", "-no", "FSTYPE", "--target", "/run/theseus-wall").stdout)
    check("the delivery account owns it", pi("stat", "-c", "%U", "/run/theseus-wall").stdout.strip() == "wall")
    keyline = pi("cat", "/home/wall/.ssh/authorized_keys").stdout
    check("the Mac's key is limited on the Pi", keyline.startswith('restrict,command="/opt/theseus-wall/pi/receive.py" ssh-ed25519 '), keyline[:80])
    sshd = pi("sshd", "-T").stdout.lower()
    check("password login is off", "passwordauthentication no" in sshd and "kbdinteractiveauthentication no" in sshd)
    listening = pi("ss", "-ltnH").stdout
    check("the page's server listens on the Pi only", "127.0.0.1:8737" in listening and "0.0.0.0:8737" not in listening and "*:8737" not in listening, listening)
    want_tz = os.path.realpath("/etc/localtime").split("/zoneinfo/")[-1]
    if "/zoneinfo/" in os.path.realpath("/etc/localtime"):
        check("the Pi has this Mac's time zone", pi("readlink", "-f", "/etc/localtime").stdout.strip().endswith(want_tz), pi("readlink", "-f", "/etc/localtime").stdout)
    check("logs stay in memory", pi("test", "-f", "/etc/systemd/journald.conf.d/theseus-wall.conf").returncode == 0)
    check("security updates are on", 'Unattended-Upgrade "1"' in pi("cat", "/etc/apt/apt.conf.d/20auto-upgrades").stdout)
    check("the prototypes stayed on the Mac", pi("test", "-e", "/opt/theseus-wall/prototype").returncode != 0)
    p = sim.theseus("wall", "setup", HOST, "--user", "pi", "--no-agent", timeout=600)
    check("running setup a second time is fine", p.returncode == 0, p.stderr[-500:])

    section("What the delivery key can do")
    for attempt in (["cat /etc/passwd"], ["bash"], ["receive; id"], ["scp -t /tmp"]):
        p = sim.wall_ssh(f"wall@{HOST}", *attempt, stdin=b"")
        check(f"refused: {attempt[0]}", p.returncode != 0 and b"root:" not in p.stdout, (p.stdout + p.stderr).decode()[:200])
    local = free_port()
    tunnel = subprocess.Popen([str(sim.bin / "ssh"), "-i", str(sim.ws / ".wall/id_ed25519"), "-o", "IdentitiesOnly=yes", "-o", "BatchMode=yes", "-o", f"UserKnownHostsFile={sim.ws / '.wall/known_hosts'}", "-o", "StrictHostKeyChecking=yes",
                               "-N", "-L", f"{local}:127.0.0.1:8737", f"wall@{HOST}"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(3)
    reached = b""
    try:
        with socket.create_connection(("127.0.0.1", local), 3) as c:
            c.settimeout(3)
            c.sendall(b"GET /wall.json HTTP/1.0\r\n\r\n")
            reached = c.recv(200)
    except OSError:
        pass
    tunnel.kill()
    tunnel.wait()
    check("refused: tunnelling to the page's server", b"HTTP" not in reached, reached.decode(errors="replace"))
    p = sim.wall_ssh(f"pi@{HOST}", "id", stdin=b"")
    check("refused: logging in as the admin account", p.returncode != 0)
    p = subprocess.run(["/usr/bin/ssh", "-F", "/dev/null", "-p", str(sim.port), "-o", "BatchMode=yes", "-o", "ConnectTimeout=5", "-o", "StrictHostKeyChecking=no", "-o", "UserKnownHostsFile=/dev/null", "-o", "PubkeyAuthentication=no", "-o", "LogLevel=ERROR", "wall@127.0.0.1", "id"], capture_output=True)
    check("refused: no key at all", p.returncode != 0)

    section("Updates arriving")
    p = sim.theseus("wall", "titles", "on")
    check("turning titles on says so", p.returncode == 0 and "on" in p.stdout, p.stderr)
    snap = on_pi_json()
    titles = [i["title"] for i in snap["sections"]["now"]["items"]]
    check("titles reach the Pi", titles == ["Renew the business license", "Send the signed lease back", "Order furnace filters"], str(titles))
    blob = json.dumps(snap)
    for canary in ("COMMS-CANARY", "DONE-CANARY", "WAITING-CANARY", "TODAY-CANARY", "private note", "raise", "someone@example.com", "id:a1"):
        check(f"never on the Pi: {canary}", canary not in blob)
    check("nothing personal is on the Pi's disk", pi_sh("grep -rl 'Renew the business' /home /opt /etc /var/lib /var/log /tmp 2>/dev/null | grep -v '^/tmp/cr-'").stdout.strip() == "")
    dom = page(shot="sectors")
    text = text_of(dom)
    check("real Chromium draws the list", "Renew the business license" in text and "Send the signed lease back" in text, text[:300])
    check("grouped by sector", "Home" in text and 'class="sector"' in dom)
    check("a due date from the list shows", "Was due" in text or "Due today" in text or "11/5" in text, text[:300])
    p = sim.theseus("done", "furnace")
    check("a check-off from Terminal", p.returncode == 0, p.stderr)
    p = sim.theseus("wall", "push")
    check("delivers", p.returncode == 0, p.stderr)
    check("and leaves the screen", "Order furnace filters" not in text_of(page()))
    p = sim.theseus("add", "Book the plumber", "--to", "now")
    sim.theseus("wall", "push")
    check("a new task appears", "Book the plumber" in text_of(page()))
    before = pi("stat", "-c", "%Y.%y", "/run/theseus-wall/wall.json").stdout
    time.sleep(1.2)
    sim.theseus("wall", "push")
    check("nothing changed, so nothing is sent", pi("stat", "-c", "%Y.%y", "/run/theseus-wall/wall.json").stdout == before)
    sim.age_heartbeat()
    sim.theseus("wall", "push")
    check("the 5-minute check-in goes out anyway", pi("stat", "-c", "%Y.%y", "/run/theseus-wall/wall.json").stdout != before)
    p = sim.theseus("wall", "view", "board")
    check("changing the view", p.returncode == 0 and on_pi_json()["change"]["active"] == "Board", p.stdout + p.stderr)
    text = text_of(page())
    check("the Pi draws it, with the extra section", "Compare insurance quotes" in text and "Refinish the deck" in text, text[:300])
    p = sim.theseus("wall", "view", "nope")
    check("an unknown view is refused and lists the real ones", p.returncode != 0 and "Sectors" in p.stderr, p.stderr)
    sim.theseus("wall", "view", "sectors")
    p = sim.theseus("wall", "status")
    check("status tells the truth", all(s in p.stdout for s in (HOST, "task titles", "Last delivered", "always on")) and "failed" not in p.stdout, p.stdout)

    section("The Mac going away")
    good = on_pi_json()
    stale = page(f"?now={now_on_pi(10)}")
    check("10 minutes without word looks normal", "This list is from" not in text_of(stale))
    stale = text_of(page(f"?now={now_on_pi(20)}", shot="stale"))
    check("20 minutes without word says so, list still up", "This list is from" in stale and "Your Mac may be asleep" in stale and "Renew the business license" in stale, stale[:300])
    later = text_of(page(f"?now={now_on_pi(60 * 26)}"))
    check("a day later it's still honest", "This list is from" in later, later[:200])

    section("The network or the Pi going away")
    sim.list_edit("Renew the business license", "Renew the business permit")
    run("docker", "pause", NAME, check_rc=True)
    t = time.time()
    p = sim.theseus("wall", "push", timeout=60)
    took = time.time() - t
    run("docker", "unpause", NAME, check_rc=True)
    check("a hung Pi: delivery fails instead of waiting forever", p.returncode != 0 and took < 45, f"rc={p.returncode} {took:.0f}s {p.stderr}")
    check("and says so", "didn't get that" in p.stderr, p.stderr)
    check("status names the failure", "Last try failed" in sim.theseus("wall", "status").stdout)
    check("the Pi still has the last good list", on_pi_json()["sections"] == good["sections"])
    p = sim.theseus("wall", "push")
    check("back again: the change that was waiting goes out", p.returncode == 0 and "Renew the business permit" in json.dumps(on_pi_json()), p.stderr)
    check("and the failure clears from status", "failed" not in sim.theseus("wall", "status").stdout)

    run("docker", "stop", "-t", "5", NAME, check_rc=True)
    sim.list_edit("Book the plumber", "Book the plumber soon")
    t = time.time()
    p = sim.theseus("wall", "push", timeout=60)
    check("the Pi off: delivery fails quickly and plainly", p.returncode != 0 and time.time() - t < 30 and "didn't get that" in p.stderr, p.stderr)
    p = sim.theseus("wall", "titles", "off")
    check("a change made while it's off doesn't claim it arrived", "didn't" in (p.stdout + p.stderr) or "try again" in (p.stdout + p.stderr), p.stdout + p.stderr)
    sim.theseus("wall", "titles", "on")

    section("A restart of the Pi")
    run("docker", "start", NAME, check_rc=True)
    wait_for_pi()
    check("services come back by themselves", wait_until(lambda: pi("systemctl", "is-active", "theseus-wall-web.service").stdout.strip() == "active", 30))
    check("the list didn't survive the restart", on_pi_json() is None)
    text = text_of(page())
    check("the screen says it's waiting, not blank", "Waiting for your Mac" in text, text[:200])
    p = sim.theseus("wall", "push")
    arrived = on_pi_json() is not None
    if not arrived:
        sim.age_heartbeat()
        sim.theseus("wall", "push")
    check("the Mac's next delivery fills it again", on_pi_json() is not None)
    check("and the screen shows it", "Book the plumber soon" in text_of(page()))

    section("Bad data")
    good = pi("cat", "/run/theseus-wall/wall.json").stdout
    base = json.loads(good)
    views = json.loads(json.dumps(base))
    views["views"][0]["layouts"]["landscape"][0]["type"] = "script"
    grid = json.loads(json.dumps(base))
    grid["views"][0]["layouts"]["landscape"][0]["x"] = 99
    leak = dict(base, mode="counts")
    for name, raw in (("not JSON", b"garbage"), ("too big", b'{"x":"' + b"y" * 300000 + b'"}'), ("a newer format", json.dumps(dict(base, schema=99)).encode()),
                      ("an unknown piece", json.dumps(views).encode()), ("a piece off the grid", json.dumps(grid).encode()), ("titles while titles are off", json.dumps(leak).encode()),
                      ("bad hours", json.dumps(dict(base, display={"on": "6am", "off": "x"})).encode()), ("empty", b"")):
        p = sim.wall_ssh(f"wall@{HOST}", "receive", stdin=raw)
        check(f"the Pi refuses {name}, and keeps the last list", p.returncode != 0 and pi("cat", "/run/theseus-wall/wall.json").stdout == good, p.stderr.decode()[:120])
    sim.list_edit("Send the signed lease back", '<img src=x onerror="document.title=1">Hostile title')
    sim.theseus("wall", "push")
    dom = page()
    check("a hostile title is drawn as text", "Hostile title" in text_of(dom) and "<img" not in dom.split("<body", 1)[-1].split("<script", 1)[0], dom[:300])
    sim.list_edit('<img src=x onerror="document.title=1">Hostile title', "Send the signed lease back")
    sim.theseus("wall", "push")
    delivered = pi("cat", "/run/theseus-wall/wall.json").stdout
    master = (sim.ws / "data/master.md").read_text()
    (sim.ws / "data/master.md").write_text("")
    p = sim.theseus("wall", "push")
    check("an empty list on the Mac sends nothing and says why", p.returncode != 0 and pi("cat", "/run/theseus-wall/wall.json").stdout == delivered, p.stdout + p.stderr)
    (sim.ws / "data/master.md").write_text(master)
    views_file = (sim.ws / "data/wall-views.json").read_text()
    (sim.ws / "data/wall-views.json").write_text("{broken")
    p = sim.theseus("wall", "push")
    check("a broken layout file sends nothing and says why", p.returncode != 0 and "wall-views.json" in p.stderr and pi("cat", "/run/theseus-wall/wall.json").stdout == delivered, p.stdout + p.stderr)
    (sim.ws / "data/wall-views.json").write_text(views_file)
    check("status recovers after a good delivery", sim.theseus("wall", "push", "--force").returncode == 0 and "failed" not in sim.theseus("wall", "status").stdout)
    pi_sh("echo 'half a fi' > /run/theseus-wall/wall.json")
    text = text_of(page())
    check("a damaged file on the Pi shows Waiting, not a crash", "Waiting for your Mac" in text, text[:200])
    sim.theseus("wall", "push", "--force")
    pi_sh("echo '{\"schema\": 99}' > /run/theseus-wall/wall.json")
    check("a newer format on the Pi shows Waiting", "Waiting for your Mac" in text_of(page()))
    sim.theseus("wall", "push", "--force")

    section("Active hours, on the real systemd timer, with a stand-in for the TV")
    pi_sh("printf '#!/bin/sh\\necho \"$@\" >> /run/cec-sim.log\\n' > /usr/local/bin/cec-ctl && chmod 755 /usr/local/bin/cec-ctl && touch /dev/cec0 /run/cec-sim.log && chgrp video /dev/cec0 && chmod 660 /dev/cec0 && chmod 666 /run/cec-sim.log")
    cec = lambda: pi("cat", "/run/cec-sim.log").stdout
    def hhmm(minutes):
        return (dt.datetime.fromisoformat(now_on_pi(minutes))).strftime("%H:%M")
    pi_sh("rm -f /run/theseus-wall/power-state; : > /run/cec-sim.log")
    p = sim.theseus("wall", "hours", hhmm(120), hhmm(180))
    check("setting hours that exclude now", p.returncode == 0 and on_pi_json()["display"]["on"] == hhmm(120), p.stdout + p.stderr)
    check("within a minute the timer asks the TV to sleep", wait_until(lambda: "--standby" in cec(), 75), cec())
    log = cec()
    check("using the commands in the cec-ctl manual", "-d /dev/cec0 --playback" in log and "-d /dev/cec0 --to 0 --standby" in log, log)
    check("as the unprivileged account", "wall" == pi("stat", "-c", "%U", "/run/theseus-wall/power-state").stdout.strip())
    dom = page()
    check("the page goes black", re.search(r'id="stage" class="[^"]*dark', dom) is not None and "Renew" not in text_of(dom), dom[:200])
    time.sleep(62)
    check("it doesn't keep repeating itself", cec().count("--standby") == 1, cec())
    p = sim.theseus("wall", "hours", hhmm(-60), hhmm(60))
    check("hours that include now wake the TV within a minute", wait_until(lambda: "--image-view-on" in cec(), 75), cec())
    check("and the list is back", "Renew the business permit" in text_of(page()))
    pi_sh(": > /run/cec-sim.log")
    sim.theseus("wall", "hours", "always")
    time.sleep(62)
    check("`hours always` leaves the TV alone", cec() == "", cec())
    sim.theseus("wall", "hours", "6am", "12am")
    today = now_on_pi()[:10]
    tomorrow = (dt.date.fromisoformat(today) + dt.timedelta(days=1)).isoformat()
    for when, dark in ((f"{today}T05:59:00", True), (f"{today}T06:00:00", False), (f"{today}T23:59:00", False), (f"{tomorrow}T00:00:00", True), (f"{tomorrow}T03:00:00", True)):
        dom = page(f"?now={when}")
        check(f"6am to midnight at {when[11:16]} is {'dark' if dark else 'on'}", (re.search(r'id="stage" class="[^"]*dark', dom) is not None) == dark)
    pi_sh("rm -f /usr/local/bin/cec-ctl /dev/cec0")
    time.sleep(1)
    p = pi_sh("sudo -u wall /opt/theseus-wall/pi/power.py; echo rc=$?")
    check("with no TV to talk to, the power job is harmless", "rc=0" in p.stdout, p.stdout + p.stderr)
    sim.theseus("wall", "hours", "always")

    section("The Pi's identity changing")
    pi_sh("rm -f /etc/ssh/ssh_host_* && ssh-keygen -A && systemctl restart ssh")
    time.sleep(1)
    sim.list_edit("Send the signed lease back", "Send the lease back today")
    before = pi("cat", "/run/theseus-wall/wall.json").stdout
    p = sim.theseus("wall", "push")
    check("a different device at that address gets nothing", p.returncode != 0 and pi("cat", "/run/theseus-wall/wall.json").stdout == before, p.stdout + p.stderr)
    check("and it says what happened in plain words", "identity" in p.stderr.lower(), p.stderr)
    p = sim.theseus("wall", "setup", HOST, "--user", "pi", "--no-agent", timeout=600)
    check("setup won't quietly trust the new identity", p.returncode != 0, p.stdout[-300:])
    check("and says how to accept it if you reinstalled the Pi", "ssh-keygen -R" in p.stderr, p.stderr)
    run("ssh-keygen", "-R", f"[127.0.0.1]:{sim.port}", "-f", str(sim.ws / ".wall/known_hosts"))
    p = sim.theseus("wall", "setup", HOST, "--user", "pi", "--no-agent", timeout=600)
    check("after accepting it, everything works again", p.returncode == 0 and "Send the lease back today" in json.dumps(on_pi_json()), p.stderr[-400:])

    section("The kiosk: real cage and real Chromium, drawing to a headless output instead of HDMI")
    check("the service waits for its page before starting the browser", "serve.py --wait" in pi("cat", "/etc/systemd/system/theseus-wall-screen.service").stdout)
    pi("apt-get", "install", "-y", "-qq", "--no-install-recommends", "grim", "python3-pil", timeout=300)
    # With no GPU here, the service has been retrying all along, which is what it's meant to do. Now give it an output it can use.
    pi_sh("systemctl stop theseus-wall-screen.service; systemctl reset-failed theseus-wall-screen.service; mkdir -p /etc/systemd/system/theseus-wall-screen.service.d && printf '[Service]\\nEnvironment=WLR_BACKENDS=headless WLR_RENDERER=pixman WLR_LIBINPUT_NO_DEVICES=1\\n' > /etc/systemd/system/theseus-wall-screen.service.d/sim.conf && systemctl daemon-reload && systemctl start --no-block theseus-wall-screen.service")
    uid = pi("id", "-u", "kiosk").stdout.strip()
    up = wait_until(lambda: pi("pgrep", "-u", "kiosk", "-f", "/usr/lib/chromium/chromium").returncode == 0 and pi("pgrep", "-u", "kiosk", "cage").returncode == 0 and pi("test", "-S", f"/run/user/{uid}/wayland-0").returncode == 0, 90)
    check("the real screen service starts cage and Chromium as the kiosk account", up, pi("journalctl", "-u", "theseus-wall-screen.service", "-n", "12", "--no-pager").stdout[-800:])
    if up:
        restarts = pi("systemctl", "show", "-p", "NRestarts", "--value", "theseus-wall-screen.service").stdout.strip()
        time.sleep(20)
        got = pi_sh(f"WAYLAND_DISPLAY=wayland-0 XDG_RUNTIME_DIR=/run/user/{uid} grim /home/kiosk/kiosk.png && stat -c %s /home/kiosk/kiosk.png", user="kiosk")
        shot_ok = got.returncode == 0 and int((got.stdout.strip() or "0").splitlines()[-1]) > 5000
        check("and it draws something real", shot_ok, got.stdout + got.stderr)
        if shot_ok:
            save_picture("/home/kiosk/kiosk.png", f"{RELEASE}-kiosk.png")
            box = pi("python3", "-c", "from PIL import Image; im = Image.open('/home/kiosk/kiosk.png').convert('RGB'); print(im.size == im.getbbox()[2:], im.size, im.getbbox())").stdout.strip()
            if RELEASE == "bookworm":
                # bookworm's older cage logs "Basic output test failed" for a headless output, and hands the browser a tiny window whatever its flags. Not checked here, so it's unknown there.
                print(f"NOTE  how much of the output the kiosk fills isn't meaningful on bookworm's headless output: {box}", flush=True)
            else:
                check("it fills the whole output", box.startswith("True"), box)
        check("once it has an output, it stays up without restarting", pi("systemctl", "show", "-p", "NRestarts", "--value", "theseus-wall-screen.service").stdout.strip() == restarts)
    pi_sh("rm -rf /etc/systemd/system/theseus-wall-screen.service.d; systemctl daemon-reload; systemctl stop theseus-wall-screen.service")

    if sys.platform == "darwin" and not os.environ.get("CI"):
        section("The background job, in this Mac's real launchd")
        label = f"com.theseus.wall-sim-{os.getpid()}"
        agent = sim.tmp / f"{label}.plist"
        with open(agent, "wb") as f:
            plistlib.dump({"Label": label, "ProgramArguments": ["/usr/bin/python3", str(ROOT / "engine/tools/wall.py"), "push"], "StartInterval": 30, "RunAtLoad": True,
                           "EnvironmentVariables": {"THESEUS_HOME": str(sim.ws), "PATH": f"{sim.bin}:/usr/bin:/bin", "PYTHONDONTWRITEBYTECODE": "1"},
                           "StandardOutPath": "/dev/null", "StandardErrorPath": "/dev/null"}, f)
        target = f"gui/{os.getuid()}"
        boot = run("launchctl", "bootstrap", target, str(agent))
        check("launchd accepts the job", boot.returncode == 0, boot.stderr)
        try:
            sim.list_edit("Send the lease back today", "Changed while nobody was looking")
            check("with nobody at the keyboard, a list change reaches the Pi within a minute", wait_until(lambda: "Changed while nobody was looking" in json.dumps(on_pi_json() or {}), 70), json.dumps(sim.state()))
        finally:
            run("launchctl", "bootout", f"{target}/{label}")
        check("and it's gone from launchd afterwards", label not in run("launchctl", "list").stdout)

    section("Turning it off")
    p = sim.theseus("wall", "off")
    check("off clears the screen", p.returncode == 0 and on_pi_json() is None, p.stdout + p.stderr)
    check("the screen goes back to Waiting", "Waiting for your Mac" in text_of(page()))
    check("config says off", json.loads((sim.ws / "config.json").read_text())["wall"]["enabled"] is False)
    sim.theseus("wall", "push")
    check("and nothing more is sent", on_pi_json() is None)
    check("the Mac's list was never touched by any of this", "COMMS-CANARY" in (sim.ws / "data/master.md").read_text() and (sim.ws / "data/today.md").read_text().startswith("TODAY-CANARY"))
    return True


def use_plain_docker():
    """Docker's credential helper can wait on a prompt nobody can answer. These images are public, so it isn't needed. Your Docker settings aren't changed."""
    if os.environ.get("DOCKER_CONFIG"):
        return
    host = run("docker", "context", "inspect", "--format", "{{.Endpoints.docker.Host}}").stdout.strip()
    if host:
        os.environ["DOCKER_HOST"] = host
    os.environ["DOCKER_CONFIG"] = tempfile.mkdtemp(prefix="wall-sim-docker-")


def main():
    use_plain_docker()
    print(f"Building the simulated Pi (Debian {RELEASE}, {run('docker', 'version', '--format', '{{.Server.Arch}}').stdout.strip()})...", flush=True)
    run("docker", "build", "-q", "--build-arg", f"RELEASE={RELEASE}", "-t", IMAGE, str(Path(__file__).parent), timeout=900, check_rc=True)
    sim = Sim()
    try:
        scenario(sim)
    except Exception as e:  # a crash in the middle is a failure to report, not a reason to leave a container running
        check("the scenario ran to the end", False, f"{type(e).__name__}: {e}"[:800])
    finally:
        run("docker", "rm", "-f", NAME)
        shutil.rmtree(sim.tmp, True)
    bad = [r for r in results if not r[1]]
    print(f"\n{len(results) - len(bad)} of {len(results)} passed on Debian {RELEASE}")
    for name, _, detail in bad:
        print(f"FAILED: {name}\n        {detail}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
