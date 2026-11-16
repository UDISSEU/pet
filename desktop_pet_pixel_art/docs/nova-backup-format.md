# Formato de backup da Nova

Os arquivos `.nova-backup.json` são documentos JSON UTF-8 versionados. A versão
atual do formato é `nova-user-config-backup` / `1`.

Cada pacote contém `created_at` (UTC ISO 8601), `backup_id`, `label` e uma lista
fixa de entradas lógicas: `settings.json` e `personality.json`. O conteúdo dos
arquivos presentes é codificado em Base64, com tamanho e SHA-256 individuais.
Entradas ausentes são representadas explicitamente com `present: false`.

O campo `integrity` contém SHA-256 do objeto completo sem o próprio campo de
integridade, serializado em JSON UTF-8 com chaves ordenadas e separadores
compactos. O leitor rejeita versões desconhecidas, entradas extras, nomes fora
da lista permitida, dados acima dos limites e conteúdo que não seja um objeto
JSON. O pacote nunca é interpretado como código.

Senhas, tokens, histórico de conversas, banco de memória, cache e arquivos
externos não fazem parte deste formato. A restauração grava somente os dois
destinos JSON fornecidos pelo gerenciador de perfil, depois de criar um backup
de segurança do estado atual.
