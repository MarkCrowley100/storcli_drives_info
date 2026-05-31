#!/usr/bin/env bash
# Run this on 192.168.96.229 (Ubuntu 24.04) as root or with sudo.
set -e

APP_DIR=/opt/storcli-web
APP_USER=storcli
SSH_KEY_DIR=/home/$APP_USER/.ssh

echo "==> Creating app user..."
id $APP_USER &>/dev/null || useradd -r -m -s /bin/bash $APP_USER

echo "==> Installing dependencies..."
apt-get update -qq
apt-get install -y python3 python3-pip python3-venv nginx

echo "==> Creating app directory..."
mkdir -p $APP_DIR
cp -r . $APP_DIR/
chown -R $APP_USER:$APP_USER $APP_DIR

echo "==> Setting up Python venv..."
su -s /bin/bash $APP_USER -c "
  python3 -m venv $APP_DIR/venv
  $APP_DIR/venv/bin/pip install -q -r $APP_DIR/requirements.txt
"

echo "==> Generating SSH key for $APP_USER (if not present)..."
mkdir -p $SSH_KEY_DIR
chown -R $APP_USER:$APP_USER $SSH_KEY_DIR
chmod 700 $SSH_KEY_DIR
if [ ! -f $SSH_KEY_DIR/id_rsa ]; then
  su -s /bin/bash $APP_USER -c "ssh-keygen -t rsa -b 4096 -N '' -f $SSH_KEY_DIR/id_rsa"
  echo ""
  echo "  *** Copy this public key to each Windows server's authorized_keys ***"
  echo "  For each Windows server run (as administrator in PowerShell):"
  echo "    \$key = '$(cat $SSH_KEY_DIR/id_rsa.pub)'"
  echo "    Add-Content -Path \"\$env:ProgramData\\ssh\\administrators_authorized_keys\" -Value \$key"
  echo "    icacls \"\$env:ProgramData\\ssh\\administrators_authorized_keys\" /inheritance:r /grant 'SYSTEM:F' /grant 'ADMINISTRATORS:F'"
  echo ""
fi

echo "==> Creating systemd service..."
cat > /etc/systemd/system/storcli-web.service <<EOF
[Unit]
Description=StorCLI Web Monitor
After=network.target

[Service]
User=$APP_USER
WorkingDirectory=$APP_DIR
ExecStart=$APP_DIR/venv/bin/python app.py
Restart=always
RestartSec=5
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable storcli-web
systemctl restart storcli-web

echo "==> Configuring nginx reverse proxy..."
cat > /etc/nginx/sites-available/storcli-web <<'EOF'
server {
    listen 21000;
    server_name 192.168.96.229;

    location / {
        proxy_pass http://127.0.0.1:5000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_read_timeout 60s;
    }
}
EOF

ln -sf /etc/nginx/sites-available/storcli-web /etc/nginx/sites-enabled/storcli-web
rm -f /etc/nginx/sites-enabled/default
nginx -t && systemctl reload nginx

echo ""
echo "==> Done! Web UI available at http://192.168.96.229:21000"
echo ""
echo "  Next steps:"
echo "  1. Add the SSH public key to each Windows server (see above)."
echo "  2. Make sure OpenSSH Server is running on each Windows server."
echo "  3. Verify storcli64.exe is in PATH or update STORCLI_CMD in app.py."
echo "  4. Edit SSH_USER in app.py if the Windows admin account differs."
