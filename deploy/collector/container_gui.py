"""Container-only desktop entry point; opening never starts collection."""
from pathlib import Path
import tkinter as tk

from collector.docker_gui import DockerCollectorWindow
from collector.errors import CollectorError


class ContainerCollectorWindow(DockerCollectorWindow):
    def _load(self, path):
        def load():
            try:
                return self.service.load(path), None
            except CollectorError as error:
                return None, str(error)

        def shown(result):
            config, error = result
            if config is None:
                self.connection_status.set('Collector setup is unavailable')
                self.sidebar_status.set('Setup required')
                self.status.set(error)
                # Installation with missing original setup is a recovery state,
                # not permission to create an empty queue or replacement key.
                self.save_button.configure(state='disabled')
            else:
                self._settings_loaded(config)

        self._start('Opening Docker Collector settings…', load, shown)

    def _refresh_actions(self):
        super()._refresh_actions()
        if self.saved is None:
            self.save_button.configure(state='disabled')
            self.import_button.configure(state='disabled')


def main():
    root = tk.Tk(className='LinkerCollectorDocker')
    icon = tk.PhotoImage(file=str(Path(__file__).with_name('collector.png')))
    root.iconphoto(True, icon)
    # Loading uses read-only probes/RPC. Only an explicit Start can resume the
    # scheduler after this desktop replacement; no native profile is created.
    ContainerCollectorWindow(root, Path('/tmp/collector-desktop/config.toml'), auto_start=False)
    root.title('SCADA Collector - Linux Docker')
    root.mainloop()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
