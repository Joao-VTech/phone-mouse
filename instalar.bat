@echo off
setlocal
cd /d "%~dp0"
chcp 65001 >nul
title Phone Mouse - instalacao
echo.
echo  ==============================================
echo    Phone Mouse - instalacao
echo    (tudo pelo teclado: responda S ou N)
echo  ==============================================
echo.

rem ---------- 1. Python ----------
set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY (
  echo [1/5] Python nao encontrado. Instalando pelo winget...
  winget install -e --id Python.Python.3.12 --scope user --accept-package-agreements --accept-source-agreements
  if errorlevel 1 (
    echo.
    echo  ERRO: nao consegui instalar o Python automaticamente.
    echo  Instale em https://www.python.org/downloads/ e rode este arquivo de novo.
    pause
    exit /b 1
  )
  set "PATH=%LOCALAPPDATA%\Programs\Python\Launcher;%LOCALAPPDATA%\Programs\Python\Python312;%PATH%"
  set "PY=py -3"
) else (
  echo [1/5] Python encontrado.
)

rem ---------- 2. Dependencias ----------
echo [2/5] Instalando dependencias...
%PY% -m pip install --disable-pip-version-check -q --upgrade -r requirements.txt
if errorlevel 1 (
  echo  ERRO ao instalar dependencias.
  pause
  exit /b 1
)

rem ---------- 3. Cabo USB (opcional, so Android) ----------
echo.
choice /c SN /m "[3/5] Usa celular ANDROID com cabo USB? (instala o adb)"
if errorlevel 2 goto noadb
winget install -e --id Google.PlatformTools --accept-package-agreements --accept-source-agreements
:noadb

rem ---------- 4. Atalho e modo administrador ----------
echo.
echo [4/5] Criando atalho na area de trabalho...
%PY% server.py --make-desktop-shortcut
echo.
echo  O modo administrador permite controlar jogos e janelas abertas como admin,
echo  e ja libera o firewall (sem janelas pedindo clique).
echo  O Windows vai pedir permissao UMA vez: aperte Alt+S (ou seta para a esquerda e Enter).
choice /c SN /m "Ativar modo administrador?"
if errorlevel 2 goto normal
%PY% server.py --install-admin
echo  Aguardando a permissao do Windows...
set /a tries=0
:waittask
schtasks /query /tn PhoneMouse >nul 2>nul && goto admin_ok
set /a tries+=1
if %tries% geq 90 goto admin_fail
timeout /t 1 /nobreak >nul
goto waittask
:admin_fail
echo  Modo administrador NAO foi ativado (permissao negada?). Iniciando no modo normal.
:normal
echo  Se o Windows perguntar sobre o firewall: Tab ate "Permitir acesso" e Enter.
start "" pyw -3 server.py
goto autostart
:admin_ok
echo  Modo administrador ativo.

rem ---------- 5. Iniciar com o Windows ----------
:autostart
echo.
choice /c SN /m "[5/5] Iniciar o Phone Mouse junto com o Windows?"
if errorlevel 2 goto done
%PY% server.py --autostart on

:done
echo.
echo  ==============================================
echo    Pronto! O Phone Mouse esta rodando.
echo  ==============================================
%PY% server.py --print-url
echo  Na primeira vez, aceite o aviso de certificado no celular e toque em Iniciar.
echo  Notificacao no celular (opcional): uma pagina com as instrucoes foi aberta.
echo.
pause
