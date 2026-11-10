# ✨ Nova — mascote de desktop para Linux

Uma companheira virtual em pixel art que vive na área de trabalho, anima-se, conversa por IA e oferece ferramentas locais para foco, lembretes e organização. O projeto é feito em Python e Tkinter, com preferência por processamento local e confirmações antes de ações que alteram arquivos ou o sistema.

> **Branch principal:** `main` · **Plataforma-alvo:** Linux

## O que a Nova oferece

- **Mascote animada:** caminha, descansa, acena, dança, boceja e reage às interações.
- **Conversa com IA:** usa Ollama local por padrão e permite configurar Gemini, Groq ou Mistral.
- **Foco e rotina:** sessões de concentração e pausa, horário silencioso, lembretes e mensagens de rotina.
- **Automações locais:** consulta de indicadores do notebook, análise de arquivos e organização de Downloads e capturas.
- **Integrações:** abertura de aplicativos Linux e controle de reprodução do Spotify.
- **Controles de segurança:** permissões para ações sensíveis, prévias e confirmações antes de operações destrutivas.

A Nova pode ser usada sem configurar provedores online. Recursos que dependem de X11, como observar janelas e posicionar a mascote sobre elas, são opcionais.

### Tecnologias

- **Linguagem:** Python
- **Interface e runtime:** Tkinter, em ambiente desktop Linux
- **Bibliotecas principais:** Pillow, OpenCV, NumPy e psutil
- **Integrações opcionais:** Ollama, APIs Gemini/Groq/Mistral, Spotify, Secret Service e `python-xlib`

## Estrutura do repositório

```text
.
├── .github/
│   └── workflows/            # CI: testes automatizados no GitHub Actions
├── desktop_pet_pixel_art/
│   ├── assets/
│   │   ├── movements/        # Vídeos usados nas animações da Nova
│   │   ├── personagem/       # Sprites e animações da personagem
│   │   ├── icons/            # Ícones da aplicação
│   │   └── references/       # Referências visuais
│   ├── docs/                 # Arquitetura e instruções para testes gráficos
│   ├── launchers/            # Lançador, ícone e atalhos da aplicação
│   ├── src/
│   │   ├── ai/               # Contexto, personalidade, roteamento e pedidos de IA
│   │   ├── providers/        # Adaptadores para Ollama, Gemini, Groq e Mistral
│   │   ├── desktop_pet.py    # Janela principal, ciclo e estado da mascote
│   │   ├── desktop_pet_ui.py # Menu, preferências e janelas da interface
│   │   ├── automations.py    # Automações locais e organização de arquivos
│   │   ├── plugin_manager.py # Registro e ciclo de vida de plugins
│   │   └── ...               # Persistência, permissões, animações e integrações
│   ├── tests/                # Testes unitários e de integração com mocks
│   ├── tools/                # Ferramentas de teste gráfico e soak tests
│   ├── install.sh            # Cria o ambiente virtual e instala dependências
│   └── requirements.txt      # Dependências Python
├── movimentação Nova/       # Vídeos e imagens de referência da personagem
├── movimento 2.0/           # Materiais de criação, sprites e referências
└── README.md                 # Apresentação do projeto
```

As pastas `movimentação Nova/` e `movimento 2.0/` guardam materiais visuais de origem e referência. Os recursos usados pelo aplicativo em execução ficam organizados em `desktop_pet_pixel_art/assets/`.

### Como as partes se conectam

`src/desktop_pet.py` coordena a janela e o ciclo da aplicação; `desktop_pet_ai.py` contém os workers e o fluxo de conversa; `desktop_pet_ui.py` agrega mixins menores de interface. `AnimationLoader` carrega as animações em segundo plano e entrega os resultados à interface Tkinter. Na conversa, `ai.request_handler` encaminha o contexto a `AICore`, que usa `ModelRouter` e os módulos de `providers/`. A identidade, as regras e a personalidade conversacional ficam em `nova_ai/personality/`; `personality.py` e `ai/personality.py` preservam importações antigas.

Pedidos locais conhecidos, como algumas automações e ações de sistema, podem ser tratados sem chamar um modelo de IA. As operações de arquivo que modificam conteúdo apresentam uma prévia e pedem confirmação; a interface também exige confirmação para esvaziar a Lixeira ou executar determinadas ações de manutenção.

### Privacidade e memória

O histórico da conversa não é salvo nem reutilizado como contexto por padrão. Em
**Preferências > Memória**, cada opção pode ser ativada separadamente; ali também é
possível consultar mensagens e apagar uma mensagem ou todo o histórico. As memórias estruturadas só são gravadas quando a pessoa confirma em
**Guardar**. Essa tela permite consultá-las, corrigir ou excluir uma memória e desativar
seu uso como contexto nas respostas. A interface indica a origem e a confiança da
informação; uma inferência não é apresentada como confirmação do usuário.

O SQLite usa um diretório de perfil privado e abertura por descritor de diretório no
Linux. `nofollow=1` não é tratado como proteção: a API `sqlite3` do Python não expõe
`SQLITE_OPEN_NOFOLLOW`. Backups são criados com permissão restrita, verificados e
publicados sem sobrescrever arquivos existentes; a restauração valida o arquivo antes
da troca e mantém uma cópia para rollback até concluir a verificação.
Essa proteção isola os dados de outros usuários do sistema; processos executados com o
mesmo usuário têm as permissões do proprietário do banco.

## Histórico e evolução

O histórico começa em **8 de outubro de 2026**, com a primeira versão da mascote e seus materiais gráficos. Os marcos identificados mostram a evolução do protótipo para uma aplicação desktop mais completa:

