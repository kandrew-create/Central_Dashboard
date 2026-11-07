"""Desktop manager for one Docker Collector; no native collection scheduler."""
from pathlib import Path
import sys
import tkinter as tk
from tkinter import ttk, messagebox

from collector.gui import CollectorWindow
from deploy.collector.desktop import DockerDesktopService
from collector.time_display import windows_timezone


class DockerCollectorWindow(CollectorWindow):
    def _build_collection(self, parent):
        super()._build_collection(parent)
        card = parent.winfo_children()[0]
        bar = ttk.Frame(card, style='Card.TFrame')
        bar.pack(fill='x', before=card.winfo_children()[1], pady=6)
        self.timezone_summary = tk.StringVar(self.root)
        ttk.Label(bar, textvariable=self.timezone_summary, style='Muted.TLabel', wraplength=1000).pack(anchor='w')
        for field, caption in (('schedule_timezone', 'Use Windows zone for schedule'),
                               ('timezone', 'Use Windows zone for source')):
            button = self._button(bar, caption, lambda selected=field: self._use_windows_timezone(selected))
            button.pack(side='left', padx=(0, 8), pady=4)
        self._update_timezone_summary()

    def _update_timezone_summary(self):
        if hasattr(self, 'timezone_summary'):
            self.timezone_summary.set('Windows timezone: ' + (windows_timezone() or 'Unavailable') +
                                      ' | Source timezone for uploads: ' + (self.variables['timezone'].get() or 'Unknown'))

    def _use_windows_timezone(self, field):
        name = windows_timezone()
        if not name:
            self.status.set('Windows timezone could not be detected. Enter the verified IANA timezone explicitly.')
            return
        if field == 'timezone' and self.saved and self.saved.source_id and self.saved.timezone != name:
            messagebox.showinfo('Source timezone review',
                                'Windows uses ' + name + '. This existing source needs a reviewed new generation '
                                'before changing timestamp interpretation. Existing uploads remain unchanged.', parent=self.root)
            return
        self.variables[field].set(name)
        self.status.set('Windows timezone selected. Save settings to apply it.')

    def _form_changed(self, *args):
        super()._form_changed(*args)
        self._update_timezone_summary()

    def __init__(self, root, config_path, service=None, auto_start=False):
        super().__init__(root, config_path, service or DockerDesktopService(config_path), load_on_open=not auto_start)
        if not auto_start and not self.busy and self.saved is None:
            self._load(self.config_path)
        self.root.title('SCADA Collector - Docker')
        self.auto_button.configure(text='Start Collector')
        self.stop_button.configure(text='Stop Collector')
        self._refresh_actions()
        self.status_poll = self.root.after(1000, self._initial_status)
        if auto_start:
            self.startup_id = self.root.after(0, self._startup)

    def _startup(self):
        def shown(result):
            config = result['config']
            self.saved = self.base = config
            self.config_path = config.path
            self._populate(config)
            self._show_collection_status(result['status'])
            self.status.set(result['message'])
        self._start('Starting Docker Desktop and checking the saved Collector setup…',
                    lambda: self.service.startup(self.config_path), shown)

    def _initial_status(self):
        if self.busy:
            self.status_poll = self.root.after(200, self._initial_status)
        else:
            self.refresh_collection_status()
            self._schedule_status_poll()

    def _schedule_status_poll(self):
        if getattr(self, 'status_poll', None) is not None:
            self.root.after_cancel(self.status_poll)
        minutes = (self.saved or self.base).status_refresh_minutes
        self.status_poll = self.root.after(minutes * 60000, self._periodic_status) if minutes else None

    def _populate(self, config):
        super()._populate(config)
        self._update_timezone_summary()
        if hasattr(self, 'status_poll'):
            self._schedule_status_poll()

    def _periodic_status(self):
        if not self.busy and not self._is_dirty() and not self.password.get() and not self.upload_token.get():
            self.refresh_collection_status()
        self._schedule_status_poll()

    def _refresh_actions(self):
        super()._refresh_actions()
        ready = self.docker_engine_ready is not False
        saved = not self._is_dirty()
        can_start = ready and saved and self.saved.collection_enabled and not self.password.get() and not self.upload_token.get() and not self.busy and not self.docker_running
        self.auto_button.configure(state='normal' if can_start else 'disabled')
        self.collect_button.configure(state='normal' if ready and saved and self.saved.collection_enabled and not self.password.get() and not self.busy and not self.docker_running else 'disabled')
        self.stop_button.configure(state='normal' if not self.busy and self.docker_running or self.manual_collecting and not self.cycle_stop.is_set() else 'disabled')
        self.import_button.configure(state='normal' if not self.busy and not self.docker_running else 'disabled')
        if self.docker_running:
            self.setup_import_status.set('Stop the Docker Collector before importing server setup.')

    def _show_collection_status(self, result):
        self.docker_running = result.get('running', self.docker_running)
        self.docker_engine_ready = result.get('engine_ready', self.docker_engine_ready)
        state = 'running' if self.docker_running else 'stopped'
        self.sidebar_status.set('Check collector status' if self.docker_engine_ready is False else 'Collector ' + state)
        self.docker_status.set(result.get('message') or 'Docker Collector is ' + state + '. Closing this manager leaves its current state unchanged.')
        if result.get('engine_ready') is False:
            self._collection_message(self.docker_status.get())
        else:
            super()._show_collection_status(result)
            self.collection_status.set('Docker Collector ' + state + '. ' + self.collection_status.get())
        self._refresh_actions()

    def refresh_collection_status(self):
        if not self.busy and not self._is_dirty():
            self._start('Reading Docker Collector status…', lambda: self.service.status(self.saved), self._show_collection_status)

    def docker_action(self, action):
        if self.busy:
            return
        if action == 'start' and (self._is_dirty() or not self.saved.collection_enabled
                                  or self.password.get() or self.upload_token.get()
                                  or self.docker_running or self.docker_engine_ready is False):
            self.status.set('Save settings, enable collection and store entered credentials before starting the Docker Collector.')
            return
        work = {'start': self.service.start, 'stop': self.service.stop,
                'status': lambda: self.service.status(self.saved)}[action]
        self._start('Updating Docker Collector…', work, self._show_collection_status)

    def start_auto(self):
        if not self._is_dirty():
            self.docker_action('start')

    def stop_auto(self):
        if self.manual_collecting:
            self.cycle_stop.set()
            self._collection_message('Stopping the current Docker collection operation; pending uploads are preserved.')
            self._refresh_actions()
        else:
            self.docker_action('stop')

    def import_server_setup(self):
        if self.docker_running:
            self._collection_message('Stop the Docker Collector before importing server setup.')
            return
        super().import_server_setup()

    def collect_now(self):
        if self.busy or self.docker_running or self._is_dirty() or self.password.get():
            return
        self.cycle_stop.clear()
        self.manual_collecting = True
        self._start('Running one bounded Docker collection cycle…',
                    lambda: self.service.cycle(self.saved, stop=self.cycle_stop), self._show_collection_status)

    def open_settings(self):
        if self._discard_ok():
            self._load(self.config_path)

    def new_setup(self):
        self.status.set('This manager uses the single Docker Collector configuration. Existing identity, queue and checkpoints are retained.')

    def store_upload_token(self):
        token = self.upload_token.get()
        self.upload_token.set('')
        if token and not self.busy and not self._is_dirty():
            self._start('Protecting the Docker upload credential…',
                        lambda: self.service.store_upload_token(self.saved, token),
                        lambda _: self._collection_message('Upload credential protected inside Docker. Use Test server to verify it.'))

    def close(self):
        # The Docker scheduler is independent of this window. A manual one-off
        # still uses the ordinary bounded cancellation path before closing.
        super().close()

    def _destroy(self):
        if hasattr(self, 'startup_id'):
            self.root.after_cancel(self.startup_id)
        if getattr(self, 'status_poll', None) is not None:
            self.root.after_cancel(self.status_poll)
        super()._destroy()


def launch(config_path):
    if sys.platform == 'win32':
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID('Linker.SCADA.Collector')
    root = tk.Tk()
    DockerCollectorWindow(root, Path(config_path), auto_start=True)
    root.mainloop()
    return 0
