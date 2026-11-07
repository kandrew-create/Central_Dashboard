"""The container desktop must preserve local routing and never resume collection on open."""
import os
from pathlib import Path
import subprocess
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

from collector.errors import CollectorError
from deploy.collector.desktop import DockerDesktopService
from deploy.collector.control import DockerControl


class ContainerDesktopTests(unittest.TestCase):
    def test_start_from_network_isolated_desktop_uses_installed_image_without_build_or_pull(self):
        control = DockerControl()
        control.containerized = True
        with patch.object(control, '_engine', return_value=(True, None)), patch.object(
                control, '_call', side_effect=['', '{"State":"running"}']) as call:
            result = control.perform('start')
        start = call.call_args_list[0]
        self.assertEqual(start.args, ('up', '-d', '--no-build', '--pull', 'never', 'collector'))
        self.assertTrue(result['running'])

    def test_failed_prebuilt_start_does_not_fall_back_to_build_or_pull(self):
        control = DockerControl()
        control.containerized = True
        with patch.object(control, '_engine', return_value=(True, None)), patch.object(
                control, '_call', side_effect=CollectorError('Installed image is unavailable')) as call:
            with self.assertRaisesRegex(CollectorError, 'Installed image'):
                control.perform('start')
        self.assertEqual(call.call_count, 1)

    def test_container_commands_remove_host_handoff_without_changing_project(self):
        control = DockerControl()
        control.containerized = True
        command = control.command('up', '-d', '--build', 'collector')
        override = str(control.compose.with_name('docker-compose.collector.container.yml'))
        self.assertIn(override, command)
        self.assertEqual(command[command.index('--project-name') + 1], 'linker-collector')
        self.assertEqual(command[-1], 'collector')
        control.containerized = False
        self.assertNotIn(override, control.command('ps'))

    def test_container_keeps_engine_local_with_untrusted_routing_environment(self):
        control = DockerControl()
        control.containerized = True
        with patch.dict(os.environ, DOCKER_HOST='tcp://wrong.example:2375', DOCKER_CONTEXT='remote',
                        COMPOSE_FILE='wrong.yml'), patch('deploy.collector.control.subprocess.run',
                        return_value=subprocess.CompletedProcess([], 0, 'linux', '')) as run:
            control._engine()
        self.assertNotIn('DOCKER_HOST', run.call_args.kwargs['env'])
        self.assertNotIn('DOCKER_CONTEXT', run.call_args.kwargs['env'])
        self.assertNotIn('COMPOSE_FILE', run.call_args.kwargs['env'])
        self.assertEqual(run.call_args.args[0][1], '--host')

    def test_desktop_open_never_autostarts_scheduler_or_native_runtime(self):
        from deploy.collector import container_gui
        with patch.object(container_gui.tk, 'Tk') as root, patch.object(container_gui.tk, 'PhotoImage'), \
                patch.object(container_gui, 'ContainerCollectorWindow') as window:
            self.assertEqual(container_gui.main(), 0)
        window.assert_called_once_with(root.return_value, Path('/tmp/collector-desktop/config.toml'), auto_start=False)
        root.return_value.mainloop.assert_called_once()


class ContainerRecoveryWindowTests(unittest.TestCase):
    def test_missing_original_setup_disables_mutations_without_modal_or_collection(self):
        import tkinter as tk
        from deploy.collector.container_gui import ContainerCollectorWindow
        try:
            root = tk.Tk()
        except tk.TclError:
            self.skipTest('desktop display unavailable')
        root.withdraw()
        service = Mock(spec=DockerDesktopService)
        service.docker_managed = True
        service.load.side_effect = CollectorError('Original setup and key are missing; no replacement was created.')
        with tempfile.TemporaryDirectory() as folder, patch('collector.gui.messagebox.showerror') as modal, \
                patch('collector.runtime.run') as native:
            app = ContainerCollectorWindow(root, Path(folder) / 'config.toml', service)
            try:
                deadline = time.monotonic() + 3
                while app.busy and time.monotonic() < deadline:
                    root.update()
                    time.sleep(.01)
                self.assertFalse(app.busy)
                self.assertIsNone(app.saved)
                self.assertIn('no replacement', app.status.get())
                self.assertEqual(str(app.save_button['state']), 'disabled')
                self.assertEqual(str(app.import_button['state']), 'disabled')
                self.assertEqual(str(app.auto_button['state']), 'disabled')
                modal.assert_not_called()
                service.start.assert_not_called()
                service.save.assert_not_called()
                native.assert_not_called()
            finally:
                app._destroy()
