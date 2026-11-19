"""Catálogo auditável das ferramentas realmente registradas pelo runtime."""
from aurova_ai.actions import create_default_tool_registry

_DETAILS = {
    "system.clock": ("Lê data/hora local", {}, "datetime ISO e resumo", "system.clock.read", "baixo"),
    "system.monitor": ("Lê métricas agregadas de CPU, memória e disco", {}, "métricas permitidas", "system.cpu.read + system.memory.read + system.disk.read", "baixo"),
    "files.search": ("Busca nomes em diretório autorizado", {"root": "string opcional", "query": "string obrigatório", "limit": "integer 1..100 opcional"}, "lista limitada de correspondências", "file.read + política de diretórios", "médio: exposição de nomes"),
    "files.list_directory": ("Lista arquivos em diretório autorizado", {"directory": "string obrigatório", "limit": "integer opcional"}, "lista limitada de entradas", "file.read + política de diretórios", "médio: exposição de nomes"),
    "files.preview_downloads": ("Prévia reversível da organização em Downloads", {}, "plano assinado de movimentos", "file.read + Downloads", "baixo: leitura"),
    "files.organize_downloads": ("Move arquivos da prévia para categorias; reversível", {"plan": "array obtido da prévia"}, "resumo e plano de desfazer", "file.organize + file.read + confirmação", "alto: movimenta arquivos"),
    "files.organize.undo": ("Desfaz movimentos válidos da organização", {"plan": "array obtido da operação"}, "resumo de reversão", "file.move + file.read + confirmação", "alto: movimenta arquivos"),
    "apps.list": ("Lista launchers de aplicativos instalados", {}, "IDs .desktop", "system.app.read", "baixo"),
    "apps.launch": ("Abre launcher .desktop do catálogo", {"app_id": "string ID do catálogo"}, "resultado do pedido de abertura", "system.app.launch + confirmação", "alto: inicia aplicativo"),
    "reminders.list": ("Lista lembretes locais", {}, "lembretes do perfil local", "reminder.read", "médio: dado pessoal local"),
    "reminders.create": ("Cria lembrete cancelável", {"text": "string até 500 caracteres", "due_at": "ISO 8601 com fuso"}, "lembrete criado", "reminder.write + confirmação", "médio: grava dado local"),
    "reminders.cancel": ("Cancela logicamente lembrete", {"reminder_id": "string obrigatório"}, "confirmação", "reminder.write + confirmação", "médio: altera dado local"),
    "reminders.reactivate": ("Reativa lembrete cancelado", {"reminder_id": "string obrigatório"}, "confirmação", "reminder.write + confirmação", "médio: altera dado local"),
}

def build_catalog():
    registry = create_default_tool_registry()
    rows = []
    for name in registry.names():
        definition = registry.get(name)
        description, params, result, permission, risk = _DETAILS[name]
        rows.append({"name": name, "location": "src/aurova_ai/actions/", "purpose": description,
                     "parameters": params, "result": result, "permissions": permission,
                     "risk": risk, "read_only": definition.read_only,
                     "requires_confirmation": definition.requires_confirmation,
                     "implementation": "functional", "tests": "tests/aurova_ai/test_actions.py"})
    return rows
