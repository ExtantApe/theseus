# A stand-in for a freshly imaged Raspberry Pi: Debian (what Pi OS is built on), systemd, an SSH server, and an admin user with passwordless sudo,
# which is what Raspberry Pi Imager sets up. It isn't a Pi: there's no HDMI, GPU, TV or Wi-Fi. See test_connection.py.
ARG RELEASE=bookworm
FROM debian:${RELEASE}
RUN apt-get update -qq \
 && apt-get install -y -qq --no-install-recommends systemd systemd-sysv dbus openssh-server sudo python3 ca-certificates tzdata procps iproute2 \
 && useradd --create-home --shell /bin/bash pi \
 && echo 'pi ALL=(ALL) NOPASSWD: ALL' > /etc/sudoers.d/010_pi-nopasswd \
 && ssh-keygen -A \
 && systemctl enable ssh
STOPSIGNAL SIGRTMIN+3
CMD ["/sbin/init"]
