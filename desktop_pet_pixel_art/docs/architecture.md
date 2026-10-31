# Arquitetura

## Visão geral

`src/desktop_pet.py` coordena a janela Tkinter, os estados da personagem, as interações e as rotinas periódicas. A interface é desenhada em pixel art com Pillow; OpenCV decodifica os vídeos de `assets/movements/` durante a inicialização.

## Módulos

- `desktop_pet.py`: ciclo principal, janela, menu, diálogos, modos da mascote e integração entre os módulos.
- `animation.py`: decodifica vídeos, prepara quadros e remove o fundo claro.
- `autonomy.py`: leitura e gravação de preferências, horários silenciosos, lembretes e busca de lançadores Linux `.desktop`.
- `assistant_actions.py`: respostas locais para data e hora e reconhecimento do pedido para abrir o calendário.
- `calendar_view.py`: calendário mensal local; não sincroniza com contas externas.
- `config.py`: caminhos dos assets, animações e parâmetros padrão.
- `ollama_client.py`: API e persistência do histórico JSON legado.
- `keyring_secret.py`: leitura e gravação de chaves Gemini, Groq e Mistral no cofre Secret Service do ambiente de desktop.
- `providers/`: provedores independentes via HTTP; não adicionam SDKs à aplicação.
- `ai/`: personalidade, contexto e roteamento; `AICore` conecta a conversa à seleção de provedor.
- `x11_helper.py`: observação da janela ativa e geometria de janelas em ambientes X11. O módulo falha de forma segura se X11 ou `python-xlib` não estiverem disponíveis.

## Fluxo da conversa

1. A interface recebe a pergunta e verifica primeiro os comandos locais de data e calendário.
2. Se a solicitação corresponder a um app cadastrado, a Nova mostra o comando e pede confirmação.
3. Outras perguntas são enviadas por `AICore` em uma thread de trabalho. Ollama é o padrão e fallback. Gemini/Groq só recebem contexto quando selecionados, ativados e com autorização de privacidade e confirmação explícita do nível gratuito. A resposta volta por uma fila; a thread não manipula widgets Tkinter.
4. Preferências e histórico são gravados em arquivos JSON por substituição atômica.

As memórias explícitas são adicionadas ao contexto enviado ao modelo local. O seletor de apps lê lançadores `*.desktop` dos diretórios XDG de aplicações; comandos são divididos em argumentos e executados sem shell.

O modo de foco usa temporizadores Tkinter: enquanto a sessão ou a pausa está ativa, as falas espontâneas, observações de apps e lembretes aguardam. A pausa reaproveita a animação de descanso existente. As rotinas de boas-vindas e encerramento são opcionais e dependem de a aplicação estar aberta.

## Dados do usuário

- `~/.desktop_pet_history.json`: histórico curto de conversa.
- `~/.config/desktop_pet/settings.json`: modo, preferências, horários, rotinas, foco, memórias, lembretes e apps cadastrados.

## Provedores de IA

As implementações usam HTTP da biblioteca padrão Python. Gemini usa `models.generateContent`, Groq usa `chat/completions`, e Mistral usa `/v1/chat/completions`; as chaves são `GEMINI_API_KEY`, `GROQ_API_KEY` e `MISTRAL_API_KEY`. Os modelos são configuráveis pela aba **Inteligência artificial**. O botão **Testar conexão** consulta apenas a disponibilidade do modelo e não envia conversa. Limites e preços variam por provedor e podem mudar; confira os painéis antes de habilitar. A Nova não ativa planos nem muda configurações de cobrança. Erros do provedor online recorrem ao Ollama local; não há fallback para um serviço pago.

O lançador tenta carregar as chaves Gemini, Groq e Mistral do cofre Secret Service antes de iniciar a interface. As chaves não são gravadas em `settings.json`; a execução direta de `desktop_pet.py` continua aceitando-as pelo ambiente.

Referências oficiais consultadas: [Gemini API generateContent](https://ai.google.dev/api/generate-content), [modelos Gemini](https://ai.google.dev/gemini-api/docs/models), [Groq chat completions](https://console.groq.com/docs/api-reference), [modelos e limites Groq](https://console.groq.com/docs/models).

Os lembretes são verificados pelo próprio processo da Nova. Eles são mostrados quando o app está em execução e não estão no horário silencioso.

## Testes

Execute da raiz do projeto:

```bash
.venv/bin/python -m unittest discover -s tests -v
```
