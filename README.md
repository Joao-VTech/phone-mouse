# Phone Mouse

Use o celular como mouse e teclado do PC (Windows), pelo navegador — sem instalar app no celular.

## Modos

| Modo | Como usa |
|---|---|
| 👆 **Touchpad** | passa o dedo na tela, como no notebook |
| 🔦 **Apontador** | gira o pulso e aponta, como um laser (giroscópio) |
| 🖱️ **Mouse de mesa** | desliza o celular deitado na mesa (acelerômetro) |

### Gestos do Touchpad
- 1 dedo arrastando: move o cursor
- toque: clique esquerdo · toque + toque e arrasta: selecionar/arrastar
- toque com 2 dedos: clique direito · 2 dedos arrastando: rolar
- toque com 3 dedos: botão do meio
- deslizar da borda até o meio: abre/guarda o teclado
  (na vertical: bordas laterais · na horizontal: bordas de cima/baixo)
- ⛶ tela cheia e ⟳ para virar a tela (vertical → horizontal → outro lado)

### Teclado
Digita no PC com acentos, corretor e emoji. Barra com Esc, Tab, Ctrl, Alt, Shift, Win, setas e Del
(toque no modificador e depois na tecla, ex.: Ctrl → `c`). Com a tela girada pela página, usa um
teclado próprio que gira junto.

## Instalação (Windows)

1. Baixe este repositório (**Code → Download ZIP**) e extraia.
2. Dê dois cliques em **`instalar.bat`**. Ele:
   - instala o Python (se faltar) e as dependências;
   - opcionalmente instala o `adb` (cabo USB, só Android);
   - cria o atalho **Phone Mouse** na área de trabalho;
   - opcionalmente ativa o **modo administrador** (pede permissão do Windows uma vez).

Manual: `py -m pip install -r requirements.txt` e `py server.py` (ou `py server.py --console` para ver as mensagens).

### PC sem mouse (só teclado)
1. **Win + R**, digite `powershell` e **Enter**.
2. Digite e dê **Enter**:
   ```powershell
   irm https://raw.githubusercontent.com/Joao-VTech/phone-mouse/main/instalar-web.ps1 | iex
   ```
   Baixa tudo para `%USERPROFILE%\phone-mouse`, instala o Python se faltar (winget ou python.org) e roda o instalador.
3. Responda as perguntas com **S** ou **N**. No aviso do Windows (modo administrador): **Alt + S**.
4. No fim aparece um **QR code na tela**: aponte a câmera do celular e pronto, o celular vira o mouse.

O modo administrador já libera o firewall, então nenhuma janela pede clique. Respondendo **S** em
"Iniciar junto com o Windows", nas próximas vezes basta entrar no Windows.

> Limites do Windows (não há como contornar): a **tela de login**, o **Ctrl+Alt+Del** e os **avisos do UAC**
> rodam numa "área de trabalho segura" que não aceita mouse/teclado virtuais. Neles use o teclado físico
> (ou Windows Hello: rosto, digital ou PIN).

### Página fica branca carregando no celular?
Quase sempre é o firewall (ou celular em outra rede). No PC: **Win + R** → `powershell` → **Enter** e digite:
```powershell
irm https://raw.githubusercontent.com/Joao-VTech/phone-mouse/main/diagnostico.ps1 | iex
```
Ele verifica servidor, rede e firewall, oferece corrigir o firewall (**Alt + S** no aviso do Windows)
e mostra o endereço certo para abrir no celular.

Comandos úteis: `py server.py --print-url` (QR code com o endereço) · `--autostart on|off` ·
`--setup-notification` · `--install-admin`.

## Uso no dia a dia

1. Abra o atalho **Phone Mouse** (ou marque *Iniciar com o Windows* no ícone da bandeja).
2. No celular, toque na notificação "Phone Mouse pronto - NOME-DO-PC".
3. Na primeira vez, aceite o aviso de certificado (é autoassinado) e toque em **Iniciar**.

### Notificação no celular
Na primeira execução abre uma página explicando como assinar a notificação no app
**[ntfy](https://ntfy.sh)**: **QR code no Android** (assina com um toque) e o **tópico para copiar no iPhone**
(no app: **+** → tópico → **Subscribe**). Para abrir de novo: ícone da bandeja →
*Configurar notificação no celular* (ou `py server.py --setup-notification`). Para usar o **mesmo tópico em vários PCs**, copie o `config.json`
entre eles. Para desligar, mude `"notify"` para `false`. Para trocar o nome mostrado, adicione
`"pc_name": "Sala"`.

### Ícone da bandeja
Enviar link para o celular · Mostrar QR do endereço · Configurar notificação no celular · Iniciar com o Windows · Ativar modo administrador · Sair.

### Troca de rede (cabo ↔ Wi-Fi)
O servidor percebe sozinho quando o endereço do PC muda: reenvia a notificação com o link novo e,
se nenhum celular estiver conectado, abre na tela um **QR code com o endereço novo** (lista também os
endereços das outras placas de rede, caso PC e celular estejam em redes diferentes).

### Conexão
- **Wi-Fi:** celular e PC na mesma rede.
- **Cabo USB (Android):** ative a *Depuração USB*, conecte e toque em **📶 Wi-Fi ⇄** na página.

## Observações

- **Segurança:** qualquer pessoa na mesma rede que abrir a página consegue controlar o mouse e o
  teclado. Use em redes de confiança (casa), não em Wi-Fi público.
- **Modo administrador:** necessário para controlar janelas abertas como administrador e muitos jogos.
  Jogos com anti-cheat em nível de kernel bloqueiam mouses virtuais de propósito.
- **iPhone:** o navegador não permite travar a orientação nem tela cheia real; a página gira a si
  mesma (⟳). Para abrir sem barras, use Safari → Compartilhar → Adicionar à Tela de Início.
  Cabo USB não funciona no iPhone.
- A notificação passa pelo servidor público ntfy.sh (só envia o nome do PC e o endereço local).
