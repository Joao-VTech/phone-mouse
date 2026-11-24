# Phone Mouse - diagnostico (so teclado)
#
# Win+R -> powershell -> Enter, e digite:
#   irm https://raw.githubusercontent.com/Joao-VTech/phone-mouse/main/diagnostico.ps1 | iex
#
# Verifica servidor, rede e firewall, e oferece corrigir o firewall (pede permissao do Windows: Alt+S).

$ProgressPreference = 'SilentlyContinue'
$port = 8443
$dir  = Join-Path $env:USERPROFILE 'phone-mouse'
$problems = @()

function Ok($m)   { Write-Host "  [OK]   $m" -ForegroundColor Green }
function Bad($m)  { Write-Host "  [ERRO] $m" -ForegroundColor Red; $script:problems += $m }
function Info($m) { Write-Host "         $m" -ForegroundColor Gray }

Write-Host ''
Write-Host '  Phone Mouse - diagnostico' -ForegroundColor Cyan
Write-Host ''

# ---------- 1. servidor ----------
Write-Host '1) Servidor' -ForegroundColor Cyan
$listen = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
if (-not $listen) {
    Bad "nada escutando na porta $port (servidor parado)"
    $started = $false
    if (Get-ScheduledTask -TaskName PhoneMouse -ErrorAction SilentlyContinue) {
        Info 'iniciando pela tarefa PhoneMouse (modo administrador)...'
        schtasks /run /tn PhoneMouse | Out-Null; $started = $true
    } elseif (Test-Path "$dir\server.py") {
        Info 'iniciando servidor...'
        Start-Process -FilePath 'pyw' -ArgumentList '-3', "`"$dir\server.py`"" -WorkingDirectory $dir; $started = $true
    } else {
        Info "Phone Mouse nao instalado em $dir"
    }
    if ($started) {
        for ($i = 0; $i -lt 15 -and -not $listen; $i++) {
            Start-Sleep 1
            $listen = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
        }
        if ($listen) { Ok 'servidor iniciado'; $script:problems = @() } else { Bad 'o servidor nao subiu' }
    }
}
if ($listen) {
    $proc = Get-Process -Id $listen.OwningProcess -ErrorAction SilentlyContinue
    Ok "servidor rodando ($($proc.ProcessName), PID $($listen.OwningProcess))"
    # curl.exe (vem no Windows 10/11) aceita o certificado autoassinado com -k
    $resp = & curl.exe -sk --max-time 5 "https://localhost:$port/info" 2>$null
    if ($LASTEXITCODE -eq 0 -and $resp) {
        $name = try { ($resp | ConvertFrom-Json).name } catch { '?' }
        Ok "responde no proprio PC (nome: $name)"
    } else { Bad "nao responde nem no proprio PC (curl codigo $LASTEXITCODE)" }
}
$log = Join-Path $dir 'phone-mouse.log'
if (Test-Path $log) { Info 'ultimas linhas do log:'; Get-Content $log -Tail 4 | ForEach-Object { Info "  $_" } }

# ---------- 2. rede ----------
Write-Host ''
Write-Host '2) Rede' -ForegroundColor Cyan
# mesmo criterio do servidor: o endereco que o Windows usa de fato para sair para a internet
$route = Find-NetRoute -RemoteIPAddress 8.8.8.8 -ErrorAction SilentlyContinue | Where-Object { $_.IPAddress } | Select-Object -First 1
$ip = $null
if ($route) {
    $ip = $route.IPAddress
    $prof = Get-NetConnectionProfile -InterfaceIndex $route.InterfaceIndex -ErrorAction SilentlyContinue
    Ok "endereco do PC: $ip  (interface: $($route.InterfaceAlias))"
    Info "rede: '$($prof.Name)' - tipo $($prof.NetworkCategory)"
    if ($prof.NetworkCategory -eq 'Public') { Info "rede marcada como PUBLICA: o firewall e mais restritivo" }
} else { Bad 'PC sem rede/internet' }

# ---------- 3. firewall ----------
Write-Host ''
Write-Host '3) Firewall' -ForegroundColor Cyan
$rules = Get-NetFirewallRule -Direction Inbound -Enabled True -ErrorAction SilentlyContinue | Where-Object {
    $_.DisplayName -match 'python|Phone Mouse' }
$block = @($rules | Where-Object { $_.Action -eq 'Block' })
$allowPort = @(Get-NetFirewallRule -DisplayName 'Phone Mouse' -ErrorAction SilentlyContinue | Where-Object { $_.Enabled -eq 'True' -and $_.Action -eq 'Allow' })
$allowPy = @($rules | Where-Object { $_.Action -eq 'Allow' -and $_.DisplayName -match 'python' })
if ($block.Count) {
    Bad "$($block.Count) regra(s) BLOQUEANDO o Python (criadas ao cancelar a janela do firewall)"
    $block | ForEach-Object { Info "  bloqueio: $($_.DisplayName) - perfil $($_.Profile)" }
}
$fwProblem = [bool]$block.Count
if ($allowPort.Count) { Ok "regra 'Phone Mouse' liberando a porta $port" }
elseif ($allowPy.Count) {
    Info 'regras liberando o Python:'
    $allowPy | ForEach-Object { Info "  $($_.DisplayName) - perfil $($_.Profile)" }
    $cat = if ($prof) { "$($prof.NetworkCategory)" } else { 'Public' }
    if ($allowPy | Where-Object { "$($_.Profile)" -match "Any|$cat" }) { Ok "liberacao vale para a rede atual ($cat)" }
    else { Bad "nenhuma liberacao vale para a rede atual ($cat)"; $fwProblem = $true }
} else { Bad "nenhuma regra liberando a porta $port"; $fwProblem = $true }

# ---------- resultado / correcao ----------
Write-Host ''
if ($fwProblem -and -not $env:PM_NOFIX) {
    $r = Read-Host 'Corrigir o firewall agora? Libera a porta 8443 e remove os bloqueios do Python (S/N)'
    if ($r -match '^[sS]') {
        $fix = "Get-NetFirewallRule -Direction Inbound | Where-Object { `$_.Action -eq 'Block' -and `$_.DisplayName -match 'python' } | Remove-NetFirewallRule;" +
               "Remove-NetFirewallRule -DisplayName 'Phone Mouse' -ErrorAction SilentlyContinue;" +
               "New-NetFirewallRule -DisplayName 'Phone Mouse' -Direction Inbound -Action Allow -Protocol TCP -LocalPort $port -Profile Any | Out-Null"
        Write-Host '  O Windows vai pedir permissao: aperte Alt+S.'
        try {
            Start-Process powershell -Verb RunAs -Wait -WindowStyle Hidden -ArgumentList '-NoProfile', '-Command', $fix
            if (Get-NetFirewallRule -DisplayName 'Phone Mouse' -ErrorAction SilentlyContinue) { Ok 'firewall corrigido' } else { Bad 'a correcao nao foi aplicada' }
        } catch { Bad 'permissao negada' }
    }
}

Write-Host ''
if ($ip) {
    Write-Host "  No celular (MESMA rede Wi-Fi do PC), abra:  https://$($ip):$port" -ForegroundColor Yellow
    Write-Host ''
    Info 'Se ainda ficar carregando: confira se o celular nao esta numa rede de convidados'
    Info 'ou nos dados moveis, e se o roteador nao isola os aparelhos (isolamento de AP).'
}
Write-Host ''
