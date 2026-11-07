"""Builder for the preference tab content."""

import subprocess
import tkinter as tk
from tkinter import messagebox, ttk
from autonomy import find_installed_apps, resolve_app_command, save_settings, valid_reminder_time
from preferences_common_ui import setup_list
from ui_theme import fit_window_to_screen


class AppsPreferencesTabMixin:
    def _build_reminders_and_apps_preferences_tabs(self, context):
        app_items = getattr(context, 'app_items', None)
        apps_content = getattr(context, 'apps_content', None)
        card = getattr(context, 'card', None)
        confirm_app_launch = getattr(context, 'confirm_app_launch', None)
        index = getattr(context, 'index', None)
        item = getattr(context, 'item', None)
        reminder_content = getattr(context, 'reminder_content', None)
        reminder_items = getattr(context, 'reminder_items', None)
        value = getattr(context, 'value', None)
        window = getattr(context, 'window', None)
        reminder_card = card(reminder_content, "Criar lembrete", "A data e hora seguem o relógio local deste computador.")
        reminder_form = ttk.Frame(reminder_card, style="Card.TFrame")
        reminder_form.pack(fill="x")
        reminder_date = tk.StringVar()
        reminder_time = tk.StringVar()
        reminder_text = tk.StringVar()
        ttk.Label(reminder_form, text="Data").grid(row=0, column=0, sticky="w")
        ttk.Entry(reminder_form, textvariable=reminder_date, width=14, style="Autonomy.TEntry").grid(row=1, column=0, sticky="ew", padx=(0, 8), pady=(3, 8), ipady=4)
        ttk.Label(reminder_form, text="Hora").grid(row=0, column=1, sticky="w")
        ttk.Entry(reminder_form, textvariable=reminder_time, width=9, style="Autonomy.TEntry").grid(row=1, column=1, sticky="ew", padx=(0, 8), pady=(3, 8), ipady=4)
        ttk.Label(reminder_form, text="Lembrete").grid(row=0, column=2, sticky="w")
        ttk.Entry(reminder_form, textvariable=reminder_text, style="Autonomy.TEntry").grid(row=1, column=2, sticky="ew", pady=(3, 8), ipady=4)
        reminder_form.columnconfigure(2, weight=1)
        reminder_list, refresh_reminders, remove_reminder = setup_list(
            reminder_content, reminder_items,
            lambda item: f"{item.get('at', '')[:16].replace('T', ' ')}   ·   {item.get('text', '')}",
            "Quando vencer, a Nova mostra o lembrete em um balão.",
        )
        def add_reminder():
            value = f"{reminder_date.get().strip()}T{reminder_time.get().strip()}"
            parsed = valid_reminder_time(value)
            text = reminder_text.get().strip()
            if not parsed or not text:
                messagebox.showerror("Confira o lembrete", "Informe uma data AAAA-MM-DD, horário HH:MM e texto.", parent=window)
                return
            reminder_items.append({"at": parsed.isoformat(timespec="minutes"), "text": text, "done": False})
            reminder_date.set("")
            reminder_time.set("")
            reminder_text.set("")
            refresh_reminders()
        ttk.Button(reminder_form, text="Adicionar", style="Primary.TButton", command=add_reminder).grid(row=2, column=0, columnspan=3, sticky="e")
        ttk.Button(reminder_content, text="Remover selecionado", style="Secondary.TButton", command=remove_reminder).pack(anchor="e", pady=(10, 0))

        app_card = card(
            apps_content,
            "Permitir que a Nova abra um app",
            "Cadastre apenas apps que você reconhece. Você pode escolher se a Nova confirma cada abertura.",
        )
        ttk.Checkbutton(
            app_card,
            text="Perguntar antes de abrir um app",
            variable=confirm_app_launch,
        ).pack(anchor="w", pady=(0, 10))
        picker_row = ttk.Frame(app_card, style="Card.TFrame")
        picker_row.pack(fill="x", pady=(0, 10))
        app_picker_button = ttk.Button(
            picker_row, text="Buscar app instalado…", style="Secondary.TButton"
        )
        app_picker_button.pack(side="left")
        ttk.Label(
            picker_row, text="ou preencha os dados manualmente abaixo",
            style="Hint.TLabel",
        ).pack(side="left", padx=(10, 0))
        app_form = ttk.Frame(app_card, style="Card.TFrame")
        app_form.pack(fill="x")
        app_name = tk.StringVar()
        app_command = tk.StringVar()
        app_desktop_file = tk.StringVar()
        ttk.Label(app_form, text="Nome").grid(row=0, column=0, sticky="w")
        ttk.Entry(app_form, textvariable=app_name, width=18, style="Autonomy.TEntry").grid(row=1, column=0, sticky="ew", padx=(0, 8), pady=(3, 7), ipady=4)
        ttk.Label(app_form, text="Comando executável").grid(row=0, column=1, sticky="w")
        app_command_input = ttk.Entry(app_form, textvariable=app_command, style="Autonomy.TEntry")
        app_command_input.grid(row=1, column=1, sticky="ew", pady=(3, 7), ipady=4)
        app_command_input.bind("<KeyRelease>", lambda _event: app_desktop_file.set(""))
        app_form.columnconfigure(1, weight=1)
        ttk.Label(
            app_form,
            text="Exemplos: firefox --new-window  ·  code .  ·  /usr/bin/gimp",
            style="Hint.TLabel",
        ).grid(row=2, column=0, columnspan=2, sticky="w", pady=(0, 6))
        app_error = tk.StringVar()
        app_error_label = ttk.Label(
            app_form, textvariable=app_error, foreground="#B42318",
            background="#F5F7FA", wraplength=360,
        )
        app_error_label.grid(row=3, column=0, columnspan=2, sticky="w", pady=(0, 5))
        app_buttons = ttk.Frame(app_form, style="Card.TFrame")
        app_buttons.grid(row=4, column=0, columnspan=2, sticky="ew")
        editing_app = {"index": None}
        app_list, refresh_apps, remove_app = setup_list(
            apps_content, app_items,
            lambda item: f"{item.get('name', '')}   ·   {item.get('command', '')}",
            "Selecione um app para editar ou remover. As alterações são salvas na hora.",
        )
        def clear_app_form():
            editing_app["index"] = None
            app_name.set("")
            app_command.set("")
            app_desktop_file.set("")
            app_error.set("")
            app_error_label.configure(foreground="#B42318")
            save_app_button.configure(text="Adicionar app")
            remove_app_button.configure(state="disabled")
            app_list.selection_clear(0, "end")

        def select_app(_event=None):
            selected = app_list.curselection()
            if not selected:
                return
            index = selected[0]
            editing_app["index"] = index
            app_name.set(app_items[index]["name"])
            app_command.set(app_items[index]["command"])
            app_desktop_file.set(app_items[index].get("desktop_file", ""))
            app_error.set("")
            save_app_button.configure(text="Salvar edição")
            remove_app_button.configure(state="normal")

        def open_app_picker():
            picker = self._set_nova_window_icon(tk.Toplevel(window))
            picker.title("Selecionar aplicativo instalado")
            picker.transient(window)
            picker.attributes("-topmost", True)
            fit_window_to_screen(picker, 460, 500, min_width=380, min_height=360)
            picker.configure(bg="#E3E8F0")
            content = ttk.Frame(picker, style="Autonomy.TFrame", padding=18)
            content.pack(fill="both", expand=True)
            ttk.Label(content, text="Selecionar aplicativo", style="Title.TLabel").pack(anchor="w")
            ttk.Label(
                content,
                text="Pesquise entre os aplicativos instalados neste computador.",
                style="Subtitle.TLabel",
            ).pack(anchor="w", pady=(3, 12))
            query = tk.StringVar()
            search_entry = ttk.Entry(content, textvariable=query, style="Autonomy.TEntry")
            search_entry.pack(fill="x", ipady=5, pady=(0, 10))
            result_frame = ttk.Frame(content, style="Card.TFrame", padding=1)
            result_list = tk.Listbox(
                result_frame, activestyle="none", relief="flat", bd=0,
                highlightthickness=0, selectforeground="#202B45",
                bg="#F5F7FA", fg="#344054", font=("TkDefaultFont", 10),
                selectbackground="#C7D2EE", selectmode="browse",
            )
            scrollbar = ttk.Scrollbar(result_frame, orient="vertical", command=result_list.yview)
            horizontal_scrollbar = ttk.Scrollbar(
                result_frame, orient="horizontal", command=result_list.xview,
            )
            result_list.configure(
                yscrollcommand=scrollbar.set,
                xscrollcommand=horizontal_scrollbar.set,
            )
            result_list.pack(side="left", fill="both", expand=True, padx=(8, 0), pady=7)
            scrollbar.pack(side="right", fill="y", padx=(0, 5), pady=7)
            horizontal_scrollbar.pack(side="bottom", fill="x", padx=8, pady=(0, 7))
            feedback = tk.StringVar()
            ttk.Label(content, textvariable=feedback, style="PageHint.TLabel").pack(anchor="w", pady=(8, 0))
            installed_apps = find_installed_apps()
            visible_apps = []

            def filter_results(*_args):
                needle = query.get().casefold().strip()
                visible_apps.clear()
                visible_apps.extend(
                    item for item in installed_apps
                    if not needle or needle in f"{item['name']} {item['generic_name']}".casefold()
                )
                result_list.delete(0, "end")
                for item in visible_apps:
                    suffix = f"  ·  {item['generic_name']}" if item["generic_name"] else ""
                    result_list.insert("end", item["name"] + suffix)
                if visible_apps:
                    feedback.set(f"{len(visible_apps)} aplicativo(s) encontrado(s).")
                else:
                    feedback.set("Nenhum app encontrado. Você ainda pode preencher o formulário manualmente.")

            def use_selected_app(_event=None):
                selected = result_list.curselection()
                if not selected:
                    feedback.set("Selecione um aplicativo da lista.")
                    return
                app = visible_apps[selected[0]]
                app_name.set(app["name"])
                app_command.set(app["command"])
                app_desktop_file.set(app.get("desktop_file", ""))
                app_error.set("")
                editing_app["index"] = None
                save_app_button.configure(text="Adicionar app")
                remove_app_button.configure(state="disabled")
                app_list.selection_clear(0, "end")
                picker.destroy()

            query.trace_add("write", filter_results)
            filter_results()
            result_list.bind("<Double-Button-1>", use_selected_app)
            picker_buttons = ttk.Frame(content, style="Autonomy.TFrame")
            picker_buttons.pack(fill="x", side="bottom", pady=(12, 0))
            ttk.Button(picker_buttons, text="Cancelar", style="Secondary.TButton", command=picker.destroy).pack(side="right")
            result_frame.pack(fill="both", expand=True)
            ttk.Button(picker_buttons, text="Usar selecionado", style="Primary.TButton", command=use_selected_app).pack(side="right", padx=(0, 8))
            picker.bind("<Return>", use_selected_app)
            picker.bind("<Escape>", lambda _event: picker.destroy())
            search_entry.focus_set()

        app_picker_button.configure(command=open_app_picker)

        def validate_app_form():
            name = app_name.get().strip()
            command = app_command.get().strip()
            try:
                argv = resolve_app_command(command)
            except ValueError as exc:
                app_error_label.configure(foreground="#B42318")
                app_error.set(str(exc))
                return None
            if not name:
                app_error_label.configure(foreground="#B42318")
                app_error.set("Informe um nome para identificar este aplicativo.")
                return None
            for index, item in enumerate(app_items):
                if index != editing_app["index"] and item["name"].casefold() == name.casefold():
                    app_error_label.configure(foreground="#B42318")
                    app_error.set("Já existe um app com esse nome. Escolha outro nome.")
                    return None
            app_error_label.configure(foreground="#B42318")
            app_error.set("")
            return name, command, argv, app_desktop_file.get().strip()

        def persist_app_items():
            updated = dict(self.settings)
            updated["apps"] = [dict(item) for item in app_items]
            if not save_settings(updated, getattr(self, "settings_path", None)):
                app_error_label.configure(foreground="#B42318")
                app_error.set("Não consegui salvar os apps. Confira as permissões e tente novamente.")
                return False
            self.settings = updated
            return True

        def save_app():
            values = validate_app_form()
            if not values:
                return
            name, command, _argv, desktop_file = values
            index = editing_app["index"]
            previous_items = [dict(item) for item in app_items]
            saved_app = {"name": name, "command": command}
            if desktop_file:
                saved_app["desktop_file"] = desktop_file
            if index is None:
                app_items.append(saved_app)
            else:
                app_items[index] = saved_app
            refresh_apps()
            if not persist_app_items():
                app_items[:] = previous_items
                refresh_apps()
                clear_app_form()
                return
            clear_app_form()

        def test_app_command():
            values = validate_app_form()
            if not values:
                return
            name, command, argv, desktop_file = values
            try:
                self._launch_app(
                    {"name": name, "command": command, "desktop_file": desktop_file},
                    question="",
                )
            except (OSError, ValueError, subprocess.SubprocessError):
                app_error_label.configure(foreground="#B42318")
                app_error.set("Não consegui iniciar esse aplicativo agora.")
                self._show_oops()
                return
            app_error_label.configure(foreground="#287247")
            app_error.set(f"Comando enviado ao sistema para abrir {name}.")

        def remove_selected_app():
            previous_items = [dict(item) for item in app_items]
            remove_app()
            if previous_items == app_items:
                return
            if not persist_app_items():
                app_items[:] = previous_items
                refresh_apps()
                clear_app_form()
                return
            clear_app_form()

        app_list.bind("<<ListboxSelect>>", select_app)
        save_app_button = ttk.Button(app_buttons, text="Adicionar app", style="Primary.TButton", command=save_app)
        save_app_button.pack(side="right")
        ttk.Button(app_buttons, text="Testar comando", style="Secondary.TButton", command=test_app_command).pack(side="right", padx=(0, 8))
        ttk.Button(app_buttons, text="Novo app", style="Secondary.TButton", command=clear_app_form).pack(side="left")
        remove_app_button = ttk.Button(
            app_buttons,
            text="Remover app",
            style="Secondary.TButton",
            command=remove_selected_app,
            state="disabled",
        )
        remove_app_button.pack(side="left", padx=(8, 0))