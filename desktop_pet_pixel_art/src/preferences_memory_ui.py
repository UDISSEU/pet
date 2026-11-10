"""Builder for the preference tab content."""

import tkinter as tk
from datetime import datetime
from tkinter import messagebox, simpledialog, ttk
from autonomy import save_settings
from nova_ai.memory.errors import (
    DuplicateMemoryError,
    MemoryNotFoundError,
    MemoryStorageError,
    SensitiveInformationError,
)
from ollama_client import save_history
from preferences_common_ui import setup_list


class MemoryPreferencesTabMixin:
    def _build_memory_preferences_tabs(self, context):
        card = getattr(context, 'card', None)
        history_content = getattr(context, 'history_content', None)
        history_refresh_callback = getattr(context, 'history_refresh_callback', None)
        index = getattr(context, 'index', None)
        item = getattr(context, 'item', None)
        memory_content = getattr(context, 'memory_content', None)
        memory_items = getattr(context, 'memory_items', None)
        profile_labels = getattr(context, 'profile_labels', [])
        profile_manager = getattr(context, 'profile_manager', None)
        profile_name = getattr(context, 'profile_name', None)
        profile_options = getattr(context, 'profile_options', {})
        profile_selection = getattr(context, 'profile_selection', None)
        profile_status = getattr(context, 'profile_status', None)
        switch_profile = getattr(context, 'switch_profile', None)
        value = getattr(context, 'value', None)
        window = getattr(context, 'window', None)

        if profile_manager is not None:
            profile_card = card(
                memory_content,
                "Perfis pessoais",
                "Cada perfil mantém sua própria memória SQLite, personalidade e histórico de conversa. "
                "O perfil principal conserva os dados anteriores.",
            )
            profile_picker = ttk.Combobox(
                profile_card, textvariable=profile_selection, values=profile_labels,
                state="readonly",
            )
            profile_picker.pack(fill="x", pady=(4, 8))
            profile_status_label = ttk.Label(
                profile_card, textvariable=profile_status, style="Hint.TLabel",
            )
            profile_status_label.pack(anchor="w", pady=(4, 0))

            def use_selected_profile():
                profile_id = profile_options.get(profile_selection.get())
                if profile_id is None:
                    messagebox.showerror(
                        "Perfil inválido", "Selecione um perfil cadastrado.", parent=window,
                    )
                    return
                if profile_id == profile_manager.active_profile.profile_id:
                    profile_status.set(
                        f"Perfil já ativo: {profile_manager.active_profile.name}"
                    )
                    return
                if not messagebox.askyesno(
                    "Trocar perfil",
                    "As alterações ainda não salvas destas Preferências serão descartadas. "
                    "Deseja trocar de perfil agora?",
                    parent=window,
                ):
                    return
                try:
                    profile = switch_profile(profile_id)
                except (RuntimeError, ValueError) as exc:
                    messagebox.showinfo("Não foi possível trocar", str(exc), parent=window)
                    return
                memory_items[:] = (
                    list(self.settings.get("memories", []))
                    if profile.profile_id == "legacy" else []
                )
                profile_status.set(f"Perfil ativo: {profile.name}")
                window.destroy()
                self.root.after_idle(
                    lambda: self.open_autonomy_settings(selected_tab="memory")
                )
                return

            ttk.Button(
                profile_card, text="Usar perfil selecionado", style="Secondary.TButton",
                command=use_selected_profile,
            ).pack(anchor="e", pady=(0, 4))

            profile_create_row = ttk.Frame(profile_card, style="Card.TFrame")
            profile_create_row.pack(fill="x", pady=(8, 0))
            profile_name_input = ttk.Entry(
                profile_create_row, textvariable=profile_name, style="Autonomy.TEntry",
            )
            profile_name_input.pack(side="left", fill="x", expand=True, ipady=5)

            def create_profile():
                name = profile_name.get().strip()
                if not name:
                    messagebox.showinfo(
                        "Nome do perfil", "Digite um nome para o novo perfil.", parent=window,
                    )
                    profile_name_input.focus_set()
                    return
                if self.ai_request_active:
                    messagebox.showinfo(
                        "Conversa em andamento",
                        "Aguarde a conversa terminar antes de criar um perfil.",
                        parent=window,
                    )
                    return
                try:
                    profile = profile_manager.create(name, activate=False)
                    label = f"{profile.name} · {profile.profile_id[:6]}"
                    profile_options[label] = profile.profile_id
                    profile_labels.append(label)
                    profile_picker.configure(values=profile_labels)
                    profile_selection.set(label)
                    profile_name.set("")
                    use_selected_profile()
                except (RuntimeError, ValueError) as exc:
                    messagebox.showerror(
                        "Não foi possível criar o perfil", str(exc), parent=window,
                    )

            ttk.Button(
                profile_create_row, text="Criar e usar", style="Primary.TButton",
                command=create_profile,
            ).pack(side="left", padx=(8, 0))

        memory_card = card(
            memory_content, "O que a Nova deve lembrar?",
            "Memórias manuais antigas pertencem ao perfil principal. "
            "Memórias de outros perfis ficam no armazenamento local separado. "
            "Desativar o uso impede sua recuperação em respostas, estilo e saudações; "
            "não apaga os registros.",
        )
        memory_enabled = tk.BooleanVar(
            value=self.settings.get("memory_enabled", True) is True
        )

        def persist_privacy_setting(key, variable, default):
            had_setting = key in self.settings
            previous = self.settings.get(key, default)
            self.settings[key] = variable.get() is True
            if save_settings(self.settings, self.settings_path):
                if key in {
                    "conversation_history_enabled", "conversation_context_enabled",
                }:
                    refresh_history()
                return
            if had_setting:
                self.settings[key] = previous
            else:
                self.settings.pop(key, None)
            variable.set(previous is True)
            messagebox.showerror(
                "Não foi possível salvar",
                "A preferência de privacidade não foi alterada.",
                parent=window,
            )

        ttk.Checkbutton(
            memory_card,
            text="Usar memórias salvas nas respostas e saudações",
            variable=memory_enabled,
            command=lambda: persist_privacy_setting(
                "memory_enabled", memory_enabled, True
            ),
        ).pack(anchor="w", pady=(0, 8))
        memory_entry = tk.StringVar()
        memory_form = ttk.Frame(memory_card, style="Card.TFrame")
        memory_form.pack(fill="x")
        memory_input = ttk.Entry(memory_form, textvariable=memory_entry, style="Autonomy.TEntry")
        memory_input.pack(side="left", fill="x", expand=True, ipady=5)
        memory_list, refresh_memories, remove_memory = setup_list(
            memory_content, memory_items, lambda item: item,
            "Suas memórias ficam neste computador e você pode removê-las quando quiser.",
        )
        memory_add_button = None
        memory_remove_button = None

        def add_memory():
            value = memory_entry.get().strip()
            if value:
                memory_items.append(value)
                memory_entry.set("")
                refresh_memories()

        def set_memory_controls(enabled):
            state = "normal" if enabled else "disabled"
            memory_input.configure(state=state)
            if memory_add_button is not None:
                memory_add_button.configure(state=state)
            if memory_remove_button is not None:
                memory_remove_button.configure(state=state)

        if profile_manager is not None:
            active_profile_id = profile_manager.active_profile.profile_id
            set_memory_controls(active_profile_id == "legacy")

        memory_add_button = ttk.Button(
            memory_form, text="Adicionar", style="Primary.TButton", command=add_memory,
        )
        memory_add_button.pack(side="left", padx=(8, 0))
        memory_input.bind("<Return>", lambda _event: add_memory())
        memory_remove_button = ttk.Button(
            memory_content, text="Remover selecionada", style="Secondary.TButton",
            command=remove_memory,
        )
        memory_remove_button.pack(anchor="e", pady=(10, 0))
        if profile_manager is not None:
            set_memory_controls(active_profile_id == "legacy")

        integration = getattr(self, "nova_integration", None)
        if integration is not None:
            structured_card = card(
                memory_content,
                "Memórias privadas deste perfil",
                "Essas informações ficam no SQLite local deste perfil. Só serão gravadas "
                "quando você confirmar ao clicar em Guardar.",
            )
            structured_memories = []
            structured_status = tk.StringVar(value="")
            ttk.Label(
                structured_card, textvariable=structured_status, style="Hint.TLabel",
            ).pack(anchor="w", pady=(6, 0))

            def refresh_structured_memories():
                structured_list.delete(0, "end")
                try:
                    structured_memories[:] = integration.memory.search("", limit=100)
                except MemoryStorageError as exc:
                    structured_memories.clear()
                    structured_status.set(f"Erro ao ler memórias: {exc}")
                    return
                for memory in structured_memories:
                    provenance_label = {
                        "user_provided": "confirmada pelo usuário",
                        "inference": "inferência",
                        "uncertain": "incerta",
                        "system_observation": "observação do sistema",
                    }.get(memory.provenance, memory.provenance)
                    structured_list.insert(
                        "end",
                        f"[{memory.kind.value} · {provenance_label} · "
                        f"confiança {memory.confidence:.0%}] {memory.content}",
                    )
                structured_status.set(
                    f"{len(structured_memories)} memória(s) neste perfil."
                )

            kind_row = ttk.Frame(structured_card, style="Card.TFrame")
            kind_row.pack(fill="x", pady=(8, 4))
            ttk.Label(kind_row, text="Categoria", style="Hint.TLabel").pack(side="left")
            memory_kind = tk.StringVar(value="profile")
            kind_picker = ttk.Combobox(
                kind_row,
                textvariable=memory_kind,
                state="readonly",
                values=(
                    "profile", "preference", "project", "episodic", "semantic",
                    "procedural", "conversation", "learning",
                ),
                width=18,
            )
            kind_picker.pack(side="right")
            structured_entry = tk.StringVar()
            structured_form = ttk.Frame(structured_card, style="Card.TFrame")
            structured_form.pack(fill="x")
            structured_input = ttk.Entry(
                structured_form, textvariable=structured_entry,
                style="Autonomy.TEntry",
            )
            structured_input.pack(side="left", fill="x", expand=True, ipady=5)

            def add_structured_memory():
                content = structured_entry.get().strip()
                if not content:
                    messagebox.showinfo(
                        "Memória vazia", "Escreva a informação que deseja guardar.",
                        parent=window,
                    )
                    return
                try:
                    integration.memory.add(
                        memory_kind.get(),
                        content,
                        source="user",
                        consent=True,
                        provenance="user_provided",
                    )
                except (
                    ValueError, SensitiveInformationError, MemoryStorageError,
                ) as exc:
                    messagebox.showerror(
                        "Não foi possível guardar", str(exc), parent=window,
                    )
                    return
                structured_entry.set("")
                refresh_structured_memories()

            ttk.Button(
                structured_form, text="Guardar", style="Primary.TButton",
                command=add_structured_memory,
            ).pack(side="left", padx=(8, 0))
            structured_input.bind(
                "<Return>", lambda _event: add_structured_memory()
            )
            structured_list, _refresh_structured_list, _remove_structured_item = setup_list(
                structured_card, [], lambda memory: (
                    f"[{memory.kind.value} · {memory.provenance} · "
                    f"confiança {memory.confidence:.0%}] {memory.content}"
                ),
                "Nenhuma memória estruturada cadastrada neste perfil.",
            )

            structured_actions = ttk.Frame(structured_card, style="Card.TFrame")
            structured_actions.pack(fill="x", pady=(8, 0))

            def selected_structured_memory():
                selected = structured_list.curselection()
                return structured_memories[selected[0]] if selected else None

            def edit_structured_memory():
                memory = selected_structured_memory()
                if memory is None:
                    messagebox.showinfo(
                        "Selecione uma memória", "Escolha uma memória para corrigir.",
                        parent=window,
                    )
                    return
                content = simpledialog.askstring(
                    "Corrigir memória",
                    "Atualize o conteúdo:",
                    initialvalue=memory.content,
                    parent=window,
                )
                if content is None:
                    return
                try:
                    integration.memory.update(
                        memory.memory_id, content=content, consent=True
                    )
                except (
                    ValueError, DuplicateMemoryError, MemoryNotFoundError,
                    SensitiveInformationError, MemoryStorageError,
                ) as exc:
                    messagebox.showerror(
                        "Não foi possível corrigir", str(exc), parent=window,
                    )
                    return
                refresh_structured_memories()

            def delete_structured_memory():
                memory = selected_structured_memory()
                if memory is None:
                    messagebox.showinfo(
                        "Selecione uma memória", "Escolha uma memória para remover.",
                        parent=window,
                    )
                    return
                if not messagebox.askyesno(
                    "Remover memória",
                    "Apagar esta memória deste perfil? Essa ação não pode ser desfeita.",
                    parent=window,
                ):
                    return
                try:
                    integration.memory.delete(memory.memory_id)
                except (MemoryNotFoundError, MemoryStorageError) as exc:
                    messagebox.showerror(
                        "Não foi possível remover", str(exc), parent=window,
                    )
                    return
                refresh_structured_memories()

            ttk.Button(
                structured_actions, text="Corrigir selecionada",
                style="Secondary.TButton", command=edit_structured_memory,
            ).pack(side="left")
            ttk.Button(
                structured_actions, text="Apagar selecionada",
                style="Secondary.TButton", command=delete_structured_memory,
            ).pack(side="right")
            refresh_structured_memories()

        history_card = card(
            history_content, "Histórico de conversa",
            "Novas conversas não são salvas nem reutilizam mensagens anteriores por padrão. "
            "Ative cada opção se desejar; as mensagens enviadas ao modelo configurado são "
            "processadas pelo Ollama local.",
        )
        history_enabled = tk.BooleanVar(
            value=self.settings.get("conversation_history_enabled", False) is True
        )
        ttk.Checkbutton(
            history_card,
            text="Salvar as conversas neste computador",
            variable=history_enabled,
            command=lambda: persist_privacy_setting(
                "conversation_history_enabled", history_enabled, True
            ),
        ).pack(anchor="w", pady=(0, 8))
        context_enabled = tk.BooleanVar(
            value=self.settings.get("conversation_context_enabled", False) is True
        )
        ttk.Checkbutton(
            history_card,
            text="Incluir mensagens anteriores como contexto ao perguntar à IA",
            variable=context_enabled,
            command=lambda: persist_privacy_setting(
                "conversation_context_enabled", context_enabled, False
            ),
        ).pack(anchor="w", pady=(0, 8))
        history_status = tk.StringVar(value="")
        ttk.Label(history_card, textvariable=history_status, style="Hint.TLabel").pack(anchor="w")
        history_list_frame = ttk.Frame(history_content, style="Card.TFrame", padding=4)
        history_list_frame.pack(fill="both", expand=True, pady=(0, 10))
        history_view = tk.Text(
            history_list_frame, height=10, wrap="word", relief="flat", bd=0,
            padx=10, pady=8, spacing1=2, spacing3=5,
            bg="#F5F7FA", fg="#344054", font=("TkDefaultFont", 9),
            cursor="arrow", takefocus=True,
        )
        history_scrollbar = ttk.Scrollbar(
            history_list_frame, orient="vertical", command=history_view.yview,
        )
        history_view.configure(yscrollcommand=history_scrollbar.set)
        history_view.pack(side="left", fill="both", expand=True)
        history_scrollbar.pack(side="right", fill="y")
        history_view.tag_configure(
            "history_header", foreground="#26344A", font=("TkDefaultFont", 9, "bold"),
        )
        history_view.tag_configure("history_selected", background="#DFE6FA")
        history_entries = []
        selected_history = {"index": None}

        def scroll_history(event):
            if getattr(event, "num", None) == 4:
                history_view.yview_scroll(-3, "units")
            elif getattr(event, "num", None) == 5:
                history_view.yview_scroll(3, "units")
            elif event.delta:
                amount = int(-event.delta / 120) if abs(event.delta) >= 120 else int(-event.delta)
                if amount:
                    history_view.yview_scroll(amount * 3, "units")
            return "break"

        history_view.bind("<MouseWheel>", scroll_history)
        history_view.bind("<Button-4>", scroll_history)
        history_view.bind("<Button-5>", scroll_history)

        ttk.Label(history_content, text="Mensagem selecionada", style="CardTitle.TLabel").pack(anchor="w", pady=(2, 5))
        history_detail_frame = ttk.Frame(history_content, style="Card.TFrame", padding=1)
        history_detail_frame.pack(fill="x", pady=(0, 10))
        history_detail = tk.Text(
            history_detail_frame, height=5, wrap="word", relief="flat", bd=0,
            bg="#F5F7FA", fg="#344054", font=("TkDefaultFont", 9),
        )
        history_detail_scrollbar = ttk.Scrollbar(
            history_detail_frame, orient="vertical", command=history_detail.yview,
        )
        history_detail.configure(yscrollcommand=history_detail_scrollbar.set)
        history_detail.pack(side="left", fill="both", expand=True)
        history_detail_scrollbar.pack(side="right", fill="y")
        history_detail.configure(state="disabled")

        def show_selected_history_message(index=None):
            if index is not None:
                selected_history["index"] = index
            index = selected_history["index"]
            content = ""
            if index is not None:
                try:
                    item = self.history[index]
                    stamp = item.get("timestamp")
                    if isinstance(stamp, str):
                        try:
                            local_time = datetime.fromisoformat(stamp).astimezone()
                            when = local_time.strftime("%d/%m/%Y às %H:%M:%S")
                        except ValueError:
                            when = "Data/hora não registrada"
                    else:
                        when = "Data/hora não registrada"
                    who = "Você" if item.get("role") == "user" else "Nova"
                    content = f"{who} · {when}\n\n{item.get('content', '')}"
                except (IndexError, ValueError):
                    pass
            history_detail.configure(state="normal")
            history_detail.delete("1.0", "end")
            history_detail.insert("1.0", content)
            history_detail.configure(state="disabled")

        def select_history_message(event):
            line = int(history_view.index(f"@{event.x},{event.y}").split(".")[0])
            for first_line, last_line, index, start, end in history_entries:
                if first_line <= line <= last_line:
                    selected_history["index"] = index
                    history_view.tag_remove("history_selected", "1.0", "end")
                    history_view.tag_add("history_selected", start, end)
                    show_selected_history_message(index)
                    break
            return "break"

        history_view.bind("<Button-1>", select_history_message)

        def refresh_history():
            history_view.configure(state="normal")
            history_view.delete("1.0", "end")
            history_entries.clear()
            for index in range(len(self.history) - 1, -1, -1):
                item = self.history[index]
                if not isinstance(item, dict):
                    continue
                stamp = item.get("timestamp")
                try:
                    when = datetime.fromisoformat(stamp).astimezone().strftime("%d/%m/%Y %H:%M")
                except (TypeError, ValueError):
                    when = "Sem data/hora"
                who = "Você" if item.get("role") == "user" else "Nova"
                message = item.get("content", "")
                if not isinstance(message, str):
                    message = str(message)
                message = message.strip() or "(mensagem vazia)"
                start = history_view.index("end-1c")
                first_line = int(start.split(".")[0])
                history_view.insert("end", f"{who} · {when}\n", "history_header")
                history_view.insert("end", f"{message}\n\n")
                end = history_view.index("end-1c")
                last_line = int(end.split(".")[0])
                history_entries.append((first_line, last_line, index, start, end))
            history_view.configure(state="disabled")
            selected_history["index"] = None
            profile = getattr(self, "profile_manager", None)
            profile_name = profile.active_profile.name if profile else "principal"
            history_status.set(
                f"{len(self.history)} mensagem(ns) no perfil {profile_name}; "
                + (
                    "salvamento ativado."
                    if history_enabled.get() else "novas mensagens não serão salvas."
                )
                + (
                    " Contexto anterior ativado."
                    if context_enabled.get() else " Contexto anterior desativado."
                )
            )
            show_selected_history_message()

        def delete_history_message():
            if self.ai_request_active:
                messagebox.showinfo("Conversa em andamento", "Aguarde a resposta terminar antes de apagar mensagens.", parent=window)
                return
            index = selected_history["index"]
            if index is None:
                messagebox.showinfo("Selecione uma mensagem", "Escolha uma mensagem na lista para apagá-la.", parent=window)
                return
            removed = self.history.pop(index)
            if not save_history(self.history, self.history_path):
                self.history.insert(index, removed)
                messagebox.showerror("Erro ao salvar", "Não consegui apagar a mensagem do arquivo de histórico.", parent=window)
                return
            refresh_history()

        def clear_conversation_history():
            if self.ai_request_active:
                messagebox.showinfo("Conversa em andamento", "Aguarde a resposta terminar antes de apagar o histórico.", parent=window)
                return
            if not self.history:
                return
            if not messagebox.askyesno("Apagar histórico", "Apagar todas as mensagens salvas?", parent=window):
                return
            previous = self.history
            self.history = []
            if not save_history(self.history, self.history_path):
                self.history = previous
                messagebox.showerror("Erro ao salvar", "Não consegui apagar o arquivo de histórico.", parent=window)
            else:
                refresh_history()

        history_actions = ttk.Frame(history_content, style="Autonomy.TFrame")
        history_actions.pack(fill="x")
        ttk.Button(
            history_actions, text="Apagar mensagem selecionada", style="Secondary.TButton",
            command=delete_history_message,
        ).pack(side="left")
        ttk.Button(
            history_actions, text="Apagar todo o histórico", style="Secondary.TButton",
            command=clear_conversation_history,
        ).pack(side="right")
        history_refresh_callback["callback"] = refresh_history
        refresh_history()