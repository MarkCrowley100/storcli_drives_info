param([string]$Username = "splunk")

$key = 'ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAACAQC8updr8YO4x1TX3g4fRJWA0EAE01DDHOt+yRaoHKGPBbR7cEt+ewKDmhu63uSBhGRCgz3W0694uPX/mYnSlIGWfB2LWxSpgtQAGKPwlPJJljREF0ZHM8PzMAJ+mViKvIThVnJG7XAg9fW5Tv0m0ujl7txqZBtM+ol0dcAfK9TzfSQ04wG4f0ofy5yyckQ5WvSNCVPM2zBUcTl/x+wTcfLtDLN3LBpW8trGCRougUjGwXTo09qN3ncZFRs+M7Kpcmtr9sIT9FhWWmA3DekV6KUgRO4QwhCq+FQpkmTEEO/I5/JkwZaBVgA2MqHbgAkeCUgDpPEgWPzvCOl1lyXZHMoUtmwFRNeAfSQfZmvq5MG9sKecj59mavvOPXsvULt/F71sf0eeNUeA/QL8FkRTqi68rkJLEPYD0g5OBrY8X0jnGF664Yo9+88YdrPqbEBVGyLkjseHKwrv9T7vZDACN2fALoCmaahH2kxa9Sz2ALQhLW8eSPBWAfx76UWfQzWhhYg40h/8FS1BrUS6K7q38GEEP53MPBi8xANg0bqj1ezp5vrIUMQhJeaTWw31HUkWDRCIq2T8luXWNiWurA5GbsmeCTNW91KfdFKG45O9hPCbE/p6nlbQ44v0RhVBQGUVTa5yi/aL3WZDjjVwz/CFxAMYRC2QG6WJNn9WQ7HY4Tl/nw== storcli@jumpbox'

$servers = @('mcserver','mcvmh1','mcnas','mcnas2','workpc')

# Add servers to TrustedHosts
$current = (Get-Item WSMan:\localhost\Client\TrustedHosts).Value
$toAdd = $servers -join ','
if ($current -notmatch '\*') {
    Set-Item WSMan:\localhost\Client\TrustedHosts -Value "$current,$toAdd" -Force
}

$cred = Get-Credential -UserName $Username -Message "Enter admin password for the Windows servers"

$scriptBlock = {
    param($key)
    $f = "$env:ProgramData\ssh\administrators_authorized_keys"
    $cap = Get-WindowsCapability -Online -Name OpenSSH.Server~~~~0.0.1.0 -ErrorAction SilentlyContinue
    if ($cap -and $cap.State -ne 'Installed') {
        Write-Host "  Installing OpenSSH Server..."
        Add-WindowsCapability -Online -Name OpenSSH.Server~~~~0.0.1.0 | Out-Null
    }
    Set-Service -Name sshd -StartupType Automatic -ErrorAction SilentlyContinue
    Start-Service sshd -ErrorAction SilentlyContinue
    if (-not (Get-NetFirewallRule -Name 'OpenSSH-Server-In-TCP' -ErrorAction SilentlyContinue)) {
        New-NetFirewallRule -Name 'OpenSSH-Server-In-TCP' -DisplayName 'OpenSSH Server (sshd)' `
            -Enabled True -Direction Inbound -Protocol TCP -Action Allow -LocalPort 22 | Out-Null
    }
    if (-not (Test-Path $f)) { New-Item -ItemType File -Path $f -Force | Out-Null }
    $existing = Get-Content $f -ErrorAction SilentlyContinue
    if ($existing -notcontains $key) { Add-Content -Path $f -Value $key }
    icacls $f /inheritance:r /grant 'SYSTEM:F' /grant 'BUILTIN\Administrators:F' | Out-Null
    "  sshd status: $((Get-Service sshd -ErrorAction SilentlyContinue).Status)"
}

foreach ($server in $servers) {
    Write-Host "==> $server" -ForegroundColor Cyan
    try {
        $result = Invoke-Command -ComputerName $server -Credential $cred -ScriptBlock $scriptBlock -ArgumentList $key -ErrorAction Stop
        Write-Host $result -ForegroundColor Green
        Write-Host "  OK" -ForegroundColor Green
    } catch {
        Write-Host "  FAILED: $_" -ForegroundColor Red
    }
}
