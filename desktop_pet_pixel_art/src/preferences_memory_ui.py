"""Builder for the preference tab content."""

import tkinter as tk
from datetime import datetime
from tkinter import messagebox, ttk
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
        value = getattr(context, 'value', None)
        window = getattr(context, 'window', None)
        memory_card = card(memory_content, "O que a Nova deve lembrar?", "Só use informações que você queira manter. Elas entram no contexto da IA local.")
        memory_entry = tk.StringVar()
        memory_form = ttk.Frame(memory_card, style="Card.TFrame")
        memory_form.pack(fill="x")
        memory_input = ttk.Entry(memory_form, textvariable=memory_entry, style="Autonomy.TEntry")
        memory_input.pack(side="left", fill="x", expand=True, ipady=5)
        memory_list, refresh_memories, remove_memory = setup_list(
            memory_content, memory_items, lambda item: item,
            "Suas memórias ficam neste computador e você pode removê-las quando quiser.",
        )
        def add_memory():
            value = memory_entry.get().strip()
            if value:
                memory_items.append(value)
                memory_entry.set("")
                refresh_memories()
        ttk.Button(memory_form, text="Adicionar", style="Primary.TButton", command=add_memory).pack(side="left", padx=(8, 0))
        memory_input.bind("<Return>", lambda _event: add_memory())
        ttk.Button(memory_content, text="Remover selecionada", style="Secondary.TButton", command=remove_memory).pack(anchor="e", pady=(10, 0))

        history_card = card(
            history_content, "Histórico de conversa",
            "Veja as mensagens salvas, quando foram registradas e apague uma mensagem ou todo o histórico.",
        )
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
            history_status.set(f"{len(self.history)} mensagem(ns) salvas neste computador.")
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
            if not save_history(self.history):
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
            if not save_history(self.history):
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