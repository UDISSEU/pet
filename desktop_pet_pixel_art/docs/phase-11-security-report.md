# Fase 11 — hardening do gerenciador de arquivos

Data: 5 de novembro de 2026

## Vulnerabilidades encontradas

- A política padrão podia resolver `~/Downloads` com `Path.resolve()` e autorizar silenciosamente um destino que fosse link simbólico.
- A prévia e a execução não estavam ligadas por uma prova íntegra: caminhos podiam ser alterados depois da aprovação.
- `shutil.move()` operava por caminhos novamente resolvidos, podia sobrescrever um destino e não garantia movimento atômico no mesmo filesystem.
- A validação do plano e do undo usava `resolve()` em alguns componentes, mantendo janelas entre checagem e movimentação.
- O rollback não verificava todos os conflitos antes da operação e também dependia de `shutil.move()`.

## Correções

- `DirectoryAccessPolicy` deixa de canonicalizar por `resolve()`, rejeita componentes simbólicos e caminhos com `..`, e não inclui raízes padrão inseguras na allowlist.
- Busca/listagem validam permissões e abrem a raiz e diretórios componentes com `O_NOFOLLOW`; links de arquivo/diretório não são seguidos.
- Organização exige uma prévia assinada por HMAC mantido apenas no processo, vinculada à raiz, aos nomes e à identidade/metadados do arquivo. Planos forjados, caminhos relativos, travessia e arquivos alterados são recusados.
- Movimentações usam `renameat2(RENAME_NOREPLACE)` com descritores de diretório abertos sem seguir links. Destinos existentes nunca são sobrescritos; diretórios de categoria precisam ser diretórios reais.
- Toda a lista é validada antes do primeiro movimento. Se cancelamento ou falha ocorrer durante a operação, movimentos já feitos são revertidos em ordem inversa. O undo usa tokens de integridade, valida novamente as origens/destinos e tem rollback simétrico.
- Nenhuma permissão existente foi ampliada.

## Testes e resultados

`python3 -m unittest tests.nova_ai.test_actions`: **24 aprovados**. Inclui Downloads como symlink, categoria Documentos como symlink, destino externo, origem trocada por symlink, conflito de destino, adulteração de token/plano, `../`, undo adulterado, interrupção entre movimentos e organização/restauração normal. Todos usam diretórios temporários.

`python3 -m py_compile src/nova_ai/actions/file_manager.py src/nova_ai/actions/action_validator.py`: aprovado.

`git diff --check`: aprovado.

Tentativa solicitada de suíte pytest: `python3 -m pytest -v` não iniciou porque pytest não está instalado (`No module named pytest`). A alternativa `python3 -m unittest discover -s tests` executou 113 casos, mas terminou com 26 erros, 1 falha e 2 skips: os testes `nova_ai` são carregados sob o nome que sombreia o pacote fonte nesse modo de descoberta, e os testes de desktop/soak não podem importar porque `cv2` (OpenCV) está ausente. A descoberta isolada `python3 -m unittest discover -s tests/nova_ai -v` passou: **67 aprovados, 2 skips** (PyTorch opcional ausente). Não foram ocultadas essas limitações ambientais.

## Limitações

- A movimentação segura depende de Linux com `renameat2(RENAME_NOREPLACE)`; o código falha fechado se a função não estiver disponível.
- Tokens de prévia/undo são intencionalmente efêmeros e deixam de ser aceitos após reiniciar o processo. O armazenamento seguro de um diário durável de undo ainda não existe.
- Rollback é tentado para cada movimento. Se outro processo criar um conflito no caminho de origem simultaneamente e impedir também o rollback, a ferramenta retorna erro de recuperação; não apaga nem sobrescreve o arquivo concorrente.
- Testes de GUI e suíte pytest integral requerem dependências do projeto (OpenCV e pytest) instaladas no ambiente.
