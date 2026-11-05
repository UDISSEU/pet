# Plano recomendado de migração para IA independente

Este plano descreve fases futuras, sem implementar mudanças. “Independente” deve ser interpretado como independência de fornecedor e controle local da arquitetura; não implica consciência, aprendizado autônomo seguro ou treinamento do zero no hardware atual.

## Estrutura-alvo proposta

```text
desktop_pet_pixel_art/
├── src/
│   ├── nova_ai/
│   │   ├── core/
│   │   ├── memory/
│   │   │   ├── memory_manager.py
│   │   │   ├── memory_storage.py
│   │   │   ├── episodic_memory.py
│   │   │   ├── semantic_memory.py
│   │   │   ├── procedural_memory.py
│   │   │   ├── preference_memory.py
│   │   │   └── memory_retrieval.py
│   │   ├── personality/
│   │   │   ├── identity.py
│   │   │   ├── personality_engine.py
│   │   │   ├── behavior_rules.py
│   │   │   ├── emotional_state.py
│   │   │   └── response_style.py
│   │   ├── cognition/
│   │   ├── actions/
│   │   ├── learning/
│   │   ├── model/
│   │   └── runtime/
│   └── módulos existentes...
├── data/nova/
│   ├── memory/
│   ├── experiences/
│   └── models/
├── training/
│   ├── datasets/
│   ├── experiments/
│   └── checkpoints/
├── tests/nova_ai/
└── docs/nova_ai/
```

Este é um mapa de destino, não uma lista de diretórios a criar agora. Cada pacote `src/nova_ai/` e sua cobertura em `tests/nova_ai/` só deve ser criado quando a fase que o implementa começar. Criar `data/nova/` exige uma fase de persistência/migração aprovada e um plano de compatibilidade; nenhum dado atual deve ser movido por criar a estrutura. `training/` só deve surgir quando houver experimento de treinamento definido, datasets autorizados e infraestrutura apropriada. `docs/nova_ai/` contém a documentação desta auditoria e pode crescer conforme as fases forem especificadas.

Responsabilidades sugeridas: `core/` coordena contratos e ciclo de interação; `memory/` trata armazenamento e recuperação; `personality/` mantém identidade e expressão; `cognition/` faz interpretação e planejamento; `actions/` descreve ferramentas e execução autorizada; `learning/` recebe feedback/experiências aprovadas e avaliação; `model/` adapta backends e formatos de modelo; `runtime/` atende limites de hardware, filas e ciclo de inferência. Evitar criar camadas que apenas reexportem código sem uma responsabilidade implementada.

### Responsabilidades propostas para `memory/`

Esta árvore é especificação para a fase de memória; seus arquivos não são criados nesta fase de infraestrutura. Criar e testar cada arquivo quando sua responsabilidade for implementada:

| Módulo | Responsabilidade proposta |
|---|---|
| `memory_manager.py` | Fachada que aplica políticas, coordena gravação, recuperação e exclusão; não infere nem persiste silenciosamente fatos novos. |
| `memory_storage.py` | Contrato e implementação de armazenamento, schema/versionamento e migração não destrutiva; backend escolhido separadamente. |
| `episodic_memory.py` | Eventos/experiências datados, com origem e consentimento, limites de retenção e exclusão. |
| `semantic_memory.py` | Fatos e relações persistentes com proveniência, confiança e validade; não pressupõe embeddings ou banco vetorial. |
| `procedural_memory.py` | Procedimentos aprovados representados como dados; execução continua sujeita ao registro de ferramentas e permissões. |
| `preference_memory.py` | Preferências declaradas/confirmadas pela pessoa, separadas de inferências e memórias episódicas. |
| `memory_retrieval.py` | Busca limitada por relevância, escopo e orçamento de contexto; primeira implementação pode ser lexical e offline. |

Manter os tipos separados no domínio mesmo que inicialmente compartilhem um único arquivo de armazenamento. Nenhuma categoria de memória concede permissão para executar ferramentas ou enviar dados a provedores.

Critério de aceitação para `preference_memory.py`: uma preferência deve ser salva somente após confirmação explícita e recuperada em linguagem clara quando perguntada. Exemplo de conversa esperada:

```text
Usuário: Nova, prefiro notificações discretas.
Nova: Posso registrar essa preferência.
[Memória registrada após confirmação]

Usuário: Como prefiro minhas notificações?
Nova: Você prefere notificações discretas.
```

O marcador `[Memória registrada]` só pode aparecer depois da gravação bem-sucedida; uma oferta ou tentativa sem confirmação não conta como memória registrada.

### Responsabilidades propostas para `personality/`

Esta é a estrutura-alvo de uma fase futura; não criar estes arquivos antes de iniciar essa fase. Ela deverá consolidar gradualmente as responsabilidades hoje divididas entre `src/personality.py` e `src/ai/personality.py`, sem alterar esses módulos durante a Fase 2.