- **Início do projeto:** primeira implementação da mascote, com assets e animações de pixel art.
- **Organização do repositório:** remoção posterior de ambientes virtuais e arquivos redundantes do rastreamento, além da adoção de `.gitignore`.
- **Expansão da aplicação:** inclusão de lançador Linux, provedores de IA, módulos separados para interface e animação e testes automatizados.
- **Automações e integrações:** ferramentas locais para organização e análise de arquivos, integração com Spotify e controles de permissão.

O projeto é uma aplicação desktop em Python/Tkinter, com animações, provedores de IA, automações locais, testes e documentação de arquitetura. O estado das branches e dos commits muda ao longo do desenvolvimento; consulte o Git para obter essas referências atualizadas.

## Instalação

### Requisitos

- Linux com Python 3 e suporte a `venv`
- Tkinter disponível para a instalação Python do sistema
- `python3-dbus` para recursos que dependem de D-Bus/Secret Service

Em Debian ou Ubuntu, instale os requisitos do sistema:

```bash
sudo apt update
sudo apt install python3-venv python3-tk python3-dbus
```

### Instalar a Nova

Na raiz do repositório:

```bash
cd desktop_pet_pixel_art
./install.sh
```

O instalador cria o ambiente virtual `.venv`, instala as dependências de `requirements.txt` e registra o lançador no menu de aplicativos do usuário.

### Iniciar

```bash
cd desktop_pet_pixel_art
.venv/bin/python src/desktop_pet.py
```

## Conversa com IA

O **Ollama local** é o provedor padrão. Para conversar com um modelo, instale o Ollama, inicie o serviço e baixe o modelo configurado por padrão:

```bash
ollama pull llama3.2:1b
```

A mascote e os recursos locais continuam disponíveis mesmo sem o Ollama. A conversa online é opcional: Gemini, Groq e Mistral podem ser configurados nas preferências da Nova. Perguntas são enviadas ao provedor selecionado; mensagens anteriores só são incluídas se a opção de contexto estiver ligada. Verifique a política do provedor antes de enviar informações. As chaves não são armazenadas em `settings.json`; o projeto oferece suporte ao cofre Secret Service ou às variáveis de ambiente indicadas abaixo:

```text
GEMINI_API_KEY
GROQ_API_KEY
MISTRAL_API_KEY
```

Verifique os limites, a privacidade e as condições da sua conta diretamente no painel do provedor. A Nova também oferece um teste de conexão que não envia o histórico da conversa.

## Recursos da interface

- **Interações com a mascote:** clique para receber uma reação, use o menu de contexto para abrir as opções e arraste a personagem para reposicioná-la.
- **Calendário:** calendário local, sem sincronização externa.
- **Foco e rotina:** escolha uma prioridade e configure o tempo de foco e de pausa. As mensagens espontâneas e os lembretes respeitam o horário silencioso.
- **Lembretes e histórico:** gerencie lembretes locais e consulte ou apague mensagens salvas.
- **Aplicativos:** pesquise aplicativos Linux instalados ou cadastre um comando. A abertura de aplicativos pode exigir confirmação.
- **Automações:** consulte informações do notebook, investigue arquivos grandes ou duplicados e organize Downloads e capturas. A organização pode ser desfeita.
- **Manutenção do sistema:** as ações com APT usam autenticação do Linux; operações que removem pacotes apresentam uma prévia.
- **Spotify:** configure a integração nas preferências para pesquisar músicas e interagir com playlists.

Os lembretes só são exibidos enquanto a aplicação está aberta. Recursos específicos de X11 dependem do ambiente gráfico; `python-xlib` é opcional e sua ausência não impede o uso geral da Nova.

## Dados e privacidade

Os dados da aplicação são mantidos localmente nos seguintes caminhos:

| Arquivo | Conteúdo |
|---|---|
| `~/.desktop_pet_history.json` | Histórico da conversa |
| `~/.config/desktop_pet/settings.json` | Preferências, rotinas, memórias, lembretes, automações e aplicativos |
| `~/.config/desktop_pet/downloads_undo.json` | Informações necessárias para desfazer a última organização de Downloads |
| `~/.config/desktop_pet/permissions.json` | Permissões concedidas ou revogadas |

As chaves dos provedores de IA não ficam nas preferências JSON. O envio de contexto a um provedor online depende das opções de privacidade configuradas na interface. Se arquivos JSON de dados estiverem corrompidos, a aplicação tenta preservar uma cópia antes de substituí-los.

## Desenvolvimento e testes

Instale as dependências Python:

```bash
cd desktop_pet_pixel_art
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

Execute a suíte de testes:

```bash
.venv/bin/python -m unittest discover -s tests -v
```

O workflow em `.github/workflows/tests.yml` executa os testes com Python 3.12, Tkinter e Xvfb. Os testes de integração com provedores usam mocks; não é necessário configurar chaves ou serviços online para executar a suíte normal.

Para habilitar recursos dependentes de X11, instale a dependência opcional:

```bash
.venv/bin/python -m pip install 'python-xlib>=0.33'
```

A documentação complementar está em `desktop_pet_pixel_art/docs/architecture.md` e `desktop_pet_pixel_art/docs/gui-testing.md`.

## Exemplos de pedidos

- “Como está meu notebook?”
- “Encontre os arquivos grandes em Downloads.”
- “Procure arquivos duplicados.”
- “Organize meus Downloads.”
- “Inicie uma sessão de foco de 25 minutos.”
- “Abra o Firefox.”
- “Toque uma música no Spotify.”

## Perguntas para explorar o projeto

- Como o `StateManager` se integra ao ciclo atual em `src/desktop_pet.py`?
- Como executar os testes gráficos descritos em `docs/gui-testing.md`?
- Como os plugins externos são registrados e quais permissões precisam de confirmação?
