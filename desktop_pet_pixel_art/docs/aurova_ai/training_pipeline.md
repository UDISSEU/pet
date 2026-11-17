# Pipeline local de dados e treinamento

O pipeline vive em `training/` e não é iniciado pela mascote nem pelo bootstrap
da aplicação. Os arquivos de configuração e o diretório `training/` existem no
repositório; `datasets/raw`, `datasets/processed`, `datasets/validation`,
`experiments` e `checkpoints` são criados somente quando necessário.

## Preparar um corpus

Coloque textos escolhidos pelo usuário em `training/datasets/raw/` como arquivos
`.txt` (um registro por linha) ou `.jsonl` (um objeto por linha com campo
string `text`). O construtor aceita fontes diretamente nesse diretório. Ele:

- lê linha a linha, limita cada linha a 8.192 caracteres, examina até 25.000
  registros e aceita no máximo 5.000 textos por execução por padrão;
- ignora texto vazio/malformado e duplicatas exatas, mantendo apenas hashes em
  memória;
- cria uma separação determinística entre treino e validação;
- aprende o vocabulário somente com textos do treino, limitado a 2.000 itens;
- grava sequências de no máximo 64 tokens em JSONL; não carrega o corpus inteiro
  na RAM;
- nunca altera fontes originais e falha se o `run_name` já tiver saídas. Use um
  novo `run_name` para preservar experimentos anteriores.

Exemplo de uso manual, depois de colocar os dados revisados em `raw/`:

```bash
PYTHONPATH=src python -m training.dataset_builder --config training/training_config.json
PYTHONPATH=src python -m training.train --config training/training_config.json
```

O primeiro comando prepara os dados. O segundo executa até `max_steps` quando
chamado explicitamente. Ambos podem ser importados sem iniciar operações.

## Controles do experimento

`training_config.json` configura o modelo, divisão, limites de dados, número de
passos, avaliação, frequência de checkpoints e taxa de aprendizado. O treinador
usa AdamW, batch 1, FP32, CPU e uma thread; avalia no máximo 16 sequências por
avaliação e busca registros diretamente do JSONL em fluxo.

O treinador verifica memória disponível antes de importar/inicializar o modelo,
antes do treino e em cada passo; `train_step` verifica novamente antes de
atualizar os pesos. Se o preflight não conseguir manter a reserva configurada,
o experimento não começa. Checkpoints carregam o vocabulário e os metadados e
ficam em um diretório exclusivo por execução. Métricas e histórico SQLite ficam
em `experiments/`.

Não há dataset de exemplo incluído, download de corpus ou treino automático.
Para um primeiro experimento, use apenas texto pequeno, autorizado e revisado.
