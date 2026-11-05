# Nova Model 0.1 — laboratório experimental

## Configuração inicial

| Parâmetro | Valor |
| --- | ---: |
| Arquitetura | Transformer decoder-only |
| Camadas | 2 |
| Cabeças | 2 |
| Dimensão interna | 64 |
| Contexto máximo | 64 tokens |
| Vocabulário | 2.000 tokens (configurável entre 1.000 e 2.000) |
| Batch | 1 |
| Dispositivo e precisão | CPU, FP32 |
| Parâmetros calculados | 234.064 |

O embedding de entrada e a projeção de saída compartilham pesos. Isso mantém a
configuração padrão dentro da faixa experimental de 100–300 mil parâmetros.
O vocabulário é local, criado explicitamente a partir de texto escolhido; não
há download de dados nem coleta automática de conversas.

## Memória

O cálculo estático estima 0,893 MiB para pesos FP32 e 133,173 MiB de pico para
pesos, gradientes, estados do Adam, ativações, logits e uma reserva fixa de
128 MiB para o runtime. Essa estimativa não substitui uma medição com PyTorch
instalado.

Na verificação mais recente do ambiente em 2026-11-05, `psutil` informou
aproximadamente 731,8 MiB disponíveis (o valor variou entre leituras). O
preflight reserva 256 MiB para o sistema além da estimativa calculada; o passo
de treino aborta se a disponibilidade cair abaixo de 192 MiB. O resultado
depende da memória livre no momento de executar e não é garantia para todo o
treinamento.

## Smoke test de treino

PyTorch CPU foi instalado somente no ambiente virtual temporário
`/tmp/nova-model-venv` para verificar este passo; o Python global e os dados do
projeto não foram alterados. Com PyTorch 2.15.0+cpu, o preflight encontrou
689 MiB disponíveis, estimou 133,2 MiB de pico e aprovou a reserva de 256 MiB.
Um lote sintético de cinco tokens executou um passo FP32; a loss observada foi
7,6617. O RSS cresceu cerca de 93,7 MiB durante o passo e o pico RSS do processo
foi 303,3 MiB (inclui o runtime Python/PyTorch). O checkpoint de smoke test
ocupou 977.746 bytes, foi recarregado e gerou quatro tokens. A sequência curta
foi `nova nova nova nova`; com um único passo, isso só confirma que o caminho
de geração funciona, não que o modelo aprendeu linguagem útil.

## Persistência e histórico

Configurações podem ser salvas/carregadas em JSON. Checkpoints usam CPU e
carregamento `weights_only`, com validação da configuração e limite de arquivo.
O histórico de execuções fica em SQLite e só cria sua base quando
`ModelHistory` recebe explicitamente um caminho.

## Limites atuais

O modelo fornece um único `train_step` para lote sintético ou lote pequeno em
CPU; não inicia ciclos ou carrega datasets. Os pesos iniciais são aleatórios e
não devem ser usados para responder ao usuário. A dependência opcional está
registrada em `requirements-ml.txt`; sem ela, o núcleo segue importável, mas o
modelo não pode ser instanciado.

## Referências

- [PyTorch — instalação local](https://pytorch.org/get-started/locally/)
- [PyTorch — tutoriais](https://pytorch.org/tutorials/)
- [Hugging Face — curso de LLM/NLP](https://huggingface.co/learn/nlp-course/)
