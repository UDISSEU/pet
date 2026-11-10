# Relatório de execução de testes — 10/11/2026

## Resultado geral

| Verificação | Resultado |
|---|---|
| Suíte completa (`unittest discover`) | **365 testes passaram; 0 falharam; 3 ignorados**, em 30,044 s |
| Testes gráficos com Xvfb | **1 teste passou**, em 2,198 s |
| Janela de preparação da Nova com Xvfb | Abriu e fechou sem erro |
| `sh -n install.sh launchers/run-nova.sh` | Passou |
| `pip check` no `.venv` do projeto | `No broken requirements found.` |
| `git diff --check` | Passou |
| Ollama local | Respondeu a `ollama list`; `llama3.2:1b` instalado |
| CI remoto das alterações locais | Não executado; o workflow foi validado apenas localmente |

Comando da suíte:

```sh
cd desktop_pet_pixel_art
PYTHONPATH="$PWD/src" .venv/bin/python -m unittest discover -s tests -t . -v
```

O comando reproduz a descoberta dos testes do CI usando o ambiente virtual local. O Python global não deve ser usado para esta validação: nele faltava OpenCV.

## Testes ignorados

- Dois testes de ciclo de vida e memória do modelo experimental: PyTorch CPU não está instalado.
- Um teste de isolamento de plugins: o host bloqueou a criação do namespace de rede do Bubblewrap; o plugin permaneceu inativo.

## Instalador e preparação

Os testes passaram cobrindo:

- Rejeição de `.venv` simbólico pelo terminal antes de ler o marcador, com o destino externo intacto.
- Rejeição do mesmo link pela interface gráfica.
- Recuperação de ambiente virtual incompleto dentro do projeto.
- Instruções `apt` para Linux Mint/Debian/Ubuntu quando falta Python ou Tkinter, sem execução automática de comandos administrativos.
- Cancelamento do download e proteção contra fechamento da janela durante a instalação.
- Falta de espaço: a saída do processo é preservada para diagnóstico.
- Falha de conexão com Ollama e erro de permissão ao iniciar um processo: erros são apresentados em vez de tratados como sucesso.

As falhas de disco, conexão e permissão são simuladas em testes; não foi preenchido o disco nem alterada a rede ou as permissões reais do sistema.

## Personalidade e preferências

Os testes unitários confirmam que preferências exigem consentimento, persistem, alteram as instruções de personalidade e não substituem a identidade ou regras centrais da Nova.

Também foi feita uma comparação prática, sem persistir alterações no perfil, enviando a mesma pergunta ao `llama3.2:1b` local com as instruções reais de verbosidade concisa e detalhada. Na execução controlada (`temperature=0`), as respostas tiveram 87 e 88 palavras, respectivamente, e ambas foram cortadas no limite de geração. Uma tentativa anterior variou mais, mas a resposta detalhada também foi truncada. **Conclusão: a suíte prova que a preferência altera as instruções enviadas, mas a evidência prática atual não comprova uma mudança consistente de estilo na resposta gerada pelo modelo.** A qualidade factual das respostas pequenas também não foi suficiente para tratar esse ensaio como validação funcional aprovada.

## Animações e interface

Os testes automatizados verificam a seleção de vídeos para estados e direções, expressões simuladas, temporizadores de poses, quadros finais de animações de ação única e transições da Nova. O teste gráfico de janelas passou sob Xvfb.

Isso valida o mapeamento e o funcionamento básico da interface, **não uma revisão visual humana da reprodução das animações**. Não foi feita captura ou inspeção visual de cada estado animado.

## Ollama

O comando `ollama list` respondeu e confirmou o modelo local instalado. A instalação e o início do serviço continuam manuais; nenhum comando administrativo foi executado e nenhum modelo foi baixado nesta execução.

## CI

A execução remota consultada em 04/11/2026 na branch `main` tinha os testes unitários e o job de qualidade aprovados, mas o job gráfico falhou ao importar `desktop_pet_ui` porque o comando não configurava `PYTHONPATH=src`. O workflow foi ajustado para definir o caminho e usar a descoberta com `-t .`; o mesmo comando passou localmente sob Xvfb. Ainda é necessário um novo run remoto para confirmar o CI após essa alteração.

## Conclusão e pendências

- **Instalador e suíte local:** aprovados nas verificações executadas.
- **Personalidade adaptativa:** persistência e montagem de instruções aprovadas; efeito consistente na geração real ainda não demonstrado.
- **Animações:** mapeamento coberto por testes; inspeção visual completa pendente.
- **Ollama:** serviço/modelo local disponíveis nesta máquina; provisionamento automático continua fora do escopo seguro do instalador.
- **CI:** resultado remoto após as alterações pendente.
