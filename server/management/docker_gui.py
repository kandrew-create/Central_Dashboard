"""Native WSLg management window for the isolated Docker Central Server."""
import argparse
import os
from pathlib import Path
import tkinter as tk
from tkinter import messagebox, ttk

from collector.errors import CollectorError
from server.management.docker import DockerManagerService
from server.management.gui import ManagerWindow


class DockerManagerWindow(ManagerWindow):
    window_title = 'Central Server - WSL / Docker'
    header_detail = 'Manage the Docker server, register SCADA sources and export encrypted collector setup files.'
    font_family = 'Helvetica'

    def __init__(self, root, service):
        super().__init__(root, service)
        root.title('Central Server - WSL / Docker')
        self.notebook.tab(3, text='4  Docker deployment')
        self.start_button.configure(text='Start Docker server')

    def _connection_tab(self, parent):
        card = self._scroll_card(parent)
        ttk.Label(card, text='WSL / Docker deployment', style='Title.TLabel').pack(anchor='w', pady=(0, 12))
        for title, value in (('Compose project', self.service.settings.project),
                             ('Linux workspace', str(self.service.settings.workspace)),
                             ('Collector upload endpoint', self.service.settings.upload_url),
                             ('Setup exports folder', str(self.service.export_directory))):
            ttk.Label(card, text=title, style='Card.TLabel', font=(self.font_family, 10, 'bold')).pack(anchor='w', pady=(12, 3))
            ttk.Label(card, text=value, style='Card.TLabel', wraplength=1000).pack(anchor='w')
        ttk.Label(card, text='Collectors use the saved endpoint shown above. PostgreSQL stays inside Docker. '
                  'Register each source and export its encrypted setup from the Sources tab.',
                  style='Card.TLabel', wraplength=1000).pack(anchor='w', pady=20)
        ttk.Label(card, text='Keep Docker Desktop running with Ubuntu integration enabled. '
                  'Remote collector access requires a separate hostname, certificate and network commissioning step.',
                  style='Card.TLabel', wraplength=1000).pack(anchor='w', pady=8)

    def _form_settings(self):
        return self.service.settings

    def _preview_url(self):
        self.url_preview.set('Collector upload URL: ' + self.service.settings.upload_url)

    def _ai_controls(self, bar):
        ttk.Label(bar, text='Alarm AI is not configured in this Docker deployment.', style='Card.TLabel').pack(side='left')
        self.button(bar, 'Refresh saved results', self.refresh_machine_ai).pack(side='left', padx=12)

    def _show_machine_ai(self, result):
        super()._show_machine_ai(result)
        self.ai_status.set('Saved results from this Docker server. Events use registered machine tags; alarm AI is not configured.')

    def _show(self, result, success_message=None):
        super()._show(result, success_message)
        self.connection_summary.set('WSL / Docker project: ' + self.service.settings.project +
                                    '. Connection mode: ' + self.service.settings.mode + '. PostgreSQL is private inside Docker.')


def main(argv=None):
    parser = argparse.ArgumentParser(description='Central Server WSL / Docker management window')
    parser.add_argument('--workspace', type=Path, default=Path.home() / 'central-server')
    parser.add_argument('--project', default='linker-scada-wsl')
    args = parser.parse_args(argv)
    try:
        service = DockerManagerService(args.workspace, args.project)
    except (CollectorError, OSError, ValueError):
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror('Central Server - WSL / Docker',
                             'Cannot open this Docker workspace. Check its private .env, saved connection mode/address and WSL Compose files.', parent=root)
        root.destroy()
        return 1
    os.chdir(service.export_directory)
    root = tk.Tk()
    DockerManagerWindow(root, service)
    root.mainloop()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
