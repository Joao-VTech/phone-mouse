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

## Uso no dia a dia

1. Abra o atalho **Phone Mouse** (ou marque *Iniciar com o Windows* no ícone da bandeja).
2. No celular, toque na notificação "Phone Mouse pronto - NOME-DO-PC".
3. Na primeira vez, aceite o aviso de certificado (é autoassinado) e toque em **Iniciar**.

### Notificação no celular
Instale o app **[ntfy](https://ntfy.sh)** e assine o tópico que está em `config.json`
(criado na primeira execução). Para usar o **mesmo tópico em vários PCs**, copie o `config.json`
entre eles. Para desligar, mude `"notify"` para `false`. Para trocar o nome mostrado, adicione
`"pc_name": "Sala"`.

### Ícone da bandeja
Enviar link para o celular · Iniciar com o Windows · Ativar modo administrador · Sair.

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
