#!/bin/bash
# Sets up a Raspberry Pi (Pi OS Lite, 64-bit) as a Theseus screen. `theseus wall setup` runs this for you, as root, on the Pi. Safe to run again.
# Works the same on a Pi 4 or a Pi 5.
# Usage: install.sh "<the Mac's public key>" ["<the Mac's time zone>"]
set -euo pipefail
[[ $(id -u) == 0 ]] || { echo "Run this as root." >&2; exit 1; }
KEY="${1:-}"
[[ "$KEY" == ssh-ed25519\ * && "$KEY" != *$'\n'* ]] || { echo "Give the Mac's ed25519 public key." >&2; exit 1; }
ZONE="${2:-}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP=/opt/theseus-wall

echo "== Packages"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
BROWSER=chromium
apt-cache show chromium >/dev/null 2>&1 || BROWSER=chromium-browser
apt-get install -y -qq --no-install-recommends cage "$BROWSER" fonts-inter python3 unattended-upgrades v4l-utils >/dev/null
BROWSER_BIN="$(command -v chromium || command -v chromium-browser)"

echo "== Users"
id wall >/dev/null 2>&1 || useradd --system --create-home --shell /bin/sh wall     # delivers snapshots, and nothing else
id kiosk >/dev/null 2>&1 || useradd --system --create-home --shell /usr/sbin/nologin kiosk   # draws the screen
usermod -aG video,render,input kiosk

echo "== Files"
rm -rf "$APP.new" && mkdir -p "$APP.new/pi"
cp -R "$HERE/../display" "$APP.new/display"
install -m 755 "$HERE/receive.py" "$HERE/serve.py" "$HERE/power.py" "$APP.new/pi/"
rm -rf "$APP" && mv "$APP.new" "$APP"
chown -R root:root "$APP"

# The list lives in memory, so an unplugged or stolen Pi holds no copy of it, and the SD card isn't written to on every change.
echo 'd /run/theseus-wall 0755 wall wall -' > /etc/tmpfiles.d/theseus-wall.conf
systemd-tmpfiles --create /etc/tmpfiles.d/theseus-wall.conf

install -d -m 700 -o wall -g wall /home/wall/.ssh
printf 'restrict,command="%s/pi/receive.py" %s\n' "$APP" "$KEY" > /home/wall/.ssh/authorized_keys
chown wall:wall /home/wall/.ssh/authorized_keys && chmod 600 /home/wall/.ssh/authorized_keys

echo "== Keeping it hands-off"
# Active hours and "Due today" both go by this Pi's clock.
if [[ "$ZONE" =~ ^[A-Za-z0-9_+/-]+$ && -e "/usr/share/zoneinfo/$ZONE" ]]; then timedatectl set-timezone "$ZONE"; fi
usermod -aG video wall   # to reach the TV over HDMI
# The Mac only got this far with a key, so passwords can go.
mkdir -p /etc/ssh/sshd_config.d
printf 'PasswordAuthentication no\nKbdInteractiveAuthentication no\n' > /etc/ssh/sshd_config.d/10-theseus-wall.conf
systemctl reload ssh 2>/dev/null || systemctl reload sshd 2>/dev/null || true
mkdir -p /etc/systemd/journald.conf.d
printf '[Journal]\nStorage=volatile\n' > /etc/systemd/journald.conf.d/theseus-wall.conf
systemctl restart systemd-journald
printf 'APT::Periodic::Update-Package-Lists "1";\nAPT::Periodic::Unattended-Upgrade "1";\n' > /etc/apt/apt.conf.d/20auto-upgrades

echo "== Services"
cat > /etc/systemd/system/theseus-wall-web.service <<EOF
[Unit]
Description=Theseus wall: the page and snapshot, on this Pi only

[Service]
User=wall
ExecStart=/usr/bin/python3 $APP/pi/serve.py
Restart=always
NoNewPrivileges=yes
ProtectSystem=strict
ProtectHome=yes
PrivateTmp=yes

[Install]
WantedBy=multi-user.target
EOF
cat > /etc/systemd/system/theseus-wall-screen.service <<EOF
[Unit]
Description=Theseus wall: the screen
After=theseus-wall-web.service systemd-user-sessions.service
Wants=theseus-wall-web.service
Conflicts=getty@tty1.service
After=getty@tty1.service

[Service]
User=kiosk
PAMName=login
TTYPath=/dev/tty1
TTYReset=yes
TTYVHangup=yes
StandardInput=tty
RuntimeDirectory=theseus-wall-kiosk
Environment=XDG_RUNTIME_DIR=/run/theseus-wall-kiosk
Environment=XDG_SESSION_TYPE=wayland
ExecStart=/usr/bin/cage -s -- $BROWSER_BIN --kiosk --incognito --no-first-run --noerrdialogs --disable-infobars --disable-translate --disable-sync --disable-extensions --disable-background-networking --ozone-platform=wayland --check-for-update-interval=31536000 http://127.0.0.1:8737/
Restart=always
RestartSec=5

[Install]
WantedBy=graphical.target
EOF
cat > /etc/systemd/system/theseus-wall-power.service <<EOF
[Unit]
Description=Theseus wall: sleep and wake the TV with your active hours

[Service]
Type=oneshot
User=wall
ExecStart=/usr/bin/python3 $APP/pi/power.py
NoNewPrivileges=yes
ProtectHome=yes
PrivateTmp=yes
EOF
cat > /etc/systemd/system/theseus-wall-power.timer <<EOF
[Unit]
Description=Theseus wall: check active hours once a minute

[Timer]
OnCalendar=minutely

[Install]
WantedBy=timers.target
EOF
systemctl daemon-reload
systemctl set-default graphical.target >/dev/null
systemctl enable theseus-wall-web.service theseus-wall-screen.service >/dev/null
systemctl enable --now theseus-wall-power.timer >/dev/null
systemctl restart theseus-wall-web.service
systemctl disable --now getty@tty1.service 2>/dev/null || true
systemctl restart theseus-wall-screen.service
echo "== Done"
