# Fase 17 — Estabilidade e validação cognitiva

Data: 5 de novembro de 2026  
Branch: `Nova-IA`

## Estado da fase

**Parcial; critérios de conclusão não aprovados.** O roteamento do organizador de Downloads foi endurecido e os testes focados em cognição, segurança dos arquivos, memória e personalidade passaram. A suíte geral e a interface gráfica não puderam ser aprovadas neste ambiente por dependências ausentes. Não foi iniciado treinamento.

## A. Alterações realizadas

- `src/nova_ai/desktop_routing.py`: roteia solicitações para uma intenção cognitiva suportada antes de consultar automações legadas; mantém intenções antigas não migradas no fluxo legado; encaminha pedidos ambíguos de organização ao Cognition para esclarecimento, sem inferir Downloads. Se o Cognition falhar ou estiver indisponível, não libera o organizador legado.
- `src/desktop_pet.py`: usa o roteador compartilhado no fluxo de conversa e protege também o botão de organização em Preferências, que chamava `_request_automation()` diretamente. O worker de execução agora captura falhas inesperadas e envia um erro sanitizado pela fila da UI; o callback restaura `automation_active`, estado visual e diálogo de progresso antes de apresentar uma mensagem recuperável. O registro da interação deixou de ocorrer duas vezes no início da mesma tarefa.
- `tests/nova_ai/test_desktop_routing.py`: cobre pedidos reconhecidos, pedido ambíguo, automação antiga não migrada, indisponibilidade e falha do classificador.
- `tests/nova_ai/test_actions.py`: acrescenta testes para origem removida após a prévia e categoria trocada por symlink após a prévia.
- `tests/__init__.py`: permite descoberta de testes qualificada sem sombrear o pacote de produção `nova_ai`.
- `requirements-test.txt`: declara a suíte principal e Pytest em uma instalação de desenvolvimento isolada. PyTorch continua separado em `requirements-ml.txt`.

Nenhum arquivo pessoal foi usado; os testes de movimentação criam raízes temporárias. Não houve treinamento, commit, push, merge ou deploy.

## B. Segurança dos arquivos

O organizador cognitivo usa os descritores de diretório e `O_NOFOLLOW` para abrir a raiz e categorias, valida os nomes e caminhos canônicos, assina planos da prévia, verifica novamente identidade de origem e destino junto à movimentação, usa `renameat2(RENAME_NOREPLACE)` e tenta rollback em falhas. O desfazer também valida token, caminhos, identidade e colisões antes de restaurar.

Os testes existentes cobrem raiz Downloads simbólica, categoria simbólica, destino externo, traversal, symlink de origem, colisão, token adulterado, undo adulterado, interrupção com rollback e organização/restauração normais. Os novos testes cobrem remoção da origem e troca da categoria por symlink entre prévia e execução. A permissão revogada antes da execução e o cancelamento com rollback são cobertos em testes do fluxo cognitivo.

Limitação: a movimentação atômica depende do `renameat2` do Linux. Em sistemas sem esse mecanismo, a operação falha fechada com `ENOTSUP`; não existe fallback menos seguro. As garantias são exercitadas por testes locais temporários, mas esta rodada não executou teste de corrida concorrente sob carga adversarial.

## C. Integração cognitiva

Antes, `ask_menu()` chamava `recognize_automation()` antes de `classify_task()`, desviando a organização para o executor legado. Agora a classificação cognitiva suportada tem prioridade. O helper de roteamento não executa ferramentas; o fluxo continua sendo classificar → preparar e inspecionar → checar permissões → mostrar prévia → confirmação explícita → executar com revalidação → verificar → oferecer desfazer.

O caminho de Preferências também foi conferido: organização direta via `_request_automation()` agora chama o fluxo cognitivo. Outras automações registradas, como status do notebook, continuam no mecanismo legado. “Separe meus arquivos por tipo” é encaminhado para esclarecimento e nunca ganha implicitamente o alvo Downloads.

O worker de preparação já encaminhava exceções sanitizadas; o worker de undo já possuía captura própria. O worker de execução recebeu a mesma proteção. Todos entregam callbacks com `post_ui_callback`; nenhum callback cognitivo novo atualiza widgets dentro da thread de trabalho. A aplicação ignora callbacks pendentes depois do fechamento e cancela a operação de execução ativa no encerramento.

## D. Estabilidade

- Falha inesperada de execução cognitiva é registrada tecnicamente e apresentada sem mensagem interna detalhada; o callback limpa os controles e permite nova interação.
- Cancelamento durante movimentação e falha de permissão são convertidos em resultados de tarefa sem sucesso falso; rollback é verificado nos testes com diretórios temporários.
- Não houve medição de fila da aplicação desktop em execução. O harness `tools/nova_soak.py` não iniciou porque importa a animação e OpenCV está ausente.
- Não foi executado soak de cinco minutos.

## E. Memória e personalidade

Testes existentes de persistência, consentimento, recuperação, atualização, exclusão, conflito, expiração, banco corrompido, regras estáveis e transições emocionais passaram na suíte focada. Não foram introduzidas mudanças nesses subsistemas nesta fase.

## F. Testes

### Executados e aprovados

- `PYTHONPATH=src python3 -m unittest tests.nova_ai.test_actions tests.nova_ai.test_desktop_integration tests.nova_ai.test_desktop_routing tests.nova_ai.test_memory tests.nova_ai.test_personality_system -v`: **66 testes aprovados**.
- `python3 -m unittest discover -s tests/nova_ai -v`: **84 aprovados, 2 ignorados** (testes que exigem PyTorch).
- `python3 -m compileall -q src training tools tests`: aprovado.
- `bash -n tools/nova_gui_test.sh tools/nova_gui_cleanup.sh install.sh`: aprovado.
- `git diff --check`: aprovado.

