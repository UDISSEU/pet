# Testes gráficos isolados da Nova

O ambiente gráfico fica em um display X independente. A sessão principal
:0.0 não é usada como display da Nova nos testes Xvfb. O smoke test reutiliza
tests/test_ui_windows.py, que abre, reutiliza e fecha dashboard, notificações
e permissões, exercita uma concessão/revogação e marca uma notificação como
lida.

## Dependências

O executor requer o ambiente .venv do projeto, Tkinter, Pillow e psutil.
Também requer Xvfb, xauth, mcookie, xdpyinfo e setsid. Para o modo aninhado,
requer Xephyr e uma sessão X11 pai acessível. A captura usa PIL.ImageGrab,
sem exigir xwd, xdotool ou ImageMagick.

O script não instala pacotes. Em uma instalação Debian/Ubuntu/Mint, as
dependências do servidor podem ser instaladas manualmente pelo administrador,
por exemplo:

    sudo apt install xvfb xauth x11-utils xserver-xephyr python3-tk

Os nomes podem variar por versão da distribuição. O script verifica os
executáveis antes de iniciar. Weston headless e Xwayland isolado não são
configurados automaticamente.

## Comandos

Executar apenas o smoke test:

    tools/nova_gui_test.sh smoke

Capturar PNGs do dashboard, notificações e permissões:

    tools/nova_gui_test.sh --reports /tmp/nova-gui-reports capture

Iniciar a aplicação num display isolado; Ctrl+C encerra a sessão:

    tools/nova_gui_test.sh launch

Para exibir o display isolado numa janela Xephyr, numa sessão X11 já
funcional:

    tools/nova_gui_test.sh --backend xephyr capture

Executar o soak com a Nova aberta e métricas separadas do servidor X:

    tools/nova_gui_test.sh --reports /tmp/nova-gui-reports soak 30m
    tools/nova_gui_test.sh --reports /tmp/nova-gui-reports soak 1h
    tools/nova_gui_test.sh --reports /tmp/nova-gui-reports soak 3h

Cada execução cria um diretório de sessão privado em /tmp, com cookie
Xauthority e PIDs. O caminho é impresso no terminal. Enquanto a sessão estiver
ativa, pode-se consultar ou encerrar somente os processos registrados:

    tools/nova_gui_test.sh status /tmp/nova-gui-session.XXXXXX
    tools/nova_gui_test.sh cleanup /tmp/nova-gui-session.XXXXXX

O encerramento também ocorre por trap ao sair, falhar ou receber interrupção.
Ele valida PID, horário de início e grupo antes de sinalizar os processos;
examina descendentes da Nova para encerrar grupos de plugins que tenham criado
uma sessão própria. O cookie e o diretório temporário são removidos. Capturas
e relatórios permanecem no diretório indicado por --reports.

O executor usa um ambiente de variáveis limpo para a Nova e para os testes,
com HOME e diretórios XDG temporários. A única credencial encaminhada à
aplicação é o cookie Xauthority do display de teste. Plugins externos
continuam sujeitos ao sandbox existente da Nova.

## Métricas do soak gráfico

Sem --target-pid ou --display-pid, tools/nova_soak.py mantém o modo original
e mede o próprio harness e seus serviços. Com ambos os PIDs, o JSONL inclui
amostras separadas de CPU, RSS, threads e filhos da Nova e do servidor X.
nova_worker_threads_estimate subtrai a thread principal do total de threads.
Grupos de filhos isolados são reportados separadamente; o campo
nova_plugin_processes_estimate reconhece lançadores chamados bwrap, bubblewrap
ou prlimit, portanto é uma estimativa observável, não uma telemetria interna
do plugin. O harness também registra CPU/RSS agregados desses grupos e dos
outros filhos da Nova. A métrica de CPU do sistema continua separada.

O soak gráfico mantém a janela da Nova aberta durante o cenário. Não inicia
por padrão durante a suíte normal. Teste de seleção de quadros não mede
fluidez visual; capturas também não constituem aprovação estética.

## Diagnóstico do ambiente auditado

Neste host foram encontrados Xvfb, xvfb-run, Xephyr, Xwayland, xauth,
xdpyinfo, xwd, wmctrl, Tk 8.6, Pillow e psutil. Não foram encontrados Weston,
xdotool nem xwdtopnm; o último não é necessário para as capturas PNG.

O início direto do Xvfb com display :187, -nolisten tcp e Xauthority privado
falhou ao criar sockets UNIX. /tmp/.X11-unix está como
drwxrwxrwt nobody:nogroup; o X server exige que essa pasta pertença a root.
Uma tentativa de usar um /tmp privado por Bubblewrap também falhou: o host
nega bind() de sockets UNIX no sandbox. Nenhuma propriedade ou permissão
global foi modificada. O executor para antes de iniciar o X server e informa
essa condição. Xephyr depende de um X pai acessível; Weston não está instalado.

Consequentemente, smoke test gráfico e capturas não foram executados neste
host, e não há avaliação visual. Em outro host o script inicia o display,
verifica xdpyinfo com Xauthority antes dos testes e encerra se a verificação
falhar. Linux Mint/Wayland não foram validados visualmente aqui.
