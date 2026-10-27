# Nova — mascote de desktop

A Nova é uma mascote em pixel art para Linux. Ela anima na área de trabalho, conversa com um modelo local pelo Ollama e pode mostrar lembretes configurados por você.

## Instalar

Na pasta do projeto, crie um ambiente Python e instale as dependências:

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

O Tkinter também precisa estar instalado no sistema. Em Debian ou Ubuntu:

```bash
sudo apt install python3-tk
```

## Iniciar

```bash
.venv/bin/python src/desktop_pet.py
```

## Usar

- Arraste a Nova para movê-la.
- Dê um duplo clique ou abra o menu com o botão direito e escolha **Perguntar** para conversar.
- No menu, escolha **Calendário** para abrir o calendário local.
- Em **Foco e rotina**, escolha uma prioridade e a duração da sessão. Ao terminar, a Nova descansa e avisa quando a pausa acabar.
- Em **Autonomia e preferências**, escolha um modo, configure o horário de silêncio, memórias, lembretes e apps.
- Na aba **Aplicativos**, pesquise apps Linux instalados ou cadastre um comando manualmente. Selecione um item cadastrado para editá-lo.
- **Testar comando** inicia o app imediatamente. Quando a Nova abrir um app a pedido, ela mostra o comando e pede confirmação.

Os lembretes são exibidos enquanto a Nova está aberta. Os horários usam a hora local do computador.

## Conversa com IA

Para usar a conversa, instale o [Ollama](https://ollama.com/), inicie o serviço e baixe o modelo definido em `src/config.py` (padrão: `llama3.2:1b`). Sem o Ollama, a mascote e os outros recursos continuam disponíveis.

## Arquivos de dados

- Histórico da conversa: `~/.desktop_pet_history.json`.
- Preferências, memórias, lembretes, sessões de foco e apps cadastrados: `~/.config/desktop_pet/settings.json`.
- As memórias são incluídas no contexto enviado ao Ollama local. Elas podem ser removidas pela interface.

## Estrutura do projeto

- `src/`: aplicação e módulos; consulte [a visão da arquitetura](docs/architecture.md).
- `assets/movements/`: vídeos usados nas animações.
- `assets/personagem/`: quadros e folhas de sprites originais.
- `assets/icons/` e `assets/references/`: ícones e referências visuais.
- `tests/`: testes automatizados.
- `requirements.txt`: dependências Python.

## Verificar

```bash
.venv/bin/python -m unittest discover -s tests -v
```
