# Fase 13 — evolução da memória

Data: 5 de novembro de 2026

## Arquitetura e compatibilidade

O armazenamento continua em SQLite local, com transações, `secure_delete`, consentimento obrigatório e detecção de corrupção. O schema foi migrado de forma transacional da versão 1 para a 2, preservando registros e os classificando como fornecidos pelo usuário quando a origem antiga era `user`/`user-confirmed`; as demais origens antigas ficam marcadas como observação do sistema.

As categorias antigas (`episodic`, `semantic`, `procedural`, `preference`) continuam aceitas. Foram acrescentadas `profile`, `project`, `conversation` e `learning`. Cada registro inclui `provenance` (`user_provided`, `inference`, `uncertain` ou `system_observation`) e expiração opcional. A API ainda exige consentimento explícito para gravar ou atualizar; não memoriza mensagens automaticamente.

## Recuperação e controle

- Busca lexical local mantém normalização de acentos, stop words e correspondência parcial, com limite de até 100 resultados.
- Pontuação considera cobertura da consulta, densidade dos termos, relevância, confiança e recência; empates favorecem relevância/confiança e atualização recente.
- Categorias são filtráveis e deduplicação segue escopo de categoria.
- `find_conflicts` sugere conflitos quando registros usam o mesmo rótulo explícito `assunto: valor`. A função não substitui nem apaga nada; a atualização requer consentimento do usuário.
- Expiração é configurável entre 1 e 3650 dias; itens expirados deixam de aparecer na busca e são fisicamente removidos periodicamente.
- A exclusão continua transacional; as conexões SQLite habilitam `secure_delete`.
- O contexto da conversa inclui origem e confiança da memória. `AICore` já serializa memórias em payload separado e instrui o provedor a tratá-las como dados não confiáveis, sem autoridade sobre ferramentas ou políticas.

## Testes

`python3 -m unittest tests.nova_ai.test_memory tests.nova_ai.test_personality_system tests.nova_ai.test_desktop_integration tests.test_ai_providers`: **67 aprovados**. Cobertura inclui categorias novas, proveniência/expiração, limpeza, migração v1, conflitos sem sobrescrita, persistência, deduplicação, exclusão, corrupção, credenciais, recuperação lexical e contexto não confiável.

`python3 -m py_compile src/nova_ai/memory/*.py`: aprovado.

## Impacto e limitações

O armazenamento adicional é pequeno: duas colunas por registro (`provenance`, `expires_at`) e texto já limitado a 8.000 caracteres. A recuperação permanece lexical em SQLite/Python, sem embeddings ou banco vetorial; o custo de memória é proporcional aos candidatos limitados e aos textos pequenos. A detecção de contradição é deliberadamente conservadora e depende de rótulos `assunto: valor`; prosa livre pode não produzir sugestão. Conflitos semânticos complexos ainda precisam de confirmação e resolução manual.
