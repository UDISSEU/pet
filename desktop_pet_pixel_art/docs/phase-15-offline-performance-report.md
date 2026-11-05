# Fase 15 — IA offline e desempenho

Data: 5 de novembro de 2026

## Provedores e modo offline

- Ollama permanece o provedor local padrão. Gemini, Groq e Mistral dependem de autorização online, envio de dados habilitado e confirmação já existentes.
- `ModelRouter` conserva timeout (até 12 s para remoto, limite configurado até 30 s local) e fallback local após erro remoto. Testes unitários simulam indisponibilidade; não desativei a rede nem acessei APIs externas.
- O payload do Ollama agora limita contexto, resposta, threads e tempo de retenção do modelo. Preferências validam `num_ctx` em 512–2048 (padrão 1024), `num_predict` em 16–256 (padrão 96), `num_thread` em 1–2 (padrão 1) e `keep_alive=30s`. Inferências locais são serializadas por lock de processo.
- Memória e personalidade continuam locais. Tarefas locais autorizadas não dependem dos provedores remotos.

## Inferência real executada

O runtime Ollama local tinha `llama3.2:1b` instalado (1,3 GB no catálogo local). Foi executada uma chamada curta via `OllamaProvider`, com contexto 512, resposta limitada a 32 tokens, uma thread e sem treinamento/download. Resultado: a chamada retornou texto em **7,744 s**. O relatório do Ollama indicou modelo carregado de **1,4 GB**, **100% CPU**, contexto **512** e retenção temporária. Uma execução exploratória anterior demorou mais e respondeu de forma semanticamente inadequada; disponibilidade e geração de texto não comprovam qualidade de assistente.

Medições do benchmark instrumentado: 4 CPUs visíveis; disponibilidade de RAM variou de 534.405.120 bytes para 314.044.416 bytes durante a amostra; CPU total amostrada média 39,0%, pico 54,6%; processo Python do benchmark RSS 25.157.632 bytes e uma thread. A memória disponível do sistema variou durante a execução e não pode ser atribuída integralmente ao modelo. O processo servidor Ollama está fora do namespace de processos visível ao sampler Python; por isso seu RSS detalhado não foi capturado. `ollama ps` forneceu o tamanho/modo de execução reportado acima. A lista de checkpoints experimentais ocupa 0 bytes.

Ferramenta reproduzível: `tools/nova_benchmark.py`. Ela executa uma inferência apenas quando chamada com `--run-inference`, coleta métricas reais via `psutil`, limita a chamada ao Ollama em localhost e pode salvar JSON. Não baixa modelos nem inicia treino.

## Laboratório Nova Model 0.1

O código do modelo experimental permanece isolado dos provedores de conversa. A configuração padrão limita-se a 234.064 parâmetros, contexto 64, batch 1 e CPU. Checkpoint requer carregamento explícito e `weights_only`. Os testes de configuração/tokenizador passaram; os testes de treino sintético, checkpoint com pesos e inferência foram **ignorados**, pois PyTorch CPU não está instalado. Portanto, essa arquitetura não foi treinada nem validada como assistente conversacional.

## Testes

`python3 -m unittest tests.test_ai_providers tests.nova_ai.test_model_experimental tests.nova_ai.test_memory tests.nova_ai.test_personality_system tests.nova_ai.test_desktop_integration tests.nova_ai.test_cognition tests.nova_ai.test_actions`: **107 aprovados, 2 ignorados** (PyTorch ausente).

Compilação dos provedores, preferências, memória, personalidade, benchmark e integração: aprovada. Não foram iniciados treinamento nem benchmarks sintéticos.

## Limitações e recomendação

- O único modelo local medido foi `llama3.2:1b`; uma inferência curta é uma medição operacional, não uma avaliação de respostas, qualidade ou latência p95.
- O ambiente expõe aproximadamente 3,6 GiB de RAM utilizável, e a disponibilidade durante a medição caiu abaixo de 300 MiB. Em uma máquina com 4 GB, feche outros aplicativos antes de inferir; mantenha contexto/resposta pequenos e uma inferência por vez.
- O modo sem rede foi comprovado para a chamada Ollama local, não por bloqueio físico de toda interface de rede.
- Fallback remoto→local é coberto por testes simulados; indisponibilidade real de cada serviço externo não foi provocada.
- Para validar o modelo experimental, instale PyTorch CPU compatível manualmente e execute apenas o smoke test de baixo custo já existente; o projeto não o instala nem o inicia automaticamente.
