"""Modern local desktop for the WSL/Docker server; backend operations remain in docker.py."""
import argparse
from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, QSize, QThreadPool, QTimer, Qt, Signal, Slot
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QApplication, QAbstractItemView, QButtonGroup, QComboBox, QDialog, QDialogButtonBox,
    QFileDialog, QFrame, QGridLayout, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
    QMainWindow, QMessageBox, QProgressBar, QPushButton, QScrollArea, QSizePolicy,
    QStackedWidget, QTableWidget, QTableWidgetItem, QTextEdit, QVBoxLayout, QWidget,
)

from collector.errors import CollectorError
from server import __version__
from server.management.docker import DockerManagerService
from server.management.docker_theme import STYLESHEET, icon
from server.management.service import text


PAGES = (
    ('Overview', 'Server health, activity and quick actions.', 'overview'),
    ('Register source', 'Connect a SCADA database source to this server.', 'register'),
    ('Sources & setup', 'Manage registrations and export collector setup files.', 'sources'),
    ('Deployment', 'Your WSL workspace and Docker server connection.', 'deployment'),
    ('Equipment identification', 'Review saved results alongside the original message.', 'identification'),
)


def label(value='', name=None, wrap=False):
    widget = QLabel(value)
    widget.setTextFormat(Qt.TextFormat.PlainText)
    widget.setWordWrap(wrap)
    if name:
        widget.setObjectName(name)
    return widget


def card():
    frame = QFrame()
    frame.setObjectName('card')
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(24, 22, 24, 22)
    layout.setSpacing(12)
    return frame, layout


def tone(widget, value):
    widget.setProperty('tone', value)
    widget.style().unpolish(widget)
    widget.style().polish(widget)


class WorkSignals(QObject):
    finished = Signal(bool, object)


class Work(QRunnable):
    def __init__(self, operation):
        super().__init__()
        self.operation = operation
        self.signals = WorkSignals()

    def run(self):
        try:
            result = self.operation()
        except CollectorError as error:
            self.signals.finished.emit(False, str(error))
        except Exception:
            self.signals.finished.emit(False, 'Operation failed. Check Docker Desktop and the selected server workspace.')
        else:
            self.signals.finished.emit(True, result)


class ExportPasswordDialog(QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle('Protect collector setup')
        self.setMinimumWidth(420)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 26, 28, 24)
        layout.setSpacing(14)
        layout.addWidget(label('Encrypt your setup file', 'sectionTitle'))
        layout.addWidget(label('Use at least 12 characters. Transfer the password separately from the file.', 'muted', True))
        self.password = QLineEdit()
        self.confirmation = QLineEdit()
        for title, entry in (('File password', self.password), ('Confirm password', self.confirmation)):
            layout.addWidget(label(title, 'fieldLabel'))
            entry.setEchoMode(QLineEdit.EchoMode.Password)
            layout.addWidget(entry)
        self.error = label('', 'help', True)
        layout.addWidget(self.error)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Ok)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText('Encrypt && export')
        buttons.button(QDialogButtonBox.StandardButton.Ok).setObjectName('primary')
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def accept(self):
        if not 12 <= len(self.password.text()) <= 1024 or self.password.text() != self.confirmation.text():
            self.error.setText('Enter matching passwords of 12–1024 characters.')
            return
        super().accept()

    def take_password(self):
        value = self.password.text()
        self.password.clear()
        self.confirmation.clear()
        return value

    def reject(self):
        self.password.clear()
        self.confirmation.clear()
        super().reject()


