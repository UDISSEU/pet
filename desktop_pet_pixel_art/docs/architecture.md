# Arquitetura

## Visão geral

`src/desktop_pet.py` coordena a janela Tkinter, os estados da personagem, as interações e as rotinas periódicas. A interface é desenhada em pixel art com Pillow. Um quadro de prévia do vídeo idle é decodificado na abertura; `AnimationLoader` carrega o restante em uma thread daemon e entrega quadros por fila para a thread Tkinter.

## Módulos

- `desktop_pet.py`: ciclo principal, janela, menu, diálogos, modos da mascote e integração entre os módulos.
- `animation.py`: decodifica vídeos, prepara quadros e remove o fundo claro.
- `animation_loader.py`: carrega as sequências completas em segundo plano; mantém a prévia caso um vídeo individual falhe e não acessa widgets Tkinter.
- `app_intents.py`: reconhece e associa pedidos de abertura de aplicativos sem executar comandos.
- `autonomy.py`: leitura e gravação de preferências, horários silenciosos, lembretes e busca de lançadores Linux `.desktop`.
- `json_persistence.py`: faz cópias não destrutivas de JSONs inválidos e bloqueia gravação quando não consegue preservar o original.
- `assistant_actions.py`: respostas locais para data e hora e reconhecimento do pedido para abrir o calendário.
- `calendar_view.py`: calendário mensal local; não sincroniza com contas externas.
- `config.py`: caminhos dos assets, animações e parâmetros padrão.
- `ollama_client.py`: API e persistência do histórico JSON legado.
- `keyring_secret.py`: leitura e gravação de chaves Gemini, Groq e Mistral no cofre Secret Service do ambiente de desktop.
- `providers/`: provedores independentes via HTTP; não adicionam SDKs à aplicação.
- `ai/`: personalidade, contexto e roteamento; `AICore` conecta a conversa à seleção de provedor. `request_handler.py` converte erros conhecidos em mensagens para a interface e mantém detalhes de exceções inesperadas fora dos logs.
- `x11_helper.py`: observação da janela ativa e geometria de janelas em ambientes X11. O módulo falha de forma segura se X11 ou `python-xlib` não estiverem disponíveis.

As dependências obrigatórias estão em `requirements.txt`. `python-xlib` é opcional e pode ser instalado separadamente para habilitar recursos que dependem de X11; sua ausência não impede os recursos gerais da mascote.

## Fluxo da conversa

1. A interface recebe a pergunta e verifica primeiro os comandos locais de data e calendário.
2. Se a solicitação corresponder a um app cadastrado, a Nova mostra o comando e pede confirmação.
3. Outras perguntas são processadas por `ai.request_handler.answer_request` em uma thread de trabalho. Ollama é o padrão e fallback. Gemini/Groq/Mistral só recebem contexto quando selecionados, ativados e com autorização de privacidade e confirmação explícita do nível gratuito. A resposta volta por uma fila; a thread não manipula widgets Tkinter.
4. Preferências e histórico são gravados em arquivos JSON por substituição atômica. Ao encontrar JSON inválido, a Nova guarda uma cópia `*.corrupt-*` antes de permitir uma nova gravação. Se não conseguir criar essa cópia, bloqueia a substituição.

As memórias explícitas são selecionadas por relevância e adicionadas ao contexto como dados de referência, nunca como instruções. Preferências duplicadas são removidas ao carregar as configurações, sem alterar o formato JSON existente. O seletor de apps lê lançadores `*.desktop` dos diretórios XDG de aplicações; comandos são divididos em argumentos e executados sem shell.

O modo de foco usa temporizadores Tkinter: enquanto a sessão ou a pausa está ativa, as falas espontâneas, observações de apps e lembretes aguardam. A pausa reaproveita a animação de descanso existente. As rotinas de boas-vindas e encerramento são opcionais e dependem de a aplicação estar aberta.

## Dados do usuário

- `~/.desktop_pet_history.json`: histórico curto de conversa.
- `~/.config/desktop_pet/settings.json`: modo, preferências, horários, rotinas, foco, memórias, lembretes e apps cadastrados.

## Provedores de IA

As implementações usam HTTP da biblioteca padrão Python. Gemini usa `models.generateContent`, Groq usa `chat/completions`, e Mistral usa `/v1/chat/completions`; as chaves são `GEMINI_API_KEY`, `GROQ_API_KEY` e `MISTRAL_API_KEY`. Os modelos são configuráveis pela aba **Inteligência artificial**. O botão **Testar conexão** consulta apenas a disponibilidade do modelo e não envia conversa. Limites e preços variam por provedor e podem mudar; confira os painéis antes de habilitar. A Nova não ativa planos nem muda configurações de cobrança. Erros do provedor online recorrem ao Ollama local; não há fallback para um serviço pago.

O lançador tenta carregar as chaves Gemini, Groq e Mistral do cofre Secret Service antes de iniciar a interface. As chaves não são gravadas em `settings.json`; a execução direta de `desktop_pet.py` continua aceitando-as pelo ambiente.

Referências oficiais consultadas: [Gemini API generateContent](https://ai.google.dev/api/generate-content), [modelos Gemini](https://ai.google.dev/gemini-api/docs/models), [Groq chat completions](https://console.groq.com/docs/api-reference), [modelos e limites Groq](https://console.groq.com/docs/models).

Os lembretes são verificados pelo próprio processo da Nova. Eles são mostrados quando o app está em execução e não estão no horário silencioso.

O desenho, a conversa e as animações não dependem do X11. Observar a janela ativa, posicionar a mascote em janelas e aplicar recursos de janela usam `python-xlib` e dependem do X11; no Wayland esses recursos podem não estar disponíveis, conforme o compositor e a sessão.

## Testes

Execute da raiz do projeto:

```bash
.venv/bin/python -m unittest discover -s tests -v
```

O CI usa Python 3.12 com Tkinter e Xvfb. Testes de integração com provedores usam mocks; uma sessão Ollama, chaves e internet não são necessárias.
