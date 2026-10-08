PET VIRTUAL - PIXEL ART

Estrutura:
  src/desktop_pet.py
  ../movimento 2.0/
    Folha de sprites_ caminhada em pixel art.png
    Folha de sprites_ garota balançando.png
    Folha de Sprites_ Animação de Piscada.png
  docs/

Requisitos:
  pip install --break-system-packages Pillow python-xlib
  sudo apt install python3-tk

Execução:
  cd /caminho/do/projeto
  python3 src/desktop_pet.py

Uso:
  - Clique e arraste para mover a mascote.
  - Duplo clique para usar IA local (requer Ollama em execução).
  - Botão direito para abrir o menu de opções.

Observações:
  - A caminhada usa 8 quadros da pasta ../movimento 2.0.
  - O balanço usa 8 quadros e a piscada usa 7 quadros da mesma pasta.
  - As folhas são recortadas automaticamente e o fundo claro é removido.
  - Para usar a IA local, instale o Ollama e baixe o modelo configurado em
    src/desktop_pet.py (padrão: llama3.2:1b).
