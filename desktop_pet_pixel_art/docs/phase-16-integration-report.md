# Fase 16 — integração e validação

Data: 5 de novembro de 2026

## Estado

**Validação parcial; critérios de conclusão de ponta a ponta ainda não aprovados.** Os componentes locais e a inferência Ollama foram exercitados, mas a janela Tk e animações não puderam ser iniciadas neste ambiente.

## Arquitetura integrada

- `DesktopPet` continua sendo a composição Tkinter e conserva o ciclo de animação existente, os eventos e a fila de callbacks para workers.
- Conversa comum usa `AICore`/`ModelRouter`; memória e personalidade alimentam contexto e prompt.
- Somente pedido reconhecido de organização de Downloads entra no caminho cognitivo. `IntentClassifier` offline → plano estático → `ResultValidator` → pedido de permissões → prévia → confirmação separada → `ToolDispatcher`/allowlist → validação e verificação → resultado e opção de undo.
- As ferramentas revalidam permissões no momento da execução. Cancelamento cooperativo e rollback protegem movimentações em lote.
- O banco SQLite continua local e consentido. Preferências são persistentes, humor visual é transitório. Provedores externos seguem opcionais, e o Ollama local é limitado por contexto, tokens, threads e concorrência.
- O laboratório Nova Model 0.1 permanece separado; não carrega automaticamente nem interfere no provedor de conversa.

## Cenários executados

| Cenário | Resultado observado |
|---|---|
| Conversa comum sem ferramenta | Teste unitário aprovou roteamento sem acionar ferramenta |
| Memória, reinício, consulta, atualização e exclusão | Testes SQLite temporários aprovados; inclui migração de schema e corrupção |
| Personalidade, preferências e estados | Testes aprovados; preferências persistem e humor transitório reinicia em IDLE |
| Organização, permissão, prévia, confirmação, execução, cancelamento e undo | Testes com diretórios temporários aprovados |
| Inferência sem provedor remoto | Uma inferência real Ollama local com `llama3.2:1b` concluiu em 7,744 s |
| Recuperação de API remota indisponível | Fallback local coberto por mocks; indisponibilidade remota real não foi provocada |
| Interface, janelas, foco e animações | Bloqueado: ambiente virtual `.venv` ausente; `cv2` também ausente |
| Soak de 30 minutos e ausência de processos órfãos da GUI | Não executados; requerem ambiente gráfico funcional |

## Testes executados

- `python3 -m unittest discover -s tests/nova_ai`: **79 aprovados, 2 ignorados** (PyTorch CPU ausente).
- `python3 -m unittest tests.test_ai_providers tests.test_personality tests.test_automations tests.test_keyring_secret tests.test_ui_windows`: **59 aprovados, 1 ignorado**.
- Testes de segurança de arquivos: 24 aprovados dentro da suíte cognitiva.
- `python3 -m compileall -q src training tools`: aprovado.
- `bash -n tools/nova_gui_test.sh tools/nova_gui_cleanup.sh install.sh`: aprovado.
- `git diff --check`: aprovado.

Tentativa da suíte pedida com `python3 -m pytest -v`: não iniciou porque `pytest` não está instalado. A descoberta total alternativa, `python3 -m unittest discover -s tests`, contou 115 casos e terminou com 26 erros, 1 falha e 2 skips. Os erros incluem a descoberta dos testes `nova_ai` como pacote top-level, que sombreia o pacote de código, e importações da GUI que encerram sem OpenCV. A falha restante é o teste do harness soak, que também depende de `cv2`. A suíte `tests/nova_ai` e os grupos independentes acima foram rodados com caminhos de importação corretos e passaram.

## Recursos medidos

- Quatro CPUs visíveis no ambiente; aproximadamente 3,6 GiB de RAM total utilizável.
- Uma inferência local: Ollama reportou modelo residente de 1,4 GB, uso 100% CPU e contexto 512. RAM disponível observada variou de ~510 MiB a ~300 MiB; o sampler não vê o processo runner do Ollama no namespace, então essa variação não deve ser atribuída exclusivamente ao modelo.
- O processo Python do benchmark usou ~24 MiB RSS e uma thread. O sampler registrou até 11 threads no processo Ollama visível. Checkpoints do modelo experimental: 0 bytes.
- Nenhum treino, download, soak ou inferência simultânea foi iniciado.

## Problemas encontrados e correções nesta rodada

- Plano cognitivo enviava `path` do planner ao organizador em vez de usar somente o plano assinado da prévia; execução agora recebe apenas os dados da prévia validada.
- Cancelamento capturado como falha genérica; agora é reportado como cancelado após a ferramenta reverter movimentos concluídos.
- Dados de memória não distinguiam categorias de perfil/projeto/conversa/aprendizado ou expiração/proveniência; schema v1 migra transacionalmente para v2.
- Preferências Ollama não limitavam contexto/resposta/threads; limites conservadores agora são configuráveis e a inferência local é serializada.
- O teste isolado de modelo experimental não configurava `src` em `sys.path`; corrigido para poder ser executado individualmente.

## Compatibilidade, pendências e próximos passos

- Compatibilidade da UI em X11, Xwayland e Wayland nativo não foi verificada. `tools/nova_gui_test.sh smoke` parou com “Ambiente virtual ausente”; não iniciou servidor gráfico. Nenhuma captura foi gerada.
- Os dois testes de ciclo de vida do modelo experimental continuam ignorados sem PyTorch; treino, checkpoint e geração desse modelo seguem não validados.
- O comportamento visual integrado à janela foi compilado, mas não clicado nem observado em runtime.
- Para aprovar a fase: preparar `.venv` com dependências declaradas, instalar Pytest e PyTorch CPU opcional, executar `python -m pytest -v`, rodar o smoke gráfico e soak em ambiente Xvfb configurado, depois validar com rede desabilitada e medir o aplicativo completo (threads, processos, RSS, CPU e responsividade). Capturar separadamente resultados X11/Xwayland/Wayland.

Não houve commit, push, merge ou deploy.
