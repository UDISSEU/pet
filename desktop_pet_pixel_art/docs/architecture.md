# Arquitetura

## Visão geral

`src/desktop_pet.py` coordena a janela Tkinter, os estados da personagem, as interações e as rotinas periódicas. `desktop_pet_ui.py` concentra o menu, o calendário e as preferências em um mixin usado pela janela principal. A interface é desenhada em pixel art com Pillow. Um quadro de prévia do vídeo idle é decodificado na abertura; `AnimationLoader` carrega o restante em uma thread daemon e entrega quadros por fila para a thread Tkinter.

## Módulos

- `desktop_pet.py`: ciclo principal, janela, modos da mascote e integração entre os módulos.
- `desktop_pet_ui.py`: menu de contexto, calendário e janelas de preferências; mantém o acesso aos widgets na thread Tkinter.
- `animation.py`: decodifica vídeos, prepara quadros e remove o fundo claro.
- `animation_loader.py`: carrega as sequências completas em segundo plano; mantém a prévia caso um vídeo individual falhe e não acessa widgets Tkinter.
- `app_intents.py`: reconhece e associa pedidos de abertura de aplicativos sem executar comandos.
- `autonomy.py`: leitura e gravação de preferências, horários silenciosos, lembretes e busca de lançadores Linux `.desktop`.
- `json_persistence.py`: faz cópias não destrutivas de JSONs inválidos e bloqueia gravação quando não consegue preservar o original.
- `assistant_actions.py`: respostas locais para data e hora e reconhecimento do pedido para abrir o calendário.
- `automations.py`: allowlist fixa, reconhecimento local de frases, relatórios de espaço e arquivos, busca por conteúdo duplicado, organização de Downloads/capturas e limpeza confirmada da Lixeira. O reconhecimento não consulta IA nem executa ações; mudanças de arquivos exigem prévia e confirmação.
- `calendar_view.py`: calendário mensal local; não sincroniza com contas externas.
- `config.py`: caminhos dos assets, animações e parâmetros padrão.
- `ollama_client.py`: API e persistência do histórico JSON legado.
- `keyring_secret.py`: leitura e gravação de chaves Gemini, Groq e Mistral no cofre Secret Service do ambiente de desktop.
- `providers/`: provedores independentes via HTTP; não adicionam SDKs à aplicação.
- `ai/`: personalidade, contexto e roteamento; `AICore` conecta a conversa à seleção de provedor. `request_handler.py` converte erros conhecidos em mensagens para a interface e mantém detalhes de exceções inesperadas fora dos logs.
- `x11_helper.py`: observação da janela ativa e geometria de janelas em ambientes X11. O módulo falha de forma segura se X11 ou `python-xlib` não estiverem disponíveis.
- `event_bus.py`: barramento tipado, com publicação síncrona e fila `post`/`drain` para encaminhar eventos de workers à thread Tkinter.
- `state_manager.py`: catálogo de estados compatível com as poses existentes, prioridade, geração e retorno de poses temporárias. `DesktopPet.state` permanece como fachada de compatibilidade e espelha as transições no controlador.
- `plugin_manager.py`: contrato e ciclo de vida para instâncias explicitamente registradas. Não importa código externo nem descobre plugins automaticamente; código Python carregado no processo da Nova é confiável, não uma sandbox.
- `permissions.py`: permissões persistidas por plugin, inicialmente negadas, com confirmação para permissões sensíveis e revogação imediata.
- `notifications.py`: histórico limitado, persistido com permissões restritas, deduplicação, leitura e descarte.
- `system_monitor.py`: coleta tolerante a indisponibilidade de CPU, RAM, disco, memória do processo e threads para o painel.
- `dashboard_ui.py`, `notifications_ui.py` e `permissions_ui.py`: janelas separadas para métricas, histórico de notificações e revisão/revogação de permissões.

As dependências obrigatórias estão em `requirements.txt`. `python-xlib` é opcional e pode ser instalado separadamente para habilitar recursos que dependem de X11; sua ausência não impede os recursos gerais da mascote.

## Fluxo da conversa

1. A interface recebe a pergunta e verifica primeiro data, calendário e intents locais de automação allowlist.
2. Automações reconhecidas localmente não passam pelos provedores de IA. Relatórios são somente leitura; movimentações mostram prévia e pedem confirmação; a Lixeira exige confirmação antes de apagar. Operações demoradas rodam em thread e retornam por Event Bus ou pela fila de callbacks UI, consumida pelo ciclo Tkinter. Avisos de pausa e bateria são verificados periodicamente, respeitando foco e horário silencioso.
3. Se a solicitação corresponder a um app cadastrado, a Nova mostra o comando e pede confirmação.
4. Outras perguntas são processadas por `ai.request_handler.answer_request` em uma thread de trabalho. Ollama é o padrão e fallback. Gemini/Groq/Mistral só recebem contexto quando selecionados, ativados e com autorização de privacidade e confirmação explícita do nível gratuito. A resposta volta por uma fila; a thread não manipula widgets Tkinter.
5. Preferências e histórico são gravados em arquivos JSON por substituição atômica. Ao encontrar JSON inválido, a Nova guarda uma cópia `*.corrupt-*` antes de permitir uma nova gravação. Se não conseguir criar essa cópia, bloqueia a substituição.

As memórias explícitas são selecionadas por relevância e adicionadas ao contexto como dados de referência, nunca como instruções. Preferências duplicadas são removidas ao carregar as configurações, sem alterar o formato JSON existente. O seletor de apps lê lançadores `*.desktop` dos diretórios XDG de aplicações; comandos são divididos em argumentos e executados sem shell.

