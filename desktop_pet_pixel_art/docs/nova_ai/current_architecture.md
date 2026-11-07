# Arquitetura atual da Nova — auditoria Fase 0

## Escopo e método

Auditoria estática do repositório em 5 de novembro de 2026. Foram lidos os READMEs, a documentação interna, o workflow de CI, os módulos Python de `desktop_pet_pixel_art/src/` e os testes. Nenhum arquivo de aplicação, configuração ou dado pessoal foi modificado; nenhum teste, serviço externo, modelo ou treinamento foi executado.

O aplicativo em desenvolvimento é `desktop_pet_pixel_art/`. Há assets e referências visuais em outras pastas, mas o runtime e a suíte estão no subdiretório do aplicativo. Os diretórios `.venv-*`, caches, `__pycache__` e materiais visuais não constituem módulos de runtime.

## Visão geral

A aplicação é um monólito Python desktop, organizado em módulos e mixins, com Tkinter como ciclo de vida e interface. `src/desktop_pet.py` compõe a fachada `DesktopPet`, inicializa serviços e coordena o método `tick()`. Controladores dividem comportamento e UI, mas continuam fortemente acoplados à instância `DesktopPet` e aos seus atributos. `EventBus` é a infraestrutura de eventos entre workers e a thread Tk; `StateManager` centraliza parcialmente estados visuais durante uma migração incremental.

```text
Tkinter / desktop_pet.py (composição e ciclo tick)
├── UI: desktop_pet_ui.py, preferences_*_ui.py, painéis
├── comportamento: animation/loader/controllers, routines, personality.py
├── tarefas locais: app_intents.py, assistant_actions.py, automations.py
├── IA: ai.request_handler → AICore → ContextManager + prompts → ModelRouter
│   └── providers/* → Ollama local (único backend de geração)
├── estado e extensões: EventBus, StateManager, PluginManager, PermissionManager
├── integração local: X11, apps Linux, Spotify, manutenção, psutil
└── dados: JSON em ~/.config/desktop_pet e ~/.desktop_pet_history.json
```

## Módulos por responsabilidade

| Área | Arquivos | Responsabilidade atual |
|---|---|---|
| Composição e experiência | `desktop_pet.py`, `desktop_pet_ui.py`, `ui_theme.py`, `calendar_view.py`, `preferences_ui.py`, `preferences_*_ui.py`, `dashboard_ui.py`, `notifications_ui.py`, `permissions_ui.py` | Ciclo da aplicação, janelas Tkinter, preferências e telas. A composição da raiz ainda importa e conecta quase todas as áreas. |
| Animação e estado da mascote | `animation.py`, `animation_loader.py`, `animation_controller.py`, `interaction_controller.py`, `routine_controller.py`, `speech_controller.py`, `window_controller.py`, `device_controller.py`, `state_manager.py`, `config.py`, `assets/` | Decodificação OpenCV/NumPy/Pillow, worker de carregamento, desenho/interação, temporizadores, falas, janela e transições de estado. |
| IA conversacional | `ai/ai_core.py`, `ai/context_manager.py`, `ai/model_router.py`, `ai/prompts.py`, `ai/personality.py`, `ai/request_handler.py`, `providers/*` | Construção de contexto e prompt, personalidade textual, seleção do modelo, HTTP e normalização de erros. |
| Personalidade comportamental | `personality.py`, `assistant_actions.py`, partes de `routine_controller.py` e `speech_controller.py` | Catálogo amplo de falas, seleção aleatória, limites de fala espontânea e intents locais de conversa. |
| Tarefas e automações | `app_intents.py`, `automations.py`, `autonomy.py`, `assistant_actions.py`, `routine_controller.py`, `preferences_computer_ui.py`, `spotify_control.py` | Reconhecimento local, leitura de arquivos/sistema, prévias, organização reversível, lembretes, apps, APT e Spotify. |
| Plugins e permissões | `plugin_manager.py`, `permissions.py`, `permissions_ui.py` | Plugins internos registrados explicitamente e subprocessos externos por manifesto; permissões negadas por padrão, persistidas e verificadas por chamada. |
| Persistência | `json_persistence.py`, `autonomy.py`, `ollama_client.py`, `notifications.py`, `permissions.py` | JSON local, gravação atômica, preservação de arquivo corrompido, preferências, histórico, notificações e grants. |
| Concorrência e observabilidade | `event_bus.py`, `system_monitor.py`, `dashboard_ui.py`, `tools/nova_soak.py` | Eventos enfileirados para thread UI, amostragem de sistema e ferramenta de soak em processo separado. |
| Dependências de plataforma | `x11_helper.py`, `spotify_control.py`, `preferences_computer_ui.py` | X11 opcional, OAuth/API Spotify, subprocessos Linux e comandos do sistema. |

## Fluxo da conversa e ações

