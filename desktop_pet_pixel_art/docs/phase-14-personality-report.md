# Fase 14 — personalidade adaptativa e identidade

Data: 5 de novembro de 2026

## Funcionamento

`NovaIdentity` e `BehaviorRules` fornecem identidade e limites imutáveis e independentes de provedor. `ResponseStyle` contém tom, detalhe e idioma; preferências só são gravadas com consentimento, no banco SQLite de preferências. A camada de prompt legada (`ai/personality.py`) continua ativa; a integração acrescenta as instruções de `PersonalityEngine` ao prompt comum do `AICore`.

Estados visuais existentes são mapeados deterministicamente para estados simulados: `thinking/curious` → curiosa, `thumbs_up/dance` → alegre, `working/busy` → focada, `sleep` → descansando, `error` → preocupada e `idle/walk/sitting` → tranquila. A mascote mantém seus sprites e animações existentes. Estados não reconhecidos não quebram a UI nem trocam aleatoriamente o estado cognitivo.

O estado visual é aplicado como estado emocional transitório em memória, no worker antes da montagem do prompt; ele volta a `IDLE` ao reiniciar e não representa sentimento humano real. As instruções de estado explicitam que humor não muda fatos, permissões ou decisões de segurança. Preferências de estilo são persistentes e separadas do humor.

## Testes

`python3 -m unittest tests.nova_ai.test_personality_system tests.nova_ai.test_desktop_integration tests.nova_ai.test_memory tests.test_ai_providers`: **69 aprovados**. Incluem identidade estável, transições determinísticas, estado temporário, preferências consentidas após reinício, instruções por estado visual e compatibilidade do prompt com provedores.

## Limitações

- Emoções são rótulos simulados e guias determinísticos de linguagem, sem inferência de sentimentos do usuário.
- A adaptação visual ao prompt ocorre na próxima interação de IA, não no meio de uma resposta já enviada.
- Estados visuais que não têm animação existente usam o mapeamento próximo ou mantêm a animação normal; nenhum sprite novo foi introduzido.
- O setter legado `set_behavior_state()` ainda permite persistência explícita por compatibilidade. A integração desktop usa `transition_behavior()` transitório e não persiste o humor.
