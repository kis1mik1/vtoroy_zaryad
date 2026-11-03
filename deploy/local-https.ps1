param([string]$Ip)

$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")

if (-not $Ip) {
    $route = Get-NetRoute -DestinationPrefix "0.0.0.0/0" -ErrorAction SilentlyContinue |
        Sort-Object RouteMetric, InterfaceMetric | Select-Object -First 1
    if ($route) {
        $Ip = Get-NetIPAddress -AddressFamily IPv4 -InterfaceIndex $route.InterfaceIndex |
            Where-Object { $_.IPAddress -notlike "169.254.*" } |
            Select-Object -First 1 -ExpandProperty IPAddress
    }
}
if (-not $Ip) {
    Write-Host "Не удалось определить адрес в Wi-Fi. Укажите его явно: deploy\local-https.ps1 -Ip 192.168.1.20"
    exit 1
}

if (-not (Get-Command mkcert -ErrorAction SilentlyContinue)) {
    Write-Host "Устанавливаю mkcert через winget..."
    winget install --id FiloSottile.mkcert --exact --accept-source-agreements --accept-package-agreements
    $env:Path = [Environment]::GetEnvironmentVariable("Path", "Machine") + ";" +
        [Environment]::GetEnvironmentVariable("Path", "User")
    if (-not (Get-Command mkcert -ErrorAction SilentlyContinue)) {
        Write-Host "mkcert установлен, но не найден в PATH. Откройте новое окно PowerShell и запустите скрипт ещё раз."
        exit 1
    }
}

mkcert -install
mkcert -cert-file certs/local.pem -key-file certs/local-key.pem localhost 127.0.0.1 $Ip
$caRoot = mkcert -CAROOT

$ruleName = "Второй заряд: доступ с телефона"
$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
    [Security.Principal.WindowsBuiltInRole]::Administrator)
$firewallRule = @{
    DisplayName = $ruleName
    Direction = "Inbound"
    Protocol = "TCP"
    LocalPort = @(8000, 8443)
    Action = "Allow"
    Profile = "Private"
}
$firewallCommand = "New-NetFirewallRule -DisplayName `"$ruleName`" -Direction Inbound -Protocol TCP -LocalPort 8000,8443 -Action Allow -Profile Private"

Write-Host ""
if (Get-NetFirewallRule -DisplayName $ruleName -ErrorAction SilentlyContinue) {
    Write-Host "Правило брандмауэра уже есть: $ruleName"
} elseif ($isAdmin) {
    New-NetFirewallRule @firewallRule | Out-Null
    Write-Host "Добавлено правило брандмауэра: входящие TCP 8000 и 8443 в частной сети."
} else {
    Write-Host "Чтобы телефон достучался до ноутбука, выполните в PowerShell от имени администратора:"
    Write-Host "  $firewallCommand"
}

Write-Host ""
Write-Host "Сертификат готов. Впишите в .env:"
Write-Host "  ALLOWED_HOSTS=localhost,127.0.0.1,$Ip"
Write-Host "  CSRF_TRUSTED_ORIGINS=https://localhost:8443,https://${Ip}:8443"
Write-Host "  SITE_URL=https://${Ip}:8443"
Write-Host ""
Write-Host "Корневой сертификат для телефона: $(Join-Path $caRoot 'rootCA.pem')"
Write-Host "После правки .env: docker compose up -d; docker compose restart nginx"
Write-Host "Адрес для телефона: https://${Ip}:8443"