A interface em `desktop_pet.py` aplica primeiro respostas/intents locais (data, calendário, personalidade simples, automações e aplicativos). Essas rotas podem não chamar modelo. Pedidos para apps mostram comando e confirmação. Automações com mudanças de arquivos oferecem prévia e confirmação; há operações destrutivas específicas com confirmação. Outras mensagens seguem em worker para `ai.request_handler.answer_request`, voltam à UI por fila/callback e são persistidas no histórico curto via `ollama_client.py`.

Na trilha moderna: `AICore.process_message()` chama `ContextManager.build()`, monta prompt através de `ai.prompts`/`ai.personality.Personality`, então delega a `ModelRouter.generate()`. O roteador permite somente Ollama local e não faz fallback remoto. `ContextManager` limita histórico a 12 mensagens e 16 mil caracteres; considera até 8 memórias explícitas (3 mil caracteres no total) por sobreposição lexical com a última pergunta.

## Memória, personalidade e aprendizado

- `settings.json` contém `memories`, preferências, rotinas e configurações; as memórias são textos explícitos cadastrados/geridos pela pessoa usuária.
- `~/.desktop_pet_history.json` contém uma janela curta de mensagens de usuário/assistente, com timestamps locais acrescentados pelo fluxo da aplicação. Não é uma base de conhecimento ou mecanismo de recuperação semântica.
- `ContextManager` faz seleção lexical simples; não há embeddings, índice vetorial, sumarização episódica ou ciclo automático de atualização da memória observado.
- `ai/personality.py` constrói instruções estáveis e enumera estados conversacionais, mas o prompt padrão cria `Personality` em estado calmo; a integração do estado visual dinâmico ao prompt não é evidente na chamada atual.
- `src/personality.py` é um sistema distinto de falas e comportamento espontâneo, não o mesmo módulo que `ai/personality.py`.
- Na auditoria de 5 de novembro de 2026, não foi encontrada implementação de aprendizado de parâmetros, treinamento/finetuning, avaliação contínua ou mudança autônoma de política com base em experiências. O projeto observado era um cliente/orquestrador de modelos.

## Atualização posterior à auditoria

- O `MemoryManager` existente usa SQLite com categorias tipadas, consentimento e proveniência; as memórias continuam sendo cadastradas ou geridas explicitamente pela pessoa usuária.
- `nova_ai.desktop_integration` conecta o fluxo de IA existente à identidade permanente, às regras, às preferências do perfil e aos estados visuais, sem criar um roteador paralelo.
- `PreferenceLearner` é opcional e vem desligado; quando habilitado, armazena apenas contagens de sinais explícitos de estilo por perfil, sem texto bruto. Adaptações só entram no prompt após evidências repetidas em pelo menos três dias. `EmotionDetector` usa pistas explícitas apenas durante a resposta atual e não persiste emoção nem produz diagnósticos.
- Estados temporários incluem CALM, CURIOUS, CARING, PLAYFUL, FOCUSED e RESTING, além dos estados visuais legados. Memórias de projeto explicitamente salvas podem ser retomadas nas saudações, com cooldown configurável, silêncio e limites existentes.
- Não há treinamento/finetuning de modelos; a adaptação é local, determinística e limitada ao estilo conversacional.
- Ollama é o único backend de geração ativo. Os adaptadores de IA remota, o acesso a credenciais do sistema e seus controles de configuração foram removidos; configurações antigas são normalizadas para o backend local.

## Dados locais referenciados

`settings.json`, `permissions.json`, `notifications.json`, `downloads_undo.json` e histórico ficam nos caminhos descritos no README. A persistência de configurações, permissões, notificações e histórico usa escrita atômica e rotinas para preservação de JSON inválido. Essa auditoria não abriu nem leu os arquivos do perfil do usuário.

## Dependências externas e recursos

Dependências Python obrigatórias declaradas: Pillow, opencv-python-headless, NumPy e psutil. Tkinter e componentes Python do sistema são requisito Linux, não estão no `requirements.txt`. `python-xlib`, Ollama, bubblewrap e prlimit são opcionais conforme os recursos. A conversa usa HTTP local para Ollama; Spotify usa HTTP/OAuth e app local. Detalhamento em [dependency_map.md](dependency_map.md) e [offline_capabilities.md](offline_capabilities.md).

## Testes observados

A pasta `tests/` contém 15 arquivos de teste: IA/provedores, persistência, personalidade, automações, permissões/segredos, plugins/arquitetura, controladores, startup, UI, animação, Spotify e soak harness. O workflow declara matriz Python 3.10–3.13, Ruff, Bandit, `pip-audit`, cobertura via `coverage` e job gráfico Tk sob Xvfb. Não foi localizado relatório de cobertura versionado nem percentual mínimo no workflow. Esta fase não executou testes; estado de CI atual não foi consultado.
