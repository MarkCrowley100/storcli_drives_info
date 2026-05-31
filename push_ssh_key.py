#!/usr/bin/env python3
"""
One-time script: push the storcli SSH public key to all target servers.
Run on the Linux server as root or storcli user:
  sudo python3 push_ssh_key.py
"""
import paramiko
import sys

PUB_KEY_PATH = "/home/storcli/.ssh/id_rsa.pub"

with open(PUB_KEY_PATH) as f:
    pub_key = f.read().strip()

WINDOWS_SERVERS = {
    "mcserver": ("plex", "shamus12"),
    "mcvmh1":   ("plex", "shamus12"),
    "mcnas":    ("plex", "shamus12"),
    "mcnas2":   ("plex", "shamus12"),
}

LINUX_SERVERS = {
    "workpc": ("admin", "$hAmus742687"),
}

# PowerShell snippet to install OpenSSH, add key, fix perms on Windows
WIN_SCRIPT = r"""
$f = "$env:ProgramData\ssh\administrators_authorized_keys"
$cap = Get-WindowsCapability -Online -Name OpenSSH.Server~~~~0.0.1.0 -ErrorAction SilentlyContinue
if ($cap -and $cap.State -ne 'Installed') { Add-WindowsCapability -Online -Name OpenSSH.Server~~~~0.0.1.0 | Out-Null }
Set-Service -Name sshd -StartupType Automatic -ErrorAction SilentlyContinue
Start-Service sshd -ErrorAction SilentlyContinue
if (-not (Get-NetFirewallRule -Name 'OpenSSH-Server-In-TCP' -ErrorAction SilentlyContinue)) {
    New-NetFirewallRule -Name 'OpenSSH-Server-In-TCP' -DisplayName 'OpenSSH Server (sshd)' -Enabled True -Direction Inbound -Protocol TCP -Action Allow -LocalPort 22 | Out-Null
}
if (-not (Test-Path $f)) { New-Item -ItemType File -Path $f -Force | Out-Null }
$existing = Get-Content $f -ErrorAction SilentlyContinue
$key = 'KEY_PLACEHOLDER'
if ($existing -notcontains $key) { Add-Content -Path $f -Value $key }
icacls $f /inheritance:r /grant 'SYSTEM:F' /grant 'BUILTIN\Administrators:F' | Out-Null
Write-Host "OK sshd=$((Get-Service sshd -ErrorAction SilentlyContinue).Status)"
""".strip().replace("KEY_PLACEHOLDER", pub_key)


def connect(host, user, password):
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(host, username=user, password=password, timeout=20)
    return c


def run(client, cmd):
    _, stdout, stderr = client.exec_command(cmd, timeout=60)
    out = stdout.read().decode("utf-8", errors="replace").strip()
    err = stderr.read().decode("utf-8", errors="replace").strip()
    return out, err


print("=" * 60)
print("Pushing SSH key to Windows servers via password auth")
print("=" * 60)
for host, (user, pw) in WINDOWS_SERVERS.items():
    print(f"\n==> {host} ({user})")
    try:
        c = connect(host, user, pw)
        out, err = run(c, f"powershell -NonInteractive -Command \"{WIN_SCRIPT}\"")
        c.close()
        print(f"    {out or '(no output)'}")
        if err:
            print(f"    stderr: {err}")
    except Exception as e:
        print(f"    FAILED: {e}")

print("\n" + "=" * 60)
print("Pushing SSH key to Linux servers via password auth")
print("=" * 60)
for host, (user, pw) in LINUX_SERVERS.items():
    print(f"\n==> {host} ({user})")
    try:
        c = connect(host, user, pw)
        cmds = [
            "mkdir -p ~/.ssh && chmod 700 ~/.ssh",
            f"grep -qxF '{pub_key}' ~/.ssh/authorized_keys 2>/dev/null || echo '{pub_key}' >> ~/.ssh/authorized_keys",
            "chmod 600 ~/.ssh/authorized_keys",
            "echo OK",
        ]
        for cmd in cmds:
            out, err = run(c, cmd)
            if out:
                print(f"    {out}")
            if err:
                print(f"    stderr: {err}")
        c.close()
    except Exception as e:
        print(f"    FAILED: {e}")

print("\nDone.")