### Executados com falhas ou bloqueios

- `PYTHONPATH=src python3 -m unittest discover -s tests -t .`: **187 testes descobertos; 13 erros, 1 falha e 4 ignorados**. Os erros de importação da interface/animação e a falha do harness soak decorrem de `cv2` ausente. A saída também contém logs esperados de testes que exercitam falhas de permissão, cancelamento e callbacks de plugins.
- `python3 -m pytest -v`: não iniciou: `No module named pytest`.
- `tools/nova_gui_test.sh smoke`: bloqueado antes de abrir o display: `.venv/bin/python` não existe.

### Não executados

- Testes gráficos reais, capturas, X11/Xwayland/Wayland separados e soak visual.
- Soak de cinco minutos e regressão completa com dependências instaladas.
- Treino, inferência do modelo experimental e retomada de checkpoint.

## G. Desempenho e ambiente

Snapshot do host durante a validação: Python 3.12.3, quatro CPUs visíveis, 3,6 GiB de RAM total, 336 MiB livres e cerca de 985 MiB disponíveis. `psutil` 5.9.8 existe. `cv2`, NumPy, PyTorch e Pytest não existem no Python disponível. Não foi possível medir RAM, CPU, threads, início ou resposta do aplicativo Nova nesta rodada, porque a aplicação não pôde ser importada sem OpenCV. A duração observada da suíte focada anterior foi 0,967 s para 64 casos; a execução final confirmou 66 casos sem erros. Isso mede os testes locais, não o desempenho do desktop ou do modelo.

Não instalei dependências no ambiente global nem criei um ambiente virtual: a memória disponível observada ficou abaixo de 1 GiB e não havia Pytest/OpenCV instalados. Para preparar um ambiente isolado quando houver memória livre suficiente:

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements-test.txt
python -m pytest -v
```

`requirements-ml.txt` é opcional e não deve ser instalado para a suíte normal. Não instale CUDA para este equipamento Intel integrado.

## H. Interface gráfica

Não houve validação gráfica real. A aplicação exige OpenCV para carregar vídeos de animação, e o harness configurado exige `.venv`; ambos estavam ausentes. Portanto, personagem, animações, prévia, janela de progresso e recuperação visual não foram aprovados nesta fase.

## I. Preparação do treinamento experimental

- Tokenizer: `ByteTokenizer` com vocabulário `Vocabulary`; vocabulário construído a partir dos textos de treino, com tamanho configurado entre 1.000 e 2.000.
- Dataset: `.txt` (um texto por linha) ou `.jsonl` (objeto por linha com campo textual `text`), lidos em fluxo; até 8.192 caracteres por linha, 25.000 registros examinados e 5.000 exemplos aceitos pela configuração atual. Duplicatas exatas são filtradas por hash.
- Partição: treino e validação determinísticos. Não há partição de teste independente; antes de comparar candidatos, deve-se reservar um conjunto de teste separado para evitar selecionar com base apenas na validação.
- Modelo: Transformer experimental CPU, FP32, batch 1, contexto máximo 64, uma thread. O padrão atual é `d_model=64`, duas cabeças e duas camadas; a configuração calcula 234.064 parâmetros e fica abaixo do teto de 300 mil.
- Checkpoint/métricas: checkpoints periódicos, loss de treino e validação em JSONL e histórico SQLite. A configuração padrão usa 100 passos e grava a cada 25.
- Retomada: não implementada pelo `TrainingManager.run()` atual. Ele cria IDs e diretórios de execução novos, salva checkpoints e não restaura optimizer/step de um checkpoint anterior. Retomada interrompida ainda precisa ser desenvolvida e testada antes de considerar o pipeline pronto.
- Dependência: o código importa PyTorch somente quando o treinamento começa e o projeto mantém essa dependência em `requirements-ml.txt`; PyTorch CPU não está instalado aqui. Nenhum treinamento foi iniciado.

Recomendação para o primeiro experimento em máquina com 4 GB: começar com um conjunto pequeno e licenciado/revisado, `vocab_size=1000`, `d_model=32`, uma cabeça, uma camada, contexto 32, batch 1, uma thread, 10–20 passos, avaliação a cada 5 passos e checkpoint a cada 10. Manter a reserva de RAM e interromper se o preflight reprovar. Tratar a loss como métrica de ajuste do corpus, não como evidência de capacidade conversacional ou inteligência. Primeiro adicionar suporte testável a retomada e holdout de teste.

## J. Pendências antes de aprovar a fase

1. Criar ambiente `.venv` e instalar `requirements-test.txt` com memória livre adequada; executar `python -m pytest -v` sem falhas.
2. Executar testes de interface e soak curto em X11/Xwayland ou Xvfb configurado; observar widgets reais e ausência de workers órfãos.
3. Exercitar os callbacks de falha do worker cognitivo com a aplicação importável e confirmar recuperação visual em runtime.
4. Implementar e testar retomada de checkpoints e criar divisão de teste separada antes da primeira comparação de modelos.
5. Repetir medições de processo real (RSS, CPU, threads, filas e duração) com a aplicação desktop iniciada.

Até essas pendências serem resolvidas, a Fase 17 permanece **parcial**.
