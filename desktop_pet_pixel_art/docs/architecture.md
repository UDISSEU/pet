# Arquitetura

## Visão geral

`src/desktop_pet.py` coordena a janela Tkinter, os estados da personagem, as interações e as rotinas periódicas. A interface é desenhada em pixel art com Pillow; OpenCV decodifica os vídeos de `assets/movements/` durante a inicialização.

## Módulos

- `desktop_pet.py`: ciclo principal, janela, menu, diálogos, modos da mascote e integração entre os módulos.
- `animation.py`: decodifica vídeos, prepara quadros e remove o fundo claro.
- `autonomy.py`: leitura e gravação de preferências, horários silenciosos, lembretes e busca de lançadores Linux `.desktop`.
- `assistant_actions.py`: respostas locais para data e hora e reconhecimento do pedido para abrir o calendário.
- `calendar_view.py`: calendário mensal local; não sincroniza com contas externas.
- `config.py`: caminhos dos assets, animações e parâmetros padrão.
- `ollama_client.py`: chamadas HTTP ao Ollama e persistência do histórico.
- `x11_helper.py`: observação da janela ativa e geometria de janelas em ambientes X11. O módulo falha de forma segura se X11 ou `python-xlib` não estiverem disponíveis.

## Fluxo da conversa

1. A interface recebe a pergunta e verifica primeiro os comandos locais de data e calendário.
2. Se a solicitação corresponder a um app cadastrado, a Nova mostra o comando e pede confirmação.
3. Outras perguntas são enviadas ao Ollama em uma thread de trabalho. A resposta volta por uma fila; a thread não manipula widgets Tkinter.
4. Preferências e histórico são gravados em arquivos JSON por substituição atômica.

As memórias explícitas são adicionadas ao contexto enviado ao modelo local. O seletor de apps lê lançadores `*.desktop` dos diretórios XDG de aplicações; comandos são divididos em argumentos e executados sem shell.

O modo de foco usa temporizadores Tkinter: enquanto a sessão ou a pausa está ativa, as falas espontâneas, observações de apps e lembretes aguardam. A pausa reaproveita a animação de descanso existente. As rotinas de boas-vindas e encerramento são opcionais e dependem de a aplicação estar aberta.

## Dados do usuário

- `~/.desktop_pet_history.json`: histórico curto de conversa.
- `~/.config/desktop_pet/settings.json`: modo, preferências, horários, rotinas, foco, memórias, lembretes e apps cadastrados.

Os lembretes são verificados pelo próprio processo da Nova. Eles são mostrados quando o app está em execução e não estão no horário silencioso.

## Testes

Execute da raiz do projeto:

```bash
.venv/bin/python -m unittest discover -s tests -v
```
