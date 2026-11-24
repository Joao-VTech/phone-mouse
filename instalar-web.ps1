# Phone Mouse - instalacao com um comando (funciona so com teclado, sem mouse)
#
# Win+R -> powershell -> Enter, e digite:
#   irm https://raw.githubusercontent.com/Joao-VTech/phone-mouse/main/instalar-web.ps1 | iex
#
# Baixa o projeto para %USERPROFILE%\phone-mouse, garante o Python e roda o instalar.bat.
# Reinstalar por cima mantem config.json (topico de notificacao) e certificados.

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$repo = 'https://github.com/Joao-VTech/phone-mouse/archive/refs/heads/main.zip'
$dest = Join-Path $env:USERPROFILE 'phone-mouse'
$tmp  = Join-Path $env:TEMP ('phone-mouse-' + [guid]::NewGuid().ToString('N'))

Write-Host ''
Write-Host '  Phone Mouse - baixando...' -ForegroundColor Cyan
New-Item -ItemType Directory -Force -Path $tmp, $dest | Out-Null
Invoke-WebRequest -UseBasicParsing -Uri $repo -OutFile "$tmp\pm.zip"
Expand-Archive -Force -Path "$tmp\pm.zip" -DestinationPath $tmp
Copy-Item -Recurse -Force -Path "$tmp\phone-mouse-main\*" -Destination $dest
Remove-Item -Recurse -Force $tmp
Write-Host "  Arquivos em $dest"

function Add-PythonToPath {
    $extra = @("$env:LOCALAPPDATA\Programs\Python\Launcher", "$env:LOCALAPPDATA\Programs\Python\Python312", "$env:WINDIR")
    $env:Path = (($extra + ($env:Path -split ';')) | Where-Object { $_ } | Select-Object -Unique) -join ';'
}

if (-not (Get-Command py -ErrorAction SilentlyContinue)) {
    Write-Host '  Python nao encontrado, instalando...' -ForegroundColor Cyan
    $ok = $false
    if (Get-Command winget -ErrorAction SilentlyContinue) {
        winget install -e --id Python.Python.3.12 --scope user --accept-package-agreements --accept-source-agreements --disable-interactivity
        $ok = ($LASTEXITCODE -eq 0)
    }
    if (-not $ok) {
        # sem winget: instalador oficial do python.org, silencioso e sem pedir admin
        $exe = Join-Path $env:TEMP 'python-3.12.10-amd64.exe'
        Invoke-WebRequest -UseBasicParsing -Uri 'https://www.python.org/ftp/python/3.12.10/python-3.12.10-amd64.exe' -OutFile $exe
        Start-Process -Wait -FilePath $exe -ArgumentList '/quiet', 'InstallAllUsers=0', 'PrependPath=1', 'Include_launcher=1', 'InstallLauncherAllUsers=0'
        Remove-Item -Force $exe
    }
    Add-PythonToPath
}

Set-Location $dest
& cmd.exe /c "`"$dest\instalar.bat`""
