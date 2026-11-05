# Fases 9 e 10 — integração desktop e auditoria offline

Data: 5 de novembro de 2026

## Integração entregue

- `DesktopPet` inicializa o núcleo local, a memória SQLite e a personalidade em modo tolerante a falhas. Erros nessa composição são registrados e não impedem a inicialização do app legado.
- A conversa consulta até oito memórias locais no worker já usado pelo app e acrescenta as instruções da personalidade ao prompt. A thread Tk não consulta o SQLite nem persiste estados.
- Os estados visuais existentes são espelhados como estado volátil; sua persistência ocorre no worker da conversa.
- Inferências são serializadas por um lock compartilhado. Ao encerrar, o app marca o evento de cancelamento e descarta respostas tardias. Uma chamada de rede em curso termina pelo timeout já configurado no roteador.
- A seleção existente de provedor/modelo continua em Preferências. Ollama é o padrão local; provedores externos seguem opcionais, sujeitos às permissões e consentimentos já existentes, e tentam Ollama como contingência.
- O registro de ferramentas e suas permissões não foram alterados. Não há treinamento ou carregamento automático de pesos na inicialização.

## Resultados verificados

| Verificação | Resultado |
|---|---|
| Núcleo inicializa sem carregar modelo ou treinamento | Aprovado por teste unitário |
| Memória SQLite e recuperação limitada de contexto | Aprovado por testes de memória e integração |
| Persistência e mapeamento de estado da personalidade | Aprovado por testes |
| Roteador local/externo e contingência | Aprovado pelos testes existentes de provedores |
| Testes selecionados | 77 passaram; 2 foram ignorados |
| Compilação dos módulos alterados | Aprovada com `py_compile` |
| Inicialização gráfica real e animações neste ambiente | Não verificada: OpenCV (`cv2`) está ausente |
| Inferência com modelo Ollama instalado e sem rede | Não verificada: requer runtime Ollama e modelo local disponíveis |
| Falha real de provedor externo durante execução desktop | Não medida em GUI; os testes de roteamento cobrem a contingência simulada |
| RAM, CPU, latência e processos do app desktop | Não medidos: a aplicação gráfica não pôde ser iniciada neste ambiente |

Comando executado: `python3 -m unittest tests.nova_ai.test_desktop_integration tests.nova_ai.test_personality_system tests.nova_ai.test_memory tests.nova_ai.test_infrastructure tests.nova_ai.test_cognition tests.nova_ai.test_model_experimental tests.test_ai_providers`.

## Conclusão offline

O núcleo, a memória e a personalidade não exigem rede para inicializar ou consultar dados; a aplicação já tem Ollama como rota local e não solicita serviço externo por padrão. Ainda não é possível declarar a inferência offline comprovada: ela depende de instalar/iniciar Ollama e disponibilizar localmente o modelo escolhido. Também não foi possível comprovar a janela Tkinter e as animações sem OpenCV. Portanto, a independência offline do app completo permanece **parcialmente validada**, não aprovada de ponta a ponta.

## Próximos passos

1. Instalar dependências declaradas e executar os testes gráficos sob Xvfb ou numa sessão desktop.
2. Com rede desativada e um modelo Ollama já baixado, verificar inicialização, conversa, memória, animações, ferramentas autorizadas e reinicialização.
3. Medir RSS/CPU, latência, threads e processos durante a inicialização e uma conversa; confirmar encerramento sem worker órfão.
4. Testar indisponibilidade de um provedor externo com fallback local real e, depois, restauração de rede.
