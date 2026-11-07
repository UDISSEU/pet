# Riscos técnicos e restrições de recursos

## Recursos do computador-alvo

O alvo informado tem Intel Core i3, 4 GB de RAM, GPU integrada e cerca de 100 GB livres. Não foi medido modelo exato do CPU, memória disponível em runtime, velocidade de disco ou consumo da aplicação. Portanto, impactos abaixo são análise qualitativa, não benchmark.

- 4 GB totais deixam pouca folga para desktop Linux, Tkinter, decodificação OpenCV, navegador e runtime LLM juntos. Ollama/modelo pode levar a pressão de memória, swap e latência alta; limites variam por quantização, tamanho de contexto e implementação.
- CPU i3 e GPU integrada indicam inferência CPU-bound para a maioria dos runtimes locais. Treinar um modelo de linguagem do zero, mesmo pequeno o bastante para esse ambiente, é incompatível com a meta prática de uso interativo; 100 GB de disco não compensam computação/RAM.
- Animações decodificam vídeos em quadros e usam cache. O loader em thread evita bloquear Tk, mas RAM cumulativa de quadros e CPU de OpenCV/Pillow devem ser monitoradas em uso longo e baixa memória.
- `ContextManager` limita a conversa a 16.000 caracteres e memórias a 3.000, reduzindo payload de rede/modelo, mas não impõe contagem de tokens nem quota de RAM do runtime.

## Riscos arquiteturais

1. **Orquestrador monolítico**: `desktop_pet.py` agrega composição, intents, serviços e integração UI, dificultando substituir UI ou executar serviços de IA isoladamente.
2. **Backend local único**: a abstração `BaseProvider` é mantida, mas roteador e fábrica permitem somente Ollama. Não há interface explícita de runtime local geral, ferramenta/planejador, execução de tarefa ou ciclo de avaliação.
3. **Disponibilidade do Ollama**: falhas de serviço/modelo são comunicadas sem fallback remoto. Isso evita envio implícito de contexto, mas deixa a conversa aberta indisponível até o runtime local ser reparado.
4. **Duas implementações Ollama**: cliente legado e provider podem divergir em contexto, timeout, prompt, segurança e erro.
5. **Memória limitada e sem aprendizado**: lista manual e histórico curto não expressam proveniência, confiança, validade, resumo de episódios, política de esquecimento ou aprovação de inferências.
6. **Identidade distribuída**: instruções de LLM e falas locais vivem em subsistemas distintos; ajustes de personalidade não necessariamente afetam ambos.
7. **Ações e geração ainda não são um plano seguro comum**: intents locais reconhecem comandos à parte, plugin e automações têm mecanismos próprios de permissão. Um agente futuro não deve tratar saída do modelo/memória como autorização para executar ação.
8. **Contratos evoluindo**: `StateManager` é migração parcial; plugins internos são código confiável no processo; APIs internas ainda dependem de mixins e atributos de `DesktopPet`.
9. **Persistência JSON local**: simples e apropriada ao uso atual, mas alterações concorrentes, versionamento de schema, recuperação/migração e crescimento de histórico precisam de política explícita antes de memória rica.
10. **Sensibilidade de dados**: histórico e memória no perfil local são legíveis ao usuário do sistema. O uso de inferência local reduz transferência para provedores de IA, mas não equivale a criptografia em repouso e não altera as integrações externas independentes, como Spotify.
11. **Plugin sandbox não é absoluto**: depende de bubblewrap/prlimit e recursos do kernel; documentação interna registra falha fechada em host sem isolamento de rede. Código de plugin interno tem confiança total no processo.
12. **Operações de sistema**: subprocessos APT, Spotify e aplicativos Linux ampliam superfície operacional. Devem permanecer fora do processo de inferência e atrás de validação, autorização e confirmação.

## Riscos de dependências e manutenção

As dependências de Python declaradas são poucas, porém NumPy/OpenCV podem pressionar memória e instalação em ambientes modestos. Tkinter, D-Bus, X11, Ollama, bwrap e prlimit são dependências de sistema ou opcionais e têm compatibilidade independente da versão Python. A CI testa versões Python declaradas, mas não prova comportamento em cada Linux Mint, compositor ou configuração de 4 GB.

O modelo local e a disponibilidade do serviço Ollama dependem da instalação do usuário. O diagnóstico de ambiente consulta o serviço local, mas não instala runtime nem baixa modelos automaticamente.

## Testes e evidência

Há testes unitários e integração por mocks e workflow com cobertura declarada. Não existe artefato de percentual consultado nem threshold no workflow visto. Documentação relata limitações de testes gráficos/Xvfb e ausência de validação visual/Wayland em execuções anteriores. Nenhum teste foi executado nesta auditoria, para respeitar o escopo documental sem alterar estado de runtime.
