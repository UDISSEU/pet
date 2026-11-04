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

## Diagnóstico e validação da Fase 6.2

Xvfb, Xephyr, Xwayland, xauth, xdpyinfo, wmctrl, Tk 8.6, Pillow e psutil estão
instalados. Weston e xdotool não estão instalados. Xephyr não pôde ser usado
porque o display pai `:0.0` não aceita conexão autenticada neste ambiente;
Xwayland precisaria de um compositor Wayland ativo.

O sandbox do executor apresenta `/tmp/.X11-unix` como uid 65534 e bloqueia o
bind de sockets UNIX. Já fora do sandbox, como o mesmo usuário normal, o
diretório aparece como uid 0; não foi necessário sudo nem qualquer alteração
global. O Xvfb iniciou no display dinâmico :90 com `-nolisten tcp`, criou seu
socket local e aceitou conexão autenticada. O encerramento removeu o socket e
o lock temporários. O Xauthority ficou em diretório privado (700/600).

A investigação também encontrou que `xdpyinfo` não aceita `-auth`. O executor
foi corrigido para passar o arquivo pela variável `XAUTHORITY`; a checagem do
display pai do Xephyr usa o mesmo método.

O smoke test real abriu e fechou as janelas, verificou reutilização, foco,
permissões, notificações, atualização do dashboard, fechamento e reabertura.
Passou: 1 teste, sem falha. Após adicionar a regressão para limpeza de sessão,
a suíte completa executou 155 testes: 153 passaram e 2 foram ignorados (UI
sem display no sandbox e isolamento de rede bloqueado pelo host). Foram
capturadas e examinadas:

- `/tmp/nova-gui-reports-phase62/character.png` — Nova real em animação; a
  captura em Xvfb sem compositor mostra fundo preto e a área branca da imagem,
  então ela confirma renderização e posição, mas não transparência composta.
- `/tmp/nova-gui-reports-phase62/nova-gui-capture.6l6MR0/dashboard.png` —
  métricas reais preenchidas.
- `.../notifications.png` — lista e controles legíveis, incluindo modo
  silencioso.
- `.../permissions.png` — controles e rolagem visíveis; lista longa requer
  rolagem.

A captura revelou que o controle de modo silencioso era cortado na linha de
botões. Ele foi movido para uma segunda linha. Também foi corrigida a ordem de
captura do dashboard, que agora espera as métricas assíncronas. Linux Mint,
Wayland, transparência composta e escala HiDPI não foram validados. Não houve
instalação de dependências; se faltarem num sistema Debian/Ubuntu/Mint, podem
ser instaladas manualmente com `sudo apt install xvfb xauth x11-utils
python3-tk`.

O soak gráfico de 30 minutos terminou em 1.800 segundos, com 180 amostras e
encerramento limpo. RSS da Nova: mínimo 107 MiB, pico 543 MiB durante a carga
inicial e 170 MiB ao final. CPU: mínimo 12,6%, pico inicial 176,4% e 16,7% na
última amostra. Threads: máximo 20 na inicialização e 12 ao final. Não houve
filhos da Nova ou do Xvfb; filas de eventos e callbacks variaram entre 0 e 1 e
terminaram em 0. O histórico de notificações chegou a 30; o histórico de
métricas permaneceu no limite de 120. O worker do harness encerrou e não
restaram processos, sockets de teste ou diretórios de sessão. A execução
também revelou que a limpeza deixava `soak.log`; o script agora remove esse
arquivo, com teste de regressão. JSONL:
`/tmp/nova-gui-reports-phase62/nova-soak-30m-20261104-100718.jsonl`.

Neste executor Codex, a execução padrão fica dentro do sandbox, que não pode
criar o socket X. Para executar manualmente no terminal normal do usuário, use
`tools/nova_gui_test.sh --reports /tmp/nova-gui-reports capture` e depois
`tools/nova_gui_test.sh --reports /tmp/nova-gui-reports soak 30m`. O script
mantém Xauthority privada, escolhe display livre, desliga TCP e limpa os
processos ao terminar; não requer sudo quando o diretório do host está
configurado normalmente.