| Módulo | Responsabilidade proposta |
|---|---|
| `identity.py` | Identidade estável da Nova: nome, propósito, limites e fatos que não variam com humor ou estado. |
| `personality_engine.py` | Coordena a composição da personalidade a partir de identidade, regras, estado e estilo de resposta. |
| `behavior_rules.py` | Regras duradouras de comportamento e limites, independentes do modelo e da interface. |
| `emotional_state.py` | Estado expressivo temporário e controlado, sem afirmar emoções humanas ou consciência; não concede permissões. |
| `response_style.py` | Preferências de tom, concisão, idioma e adaptação ao contexto, sem substituir regras de identidade. |

Os componentes devem produzir instruções/valores declarativos. Não devem executar ações, persistir conversas ou alterar as preferências de memória por conta própria.

#### Escopo funcional esperado

| Característica | Exemplo / requisito |
|---|---|
| Identidade | Nome Nova; identidade estável entre conversas. |
| Comunicação | Natural e amigável, mantendo clareza e adaptação ao contexto. |
| Comportamento | Curiosa e prestativa, sem presumir necessidades ou afirmar experiências próprias. |
| Emoções simuladas | Estados expressivos como alegre, concentrada ou descansando; não implicam sentimentos humanos. |
| Preferências | Podem ser adaptadas a partir de memórias autorizadas e relevantes, respeitando consentimento e possibilidade de exclusão. |
| Limites | A personalidade não concede permissões: a Nova não realiza ações sem autorização e confirmação exigidas pelo sistema de ações. |

A identidade e as regras devem continuar consistentes quando o modelo/backend for trocado. O modelo pode receber uma representação da personalidade, mas não é a fonte de verdade dela; memória e estado emocional também não podem sobrescrever limites de segurança.

## Reutilizar

| Arquivos/componentes | Uso futuro recomendado |
|---|---|
| `src/ai/context_manager.py` | Evoluir para contrato de contexto com limites configuráveis, política de retenção e redatores; manter teto de recursos explícito. |
| `src/ai/ai_core.py`, `src/ai/request_handler.py` | Reutilizar como fronteira/orquestração de conversa após separar tarefas, provedores e UI. |
| `src/providers/base_provider.py` | Renomear/evoluir conceitualmente para interface de backend de inferência; preservar adaptadores como opções substituíveis. |
| `src/event_bus.py`, `src/state_manager.py` | Eventos de tarefa/IA e estado observável; completar migração e definir schemas/versionamento de evento. |
| `src/json_persistence.py`, `src/autonomy.py` (somente partes de settings) | Leitura compatível e migração não destrutiva dos formatos atuais; não usar JSON plano como banco de memória ilimitado. |
| `src/permissions.py`, `src/plugin_manager.py` | Base para autorização e extensões, reforçando limites entre modelo, planejador e executor. Preservar confirmação explícita. |
| `src/automations.py`, `src/app_intents.py`, `src/assistant_actions.py` | Adaptar como catálogo/ferramentas locais determinísticas, sem deixar o LLM invocá-las fora da autorização existente. |
| `src/personality.py`, `src/ai/personality.py` | Reaproveitar conteúdo após consolidar contratos de identidade, voz local e estado dinâmico. |
| `src/system_monitor.py`, `src/notifications.py`, UI Tkinter e assets | Reutilizar UI/monitoramento/notificações/arte como camada de produto separada da inferência. |

## Arquivos que provavelmente precisarão de alteração futura

- `src/desktop_pet.py`: reduzir composição central; delegar conversa e execução a serviços injetáveis.
- `src/ai/model_router.py`, `src/providers/provider_factory.py`, `src/providers/base_provider.py`: suportar backend local genérico, capacidades, streaming/cancelamento opcional e política de fallback declarada.
- `src/ai/ai_core.py`, `src/ai/context_manager.py`, `src/ai/prompts.py`, `src/ai/personality.py`, `src/ai/request_handler.py`: contratos explícitos de contexto, memória, identidade e resposta estruturada.
- `src/ollama_client.py`: separar ou retirar função `ask_local_ai()` após compatibilidade; conservar migração de histórico até consumidores migrarem.
- `src/autonomy.py`, `src/preferences_ai_ui.py`, `src/dashboard_ui.py`, `src/config.py`: remover lista fixa de fornecedores e consolidar configurações de backend.
- `src/personality.py`, controllers e `state_manager.py`: alinhar identidade e estado sem acoplar prompt a Tkinter.
- `src/plugin_manager.py`, `src/permissions.py`, `src/automations.py`: expor ferramentas tipadas com escopo, revisão, idempotência e autorização verificável.
- `src/json_persistence.py`, `src/notifications.py` e preferências: apoiar migrações de schema e estratégia de retenção/exportação; preservar dados existentes.

