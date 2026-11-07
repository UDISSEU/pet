# Mapa de dependências e acoplamentos

## Grafo principal

```text
src/desktop_pet.py
├─ autonomia.py ─ json_persistence.py
├─ assistant_actions.py / app_intents.py / automations.py
│  └─ json_persistence.py
├─ ai.request_handler.py
│  └─ ai.ai_core.py
│     ├─ ai.context_manager.py
│     ├─ ai.prompts.py ─ ai.personality.py + assistant_actions.py
│     └─ ai.model_router.py ─ providers.provider_factory.py
│        └─ providers.ollama_provider.py ─ base_provider.py
├─ ollama_client.py (histórico legado + função direta Ollama)
├─ controllers / UI (Tkinter e módulos de domínio)
├─ event_bus.py ─ state_manager.py / notifications.py / system_monitor.py
├─ plugin_manager.py ─ permissions.py + subprocess/bwrap/prlimit
├─ spotify_control.py (OAuth/API e app local)
└─ x11_helper.py (python-xlib opcional)
```

## Dependências entre áreas

| Origem | Depende de | Observação de acoplamento |
|---|---|---|
| `desktop_pet.py` | Quase todos os serviços, controladores e integrações | Maior ponto de composição e provável gargalo de alteração. Importa diretamente provider factory e `ProviderError`, além de `answer_request`; parte da lógica de IA vaza para a camada principal. |
| `ai.request_handler` | `AICore`, `ProviderError` | Ponto adequado para fronteira de aplicação; converte falhas em resposta da UI. |
| `ai.ai_core` | ContextManager, ModelRouter, prompts | Abstração útil, mas ainda entende formato de settings e estrutura de provedor. |
| `ai.model_router` | `SUPPORTED_PROVIDERS`, fábrica concreta, settings flat | Roteamento conhece nomes explícitos, regras de privacidade e fallback para Ollama. |
| `providers.provider_factory` | Cada adaptador concreto | Importa os quatro providers no carregamento; adicionar provider exige alterar a fábrica e validação/settings. |
| `autonomy.py` | `json_persistence.py`, XDG/applications, arquivos de usuário | Mistura settings, agenda/quiet hours e descoberta/validação de apps. |
| `automations.py` | `json_persistence`, FS, shutil/hashlib | Mistura reconhecimento de frases, leitura, prévias e execução de ações. Reconhecimento e executor existem no mesmo módulo. |
| `personality.py` + controllers | `config.py`, estado temporário, preferências | Falas e comportamento distribuídos entre personalidade, configuração e mixins. |
| `plugin_manager.py` | `permissions.py`, EventBus, subprocesso | Plugin interno executa no processo confiável; plugin externo em subprocesso configurado com bubblewrap/prlimit. |
| `preferences_*_ui.py` | diretamente serviços e estado da aplicação | UI não é apenas adaptador de apresentação; algumas abas chamam funções de domínio/persistência diretamente. |
| `notifications.py` / `system_monitor.py` | arquivos locais, psutil/pathlib, EventBus | Serviços razoavelmente reutilizáveis, porém inicialização e consumo ligados à janela principal. |

## Provedores e caminhos de execução

A interface comum é `BaseProvider.is_available/generate/test_connection`. `ModelRouter` e `provider_factory` permitem somente Ollama local e serializam uma chamada por vez com lock. Requisições usam `urllib` e JSON sem SDKs específicos; erros locais não recorrem a provedores remotos.

As preferências e o painel apresentam Ollama como backend único. `autonomy.py` migra configurações antigas para Ollama e remove opções de provedores remotos ao salvar.

### Trilha Ollama duplicada

`providers/ollama_provider.py` é o adaptador da arquitetura nova. `ollama_client.py` também implementa `ask_local_ai()` com HTTP próprio, construção própria de prompt e persistência de histórico. O uso central do `ollama_client` no fluxo atual é histórico (`load_history/save_history`) e há função de geração legada. Essa duplicação pode causar comportamento divergente de timeout, contexto, erros e prompt caso a função antiga seja reativada.

### Personalidade duplicada

`ai/personality.py` oferece identidade e instrução ao LLM; `src/personality.py` define catálogo e cadência de falas da mascote. A separação de finalidade é legítima, mas a palavra “personalidade” oculta contratos diferentes e comportamento pode divergir entre texto gerado e fala local.

## Responsabilidades sobrepostas

- Estado/configuração/memória: `autonomy.py` carrega, saneia e salva configurações, enquanto partes da UI/editors e `desktop_pet.py` atualizam o mesmo dicionário e chamam persistência.
- Histórico/IA: `ollama_client.py` combina armazenamento de histórico, cliente Ollama legado e prompt; a arquitetura `ai/` separa contexto e provider.
- Intents/tarefas: `assistant_actions.py`, `app_intents.py` e `automations.py` reconhecem frases localmente; o roteamento dessas decisões está no `desktop_pet.py`.
- Poses/estado: `state_manager.py` migra gradualmente a lógica mantida em `animation_controller.py` e `DesktopPet.state`.
- Falas/persona: `src/personality.py`, `ai/personality.py`, `ai/prompts.py` e controllers contribuem para a saída conversacional/comportamental.
- Filas entre trabalhadores: EventBus tem fila própria; alguns controladores também usam fila/callbacks UI. A documentação de arquitetura descreve ambos, logo limites e política de erro/descarte devem permanecer claros.

## Fronteiras reutilizáveis para evolução

Boas candidatas a interfaces estáveis: `BaseProvider`, `ContextManager`, `AICore`, `EventBus`, `StateManager`, `PermissionManager`, `NotificationManager`, `PluginManifest`/`PluginManager`, e `json_persistence`. A reutilização deve preservar independência de Tkinter e evitar permitir que memória ou modelo autorize operações diretamente. Persistência de chat e memória deve migrar por adaptadores/versionamento, não por edição in-place durante a primeira migração.
