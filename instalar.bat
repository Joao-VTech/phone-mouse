@echo off
setlocal
cd /d "%~dp0"
title Phone Mouse - instalacao
echo.
echo  ==============================================
echo    Phone Mouse - instalacao
echo  ==============================================
echo.

rem ---------- 1. Python ----------
set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY (
  echo [1/4] Python nao encontrado. Instalando pelo winget...
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
  echo [1/4] Python encontrado.
)

rem ---------- 2. Dependencias ----------
echo [2/4] Instalando dependencias...
%PY% -m pip install --disable-pip-version-check -q --upgrade -r requirements.txt
if errorlevel 1 (
  echo  ERRO ao instalar dependencias.
  pause
  exit /b 1
)

rem ---------- 3. Cabo USB (opcional, so Android) ----------
echo.
choice /c SN /m "[3/4] Usa celular ANDROID com cabo USB? (instala o adb)"
if errorlevel 2 goto noadb
winget install -e --id Google.PlatformTools --accept-package-agreements --accept-source-agreements
:noadb

rem ---------- 4. Atalho e modo administrador ----------
echo [4/4] Criando atalho na area de trabalho...
%PY% server.py --make-desktop-shortcut
echo.
echo  O modo administrador permite controlar jogos e janelas abertas como admin.
echo  O Windows vai pedir permissao UMA vez.
choice /c SN /m "Ativar modo administrador?"
if errorlevel 2 goto normal
%PY% server.py --install-admin
goto done
:normal
start "" pyw -3 server.py

:done
echo.
echo  Pronto! O Phone Mouse esta rodando (icone perto do relogio).
echo  Uma pagina vai abrir mostrando como receber a notificacao no celular
echo  (QR code no Android, topico para copiar no iPhone).
echo  Para abrir de novo: icone perto do relogio - "Configurar notificacao no celular".
echo.
pause
