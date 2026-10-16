PET VIRTUAL - PIXEL ART

Estrutura:
  src/desktop_pet.py
  ../movimentos em vídeos/
    acenando.mp4
    andar.direita.mp4
    andar.esquerda.mp4
    dormindo.mp4
    irritada.mp4
    parada.mp4
  docs/

Requisitos:
  python3 -m venv .venv
  .venv/bin/pip install -r requirements.txt
  sudo apt install python3-tk

Execução:
  cd /caminho/do/projeto
  .venv/bin/python src/desktop_pet.py

Uso:
  - Clique e arraste para mover a mascote.
  - Duplo clique para usar IA local (requer Ollama em execução).
  - Botão direito para abrir o menu de opções.

Observações:
  - A mascote caminha horizontalmente e alterna entre os vídeos de caminhada
    para a esquerda e para a direita.
  - Os vídeos de parada, aceno e sono são usados conforme a mascote estiver
    parada, falando ou sentada; uma batida na borda da tela usa o vídeo irritada.
  - Os vídeos são decodificados em quadros menores e o fundo claro conectado
    às bordas é removido para manter a transparência da janela.
  - A refatoração separou configurações em src/config.py, a IA local em
    src/ollama_client.py e a lógica opcional de X11 em src/x11_helper.py,
    preservando o comportamento principal da mascote sem exigir que a
    biblioteca python-xlib esteja presente.
  - Para usar a IA local, instale o Ollama e baixe o modelo configurado em
    src/config.py (padrão: llama3.2:1b).
