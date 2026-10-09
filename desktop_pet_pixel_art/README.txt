PET VIRTUAL - PIXEL ART

Estrutura:
  src/desktop_pet.py
  ../movimento 2.0/
    ChatGPT Image 8 de out. de 2026, 14_06_59.png
    ChatGPT Image 8 de out. de 2026, 14_39_09.png
    ChatGPT Image 8 de out. de 2026, 14_41_23.png
    ChatGPT Image 9 de out. de 2026, 14_45_38.png
    ChatGPT Image 9 de out. de 2026, 14_47_07.png
    ChatGPT Image 9 de out. de 2026, 14_48_36.png
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
  - A mascote passeia pela tela em oito direções e escolhe outra direção
    a cada poucos segundos, desviando das bordas.
  - Os quadros de lado, frente, costas e diagonal são escolhidos conforme
    a direção do movimento. Para a esquerda, os quadros laterais/diagonais
    são espelhados.
  - Os quadros intermediários de caminhada são usados para suavizar o ciclo;
    a folha de cabelo balançando aparece enquanto ela pensa.
  - O balanço usa 8 quadros e a piscada usa 7 quadros da mesma pasta.
  - As folhas são recortadas automaticamente, sem títulos/legendas, e o
    fundo claro é removido.
  - Para usar a IA local, instale o Ollama e baixe o modelo configurado em
    src/desktop_pet.py (padrão: llama3.2:1b).
