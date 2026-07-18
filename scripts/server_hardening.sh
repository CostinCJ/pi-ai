#!/usr/bin/env bash
# One-shot root setup: run with  sudo bash /home/pi/pi-ai/scripts/server_hardening.sh
# Everything here is idempotent — safe to re-run.
set -uo pipefail

step() { echo; echo "==== $* ===="; }

step "apt: update + pending upgrades + packages"
apt-get update -qq
apt-get -y upgrade
apt-get -y install unattended-upgrades fail2ban sqlite3 ufw

step "unattended-upgrades: enable"
cat > /etc/apt/apt.conf.d/20auto-upgrades <<'EOF'
APT::Periodic::Update-Package-Lists "1";
APT::Periodic::Unattended-Upgrade "1";
EOF
systemctl enable --now unattended-upgrades

step "fail2ban: sshd jail via journald"
cat > /etc/fail2ban/jail.local <<'EOF'
[DEFAULT]
backend = systemd
[sshd]
enabled = true
maxretry = 5
bantime = 1h
EOF
systemctl enable --now fail2ban
systemctl restart fail2ban

step "logrotate: pi-ai logs"
cat > /etc/logrotate.d/pi-ai <<'EOF'
/home/pi/pi-ai/*.log {
    weekly
    rotate 4
    size 5M
    compress
    missingok
    notifempty
    copytruncate
    su pi pi
}
EOF

step "arp-scan: grant cap_net_raw so network_radar can drop sudo"
setcap cap_net_raw+ep /usr/sbin/arp-scan
getcap /usr/sbin/arp-scan

step "ollama: disable dead service"
systemctl disable ollama 2>/dev/null || true

step "ufw: default deny incoming, allow known services"
ufw default deny incoming
ufw default allow outgoing
ufw allow in on tailscale0
ufw allow 22/tcp    comment 'ssh'
ufw allow 53        comment 'adguard dns'
ufw allow 80/tcp    comment 'adguard ui'
ufw allow 5353/udp  comment 'mdns/avahi'
ufw allow 3000/tcp  comment 'homepage'
ufw allow 3001/tcp  comment 'uptime-kuma'
ufw allow 8080/tcp  comment 'stirling-pdf'
ufw allow 8770/tcp  comment 'lache-status'
ufw --force enable
ufw status verbose

step "sshd: effective auth settings (want: passwordauthentication no)"
sshd -T 2>/dev/null | grep -Ei '^(passwordauthentication|permitrootlogin|pubkeyauthentication)'

step "restart pi-ai services (pick up network_radar.py change)"
systemctl restart piai.service piaibot.service
systemctl --no-pager --no-legend status piai.service piaibot.service | grep -E 'Active|●'

echo
echo "==== done ===="
