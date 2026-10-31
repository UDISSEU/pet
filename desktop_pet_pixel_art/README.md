# Nova — mascote de desktop

A Nova é uma mascote em pixel art para Linux. Ela anima na área de trabalho, conversa com um modelo local pelo Ollama e pode mostrar lembretes configurados por você.

## Instalar

Na pasta do projeto, execute o instalador. Ele cria o ambiente virtual, instala as dependências e registra o lançador no menu do usuário:

```bash
./install.sh
```

O Tkinter também precisa estar instalado no sistema. Em Debian ou Ubuntu:

```bash
sudo apt install python3-tk python3-dbus
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
- Na aba **Foco e rotina**, você pode ativar o aceno ao iniciar, comentários por período do dia, bocejo após inatividade, comemoração ao concluir o foco e recadinhos ocasionais com intervalo mínimo de quatro horas.
- Na aba **Meu Computador**, confira atualizações, atualize pacotes e revise limpezas do APT. A autenticação é feita pelo Linux; a remoção de pacotes mostra uma prévia antes de pedir confirmação.
- Na aba **Histórico**, consulte mensagens com data e hora e apague uma mensagem selecionada ou todo o histórico.
- Na aba **Aplicativos**, pesquise apps Linux instalados ou cadastre um comando manualmente. Selecione um item cadastrado para editá-lo.
- **Testar comando** inicia o app imediatamente. Quando a Nova abrir um app a pedido, ela mostra o comando e pede confirmação. Apps cadastrados e encontrados pelo nome completo podem ser abertos; o alias **Google** também abre o Google Chrome. Comandos curtos como “abre o Firefox” são tratados como pedidos de abertura. Perguntas sobre programação seguem para a IA mesmo que contenham “abrir”, “executar” ou “iniciar”.

Os lembretes são exibidos enquanto a Nova está aberta. Os horários usam a hora local do computador.

## Conversa com IA

Para usar a conversa, instale o [Ollama](https://ollama.com/), inicie o serviço e baixe o modelo definido em `src/config.py` (padrão: `llama3.2:1b`). Sem o Ollama, a mascote e os outros recursos continuam disponíveis.

Na aba **Inteligência artificial** das preferências, a Nova também permite configurar Gemini, Groq ou Mistral. O Ollama continua selecionado por padrão. Uma chamada online exige provedor selecionado, opção online ativa, autorização de envio de contexto e confirmação de que a chave está em uma modalidade gratuita sem cobrança habilitada. O histórico recente e apenas memórias relacionadas à pergunta podem ser enviados; não habilite isso para informações privadas. Para guardar a chave no cofre do sistema, cadastre-a pelo terminal sem exibi-la:

```bash
read -r -s -p 'Chave Gemini: ' API_KEY
printf '\n'
printf '%s' "$API_KEY" | /usr/bin/python3 src/keyring_secret.py store gemini
unset API_KEY
```

Para Groq ou Mistral, repita o comando usando o prompt correspondente (`Chave Groq:` ou `Chave Mistral:`) e troque `store gemini` por `store groq` ou `store mistral`. O lançador lê as três chaves do cofre do GNOME ao iniciar a Nova. Para executar diretamente com Python, defina `GEMINI_API_KEY`, `GROQ_API_KEY` ou `MISTRAL_API_KEY` no ambiente antes de iniciar. O botão **Testar conexão** verifica chave e modelo sem enviar histórico ou memórias. Quotas e condições dependem da conta e podem mudar. Confira privacidade e uso no painel do provedor; a Nova não muda o plano de cobrança.

## Arquivos de dados

- Histórico da conversa: `~/.desktop_pet_history.json`.
- Preferências, memórias, lembretes, sessões de foco e apps cadastrados: `~/.config/desktop_pet/settings.json`.
- As memórias são incluídas no contexto enviado ao Ollama local. Elas podem ser removidas pela interface.
- O provedor, autorização de contexto online e modelos ficam em `settings.json`; nenhuma chave de API é armazenada ali. As chaves dos provedores podem ficar no cofre do sistema.

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
