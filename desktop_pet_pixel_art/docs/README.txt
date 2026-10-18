NOTAS DE IMPLEMENTAÇÃO — NOVA

Os recursos do projeto estão dentro de ../assets:
  movements/    vídeos usados pela mascote
  icons/        ícone de resposta
  personagem/   folhas de sprites em pixel art
  references/   referências visuais da interface

O módulo src/animation.py prepara os vídeos fora da lógica da interface,
incluindo o vídeo de pensamento usado enquanto o Ollama responde.
O módulo src/ollama_client.py cuida das chamadas ao Ollama e grava o histórico
por arquivo temporário seguido de substituição atômica. A resposta da IA é
entregue à interface por uma fila consumida pelo laço principal do Tkinter;
assim, a thread da requisição não altera widgets.

O módulo src/calendar_view.py exibe um calendário mensal local. Ele não acessa
contas ou dados externos; a integração com Google Calendar fica para uma etapa
posterior.

O módulo src/assistant_actions.py fornece a data e hora locais ao contexto do
Ollama, responde diretamente a perguntas sobre a data de hoje e reconhece o
pedido explícito para abrir a janela do calendário.

Para instalação, execução, atalhos e configuração do Ollama, consulte
../README.txt.
