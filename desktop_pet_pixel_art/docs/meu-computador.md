# Meu Computador

## Organização

`preferences_computer_ui.py` mantém o inventário de aplicativos e atualizações dentro de Preferências > Meu Computador. A Central do Computador, em `computer_center_ui.py`, organiza as páginas de visão geral, inicialização, armazenamento, rede, saúde do sistema e discos, logs, limpeza, backup, desempenho, alertas, consultor e histórico de ações. O atalho **Biblioteca de Aplicativos** da central abre o inventário existente; não há uma segunda implementação.

Os coletores sem interface ficam em módulos pequenos:

- `computer_services.py`: métricas do sistema, rede e armazenamento.
- `startup_manager.py`: lançadores de inicialização do usuário.
- `computer_diagnostics.py`: amostras de rede/saúde e verificações solicitadas.
- `computer_maintenance.py`: SMART, logs limitados e análise/remoção assistida.
- `computer_backup.py`: formato, integridade e restauração de configurações permitidas. Veja [formato de backup](aurova-backup-format.md).
- `performance_monitor.py`: coleta histórica limitada e alertas.
- `computer_consultant.py`: contexto factual limitado e histórico de ações sem credenciais.

`DesktopPet` fornece os serviços compartilhados, histórico de notificações e permissões. O Consultor envia a pergunta pelo fluxo de conversa já existente; não mantém outro chat ou provedor. Consultas de interface usam workers e retornam resultados à thread Tk. Amostras de rede e saúde param ao sair de suas páginas, timers são cancelados no fechamento e o monitor de desempenho para junto da aplicação.

## Dependências e permissões

`psutil` é a dependência Python usada para métricas. `lsblk`, `smartctl` e `journalctl` são opcionais e descobertos em tempo de execução; sem eles, a página informa indisponibilidade. SMART pode exigir permissão adicional do sistema; a Aurova não eleva privilégios nem usa `sudo`. Acesso a informações e alterações passa pelo Permission Manager. Exclusão assistida e restauração mostram confirmação e validam arquivos/caminhos. Ferramentas de rede são chamadas com argumentos fixos, sem shell e sem comandos formados a partir de nomes de aplicativos.

Os registros de limpeza são candidatos, não uma promessa de espaço recuperado; a análise tem limites de entradas/tempo e a remoção revalida propriedade, tipo e links simbólicos. Logs consultados são limitados e passam por filtros de segredos conhecidos. O formato de backup contém apenas chaves de configuração permitidas, é validado e gravado atomicamente; não restaura código nem caminhos arbitrários.

## Executar e validar

Inicie a aplicação pelo lançador documentado no README (`./launchers/run-aurova.sh`) ou diretamente no ambiente de desenvolvimento com `.venv/bin/python src/desktop_pet.py`. Os testes direcionados da área podem ser executados da raiz:

```bash
PYTHONPATH=src .venv/bin/python -m unittest \
  tests.test_computer_backup tests.test_computer_consultant \
  tests.test_computer_diagnostics tests.test_computer_maintenance \
  tests.test_computer_maintenance_services tests.test_performance_monitor \
  tests.test_installed_apps tests.test_desktop_pet_ai \
  tests.test_desktop_startup
```

Os testes de serviço usam dados controlados e não validam SMART, journal, rede externa ou exclusão de arquivos reais da máquina. Os testes Tk dependem de display funcional; para smoke tests gráficos isolados, veja [gui-testing.md](gui-testing.md). A ausência de display significa que a aparência final, foco, escalas e fluidez precisam de validação manual numa sessão gráfica. Não há serviço do Meu Computador separado: a coleta em segundo plano roda apenas durante a vida da aplicação, com intervalo padrão de 60 segundos e limites de histórico.
