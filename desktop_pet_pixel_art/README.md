# Nova — mascote de desktop

A Nova é uma mascote em pixel art para Linux. Ela anima na área de trabalho, conversa com um modelo local pelo Ollama e pode mostrar lembretes configurados por você.

## Instalar

É necessário Python 3.10 ou superior, o módulo `venv` e Tkinter. Em Debian ou Ubuntu, instale os componentes de sistema e execute o instalador. Ele valida a versão e as dependências, diagnostica recursos opcionais, cria/reutiliza o ambiente virtual, verifica a importação da aplicação e registra o lançador no menu do usuário:

```bash
sudo apt install python3-venv python3-tk
./install.sh
```

Uma instalação existente é detectada antes da atualização. Para automatizar a instalação sem confirmação, use `./install.sh --yes`. Para remover o ambiente virtual e o lançador, preservando preferências, histórico e demais dados pessoais:

```bash
./install.sh --uninstall
```

O instalador prepara somente o ambiente Python da aplicação e o lançador; não instala serviços do sistema, não inicia o Ollama e não baixa modelos. Instalação do Ollama e dependências do sistema são ações manuais.

Na primeira abertura, a tela de boas-vindas verifica a versão do Python, dependências, Ollama, modelo local, banco, personalidade, animações e espaço em disco. O diagnóstico também fica disponível no menu principal e pode ser atualizado sem instalar ou modificar dados. A Nova pode continuar sem Ollama. Essa tela não instala o Ollama nem baixa modelos; qualquer download de modelo exige confirmação posterior. O estado da instalação fica separado dos perfis em `~/.config/desktop_pet/installation_state.json`.

`python-xlib` é opcional. Sem ela, os recursos dependentes de X11 (observar janelas, transparência por forma e posicionamento sobre outras janelas) ficam indisponíveis. O instalador informa também se Ollama, Bubblewrap e `prlimit` estão disponíveis; são recursos opcionais para IA local e execução isolada de plugins externos. Para habilitar X11 no ambiente virtual:

```bash
.venv/bin/python -m pip install 'python-xlib>=0.33'
```

## Iniciar

```bash
.venv/bin/python src/desktop_pet.py
```

## Usar

- Ao iniciar, a Nova fica parada por cerca de 3 segundos antes de começar a caminhar; a saudação configurada vem depois.
- Clique na Nova para receber um aceno; se ela estiver descansando, o aceno vem acompanhado de uma fala de despertar. Dê um duplo clique para vê-la dançar. Cinco ou mais cliques rápidos deixam a Nova irritada. Arraste-a para movê-la: ela comenta quando é pega e quando é solta.
- Abra o menu com o botão direito e escolha **Perguntar** para conversar. Cumprimentos, elogios, piadas, dança, aceno, joinha, descanso e esconde-esconde também são respondidos localmente, sem chamar o modelo.
- No menu, escolha **Calendário** para abrir o calendário local.
- Em **Foco e rotina**, escolha uma prioridade e a duração da sessão. A Nova usa a animação de estudo durante o foco, dá um joinha ao concluir e dança ao fim da pausa.
- Em **Autonomia e preferências**, escolha um modo, configure o horário de silêncio, memórias, lembretes e apps. Na aba **Memória**, desative o uso das memórias nas respostas, revise sua origem e confiança, corrija ou apague registros e controle se novas conversas serão salvas. O histórico existente pode ser consultado e apagado por mensagem ou por completo. Memórias estruturadas só são gravadas quando você confirma em **Guardar**. Na aba **Comportamento**, o aprendizado de preferências é opcional e desligado por padrão; quando ligado, guarda apenas contagens agregadas de preferências explicitamente expressas sobre brevidade, formalidade, humor e incentivo. Memórias de projeto cadastradas podem ser retomadas nas saudações, respeitando o controle de contexto e o silêncio. A aba **Automações** mostra indicadores do notebook, arquivos grandes, duplicados e espaço por pasta; também oferece organização de Downloads e capturas com prévia e desfazer, e esvaziamento confirmado da Lixeira. As prévias são preparadas fora da thread da interface; a organização cognitiva é bloqueada se houver mais de 500 arquivos elegíveis, para evitar confirmar uma operação parcial. Avisos de pausa e bateria baixa respeitam foco e silêncio. No menu **Perguntar**, intents locais executam essas ações sem consultar a IA.
- Na aba **Foco e rotina**, você pode ativar o aceno ao iniciar, comentários por período do dia, bocejo após cinco minutos sem interação, comemoração ao concluir o foco, recadinhos ocasionais (intervalo mínimo de 30 minutos), dança espontânea e lembretes de pausa saudável. A rotina da noite também pode ser desligada. As falas espontâneas respeitam o horário silencioso e o modo selecionado.
- Na aba **Meu Computador**, confira atualizações, atualize pacotes e revise limpezas do APT. A autenticação é feita pelo Linux; a remoção de pacotes mostra uma prévia antes de pedir confirmação.
- Na aba **Histórico**, consulte mensagens com data e hora e apague uma mensagem selecionada ou todo o histórico.
- Na aba **Aplicativos**, pesquise apps Linux instalados ou cadastre um comando manualmente. Selecione um item cadastrado para editá-lo.
- **Testar comando** inicia o app imediatamente. Quando a Nova abrir um app a pedido, ela mostra o comando e pede confirmação. Apps cadastrados e encontrados pelo nome completo podem ser abertos; o alias **Google** também abre o Google Chrome. Comandos curtos como “abre o Firefox” são tratados como pedidos de abertura. Perguntas sobre programação seguem para a IA mesmo que contenham “abrir”, “executar” ou “iniciar”.
- Na aba **Inteligência artificial**, conecte a conta Spotify para pedir “toca Evidências do Chitãozinho e Xororó” ou “bota uma música”. Se não disser uma faixa, a Nova pergunta qual música você quer. A busca usa a API do Spotify e a reprodução é enviada ao aplicativo local; para tocar playlist sem conectar a API, ainda é possível informar o link.