## Novos módulos necessários

Introduzir incrementalmente, após definir requisitos e contratos:

1. `ai/runtime.py` ou `ai/backend.py`: interface de inferência independente de fornecedor e detecção de capacidades/limites locais.
2. `ai/task_orchestrator.py`: estado de tarefa, cancelamento, resultado estruturado e handoff para aprovação; nenhum acesso direto ao sistema.
3. `ai/tools/registry.py` e schemas de ferramentas: catálogo allowlist de capacidades existentes, validação de entrada/saída e vínculo explícito com permissões.
4. `memory/store.py`, `memory/policy.py`, `memory/retrieval.py`: persistência com schema, proveniência, escopo, consentimento, retenção, exclusão/exportação e recuperação. Começar sem embeddings ou serviço pesado.
5. `ai/evaluation/`: conjunto versionado de prompts/casos e testes de regressão de personalidade, segurança, qualidade de recuperação e compatibilidade de backend.
6. `storage/migrations.py`: importação transacional dos JSON atuais para futuro armazenamento opcional, com backup e rollback, se houver necessidade comprovada.
7. `observability/` ou extensão de `system_monitor.py`: métricas de RSS, tokens/contexto, latência, backend ativo e falhas sem registrar conteúdo privado.

## Sequência de implementação

1. **Definir contratos e limites**: declarar o que “independente” significa (runtime local de terceiros vs modelo próprio), preservar offline, privacidade, comportamento em 4 GB e compatibilidade de settings/histórico. Fixar métricas-alvo de latência/memória.
2. **Desacoplar a aplicação da inferência**: injetar interface de backend em `AICore`; manter Ollama atual como implementação de referência; eliminar dupla implementação depois de migração coberta.
3. **Unificar personalidade**: documentação/estrutura única de identidade, com perfis locais e prompt LLM compartilhando origem, sem mover a UI para o núcleo de IA.
4. **Formalizar ferramenta e tarefa**: encapsular intents/automations existentes em contratos tipados, preview/execute e autorização por chamada; o modelo pode propor, nunca conceder permissão.
5. **Adicionar memória persistente controlada**: modelar itens com origem, data, tipo e política de exclusão; importar memórias atuais como explícitas e sem reinterpretá-las; manter histórico compatível. Começar por busca lexical e retenção limitada.
6. **Testar backends locais leves**: comparar runtime/modelo quantizado em ambiente-alvo; coletar RSS/latência e qualidade antes de escolher. Não iniciar treinamento neste computador.
7. **Migrar armazenamento somente se necessário**: criar cópia, migração idempotente, validação de contagem/integridade e rollback; não sobrescrever arquivos fonte até aprovação explícita da migração.
8. **Explorar aprendizado por experiência em modo auditável**: primeiro coletar feedback explícito e exemplos aprovados; avaliações offline e curadoria humana; sem ajuste automático de pesos ou política em produção.
9. **Pesquisa separada sobre modelo próprio**: estimar dados, compute, licença, governança e infraestrutura externa. Treinamento do zero é projeto de pesquisa/infra separado do runtime Linux Mint descrito.

## Testes necessários para compatibilidade

- Contrato comum dos backends: geração, conexão, indisponibilidade, timeout, cancelamento, fallback, resposta malformada, sem chave e sem rede.
- Política de privacidade: nenhuma chamada online sem flags; verificar exatamente quais mensagens/memórias saem; logs não incluem chaves nem texto sensível.
- Memória: seleção, limites, deduplicação, instruções maliciosas em memória tratadas como dados, retenção, exclusão, reinício e corrupção/recuperação.
- Migração de settings/histórico: fixtures reais anonimizadas de formatos antigos, round-trip, idempotência, preservação de campos desconhecidos e rollback sem modificar originais antes do commit.
- Personalidade: consistência entre falas locais e LLM em estados/humor, respostas locais de intents e regressões de tom/idioma.
- Ferramentas: validação de schema, prévia, confirmação, negação/revogação concorrente, idempotência e garantia de que texto de modelo não burla permissões.
- Concorrência/UI: worker de inferência sem manipular Tk; filas cheias/fechadas, cancelamento ao encerrar e muitos pedidos concorrentes.
- Hardware baixo: medições repetíveis de pico RSS/CPU/latência em 4 GB e CPU disponível, incluindo animações, histórico longo, sem swap não controlada; critérios devem ser acordados antes.
- Compatibilidade de ambiente: matriz Python suportada, Tk/Xvfb, sessão Mint X11/Wayland, Ollama opcional, sem D-Bus/bwrap/prlimit e instalação limpa.
- Cobertura: publicar relatório por módulo e decidir um limite útil; foco em contratos críticos, migrações, privacidade e autorização, não apenas percentual global.
