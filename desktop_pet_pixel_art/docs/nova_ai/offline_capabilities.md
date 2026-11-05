# Capacidades offline

## Funcionam sem provedor online

| Capacidade | Condição / limite observado |
|---|---|
| Interface, mascote e animações | Python/Tkinter e dependências de imagem presentes; vídeos carregados localmente. |
| Personalidade local da mascote | Falas e reações predefinidas, limitadas às regras e dados locais. |
| Data/hora e calendário | Local, sem sincronização. |
| Preferências, histórico, memórias explícitas, notificações e permissões | JSON local; arquivos apenas acessíveis ao usuário. Lembretes dependem do processo estar aberto. |
| Foco, rotinas, horário silencioso | Temporizadores locais enquanto a aplicação estiver rodando. |
| Métricas de CPU/RAM/disco/bateria | Coleta local; disponibilidade varia por hardware/OS e algumas permissões. |
| Busca/análise e organização de arquivos | Local; leitura pode funcionar offline. Modificação oferece prévia, confirmação e em casos undo. |
| Abertura de aplicativos | Lançadores locais; execução de aplicativo é confirmada na interface. |
| Plugins | Plugins internos podem operar sem rede; plugins externos dependem de bubblewrap/prlimit e permissões configuradas. |
| IA conversacional via Ollama | Offline após serviço local e modelo estarem instalados/baixados e caberem nos recursos. A Nova depende do processo Ollama acessível. |

## Dependem de rede ou serviço externo

- Gemini, Groq e Mistral requerem internet, chave válida e consentimentos de uso/envio configurados. O fallback para Ollama tenta continuar localmente quando serviço/modelo local estão disponíveis.
- Spotify Connect usa OAuth/API; reprodução local exige cliente Spotify compatível ou navegador/URI de playlist, conforme caminho acionado.
- Verificação/instalação/atualização APT depende dos repositórios e serviços do sistema; as operações de manutenção podem autenticar via Linux.
- Descoberta X11 depende do display e de `python-xlib`; não é requisito para conversa local ou renderização básica. Wayland não garante os recursos de controle de janela.
- Plugins com permissão de rede requerem conectividade. Sem `network.access`, a arquitetura tenta restringir a rede no sandbox; a documentação atual registra que alguns hosts não suportam o isolamento de rede e o plugin falha fechado.

## IA independente e funcionamento offline

A arquitetura atual permite trocar o backend de geração com custo localizado, mas “offline” significa chamar um runtime/modelo local de terceiro (Ollama), não inferência própria da aplicação. Sem Ollama e sem rede, permanecem respostas/intents locais e funcionalidades da mascote; não há geração aberta equivalente para perguntas livres.

Para independência operacional, a futura camada de inferência local precisará ser substituível atrás de interface, com detecção de hardware/modelo, limites de contexto e fallback explícito. Para independência de provedor, separar backend de geração é pré-requisito; treinamento do zero não é um passo de implementação no hardware descrito.
