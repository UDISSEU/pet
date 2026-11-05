# Fase 12 — integração cognitiva

Data: 5 de novembro de 2026

## Fluxo anterior

O `DesktopPet.ask_menu()` roteava algumas tarefas diretamente para automações legadas e encaminhava as demais mensagens ao `answer_request()` em worker. Os módulos `nova_ai.cognition` e `nova_ai.actions` existiam, mas não participavam do fluxo de conversa da janela.

## Fluxo integrado

1. O classificador offline por regras reconhece apenas pedidos de organização de Downloads. Conversas e tarefas não suportadas continuam no roteamento legado.
2. `CognitiveEngine` usa o `Planner` estático; `ResultValidator` limita intenções, operações, parâmetros estruturais e dependências.
3. A UI pede concessão de cada permissão em diálogo próprio. Uma permissão concedida não confirma a movimentação.
4. Com permissões presentes, o dispatcher executa somente `files.preview_downloads` e constrói uma prévia.
5. A UI apresenta nomes e destinos e aguarda confirmação explícita.
6. A execução ocorre em worker, reconsulta permissões no dispatcher, usa cancelamento cooperativo e rollback da operação de arquivos.
7. O resultado passa por validação estrutural e verificação independente de origem/destino.
8. A Nova apresenta o resultado e pergunta separadamente se deve desfazer. A restauração revalida permissões e exige confirmação.

Nenhum texto livre do modelo é transformado em chamada de ferramenta. A classificação de tarefa é por regras locais, nomes de operação são constantes e registradas, e o modelo conversacional existente continua responsável por conversa comum.

## Módulos envolvidos

- `desktop_pet.py`: roteamento, diálogos e callbacks na thread Tk; preparação, execução e undo em workers.
- `nova_ai/desktop_integration.py`: composição de core, memória, personalidade, registry e `CognitiveEngine`.
- `nova_ai/cognition/*`: classificação, plano, decisões, validação e execução.
- `nova_ai/actions/*`: allowlist, revalidação de permissão, cancelamento, timeout e ferramentas locais.
- `nova_ai/actions/file_manager.py`: operações ancoradas em descritores e rollback, endurecidos na Fase 11.

## Testes

- `python3 -m unittest tests.nova_ai.test_desktop_integration tests.nova_ai.test_cognition tests.nova_ai.test_actions`: **39 aprovados**.
- Cenários cobertos: conversa comum sem ferramenta, intenção reconhecida/desconhecida, plano inválido, ausência/revogação de permissão, confirmação recusada/concedida, execução real em diretório temporário, cancelamento entre arquivos com rollback, timeout/erro de ferramenta e desfazer.
- `py_compile` de `desktop_pet.py`, `desktop_integration.py` e `cognitive_engine.py`: aprovado.

## Limitações

- A UI Tk real não pôde ser inicializada neste ambiente porque `cv2` está ausente; seus callbacks foram compilados, mas testes de clique/janela dependem do ambiente gráfico e das dependências desktop.
- A primeira versão suporta exclusivamente a organização de arquivos diretamente em Downloads. Outras ações cognitivas permanecem fora da allowlist.
- O undo assinado é válido durante o processo atual; reiniciar a aplicação invalida a autorização efêmera de restauração.
- Falha do modelo classificador opcional não é necessária para a tarefa implementada: a regra offline é a fonte de intenção e não consulta modelo.
