NOVA — MASCOTE DE DESKTOP EM PIXEL ART

Estrutura:
  src/desktop_pet.py       Interface e comportamento da mascote
  src/animation.py         Leitura e preparação dos vídeos
  src/ollama_client.py     Conversa local e histórico
  src/x11_helper.py        Integração opcional com X11
  assets/movements/        Vídeos das animações
  assets/icons/            Ícones de pensamento e resposta
  assets/personagem/       Folhas de sprites originais
  assets/references/       Referências visuais

Requisitos (Linux):
  python3 -m venv .venv
  .venv/bin/pip install -r requirements.txt
  sudo apt install python3-tk

Execução, a partir desta pasta:
  .venv/bin/python src/desktop_pet.py

Uso:
  - Clique e arraste para mover a Nova.
  - Duplo clique ou botão direito > Perguntar para conversar com a IA local.
  - Botão direito > Calendário abre a visualização do mês atual.
  - Pergunte "que dia é hoje?" para receber a data local, ou peça para abrir
    o calendário pela janela de conversa.
  - Botão direito > Abrir Claude no navegador abre claude.ai.
  - Use o menu do botão direito para configurar os comportamentos ou fechar.

IA local:
  Instale e inicie o Ollama, depois baixe o modelo configurado em
  src/config.py (padrão: llama3.2:1b). Sem Ollama, os demais recursos continuam
  disponíveis e a mascote informa quando não consegue obter uma resposta.

Calendário:
  O calendário é uma visualização local do mês, sem conexão com uma conta
  Google. A sincronização de compromissos pode ser adicionada depois.

Notas:
  - Os vídeos são carregados de assets/movements durante a inicialização; o
    vídeo "Vídeo com balão pensamento.mp4" anima a Nova enquanto ela responde.
  - Pillow e OpenCV são necessários; python-xlib é opcional para recursos X11.
  - O histórico é salvo em ~/.desktop_pet_history.json por substituição atômica.
