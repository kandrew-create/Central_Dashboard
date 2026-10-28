"""Local Windows desktop setup and data preview. All source I/O runs off the UI thread."""
import argparse
from datetime import datetime
import json
from pathlib import Path
import queue
import sys
import threading
import tkinter as tk
from tkinter import font as tkfont
from tkinter import filedialog, messagebox, simpledialog, ttk

from collector import __version__
from collector.desktop import DesktopService, EDITABLE_FIELDS, default_config, form_config, table_values
from collector.errors import CollectorError


class CollectorWindow:
    def __init__(self, root, config_path, service=None):
        self.root = root
        self.service = service or DesktopService()
        self.config_path = Path(config_path).resolve()
        self.saved = None
        self.base = default_config(self.config_path)
        self.busy = False
        self.connected = False
        self.closing = False
        self.loading = False
        self.pending = queue.Queue()
        self.controls = []
        self.records = []
        self.detail_windows = []
        self.auto_thread = None
        self.auto_stop = threading.Event()
        self.collection_status = tk.StringVar(root, 'Collection is stopped. Configure and save settings before starting.')
        self.upload_token = tk.StringVar(root)
        self.variables = {name: tk.StringVar(root) for name in EDITABLE_FIELDS}
        self.password = tk.StringVar(root)
        self.location = tk.StringVar(root)
        self.status = tk.StringVar(root, "Create or open a setup to get started.")
        self.connection_status = tk.StringVar(root, "Not connected")
        self.password_status = tk.StringVar(root, "No saved password")
        self.table_choice = tk.StringVar(root, "Alarms")
        self.preview_limit = tk.StringVar(root, "20")
        self.after_id = tk.StringVar(root)
        self.include_users = tk.BooleanVar(root, False)
        self.preview_status = tk.StringVar(root, "Test your connection, then load a preview.")
        self.root.title("SCADA Collector · Linker Enterprise")
        self.root.geometry("1220x840")
        self.root.minsize(1040, 740)
        self.root.configure(bg="#f3f6fa")
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self._styles()
        self._build()
        for variable in self.variables.values():
            variable.trace_add("write", self._form_changed)
        self.password.trace_add("write", self._password_changed)
        for variable in (self.table_choice, self.after_id, self.preview_limit, self.include_users):
            variable.trace_add("write", self._preview_changed)
        self._populate(self.base)
        self._refresh_actions()
        self.poll_id = self.root.after(80, self._poll)
        if self.config_path.exists():
            self._load(self.config_path)

    def _styles(self):
        style = ttk.Style(self.root)
        style.theme_use("clam")
        for name in ("TkDefaultFont", "TkTextFont", "TkMenuFont"):
            tkfont.nametofont(name, root=self.root).configure(family="Segoe UI", size=10)
        style.configure("TFrame", background="#f3f6fa")
        style.configure("Card.TFrame", background="#ffffff")
        style.configure("TLabel", background="#f3f6fa", foreground="#17283e")
        style.configure("Card.TLabel", background="#ffffff", foreground="#17283e")
        style.configure("Muted.TLabel", background="#ffffff", foreground="#627287")
        style.configure("Title.TLabel", background="#ffffff", foreground="#17283e", font=("Segoe UI", 15, "bold"))
        style.configure("TButton", padding=(14, 8), background="#e8eef6", foreground="#17283e")
        style.configure("Primary.TButton", background="#2265d7", foreground="white")
        style.map("Primary.TButton", background=[("disabled", "#d5deea"), ("active", "#184eab")],
                  foreground=[("disabled", "#66758a")])
        style.configure("TEntry", padding=7, fieldbackground="white")
        style.configure("TCombobox", padding=6, fieldbackground="white")
        style.configure("TNotebook", background="#f3f6fa", borderwidth=0)
        style.configure("TNotebook.Tab", padding=(22, 12), font=("Segoe UI", 10, "bold"))
        style.map("TNotebook.Tab", background=[("selected", "white")], foreground=[("selected", "#2265d7")])
        style.configure("Treeview", rowheight=34, background="white", fieldbackground="white", borderwidth=0)
        style.configure("Treeview.Heading", padding=(8, 10), background="#eaf0f7", foreground="#33465e",
                        font=("Segoe UI", 10, "bold"))
        style.configure("Card.TCheckbutton", background="white", foreground="#33465e")
        style.configure("Horizontal.TProgressbar", background="#2265d7", troughcolor="#e8eef6", borderwidth=0)

    def _button(self, parent, title, command, primary=False):
        button = ttk.Button(parent, text=title, command=command,
                            style="Primary.TButton" if primary else "TButton")
        self.controls.append((button, "normal"))
        return button

    def _entry(self, parent, name, row, column, label, values=None, width=28):
        ttk.Label(parent, text=label, style="Card.TLabel").grid(row=row, column=column, sticky="w", pady=(8, 5))
        options = dict(textvariable=self.variables[name], width=width)
        field = (ttk.Combobox(parent, values=values, state="readonly", **options) if values
                 else ttk.Entry(parent, **options))
        field.grid(row=row + 1, column=column, sticky="ew", padx=(0, 18))
        self.controls.append((field, "readonly" if values else "normal"))

    def _build(self):
        header = tk.Frame(self.root, bg="#12243c", padx=28, pady=19)
        header.pack(fill="x")
        tk.Label(header, text="LINKER  /  SCADA COLLECTOR", bg="#12243c", fg="#a8c9ff",
                 font=("Segoe UI", 10, "bold")).pack(anchor="w")
        tk.Label(header, text="Source connection, collection & upload", bg="#12243c", fg="white",
                 font=("Segoe UI", 21, "bold")).pack(anchor="w", pady=(5, 0))
        tk.Label(header, text="Set up this PC’s read-only connection and inspect its alarm and event history.",
                 bg="#12243c", fg="#c7d4e5", font=("Segoe UI", 10)).pack(anchor="w", pady=(4, 0))
        toolbar = ttk.Frame(self.root, padding=(24, 14))
        toolbar.pack(fill="x")
        ttk.Label(toolbar, textvariable=self.location, foreground="#607086").pack(side="left", fill="x", expand=True)
        self._button(toolbar, "New setup…", self.new_setup).pack(side="right", padx=(8, 0))
        self._button(toolbar, "Open settings…", self.open_settings).pack(side="right")
        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill="both", expand=True, padx=24)
        connection_tab = ttk.Frame(self.notebook, padding=(0, 16))
        preview_tab = ttk.Frame(self.notebook, padding=(0, 16))
        self.notebook.add(connection_tab, text="1   Connection & setup")
        self.notebook.add(preview_tab, text="2   Alarm & event preview")
        collection_tab = ttk.Frame(self.notebook, padding=(0,16))
        self.notebook.add(collection_tab, text='3   Collection & upload')
        self._build_collection(collection_tab)
        connection_tab.columnconfigure(0, weight=3)
        connection_tab.columnconfigure(1, weight=2)
        connection_tab.rowconfigure(0, weight=1)

        form = ttk.Frame(connection_tab, style="Card.TFrame", padding=22)
        form.grid(row=0, column=0, sticky="nsew", padx=(0, 16))
        form.columnconfigure(0, weight=1)
        form.columnconfigure(1, weight=1)
        ttk.Label(form, text="PostgreSQL connection", style="Title.TLabel").grid(row=0, column=0, columnspan=2, sticky="w")
        self._entry(form, "host", 1, 0, "Host")
        self._entry(form, "port", 1, 1, "Port", width=12)
        self._entry(form, "database", 3, 0, "Database name")
        self._entry(form, "user", 3, 1, "Read-only username")
        self._entry(form, "sslmode", 5, 0, "Database TLS", values=("disable", "require", "verify-ca", "verify-full"))
        self._entry(form, "timezone", 5, 1, "Source timezone (IANA)")
        ttk.Label(form, text="Leave timezone blank if unknown. Unencrypted access is limited to this PC.",
                  style="Muted.TLabel", wraplength=590).grid(row=7, column=0, columnspan=2, sticky="w", pady=(9, 12))
        ttk.Separator(form).grid(row=8, column=0, columnspan=2, sticky="ew", pady=(0, 4))
        self._entry(form, "schema", 9, 0, "Approved schema")
        mapping = ttk.Frame(form, style="Card.TFrame")
        mapping.grid(row=9, column=1, rowspan=2, sticky="nsew")
        mapping.columnconfigure(0, weight=1)
        mapping.columnconfigure(1, weight=1)
        self._entry(mapping, "alarm_table", 0, 0, "Alarm table", width=15)
        self._entry(mapping, "event_table", 0, 1, "Event table", width=15)
        self.save_button = self._button(form, "Save settings", self.save_settings, primary=True)
        self.save_button.grid(row=11, column=0, columnspan=2, sticky="w", pady=(18, 0))

        side = ttk.Frame(connection_tab)
        side.grid(row=0, column=1, sticky="nsew")
        credential = ttk.Frame(side, style="Card.TFrame", padding=22)
        credential.pack(fill="x")
        ttk.Label(credential, text="Protected password", style="Title.TLabel").pack(anchor="w")
        ttk.Label(credential, text="Save your settings first, then store the database password.",
                  style="Muted.TLabel", wraplength=350).pack(anchor="w", pady=(8, 14))
        password_entry = ttk.Entry(credential, textvariable=self.password, show="●")
        password_entry.pack(fill="x")
        self.password_entry = password_entry
        self.controls.append((password_entry, "normal"))
        self.password_button = self._button(credential, "Store password", self.store_password)
        self.password_button.pack(anchor="w", pady=(12, 8))
        ttk.Label(credential, textvariable=self.password_status, style="Muted.TLabel").pack(anchor="w")
        ttk.Label(credential, text="Protected for the current Windows account.", style="Muted.TLabel").pack(anchor="w", pady=(5, 0))

        health = ttk.Frame(side, style="Card.TFrame", padding=22)
        health.pack(fill="both", expand=True, pady=(16, 0))
        ttk.Label(health, text="Connection status", style="Title.TLabel").pack(anchor="w")
        ttk.Label(health, textvariable=self.connection_status, style="Card.TLabel",
                  font=("Segoe UI", 12, "bold"), wraplength=350).pack(anchor="w", pady=(12, 12))
        self.test_button = self._button(health, "Test connection", self.test_connection, primary=True)
        self.test_button.pack(anchor="w")
        ttk.Label(health, text="Read-only access · two approved tables.\n\nConfigure automatic collection and delivery on the Collection & upload tab.",
                  style="Muted.TLabel", wraplength=350).pack(anchor="w", pady=(16, 0))

        self._build_preview(preview_tab)
        footer = ttk.Frame(self.root, padding=(24, 12))
        footer.pack(side="bottom", fill="x", before=self.notebook)
        self.progress = ttk.Progressbar(footer, mode="determinate", length=105)
        self.progress.pack(side="right", padx=(12, 0))
        ttk.Label(footer, text=f"v{__version__}", foreground="#627287").pack(side="right", padx=12)
        ttk.Label(footer, textvariable=self.status, wraplength=860).pack(side="left", fill="x", expand=True)

    def _build_collection(self, parent):
        card = ttk.Frame(parent, style='Card.TFrame', padding=16)
        card.pack(fill='both', expand=True)
        ttk.Label(card, text='Automatic collection and delivery', style='Title.TLabel').pack(anchor='w')
        ttk.Label(card, textvariable=self.collection_status, style='Muted.TLabel', wraplength=1000).pack(anchor='w', pady=10)
        bar = ttk.Frame(card, style='Card.TFrame')
        bar.pack(fill='x', pady=6)
        self.collect_button = self._button(bar, 'Collect now', self.collect_now, primary=True)
        self.collect_button.pack(side='left')
        self.auto_button = self._button(bar, 'Start automatic collection', self.start_auto)
        self.auto_button.pack(side='left', padx=8)
        self.stop_button = self._button(bar, 'Stop', self.stop_auto)
        self.stop_button.pack(side='left')
        self.status_button = self._button(bar, 'Refresh status', self.refresh_collection_status)
        self.status_button.pack(side='left', padx=8)
        self.collection_save_button = self._button(bar, 'Save settings', self.save_settings)
        self.collection_save_button.pack(side='right')
        token_bar = ttk.Frame(card, style='Card.TFrame')
        token_bar.pack(fill='x', pady=8)
        ttk.Label(token_bar, text='Upload credential', style='Card.TLabel').pack(side='left')
        token = ttk.Entry(token_bar, textvariable=self.upload_token, show='*', width=45)
        token.pack(side='left', padx=8)
        self.controls.append((token, 'normal'))
        self.token_button = self._button(token_bar, 'Store upload credential', self.store_upload_token)
        self.token_button.pack(side='left')
        self.import_button = self._button(token_bar, 'Import server setup', self.import_server_setup)
        self.import_button.pack(side='left', padx=8)
        self.server_test_button = self._button(token_bar, 'Test server', self.test_server)
        self.server_test_button.pack(side='left')
        area = ttk.Frame(card, style='Card.TFrame')
        area.pack(fill='both', expand=True)
        canvas = tk.Canvas(area, background='white', highlightthickness=0)
        scrollbar = ttk.Scrollbar(area, orient='vertical', command=canvas.yview)
        form = ttk.Frame(canvas, style='Card.TFrame', padding=8)
        window = canvas.create_window((0,0), window=form, anchor='nw')
        form.bind('<Configure>', lambda _: canvas.configure(scrollregion=canvas.bbox('all')))
        canvas.bind('<Configure>', lambda e: canvas.itemconfigure(window, width=e.width))
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side='left', fill='both', expand=True)
        scrollbar.pack(side='right', fill='y')
        form.columnconfigure(0, weight=1)
        form.columnconfigure(1, weight=1)
        labels = {'source_id':'Source ID (from server provisioning)', 'generation_id':'Generation ID (from server provisioning)',
                  'collection_enabled':'Enable collection', 'marker_verified':'Change marker verified locally',
                  'scan_mode':'Collection mode', 'history_start':'Initial history start (local ISO time)',
                  'history_end':'Initial history end (exclusive local ISO time)', 'all_history':'Approve all initial history',
                  'page_rows':'Records per read', 'max_pages':'Maximum reads per run', 'overlap_seconds':'Change overlap (seconds)',
                  'reconcile_ids':'Recent ID reconciliation range', 'queue_bytes':'Local state quota (bytes)',
                  'min_free_bytes':'Minimum free disk space (bytes)', 'privacy':'Operator field policy',
                  'upload_url':'Fixed HTTPS upload URL', 'upload_enabled':'Enable uploads', 'interval_seconds':'Interval (seconds)',
                  'schedule_mode':'Schedule', 'schedule_timezone':'Schedule timezone (IANA)', 'schedule_time':'Daily/weekly time (HH:MM)',
                  'upload_ca_file':'Trusted upload CA file (blank uses public CAs)',
                  'schedule_weekday':'Weekly day (Monday=0, Sunday=6)'}
        for index, name in enumerate(EDITABLE_FIELDS[9:]):
            options = ('True','False') if type(getattr(self.base, name)) is bool else {
                'scan_mode':('id_range','marker'), 'privacy':('upload_all','omit','hash'), 'schedule_mode':('interval','daily','weekly')}.get(name)
            self._entry(form, name, (index//2)*2, index%2, labels[name], values=options, width=42)

    def _show_collection_status(self, result):
        next_run=result.get('next_run')
        next_text=datetime.fromtimestamp(next_run).strftime('%Y-%m-%d %H:%M:%S') if next_run else 'Not scheduled'
        self.collection_status.set(f"Pending batches: {result.get('pending_batches',0)} | Queue: {result.get('pending_bytes',0)} bytes | "
                                   f"Last upload: {result.get('last_successful_upload') or 'None'} | Next run on this PC: {next_text} | "
                                   f"Confirmed source time: {result.get('latest_confirmed_source_timestamp') or 'Unknown'} | Error: {result.get('latest_error') or 'None'}")

    def collect_now(self):
        if self.busy or self._is_dirty() or self.password.get():
            return
        config = self.saved
        self._start('Collecting changed records and delivering pending batches...', lambda: self.service.cycle(config), self._show_collection_status)

    def refresh_collection_status(self):
        if not self.busy and not self._is_dirty():
            self._start('Reading local collection status...', lambda: self.service.status(self.saved), self._show_collection_status)

    def store_upload_token(self):
        token = self.upload_token.get()
        self.upload_token.set('')
        if not token or self.busy or self._is_dirty():
            return
        self._start('Protecting upload credential...', lambda: self.service.store_upload_token(self.saved, token),
                    lambda _: self.collection_status.set('Upload credential protected for this Windows account.'))

    def import_server_setup(self):
        if self.busy or self._is_dirty() or (self.auto_thread and self.auto_thread.is_alive()):
            return
        path = filedialog.askopenfilename(parent=self.root, title='Import encrypted Central Server setup',
                    filetypes=(('Encrypted collector setup', '*.linker-collector'),))
        if not path:
            return
        password = simpledialog.askstring('Unlock server setup', 'Setup-file password:', show='*', parent=self.root)
        if password is None:
            return
        config = self.saved
        def imported(result):
            self.saved = self.base = result
            self.config_path = result.path
            self.connected = False
            self._clear_preview()
            self._populate(result)
            self.connection_status.set('Not tested')
            self.status.set('Server setup imported. Source IDs, upload destination and credential are ready. Test the connection, then collect.')
            self.collection_status.set('Setup imported. Database connection, history approval and schedule preserved. Local-test setups work on the server PC only.')
        self._start('Unlocking and importing server setup...', lambda: self.service.import_setup(config, path, password), imported)

    def test_server(self):
        if self.busy or self._is_dirty() or self.upload_token.get():return
        config=self.saved
        self._start('Testing HTTPS, upload credential and source registration...',lambda:self.service.check_upload(config),
                    lambda result:self.collection_status.set('Server connection verified: '+result['upload_url']+'. Credential and active source/generation accepted; no records were uploaded.'))

    def start_auto(self):
        if self.busy or self._is_dirty() or not self.saved.collection_enabled or (self.auto_thread and self.auto_thread.is_alive()):
            return
        from collector.runtime import run
        self.auto_stop.clear()
        path = self.saved.path
        def scheduled():
            try:
                run(path, self.auto_stop)
            except Exception:
                self.pending.put((False, 'Automatic collection stopped. Check settings, source permissions, and local state.', lambda _: None))
        self.auto_thread = threading.Thread(target=scheduled, daemon=True, name='collector-local-scheduler')
        self.auto_thread.start()
        self.collection_status.set('Automatic collection is running. Refresh status to see pending work and delivery results.')
        self._refresh_actions()

    def stop_auto(self):
        self.auto_stop.set()
        self.collection_status.set('Stopping after the current bounded operation finishes.')

    def _build_preview(self, parent):
        card = ttk.Frame(parent, style="Card.TFrame", padding=20)
        card.pack(fill="both", expand=True)
        ttk.Label(card, text="Inspect source records", style="Title.TLabel").pack(anchor="w")
        bar = ttk.Frame(card, style="Card.TFrame")
        bar.pack(fill="x", pady=(16, 12))
        table = ttk.Combobox(bar, textvariable=self.table_choice, values=("Alarms", "Events"), state="readonly", width=12)
        table.pack(side="left")
        self.controls.append((table, "readonly"))
        ttk.Label(bar, text="Rows", style="Card.TLabel").pack(side="left", padx=(16, 5))
        rows = ttk.Entry(bar, textvariable=self.preview_limit, width=5)
        rows.pack(side="left")
        self.controls.append((rows, "normal"))
        ttk.Label(bar, text="After ID (optional)", style="Card.TLabel").pack(side="left", padx=(16, 5))
        after = ttk.Entry(bar, textvariable=self.after_id, width=10)
        after.pack(side="left")
        self.controls.append((after, "normal"))
        users = ttk.Checkbutton(bar, text="Include operator fields", variable=self.include_users, style="Card.TCheckbutton")
        users.pack(side="left", padx=16)
        self.controls.append((users, "normal"))
        self.preview_button = self._button(bar, "Load preview", self.load_preview, primary=True)
        self.preview_button.pack(side="right")
        ttk.Label(card, textvariable=self.preview_status, style="Muted.TLabel").pack(anchor="w", pady=(0, 12))
        area = ttk.Frame(card, style="Card.TFrame")
        area.pack(fill="both", expand=True)
        area.columnconfigure(0, weight=1)
        area.rowconfigure(0, weight=1)
        headings = ("ID", "Source local time", "Tag / source", "Description", "Value", "Active", "Ack", "Time quality")
        widths = (55, 205, 175, 285, 90, 70, 70, 115)
        self.tree = ttk.Treeview(area, columns=tuple(range(8)), show="headings", selectmode="browse")
        for index, (title, width) in enumerate(zip(headings, widths)):
            self.tree.heading(index, text=title)
            self.tree.column(index, width=width, minwidth=50, stretch=index == 3)
        vertical = ttk.Scrollbar(area, orient="vertical", command=self.tree.yview)
        horizontal = ttk.Scrollbar(area, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        vertical.grid(row=0, column=1, sticky="ns")
        horizontal.grid(row=1, column=0, sticky="ew")
        self.tree.tag_configure("even", background="#f3f7fc")
        bottom = ttk.Frame(card, style="Card.TFrame")
        bottom.pack(fill="x", pady=(14, 0))
        self.details_button = self._button(bottom, "View selected record", self.view_details)
        self.details_button.pack(side="left")
        ttk.Label(bottom, text="Source times are preserved. A preview does not confirm delivery or change a checkpoint.",
                  style="Muted.TLabel", wraplength=700).pack(side="right")

    def _populate(self, config):
        self.loading = True
        for name, variable in self.variables.items():
            variable.set(str(getattr(config, name)))
        self.preview_limit.set(str(config.preview_rows))
        self.password.set("")
        self.upload_token.set('')
        self.location.set(str(config.path))
        self.loading = False

    def _is_dirty(self):
        return self.saved is None or any(self.variables[name].get() != str(getattr(self.saved, name))
                                         for name in EDITABLE_FIELDS)

    def _refresh_actions(self):
        for control, state in self.controls:
            control.configure(state="disabled" if self.busy else state)
        saved = not self._is_dirty()
        has_password = saved and self.saved.password_path.is_file()
        self.password_button.configure(state="normal" if saved and not self.busy else "disabled")
        self.password_entry.configure(state="normal" if saved and not self.busy else "disabled")
        self.test_button.configure(state="normal" if has_password and not self.password.get() and not self.busy else "disabled")
        self.preview_button.configure(state="normal" if self.connected and saved and not self.busy else "disabled")
        self.details_button.configure(state="normal" if self.records and not self.busy else "disabled")
        self.save_button.configure(state="normal" if not self.busy and self._is_dirty() else "disabled")
        running = self.auto_thread is not None and self.auto_thread.is_alive()
        self.collect_button.configure(state='normal' if saved and self.saved.collection_enabled and not self.busy and not self.password.get() else 'disabled')
        self.auto_button.configure(state='normal' if saved and self.saved.collection_enabled and not self.busy and not running else 'disabled')
        self.stop_button.configure(state='normal' if running else 'disabled')
        self.token_button.configure(state='normal' if saved and not self.busy else 'disabled')
        self.import_button.configure(state='normal' if saved and not self.busy and not running else 'disabled')
        self.server_test_button.configure(state='normal' if saved and not self.busy and self.saved.upload_url else 'disabled')
        self.collection_save_button.configure(state='normal' if not self.busy and self._is_dirty() else 'disabled')

    def _clear_preview(self):
        self.records.clear()
        children = self.tree.get_children()
        if children:
            self.tree.delete(*children)
        for window in self.detail_windows:
            if window.winfo_exists():
                window.destroy()
        self.detail_windows.clear()

    def _form_changed(self, *_args):
        if self.loading:
            return
        self.connected = False
        self.connection_status.set("Settings changed · test again after saving")
        self._clear_preview()
        self.status.set("Unsaved changes. Save settings before testing the connection.")
        self._refresh_actions()

    def _preview_changed(self, *_args):
        if self.loading:
            return
        self._clear_preview()
        self.preview_status.set("Preview options changed. Load a new sample.")
        self._refresh_actions()

    def _password_changed(self, *_args):
        if self.loading:
            return
        self.connected = False
        self._clear_preview()
        if self.password.get():
            self.password_status.set("New password entered · click Store password")
            self.status.set("Store the new password before testing the connection.")
        else:
            available = self.saved is not None and self.saved.password_path.is_file()
            self.password_status.set("Saved password available" if available else "No saved password")
        self._refresh_actions()

    def _start(self, label, work, done):
        if self.busy:
            return False
        self.busy = True
        self.status.set(label)
        self.progress.configure(mode="indeterminate")
        self.progress.start(12)
        self._refresh_actions()

        def run():
            try:
                result = work()
            except CollectorError as error:
                self.pending.put((False, str(error), done))
            except Exception:
                self.pending.put((False, "Operation failed. Check local settings, permissions, and the database connection.", done))
            else:
                self.pending.put((True, result, done))

        threading.Thread(target=run, daemon=True, name="collector-desktop-task").start()
        return True

    def _poll(self):
        try:
            success, result, done = self.pending.get_nowait()
        except queue.Empty:
            pass
        else:
            self.busy = False
            self.progress.stop()
            self.progress.configure(mode="determinate", value=0)
            if success:
                done(result)
            else:
                self.connected = False
                self.connection_status.set("Not connected · check the latest error")
                self._clear_preview()
                self.status.set(result)
                if not self.closing:
                    messagebox.showerror("Collector", result, parent=self.root)
            self._refresh_actions()
        if self.closing and not self.busy and not (self.auto_thread and self.auto_thread.is_alive()):
            self.root.destroy()
            return
        self.poll_id = self.root.after(80, self._poll)

    def _discard_ok(self):
        if self.busy:
            return False
        if self._has_unsaved_edits():
            return messagebox.askyesno("Unsaved settings", "Discard unsaved connection changes?", parent=self.root)
        return True

    def _has_unsaved_edits(self):
        return bool(self.password.get()) or bool(self.upload_token.get()) or any(self.variables[name].get() != str(getattr(self.base, name))
                                                for name in EDITABLE_FIELDS)

    def _load(self, path):
        path = Path(path).resolve()

        def loaded(config):
            self.saved = self.base = config
            self.config_path = config.path
            self.connected = False
            self._clear_preview()
            self._populate(config)
            self.connection_status.set("Not tested")
            self.password_status.set("Saved password available" if config.password_path.is_file() else "No saved password")
            self.status.set("Settings opened. Test the connection before loading a preview.")

        self._start("Opening local settings…", lambda: self.service.load(path), loaded)

    def open_settings(self):
        if not self._discard_ok():
            return
        path = filedialog.askopenfilename(parent=self.root, title="Open collector settings",
                                         filetypes=(("Collector settings", "*.toml"), ("All files", "*.*")))
        if path:
            self._load(path)

    def new_setup(self):
        if not self._discard_ok():
            return
        parent = filedialog.askdirectory(parent=self.root, title="Choose a parent folder for a new SCADA Collector setup")
        if not parent:
            return
        path = Path(parent).resolve() / "SCADA Collector" / "config.toml"
        if path.parent.exists():
            messagebox.showerror("Setup already exists", "The SCADA Collector folder already exists here. Open its settings or choose another parent folder.", parent=self.root)
            return
        self.saved = None
        self.base = default_config(path)
        self.config_path = path
        self.connected = False
        self._clear_preview()
        self._populate(self.base)
        self.password_status.set("No saved password")
        self.connection_status.set("Not connected")
        self.status.set("Enter connection details and save settings to create this setup.")
        self._refresh_actions()

    def save_settings(self):
        if self.busy:
            return
        try:
            config = form_config(self.base, {name: variable.get() for name, variable in self.variables.items()})
        except CollectorError as error:
            messagebox.showerror("Check settings", str(error), parent=self.root)
            return
        previous = self.saved

        def saved(result):
            self.saved = self.base = result
            self.config_path = result.path
            self.connected = False
            self._clear_preview()
            self._populate(result)
            self.password_status.set("Saved password available" if result.password_path.is_file() else "No saved password")
            self.connection_status.set("Not tested")
            self.status.set("Settings saved. Store a password, then test the connection.")

        self._start("Saving local settings…", lambda: self.service.save(config, previous), saved)

    def store_password(self):
        if self.busy or self._is_dirty():
            return
        password = self.password.get()
        self.password.set("")
        if not password:
            messagebox.showerror("Password required", "Enter the database password first.", parent=self.root)
            return
        config = self.saved

        def stored(_result):
            self.connected = False
            self._clear_preview()
            self.password_status.set("Password protected for this Windows account")
            self.connection_status.set("Not tested")
            self.status.set("Password stored securely. Test the connection next.")

        self._start("Protecting database password…", lambda: self.service.store_password(config, password), stored)

    def test_connection(self):
        if self.busy or self._is_dirty() or self.password.get():
            return
        config = self.saved
        self.connected = False
        self._clear_preview()

        def checked(_result):
            self.connected = True
            self.connection_status.set("Connected · read-only\nBoth approved tables verified")
            self.status.set("Connection verified at " + datetime.now().strftime("%H:%M:%S") + ". Open the preview tab to inspect records.")
            self.preview_status.set("Connection verified. Choose alarms or events and load a preview.")

        self._start("Testing database connection and table permissions…", lambda: self.service.check(config), checked)

    def load_preview(self):
        if self.busy or self._is_dirty() or not self.connected:
            return
        try:
            limit = int(self.preview_limit.get())
            after = int(self.after_id.get()) if self.after_id.get().strip() else None
        except ValueError:
            messagebox.showerror("Check preview options", "Rows and After ID must be whole numbers.", parent=self.root)
            return
        config = self.saved
        if not 1 <= limit <= config.preview_rows:
            messagebox.showerror("Check preview options", f"Rows must be from 1 to {config.preview_rows}.", parent=self.root)
            return
        table = "alarmhistory" if self.table_choice.get() == "Alarms" else "eventhistory"
        include = self.include_users.get()
        self._clear_preview()

        def previewed(records):
            self.records = records
            for index, record in enumerate(records):
                self.tree.insert("", "end", iid=str(index), values=table_values(record), tags=("even",) if index % 2 == 0 else ())
            privacy = "Operator fields included in record details." if include else "Operator fields omitted."
            self.preview_status.set(f"{len(records)} record(s) loaded from {table}. {privacy}")
            self.status.set("Preview loaded. Select a row and choose View selected record for all preserved fields.")

        self._start("Reading a limited sample from the source…",
                    lambda: self.service.preview(config, table, limit, after, include), previewed)

    def view_details(self):
        selected = self.tree.selection()
        if not selected:
            messagebox.showinfo("Select a record", "Select a row in the preview table first.", parent=self.root)
            return
        record = self.records[int(selected[0])]
        window = tk.Toplevel(self.root)
        window.title(f"Source record {record['source_record_id']} · {record['source_table']}")
        window.geometry("780x610")
        window.transient(self.root)
        content = ttk.Frame(window, padding=16)
        content.pack(fill="both", expand=True)
        ttk.Label(content, text="Preserved source fields and timestamp quality", font=("Segoe UI", 12, "bold")).pack(anchor="w", pady=(0, 12))
        area = ttk.Frame(content)
        area.pack(fill="both", expand=True)
        text = tk.Text(area, wrap="none", font=("Consolas", 10), padx=12, pady=12,
                       background="white", foreground="#17283e", relief="flat")
        area.columnconfigure(0, weight=1)
        area.rowconfigure(0, weight=1)
        scroll = ttk.Scrollbar(area, command=text.yview)
        horizontal = ttk.Scrollbar(area, orient="horizontal", command=text.xview)
        text.configure(yscrollcommand=scroll.set, xscrollcommand=horizontal.set)
        scroll.grid(row=0, column=1, sticky="ns")
        horizontal.grid(row=1, column=0, sticky="ew")
        text.grid(row=0, column=0, sticky="nsew")
        text.insert("1.0", json.dumps(record, indent=2, ensure_ascii=False))
        text.configure(state="disabled")
        ttk.Button(content, text="Close", command=window.destroy).pack(anchor="e", pady=(12, 0))
        self.detail_windows.append(window)

    def close(self):
        if self.busy or (self.auto_thread and self.auto_thread.is_alive()):
            self.auto_stop.set()
            self.closing = True
            self.status.set("Finishing the current operation before closing…")
            return
        if self._has_unsaved_edits():
            if not messagebox.askyesno("Unsaved settings", "Close without saving connection changes?", parent=self.root):
                return
        self.password.set("")
        self.root.after_cancel(self.poll_id)
        self.upload_token.set('')
        self.root.destroy()


def launch(config_path):
    try:
        root = tk.Tk()
    except tk.TclError:
        print("Collector: A Windows desktop session with Tk is required.", file=sys.stderr)
        return 1
    CollectorWindow(root, config_path)
    root.mainloop()
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description="SCADA Collector desktop setup")
    parser.add_argument("--config", type=Path, default=Path("collector-local/config.toml"))
    return launch(parser.parse_args(argv).config)


if __name__ == "__main__":
    raise SystemExit(main())
