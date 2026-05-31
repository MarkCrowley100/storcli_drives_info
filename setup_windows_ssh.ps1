# Run this on EACH Windows server as Administrator.
# Installs OpenSSH Server and adds the Linux server's public key.

param(
    [Parameter(Mandatory=$true)]
    [string]$PublicKey
)

# Install OpenSSH Server if not present
$sshCap = Get-WindowsCapability -Online -Name OpenSSH.Server~~~~0.0.1.0
if ($sshCap.State -ne 'Installed') {
    Write-Host "Installing OpenSSH Server..."
    Add-WindowsCapability -Online -Name OpenSSH.Server~~~~0.0.1.0
}

# Start and enable sshd
Set-Service -Name sshd -StartupType Automatic
Start-Service sshd

# Open firewall
$fw = Get-NetFirewallRule -Name 'OpenSSH-Server-In-TCP' -ErrorAction SilentlyContinue
if (-not $fw) {
    New-NetFirewallRule -Name 'OpenSSH-Server-In-TCP' -DisplayName 'OpenSSH Server (sshd)' `
        -Enabled True -Direction Inbound -Protocol TCP -Action Allow -LocalPort 22
}

# Add public key for administrators
$authKeys = "$env:ProgramData\ssh\administrators_authorized_keys"
if (-not (Test-Path $authKeys)) { New-Item -ItemType File -Path $authKeys -Force | Out-Null }

$existing = Get-Content $authKeys -ErrorAction SilentlyContinue
if ($existing -notcontains $PublicKey) {
    Add-Content -Path $authKeys -Value $PublicKey
    Write-Host "Public key added."
} else {
    Write-Host "Public key already present."
}

# Fix permissions (required by OpenSSH)
icacls $authKeys /inheritance:r /grant "SYSTEM:F" /grant "BUILTIN\Administrators:F"

# Ensure storcli64 is accessible
$storcli = Get-Command storcli64 -ErrorAction SilentlyContinue
if (-not $storcli) {
    Write-Warning "storcli64 not found in PATH. Add its folder to the system PATH or update STORCLI_CMD in app.py."
} else {
    Write-Host "storcli64 found at: $($storcli.Source)"
}

Write-Host "Done. SSH server is running on port 22."
