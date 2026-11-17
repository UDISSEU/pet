# Avaliação de respostas locais

O arquivo `evaluations/responses.json` contém perguntas fixas em português e um
critério de revisão para cada resposta. O conjunto cobre identidade, limites de
observação, instruções conflitantes, segurança, data contextual e concisão.

Para executar a avaliação, o serviço Ollama precisa estar iniciado e o modelo
escolhido precisa já estar instalado. O comando não instala, baixa ou inicia
modelos:

```bash
PYTHONPATH=src .venv/bin/python tools/aurova_response_eval.py \
  --run-inference --model llama3.2:1b \
  --output ~/.local/state/desktop_pet/response-evaluation.json
```

O relatório registra as respostas e tempos de execução. `rating` e
`review_notes` ficam vazios para revisão humana; não há pontuação automática,
pois correspondência de palavras não mede segurança ou qualidade semântica.
Use apenas as perguntas fixas do conjunto e revise o relatório antes de
compartilhá-lo. O Ollama é local por padrão; esta ferramenta não escolhe nem
contata provedores remotos.