class DockerManagerWindow(QMainWindow):
    def __init__(self, service, auto_refresh=True):
        super().__init__()
        self.service = service
        self.busy = False
        self.closing = False
        self.form_dirty = False
        self._ai_pending = False
        self._work = None
        self._done = None
        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(1)
        self.controls = []
        self.registry = {key: [] for key in ('customers', 'sites', 'projects', 'machines')}
        self.source_rows = []
        self.ai_rows = []
        self.status = {}
        self.setWindowTitle('Central Server - WSL / Docker')
        self.setWindowIcon(icon('sources', '#356ff0', 32))
        self.resize(1320, 860)
        self.setMinimumSize(1100, 740)
        self.setStyleSheet(STYLESHEET)
        self._build()
        self._sync_controls()
        if auto_refresh:
            self.refresh()

    def button(self, title, action, style=None, symbol=None):
        widget = QPushButton(title.replace('&', '&&'))
        widget.setCursor(Qt.CursorShape.PointingHandCursor)
        if style:
            widget.setObjectName(style)
        if symbol:
            widget.setIcon(icon(symbol, '#ffffff' if style == 'primary' else '#7488a6', 16))
        widget.clicked.connect(lambda checked=False: action())
        self.controls.append(widget)
        return widget

    def _build(self):
        central = QWidget()
        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        self.setCentralWidget(central)
        sidebar = QWidget()
        sidebar.setObjectName('sidebar')
        sidebar.setFixedWidth(224)
        side = QVBoxLayout(sidebar)
        side.setContentsMargins(18, 28, 18, 22)
        side.setSpacing(7)
        brand = QHBoxLayout()
        mark = label('L')
        mark.setAlignment(Qt.AlignmentFlag.AlignCenter)
        mark.setFixedSize(37, 39)
        mark.setStyleSheet('background:#477dfa;color:white;border-radius:10px;font-size:24px;font-weight:700;')
        brand.addWidget(mark)
        names = QVBoxLayout()
        names.setSpacing(1)
        names.addWidget(label('linker', 'brand'))
        names.addWidget(label('CENTRAL SERVER', 'brandCaption'))
        brand.addLayout(names)
        brand.addStretch()
        side.addLayout(brand)
        side.addSpacing(32)
        side.addWidget(label('WORKSPACE', 'sidebarCaption'))
        side.addSpacing(8)
        self.navigation = QButtonGroup(self)
        self.nav_buttons = []
        for index, (title, _, symbol) in enumerate(PAGES):
            button = QPushButton(('Identification' if index == 4 else title).replace('&', '&&'))
            button.setObjectName('nav')
            button.setIcon(icon(symbol))
            button.setCheckable(True)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            self.navigation.addButton(button, index)
            button.clicked.connect(lambda checked=False, page=index: self.navigate(page))
            self.nav_buttons.append(button)
            side.addWidget(button)
        side.addStretch()
        rule = QFrame()
        rule.setObjectName('sidebarRule')
        side.addWidget(rule)
        side.addSpacing(13)
        side.addWidget(label('LOCAL ENVIRONMENT', 'sidebarCaption'))
        side.addWidget(label('WSL 2  /  Docker', 'sidebarNote'))
        self.sidebar_status = label('Checking server…', 'sidebarNote')
        side.addWidget(self.sidebar_status)
        side.addSpacing(15)
        side.addWidget(label('Linker  ·  v' + __version__, 'sidebarNote'))
        root.addWidget(sidebar)
        workspace = QWidget()
        workspace.setObjectName('workspace')
        content = QVBoxLayout(workspace)
        content.setContentsMargins(0, 0, 0, 0)
        content.setSpacing(0)
        heading = QWidget()
        top = QHBoxLayout(heading)
        top.setContentsMargins(32, 27, 32, 21)
        titles = QVBoxLayout()
        titles.setSpacing(5)
        titles.addWidget(label('CENTRAL SERVER  /  WORKSPACE', 'eyebrow'))
        self.page_title = label('', 'pageTitle')
        self.page_subtitle = label('', 'pageSubtitle', True)
        titles.addWidget(self.page_title)
        titles.addWidget(self.page_subtitle)
        top.addLayout(titles, 1)
        environment = label('LOCAL  ·  WSL / DOCKER', 'pill')
        top.addWidget(environment, 0, Qt.AlignmentFlag.AlignTop)
        content.addWidget(heading)
        self.pages = QStackedWidget()
        content.addWidget(self.pages, 1)
        for builder in (self._overview_page, self._register_page, self._sources_page,
                        self._deployment_page, self._identification_page):
            self.pages.addWidget(builder())
        self.footer_frame = QFrame()
        self.footer_frame.setObjectName('footer')
        footer = QHBoxLayout(self.footer_frame)
        footer.setContentsMargins(30, 13, 30, 13)
        footer.setSpacing(15)
        self.footer = label('Checking the Docker server…', 'footerText', True)
        self.footer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        footer.addWidget(self.footer, 1)
        self.progress = QProgressBar()
        self.progress.setFixedWidth(96)
        self.progress.setTextVisible(False)
        self.progress.setRange(0, 1)
        self.progress.setValue(0)
        footer.addWidget(self.progress)
        content.addWidget(self.footer_frame)
        root.addWidget(workspace, 1)
        self.navigate(0)

    def _page(self):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        body = QWidget()
        body.setObjectName('workspace')
        layout = QVBoxLayout(body)
        layout.setContentsMargins(32, 2, 32, 28)
        layout.setSpacing(18)
        scroll.setWidget(body)
        return scroll, layout

    def _overview_page(self):
        page, layout = self._page()
        hero, box = card()
        row = QHBoxLayout()
        text_column = QVBoxLayout()
        text_column.setSpacing(7)
        text_column.addWidget(label('Your collection hub', 'heroTitle'))
        text_column.addWidget(label('A central home for your SCADA alarm and event history.', 'muted', True))
        row.addLayout(text_column, 1)
        self.health_pill = label('Checking…', 'pill')
        row.addWidget(self.health_pill, 0, Qt.AlignmentFlag.AlignTop)
        box.addLayout(row)
        box.addSpacing(8)
        services = QHBoxLayout()
        self.service_dots = {}
        self.service_labels = {}
        for key, title in (('api_ready', 'HTTPS API'), ('database_ready', 'PostgreSQL'), ('worker_running', 'Background worker')):
            group = QHBoxLayout()
            dot = label('●', 'serviceDot')
            value = label('Checking', 'muted')
            self.service_dots[key] = dot
            self.service_labels[key] = value
            group.addWidget(dot)
            group.addSpacing(3)
            group.addWidget(label(title, 'fieldLabel'))
            group.addWidget(value)
            group.addStretch()
            services.addLayout(group, 1)
        box.addLayout(services)
        box.addSpacing(9)
        actions = QHBoxLayout()
        self.start_button = self.button('Start server', self.start_server, 'primary')
        self.stop_button = self.button('Stop server', self.stop_server)
        self.refresh_button = self.button('Refresh', self.refresh, 'quiet', 'refresh')
        actions.addWidget(self.start_button)
        actions.addWidget(self.stop_button)
        actions.addWidget(self.refresh_button)
        actions.addStretch()
        box.addLayout(actions)
        layout.addWidget(hero)
        metrics = QHBoxLayout()
        metrics.setSpacing(14)
        self.metric_values = {}
        for key, title, hint in (('sources', 'Registered sources', 'SCADA database connections'),
                                 ('batches', 'Received batches', 'Durably saved uploads'),
                                 ('revisions', 'Saved record versions', 'Includes first copies'),
                                 ('quarantined_batches', 'Batches awaiting machine mapping', 'Batches already saved')):
            frame, column = card()
            column.setContentsMargins(18, 18, 18, 17)
            column.setSpacing(7)
            column.addWidget(label(title, 'metricLabel', True))
            value = label('—', 'metricNumber')
            self.metric_values[key] = value
            column.addWidget(value)
            column.addWidget(label(hint, 'metricHint', True))
            metrics.addWidget(frame, 1)
        layout.addLayout(metrics)
        self.processing_note = label('Processing jobs will be checked with the server status.', 'help')
        layout.addWidget(self.processing_note)
        connection, box = card()
        row = QHBoxLayout()
        row.addWidget(label('Collector connection', 'sectionTitle'))
        row.addStretch()
        row.addWidget(label('HTTPS', 'pill'))
        box.addLayout(row)
        box.addWidget(label('Collectors on this PC send their uploads to this endpoint.', 'muted', True))
        endpoint_box = QFrame()
        endpoint_box.setObjectName('endpointBox')
        endpoint_row = QHBoxLayout(endpoint_box)
        endpoint_row.setContentsMargins(15, 4, 6, 4)
        endpoint_row.addWidget(label(self.service.settings.upload_url, 'endpoint'), 1)
        endpoint_row.addWidget(self.button('Copy URL', self.copy_url, 'quiet'))
        box.addWidget(endpoint_box)
        layout.addWidget(connection)
        getting_started, box = card()
        row = QHBoxLayout()
        column = QVBoxLayout()
        self.next_title = label('Connect your first source', 'sectionTitle')
        self.next_hint = label('Register a SCADA database, then export its encrypted collector setup.', 'muted', True)
        column.addWidget(self.next_title)
        column.addWidget(self.next_hint)
        row.addLayout(column, 1)
        row.addWidget(self.button('Register source', lambda: self.navigate(1), 'primary', 'arrow'))
        box.addLayout(row)
        layout.addWidget(getting_started)
        layout.addStretch()
        return page

    def _register_page(self):
        page, layout = self._page()
        frame, box = card()
        box.addWidget(label('Source registration', 'sectionTitle'))
        box.addWidget(label('Reuse existing registry items, or enter the details for a new one.', 'muted', True))
        grid = QGridLayout()
        grid.setHorizontalSpacing(20)
        grid.setVerticalSpacing(10)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        self.choices = {}
        self.names = {}
        for index, name in enumerate(('customer', 'site', 'project', 'machine')):
            row = index * 3
            title = 'Machine tag' if name == 'machine' else name.title()
            grid.addWidget(label(title, 'fieldLabel'), row, 0)
            grid.addWidget(label('New ' + title.lower(), 'fieldLabel'), row, 1)
            combo = QComboBox()
            combo.addItem('Create new ' + name, None)
            entry = QLineEdit()
            entry.setPlaceholderText('Enter ' + title.lower())
            grid.addWidget(combo, row + 1, 0)
            grid.addWidget(entry, row + 1, 1)
            grid.setRowMinimumHeight(row + 2, 10)
            self.choices[name] = combo
            self.names[name] = entry
            self.controls.extend((combo, entry))
            combo.currentIndexChanged.connect(lambda index, field=name: self._choice_changed(field))
            entry.textChanged.connect(self._form_edited)
        grid.addWidget(label('SCADA PC / database source name', 'fieldLabel'), 12, 0, 1, 2)
        self.names['source'] = QLineEdit()
        self.names['source'].setPlaceholderText('A clear name for this SCADA database source')
        self.names['source'].textChanged.connect(self._form_edited)
        self.controls.append(self.names['source'])
        grid.addWidget(self.names['source'], 13, 0, 1, 2)
        box.addLayout(grid)
        actions = QHBoxLayout()
        self.register_button = self.button('Register source & generate IDs', self.register_source, 'primary', 'register')
        actions.addWidget(self.register_button)
        actions.addStretch()
        box.addLayout(actions)
        box.addWidget(label('Database credentials, collection history and schedules stay on the Collector PC.', 'help', True))
        layout.addWidget(frame)
        layout.addStretch()
        return page

    def _table(self, columns):
        table = QTableWidget(0, len(columns))
        table.setHorizontalHeaderLabels(columns)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setShowGrid(False)
        table.setAlternatingRowColors(False)
        table.verticalHeader().setVisible(False)
        table.verticalHeader().setDefaultSectionSize(47)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        table.horizontalHeader().setStretchLastSection(True)
        table.setMinimumHeight(190)
        return table

    def _sources_page(self):
        page, layout = self._page()
        frame, box = card()
        row = QHBoxLayout()
        row.addWidget(label('Registered sources', 'sectionTitle'))
        row.addStretch()
        row.addWidget(self.button('Refresh', self.refresh, 'quiet', 'refresh'))
        row.addWidget(self.button('New source', lambda: self.navigate(1), 'primary', 'register'))
        box.addLayout(row)
        self.source_empty = QFrame()
        self.source_empty.setObjectName('emptyState')
        empty = QVBoxLayout(self.source_empty)
        empty.setContentsMargins(30, 38, 30, 38)
        empty.setSpacing(12)
        illustration = label()
        illustration.setPixmap(icon('sources', '#839cbe', 35).pixmap(QSize(35, 35)))
        empty.addWidget(illustration, 0, Qt.AlignmentFlag.AlignCenter)
        empty.addWidget(label('No sources registered yet', 'sectionTitle'), 0, Qt.AlignmentFlag.AlignCenter)
        empty.addWidget(label('Register your SCADA database to create a collector setup.', 'muted'), 0, Qt.AlignmentFlag.AlignCenter)
        empty.addSpacing(6)
        empty.addWidget(self.button('Register source', lambda: self.navigate(1), 'primary', 'register'), 0, Qt.AlignmentFlag.AlignCenter)
        box.addWidget(self.source_empty)
        self.source_table = self._table(('SOURCE', 'CUSTOMER', 'SITE', 'PROJECT', 'LAST RECEIVED', 'AWAITING MAPPING'))
        self.source_table.itemSelectionChanged.connect(self._source_selected)
        box.addWidget(self.source_table, 1)
        self.source_details = label('Select a source to view its identity and export its setup.', 'help', True)
        self.source_details.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        box.addWidget(self.source_details)
        self.source_actions = QWidget()
        row = QHBoxLayout(self.source_actions)
        row.setContentsMargins(0, 0, 0, 0)
        self.export_button = self.button('Export collector setup', self.export_setup, 'primary')
        self.rotate_button = self.button('Replace credential', self.rotate_credential)
        self.delete_button = self.button('Delete source', self.delete_source, 'danger')
        row.addWidget(self.export_button)
        row.addWidget(self.rotate_button)
        row.addStretch()
        row.addWidget(self.delete_button)
        box.addWidget(self.source_actions)
        layout.addWidget(frame)
        layout.addWidget(label('Exported setup files are encrypted. Keep their passwords separate and use Test server in the Collector.', 'help', True))
        layout.addStretch()
        return page

    def _deployment_page(self):
        page, layout = self._page()
        frame, box = card()
        row = QHBoxLayout()
        row.addWidget(label('A separate Linux workspace', 'sectionTitle'))
        row.addStretch()
        row.addWidget(label('LOCAL DEPLOYMENT', 'pill'))
        box.addLayout(row)
        box.addWidget(label('This window manages the Docker server in WSL. Your Windows installation remains separate.', 'muted', True))
        for title, value in (('Compose project', self.service.settings.project),
                             ('Linux workspace', str(self.service.settings.workspace)),
                             ('Collector endpoint', self.service.settings.upload_url),
                             ('Encrypted setup exports', str(self.service.export_directory))):
            box.addSpacing(7)
            box.addWidget(label(title.upper(), 'eyebrow'))
            value_label = label(value, 'endpoint', True)
            value_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            box.addWidget(value_label)
        layout.addWidget(frame)
        note, box = card()
        box.addWidget(label('Connection & operation', 'sectionTitle'))
        box.addWidget(label('Keep Docker Desktop running with Ubuntu integration enabled. PostgreSQL is private inside Docker, '
                            'and HTTPS accepts collectors on this PC.', 'muted', True))
        box.addWidget(label('Connecting other Collector PCs requires a stable server address, a matching certificate and network commissioning.', 'help', True))
        box.addWidget(label('Closing this window leaves the server running. Stop server pauses this Docker project and preserves its data.', 'help', True))
        layout.addWidget(note)
        layout.addStretch()
        return page

    def _identification_page(self):
        page, layout = self._page()
        frame, box = card()
        row = QHBoxLayout()
        row.addWidget(label('Saved equipment results', 'sectionTitle'))
        row.addStretch()
        row.addWidget(self.button('Refresh results', self.refresh_identification, 'quiet', 'refresh'))
        box.addLayout(row)
        box.addWidget(label('Events use the registered machine tag. Alarm AI is not configured in this Docker deployment.', 'muted', True))
        self.ai_note = label('No saved results yet. Results appear here after records are received and processed.', 'help', True)
        box.addWidget(self.ai_note)
        self.ai_table = self._table(('SOURCE', 'TABLE', 'RECORD ID', 'STATUS', 'EQUIPMENT', 'METHOD / MODEL'))
        self.ai_table.itemSelectionChanged.connect(self._show_evidence)
        box.addWidget(self.ai_table, 1)
        box.addWidget(label('ORIGINAL MESSAGE', 'eyebrow'))
        self.ai_evidence = QTextEdit()
        self.ai_evidence.setReadOnly(True)
        self.ai_evidence.setPlaceholderText('Select a result to compare the equipment name with its original message.')
        self.ai_evidence.setMinimumHeight(85)
        self.ai_evidence.setMaximumHeight(110)
        box.addWidget(self.ai_evidence)
        layout.addWidget(frame)
        layout.addWidget(label('Names are suggestions for review. Saved data and mapping approvals remain unchanged when you view these results.', 'help', True))
        layout.addStretch()
        return page

    def navigate(self, index):
        self.pages.setCurrentIndex(index)
        self.nav_buttons[index].setChecked(True)
        self.page_title.setText(PAGES[index][0])
        self.page_subtitle.setText(PAGES[index][1])
        if index == 4:
            if self.busy:
                self._ai_pending = True
            elif self.status:
                self.refresh_identification()

    def _form_edited(self, *args):
        self.form_dirty = True

    def _choice_changed(self, field):
        self.form_dirty = True
        self._cascade(field)

    def _cascade(self, changed=None):
        order = ('customer', 'site', 'project', 'machine')
        tables = dict(customer='customers', site='sites', project='projects', machine='machines')
        start = order.index(changed) + 1 if changed else 0
        for name in order[start:]:
            box = self.choices[name]
            previous = box.currentData() if changed is None else None
            records = self.registry[tables[name]]
            for ancestor in order[:order.index(name)]:
                parent = self.choices[ancestor].currentData()
                records = [row for row in records if parent and str(row[ancestor + '_id']) == str(parent[ancestor + '_id'])]
            box.blockSignals(True)
            box.clear()
            box.addItem('Create new ' + name, None)
            for record in records:
                box.addItem(record.get('machine_tag', record['name']), record)
                if previous and str(previous[name + '_id']) == str(record[name + '_id']):
                    box.setCurrentIndex(box.count() - 1)
            box.blockSignals(False)
        self._sync_controls()

    def _sync_controls(self):
        for control in self.controls:
            control.setEnabled(not self.busy)
        for name, choice in getattr(self, 'choices', {}).items():
            self.names[name].setEnabled(not self.busy and choice.currentData() is None)
        ready = all(self.status.get(key, False) for key in ('api_ready', 'database_ready', 'worker_running'))
        self.start_button.setEnabled(not self.busy and not ready)
        self.stop_button.setEnabled(not self.busy and any(self.status.get(key, False) for key in ('initialized', 'api_ready', 'database_ready', 'worker_running')))
        self.register_button.setEnabled(not self.busy and self.status.get('database_ready', False))
        selected = self.selected_source() is not None and self.status.get('database_ready', False)
        for control in (self.export_button, self.rotate_button, self.delete_button):
            control.setEnabled(not self.busy and selected)

    def _start(self, message, operation, done):
        if self.busy or self.closing:
            return False
        self.busy = True
        self.footer.setText(message)
        self.progress.setRange(0, 0)
        self._sync_controls()
        self._done = done
        self._work = Work(operation)
        self._work.signals.finished.connect(self._finished, Qt.ConnectionType.QueuedConnection)
        self.pool.start(self._work)
        return True

    @Slot(bool, object)
    def _finished(self, success, result):
        done = self._done
        self._done = None
        self._work = None
        self.busy = False
        self.progress.setRange(0, 1)
        self.progress.setValue(0)
        self._sync_controls()
        if success:
            done(result)
        else:
            self.footer.setText(result)
            if not self.closing:
                QMessageBox.critical(self, 'Central Server', result)
        if self.closing:
            QTimer.singleShot(0, self.close)
        elif self._ai_pending and not self.busy:
            self._ai_pending = False
            self.refresh_identification(preserve_feedback=True)

    def refresh(self, success_message=None):
        def operation():
            status = self.service.status()
            result = dict(status=status, catalog=self.service.catalog() if status['database_ready'] else {key: [] for key in self.registry},
                          sources=self.service.sources() if status['database_ready'] else [])
            try:
                result['ai'] = self.service.machine_interpretations(include_records=status['database_ready'])
            except CollectorError as error:
                result['ai_error'] = str(error)
            return result
        self._start(success_message or 'Refreshing server health and sources…', operation,
                    lambda result: self._show_snapshot(result, success_message))

    def _show_snapshot(self, result, success_message=None):
        self.status = result['status']
        ready = all(self.status[key] for key in ('api_ready', 'database_ready', 'worker_running'))
        active = any(self.status[key] for key in ('api_ready', 'database_ready', 'worker_running'))
        self.health_pill.setText('●  Server ready' if ready else '●  Needs attention' if active else '●  Server stopped')
        tone(self.health_pill, 'good' if ready else 'warning' if active else 'stopped')
        self.sidebar_status.setText('●  Server ready' if ready else '●  Check server status')
        for key, dot in self.service_dots.items():
            dot.setProperty('ready', bool(self.status[key]))
            dot.style().unpolish(dot)
            dot.style().polish(dot)
            self.service_labels[key].setText('Ready' if self.status[key] else 'Stopped')
        for key, widget in self.metric_values.items():
            widget.setText(f"{self.status[key]:,}" if self.status['database_ready'] else '—')
        self.processing_note.setText('Failed processing jobs: ' +
                                     (f"{self.status['failed_jobs']:,}" if self.status['database_ready'] else '—'))
        if self.status['sources']:
            self.next_title.setText('Keep your collectors connected')
            self.next_hint.setText('Manage sources, export setup files and review records awaiting machine mapping.')
        else:
            self.next_title.setText('Connect your first source')
            self.next_hint.setText('Register a SCADA database, then export its encrypted collector setup.')
        self.registry = result['catalog']
        self._cascade()
        selected = self.selected_source()
        self.source_rows = result['sources']
        self.source_table.blockSignals(True)
        self.source_table.setRowCount(len(self.source_rows))
        selected_index = -1
        for index, source in enumerate(self.source_rows):
            values = (source['name'], source['customer_name'], source['site_name'], source['project_name'],
                      str(source['last_received'] or 'No uploads yet'), str(source['quarantined_batches']))
            for column, value in enumerate(values):
                self.source_table.setItem(index, column, QTableWidgetItem(str(value)))
            if selected and str(source['source_id']) == str(selected['source_id']):
                selected_index = index
        self.source_table.clearSelection()
        self.source_table.setCurrentCell(selected_index, 0 if selected_index >= 0 else -1)
        if selected_index >= 0:
            self.source_table.selectRow(selected_index)
        self.source_table.blockSignals(False)
        self.source_empty.setVisible(not self.source_rows)
        self.source_table.setVisible(bool(self.source_rows))
        self.source_details.setVisible(bool(self.source_rows))
        self.source_actions.setVisible(bool(self.source_rows))
        self._source_selected()
        if 'ai' in result:
            self._show_identification(result['ai'])
        elif result.get('ai_error'):
            self.ai_note.setText(result['ai_error'])
        self._sync_controls()
        self.footer.setText(success_message or self.status.get('error') or 'Server status is up to date.')

    def start_server(self):
        self._start('Starting the Docker server…', self.service.start,
                    lambda result: self.refresh('Docker server started successfully.'))

    def confirm(self, title, message):
        box = QMessageBox(QMessageBox.Icon.Question, title, message,
                          QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, self)
        box.setTextFormat(Qt.TextFormat.PlainText)
        box.setDefaultButton(QMessageBox.StandardButton.No)
        return box.exec() == QMessageBox.StandardButton.Yes

    def stop_server(self):
        if not self.busy and self.confirm('Stop Docker server?', 'Stop this project’s API, worker and database? '
                                         'Saved data is retained. Collectors keep pending uploads until the server starts again.'):
            self._start('Stopping the Docker server…', self.service.stop,
                        lambda result: self.refresh('Docker server stopped. Saved data and credentials are retained.'))

    def register_source(self):
        if self.busy:
            return
        values = {}
        try:
            for name, parameter, title in (('customer', 'customer_name', 'customer name'), ('site', 'site_name', 'site name'),
                                            ('project', 'project_name', 'project name'), ('machine', 'machine_tag', 'machine tag')):
                existing = self.choices[name].currentData()
                values[name + '_id'] = existing[name + '_id'] if existing else None
                values[parameter] = '' if existing else text(self.names[name].text(), title)
            values['source_name'] = text(self.names['source'].text(), 'SCADA PC/database source name')
        except CollectorError as error:
            self.footer.setText(str(error))
            QMessageBox.warning(self, 'Registration details', str(error))
            return
        def registered(result):
            self.names['source'].clear()
            self.form_dirty = False
            self.navigate(2)
            self.refresh('Source registered. Select it to export the encrypted collector setup.')
        self._start('Registering the source and protecting its credential…', lambda: self.service.register(**values), registered)

    def selected_source(self):
        row = self.source_table.currentRow()
        return self.source_rows[row] if 0 <= row < len(self.source_rows) else None

    def _source_selected(self):
        selected = self.selected_source()
        self.source_details.setText(('Source ID: ' + str(selected['source_id']) + '\nGeneration ID: ' + str(selected['generation_id'] or ''))
                                    if selected else 'Select a source to view its identity and export its setup.')
        self._sync_controls()

    def export_setup(self):
        source = self.selected_source()
        if self.busy or not source:
            return
        path, _ = QFileDialog.getSaveFileName(self, 'Export encrypted collector setup',
                                             str(self.service.export_directory / ('collector-' + str(source['source_id'])[:8] + '.linker-collector')),
                                             'Encrypted collector setup (*.linker-collector)',
                                             options=QFileDialog.Option.DontUseNativeDialog)
        if not path:
            return
        if not path.endswith('.linker-collector'):
            path += '.linker-collector'
        if Path(path).exists() or Path(path).is_symlink():
            QMessageBox.warning(self, 'Choose a new filename', 'Existing setup files are preserved. Choose a new filename for this export.')
            return
        dialog = ExportPasswordDialog(self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        password = dialog.take_password()
        self._start('Encrypting and exporting collector setup…', lambda: self.service.export(source['source_id'], path, password),
                    lambda result: self.footer.setText('Encrypted setup exported. Import it in the Collector, then use Test server.'))

    def rotate_credential(self):
        source = self.selected_source()
        if not self.busy and source and self.confirm('Replace upload credential?',
                'Create a replacement credential for this source? Earlier credentials remain valid. Export and import a new setup to use the replacement.'):
            self._start('Creating a protected replacement credential…', lambda: self.service.rotate(source['source_id']),
                        lambda result: self.footer.setText('Replacement credential created. Export a new encrypted setup for this source.'))

    def delete_source(self):
        source = self.selected_source()
        if not self.busy and source and self.confirm('Delete source registration?',
                f"Remove {source['name']}?\n\nThis revokes all its upload credentials. Received data, mappings and audit history remain saved. "
                'Unsent batches stay on the Collector. This registration cannot be restored from this window.'):
            self._start('Removing the source registration…', lambda: self.service.delete_source(source['source_id']),
                        lambda result: self.refresh('Source removed. Upload credentials revoked; received history retained.'))

    def refresh_identification(self, preserve_feedback=False):
        previous = self.footer.text()
        def operation():
            try:
                status = self.service.status()
                return self.service.machine_interpretations(include_records=status['database_ready'])
            except CollectorError as error:
                return dict(error=str(error))
        def shown(result):
            if 'error' in result:
                self.ai_note.setText(result['error'])
            else:
                self._show_identification(result)
            self.footer.setText(previous if preserve_feedback else 'Saved equipment results refreshed.')
        self._start('Reading saved identification results…', operation, shown)

    def _show_identification(self, result):
        self.ai_rows = result['rows']
        self.ai_table.setRowCount(len(self.ai_rows))
        self.ai_evidence.clear()
        for index, row in enumerate(self.ai_rows):
            names = ', '.join(dict.fromkeys(candidate['label'] for candidate in row['candidates']))
            method = 'Registered machine tag' if row.get('policy_version') == 'registered-event-machine-v1' else row['model'] or 'Not yet run'
            for column, value in enumerate((row['source_name'], row['source_table'], row['source_record_id'], row['status'], names or 'Uncertain', method)):
                self.ai_table.setItem(index, column, QTableWidgetItem(str(value)))
        self.ai_table.clearSelection()
        self.ai_table.setCurrentCell(-1, -1)
        self.ai_evidence.clear()
        self.ai_note.setText(('Saved results from this server. Select a row to inspect the original message.' if self.ai_rows else
                              'No saved results yet. Results appear after records are received and processed.')
                             if result.get('records_available', True) else 'Start the server to load its saved results. Alarm AI remains disabled.')

    def _show_evidence(self):
        index = self.ai_table.currentRow()
        self.ai_evidence.setPlainText(self.ai_rows[index].get('original_message') or 'No original message available.'
                                      if 0 <= index < len(self.ai_rows) else '')

    def copy_url(self):
        QApplication.clipboard().setText(self.service.settings.upload_url)
        self.footer.setText('Collector upload URL copied.')

    def closeEvent(self, event):
        if self.busy:
            self.closing = True
            self.footer.setText('Finishing the current operation before closing…')
            event.ignore()
        elif self.form_dirty and not self.confirm('Close manager?', 'Discard the unfinished source registration and close this window? The server stays running.'):
            self.closing = False
            event.ignore()
        else:
            event.accept()


def main(argv=None):
    parser = argparse.ArgumentParser(description='Modern WSL / Docker Central Server manager')
    parser.add_argument('--workspace', type=Path, default=Path.home() / 'central-server')
    parser.add_argument('--project', default='linker-scada-wsl')
    args = parser.parse_args(argv)
    app = QApplication.instance() or QApplication([])
    app.setApplicationName('Linker Central Server')
    app.setStyle('Fusion')
    app.setFont(QFont('Ubuntu Sans', 10))
    try:
        service = DockerManagerService(args.workspace, args.project)
    except (CollectorError, OSError, ValueError):
        QMessageBox.critical(None, 'Central Server - WSL / Docker', 'Cannot open this workspace. Check its private .env, localhost setting and WSL Compose files.')
        return 1
    window = DockerManagerWindow(service)
    window.show()
    return app.exec()


if __name__ == '__main__':
    raise SystemExit(main())
