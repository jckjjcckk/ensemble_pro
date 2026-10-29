#!/usr/bin/env bash
# Yoga as an unattended OMR/engraving box on Wi-Fi: no sleep, Wi-Fi power saving off, a watchdog that bounces Wi-Fi and
# finally reboots, cloudflared as a service for ssh over a Cloudflare tunnel. Ubuntu 24.04. Run once as root:
#   sudo bash deploy/yoga/setup.sh
# Before running: save the tunnel connector token (Zero Trust -> Networks -> Tunnels -> <tunnel> -> Install connector,
# token only) to /home/ck/.cloudflared/yoga-tunnel.token (chmod 600). The dashboard's public hostname for ssh points at
# ssh://localhost:22. Nothing here needs the token to exist; cloudflared just stays inactive until it does.
set -euo pipefail
[ "$(id -u)" = 0 ] || { echo "run with sudo"; exit 1; }
USER_NAME=${SUDO_USER:-ck}

echo "== no sleep, lid ignored, no idle action"
mkdir -p /etc/systemd/logind.conf.d
cat > /etc/systemd/logind.conf.d/folio-nosleep.conf <<'CONF'
[Login]
HandleLidSwitch=ignore
HandleLidSwitchExternalPower=ignore
HandleLidSwitchDocked=ignore
IdleAction=ignore
CONF
systemctl mask sleep.target suspend.target hibernate.target hybrid-sleep.target >/dev/null 2>&1 || true
systemctl restart systemd-logind

echo "== Wi-Fi: power saving off, autoconnect"
mkdir -p /etc/NetworkManager/conf.d
cat > /etc/NetworkManager/conf.d/folio-wifi-powersave.conf <<'CONF'
[connection]
wifi.powersave = 2
CONF
for c in $(nmcli -t -f NAME,TYPE con show | awk -F: '$2=="802-11-wireless"{print $1}'); do
  nmcli con modify "$c" connection.autoconnect yes connection.autoconnect-retries 0 connection.autoconnect-priority 10 || true
done
systemctl restart NetworkManager

echo "== watchdog: bounce Wi-Fi after 2 min without the gateway, reboot after 10"
cat > /usr/local/sbin/folio-netwatch <<'SH'
#!/usr/bin/env bash
# Runs every minute from a systemd timer. Keeps a down-counter in /run.
state=/run/folio-netwatch.down
gw=$(ip route | awk '/^default/{print $3; exit}')
if [ -n "$gw" ] && ping -c1 -W3 "$gw" >/dev/null 2>&1 && ping -c1 -W3 1.1.1.1 >/dev/null 2>&1; then
  rm -f "$state"; exit 0
fi
n=$(( $(cat "$state" 2>/dev/null || echo 0) + 1 )); echo "$n" > "$state"
logger -t folio-netwatch "network down, minute $n"
if [ "$n" -eq 2 ]; then nmcli radio wifi off; sleep 5; nmcli radio wifi on; fi
if [ "$n" -ge 10 ]; then logger -t folio-netwatch "rebooting"; systemctl reboot; fi
SH
chmod +x /usr/local/sbin/folio-netwatch
cat > /etc/systemd/system/folio-netwatch.service <<'UNIT'
[Unit]
Description=Folio network watchdog (Wi-Fi bounce, then reboot)
[Service]
Type=oneshot
ExecStart=/usr/local/sbin/folio-netwatch
UNIT
cat > /etc/systemd/system/folio-netwatch.timer <<'UNIT'
[Unit]
Description=Run the Folio network watchdog every minute
[Timer]
OnBootSec=3min
OnUnitActiveSec=1min
AccuracySec=10s
[Install]
WantedBy=timers.target
UNIT
systemctl daemon-reload
systemctl enable --now folio-netwatch.timer

echo "== cloudflared (Cloudflare apt repo)"
if ! command -v cloudflared >/dev/null; then
  mkdir -p --mode=0755 /usr/share/keyrings
  curl -fsSL https://pkg.cloudflare.com/cloudflare-main.gpg -o /usr/share/keyrings/cloudflare-main.gpg
  echo "deb [signed-by=/usr/share/keyrings/cloudflare-main.gpg] https://pkg.cloudflare.com/cloudflared noble main" > /etc/apt/sources.list.d/cloudflared.list
  apt-get update -qq && apt-get install -y -qq cloudflared
fi
TOKEN_FILE=/home/$USER_NAME/.cloudflared/yoga-tunnel.token
cat > /etc/systemd/system/cloudflared-yoga.service <<UNIT
[Unit]
Description=Cloudflare tunnel connector (yoga: ssh, OMR box)
After=network-online.target
Wants=network-online.target
ConditionPathExists=$TOKEN_FILE
[Service]
ExecStart=/bin/sh -c 'exec /usr/bin/cloudflared --no-autoupdate tunnel run --token "\$(cat $TOKEN_FILE)"'
Restart=always
RestartSec=5
[Install]
WantedBy=multi-user.target
UNIT
systemctl daemon-reload
systemctl enable cloudflared-yoga.service
systemctl start cloudflared-yoga.service || echo "cloudflared waits for $TOKEN_FILE"

echo "== ssh stays on"
systemctl enable --now ssh

echo
echo "Done. Check: systemctl status cloudflared-yoga folio-netwatch.timer --no-pager; cat /sys/class/power_supply/BAT*/status"
echo "Plug the laptop in. Then power-cycle it once and confirm ssh over the tunnel comes back without a login."