Os lembretes são exibidos enquanto a Nova está aberta. Os horários usam a hora local do computador.

## Conversa com IA

Para usar a conversa, instale o [Ollama](https://ollama.com/), inicie o serviço e baixe o modelo definido em `src/config.py` (padrão: `llama3.2:1b`). Sem o Ollama, a mascote e os outros recursos continuam disponíveis.

O Ollama local é o provedor padrão. Se outro provedor estiver configurado, a pergunta, o histórico enviado como contexto e as memórias habilitadas podem ser processados por esse serviço; verifique os termos do provedor. O histórico não é salvo nem reutilizado como contexto por padrão. Em **Preferências > Memória**, as opções de salvar e reutilizar conversas podem ser ativadas separadamente; o histórico pode ser consultado e apagado. O download do modelo Ollama configurado só começa após confirmação explícita.

## Arquivos de dados

- Histórico da conversa: `~/.desktop_pet_history.json`.
- Banco SQLite de memórias estruturadas: `~/.config/desktop_pet/nova_memory.sqlite3`; perfis adicionais têm seus próprios arquivos dentro de `~/.config/desktop_pet/profiles/`.
- Preferências, automações, memórias legadas, lembretes, sessões de foco e apps cadastrados: `~/.config/desktop_pet/settings.json`. O mapa da última organização de Downloads fica em `~/.config/desktop_pet/downloads_undo.json`.
- A Nova guarda também a data da última visita e um contador de interações para variar os cumprimentos; não armazena texto digitado nesses metadados.
- Se o aprendizado opcional estiver ligado, `settings.json` guarda somente contagens agregadas por categoria e dia de evidência, isoladas por perfil. Os sinais são analisados em memória e o texto original da conversa não é armazenado nesse registro.
- Se um desses arquivos contiver JSON inválido, a Nova preserva uma cópia com sufixo `.corrupt-*` antes de gravar dados novos. Se não puder ler ou preservar o arquivo, bloqueia a gravação e registra o motivo no log.
- O histórico pode ser consultado, apagado por mensagem ou limpo em **Preferências > Memória**; a opção de gravação controla as próximas mensagens.
- Memórias estruturadas só são armazenadas após confirmação explícita e podem ser revistas, corrigidas ou removidas. Desativar seu uso no contexto não apaga os registros.
- Backups SQLite são privados e não sobrescrevem arquivos existentes. A restauração aceita versões anteriores suportadas, valida integridade e referências e mantém uma cópia para rollback até concluir a verificação.
- Memórias repetidas são consolidadas ao carregar as preferências; o arquivo JSON mantém o formato atual. Memórias selecionadas entram no contexto como dados de referência, nunca como instruções.
- O modelo Ollama e os limites locais de contexto, resposta e threads ficam em `settings.json`.

O desenho, a conversa e as animações funcionam sem recursos específicos do X11. Observar a janela ativa, sentar sobre outras janelas e alguns recursos de posicionamento dependem de `python-xlib` e do X11; no Wayland, a disponibilidade varia conforme a sessão e o compositor.

## Estrutura do projeto

- `src/`: aplicação e módulos; consulte [a visão da arquitetura](docs/architecture.md).
- `assets/movements/`: vídeos usados nas animações.
- `assets/personagem/`: quadros e folhas de sprites originais.
- `assets/icons/` e `assets/references/`: ícones e referências visuais.
- `tests/`: testes automatizados.
- `requirements.txt`: dependências Python.

## Verificar

```bash
PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -t . -v
```

Os testes são executados na integração contínua com Python 3.10–3.13. O workflow também verifica Ruff, Bandit, cobertura, consistência e auditoria de dependências, instalação limpa/inicialização e testes Tk separados.

Os vídeos são carregados em segundo plano. Cada clipe usa uma caixa e uma escala comuns a todos os quadros, com os pés alinhados pela mesma âncora; marcas pequenas e isoladas no canto inferior direito são filtradas numa margem de 12% da largura por 8% da altura, sem apagar componentes grandes da personagem. As janelas de repetição com menor diferença visual ficam em `VIDEO_LOOP_WINDOWS`; foco, lembrete, joinha e desaparecimento reproduzem uma vez e seguram o último quadro até a transição de estado. `VIDEO_FALLBACKS` indica a animação existente a usar quando um vídeo futuro estiver ausente.

Para validar a reprodução manualmente, inicie a Nova e observe alguns ciclos andando para os dois lados; compare os pés e o tamanho da personagem durante caminhada, aceno e balão de pensamento; clique, arraste e conclua uma sessão de foco; confirme que um erro de carregamento não interrompe a interface e que as poses temporárias cedem a uma interação nova. A suíte automatizada valida recorte, escala, margem do canto, seleção de quadros e callbacks obsoletos; ela não substitui a conferência visual em cada compositor.