O modo de foco usa temporizadores Tkinter: enquanto a sessão ou a pausa está ativa, as falas espontâneas, observações de apps e lembretes aguardam. A pausa reaproveita a animação de descanso existente. As rotinas de boas-vindas e encerramento são opcionais e dependem de a aplicação estar aberta.

## Dados do usuário

- `~/.desktop_pet_history.json`: histórico curto de conversa.
- `~/.config/desktop_pet/settings.json`: modo, preferências, horários, rotinas, foco, memórias, lembretes e apps cadastrados.
- `~/.config/desktop_pet/downloads_undo.json`: mapa da última organização confirmada de Downloads.

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

Os testes de integração com provedores usam mocks; uma sessão Ollama, chaves e internet não são necessárias. `tests/test_ui_windows.py` abre e fecha as três janelas se Tk puder conectar a um display; sem display, o teste fica marcado como ignorado.

Para executar o smoke test em display isolado, capturar PNGs ou iniciar a
aplicação e o soak em conjunto, consulte [Testes gráficos isolados](gui-testing.md).

## Componentes extensíveis

`EventBus.post(event)` recebe resultados de IA e automações em workers sem chamar assinantes; a UI consome a fila com `drain()` no ciclo Tkinter. Widgets são atualizados apenas na thread principal. Mudanças de estado e animação são publicadas no ciclo principal. Para uma habilidade interna confiável, implemente `Plugin`, declare `PluginManifest` e registre explicitamente a instância no `PluginManager`. Confirme permissões no momento da operação com `PermissionManager.require`; declarar uma permissão no manifesto não concede acesso. O menu **Permissões** permite revisar e revogar grants da Nova e das habilidades registradas.

Plugins externos usam manifesto JSON explicitamente selecionado via `PluginManager.register_external_manifest`. O processo usa JSON por stdin/stdout, timeout, limite de mensagem, `prlimit` para CPU, espaço virtual de memória, processos, arquivos abertos e tamanho de arquivo, `bubblewrap`, diretório do plugin somente leitura, ambiente sem credenciais e namespaces de usuário e PID. Sem autorização `network.access`, tenta também desabilitar a rede; se o isolamento de rede não for suportado, a execução falha fechada. Com `network.access` concedida, o processo pode usar a rede. O sandbox reduz acesso ao sistema, mas não deve ser tratado como isolamento perfeito contra vulnerabilidades do kernel ou do bubblewrap.

O menu abre **Painel da Nova**, **Notificações** e **Permissões**. Cada janela reutiliza a instância já aberta e traz essa janela para frente. O painel coleta métricas em worker, mantém histórico limitado e atualiza a interface pela thread principal; a frequência pode ser ajustada ou pausada na janela. Notificações são salvas em `~/.config/desktop_pet/notifications.json`, incluindo filtros por categoria, modo silencioso e intervalo anti-repetição; permissões ficam em `~/.config/desktop_pet/permissions.json`. Os controles de permissões internas usam o identificador `nova.core`, igual ao Permission Manager.

O controlador de estado é uma migração incremental. O código existente ainda escolhe poses e temporizadores; novas alterações devem migrar para `StateManager.transition` antes de remover a fachada `DesktopPet.state`. Workers que precisem retornar uma ação visual usam `post_ui_callback`; o callback só é executado pelo `tick()` na thread que criou Tk. Não chame `root.after()` de workers.

Validação operacional registrada: probes limitados confirmaram o encerramento por limite de CPU, `MemoryError` no teto de espaço virtual, limite de criação de processos e limpeza dos filhos/process groups após limite e timeout. Uma automação e uma consulta de IA terminaram concorrendo sem perder os eventos; o histórico de notificações permaneceu no limite configurado durante uma sequência de avisos. O sandbox com rede explicitamente autorizada conseguiu ler o protocolo sem receber variáveis de credencial e não conseguiu ler um arquivo fora da pasta montada. A verificação sem permissão de rede foi bloqueada pelo host (`bwrap: loopback: Failed to create NETLINK_ROUTE socket: Operation not permitted`); nessa condição o plugin não ativa. A suíte Tk não pôde abrir janelas: `xvfb-run` e Xvfb direto falharam porque `/tmp/.X11-unix` pertence a `nobody` (o servidor requer diretório de socket de propriedade de root), e o servidor também não conseguiu abrir sockets TCP. O teste de janelas foi, portanto, ignorado. Não há validação visual nem teste real em Linux Mint/Wayland. Os recursos X11 continuam condicionais a uma sessão X11; o desenho e a conversa não dependem deles.

### Soak tests

`tools/nova_soak.py` executa os serviços reais de EventBus, fila de callbacks da
UI, notificações, monitor de sistema e seleção de quadros de animação em um
processo separado. O arquivo JSONL registra CPU, RSS, threads, filhos, filas,
históricos limitados e quadros selecionados. Ele não cria uma janela Tk e não
mede fluidez visual. Os cenários de 30 minutos, 1 hora e 3 horas são separados
da suíte normal:

```bash
.venv/bin/python tools/nova_soak.py --scenario 30m --output /tmp/nova-soak-30m.jsonl
.venv/bin/python tools/nova_soak.py --scenario 1h --output /tmp/nova-soak-1h.jsonl
.venv/bin/python tools/nova_soak.py --scenario 3h --output /tmp/nova-soak-3h.jsonl
```

`--duration-seconds` e `--sample-interval` permitem verificações curtas. Os
relatórios registram somente métricas observadas; tendências prolongadas só
podem ser avaliadas após executar e comparar os cenários completos.
