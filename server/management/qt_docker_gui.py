"""Modern local desktop for the WSL/Docker server; backend operations remain in docker.py."""
import argparse
import csv
import os
import tempfile
from dataclasses import replace
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QObject, QPoint, QRunnable, QSize, QThreadPool, QTimer, Qt, Signal, Slot
from PySide6.QtGui import QFont, QIcon
from PySide6.QtWidgets import (
    QApplication, QAbstractItemView, QButtonGroup, QCheckBox, QComboBox, QDialog, QDialogButtonBox,
    QFileDialog, QFrame, QGridLayout, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
    QListWidget, QListWidgetItem, QMainWindow, QMessageBox, QProgressBar, QPushButton, QScrollArea, QSizePolicy,
    QDoubleSpinBox, QStackedWidget, QTableWidget, QTableWidgetItem, QTextEdit, QVBoxLayout, QWidget,
)

from collector.errors import CollectorError
from server import __version__
from server.management.docker import DockerManagerService
from server.management.docker_theme import STYLESHEET, icon
from server.management.desktop_identity import runtime_caption
from server.management.service import text


PAGES = (
    ('Overview', 'Server health, activity and quick actions.', 'overview'),
    ('Register source', 'Connect a SCADA database source to this server.', 'register'),
    ('Sources & setup', 'Manage registrations and export collector setup files.', 'sources'),
    ('Settings & Configuration', 'Your Linux workspace and Docker server connection.', 'deployment'),
    ('Analysis', 'Recurring alarms, daily alarm/event activity and equipment evidence.', 'overview'),
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


def application_icon():
    path = Path(__file__).resolve().parents[2] / 'deploy/wsl/central-server.ico'
    return QIcon(str(path)) if path.is_file() else icon('sources', '#356ff0', 128)


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


class EquipmentOverrideDialog(QDialog):
    save_requested = Signal(object)

    def __init__(self,parent,row):
        super().__init__(parent)
        self.setWindowTitle('Edit equipment suggestion')
        self.setWindowModality(Qt.WindowModality.WindowModal)
        self.setMinimumWidth(560)
        self.saving=False
        box=QVBoxLayout(self)
        box.setContentsMargins(24,24,24,24)
        box.addWidget(label('Equipment for this alarm', 'sectionTitle'))
        box.addWidget(label('Source: '+row['source_name'],'fieldLabel',True))
        box.addWidget(label('Tag: '+(row.get('tag') or 'No tag'),'muted',True))
        evidence=QTextEdit()
        evidence.setReadOnly(True)
        evidence.setPlainText(row.get('message') or 'No original message available.')
        evidence.setMaximumHeight(130)
        box.addWidget(evidence)
        box.addWidget(label('Saved AI suggestion: '+(row.get('ai_suggestions') or 'No saved suggestion yet'),'help',True))
        box.addWidget(label('Equipment name','fieldLabel'))
        self.entry=QLineEdit(row.get('equipment_override') or row.get('ai_suggestions') or '')
        self.entry.setPlaceholderText('Enter equipment name (up to 255 characters)')
        box.addWidget(self.entry)
        box.addWidget(label('Your edit applies to this exact message and tag in this source, including future matching alarms. '
                            'The original data and saved AI suggestion are retained.','help',True))
        self.error=label('','help',True)
        box.addWidget(self.error)
        self.buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        self.buttons.button(QDialogButtonBox.StandardButton.Save).setText('Save override')
        self.buttons.button(QDialogButtonBox.StandardButton.Save).setObjectName('primary')
        self.use_ai=self.buttons.addButton('Use AI again',QDialogButtonBox.ButtonRole.ActionRole)
        self.use_ai.setEnabled(row.get('equipment_override') is not None)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        self.use_ai.clicked.connect(lambda:self.save_requested.emit(None))
        box.addWidget(self.buttons)

    def accept(self):
        if self.saving:return
        try:value=text(self.entry.text(),'equipment name')
        except CollectorError as error:
            self.error.setText(str(error));return
        self.save_requested.emit(value)

    def set_saving(self,value):
        self.saving=value
        self.entry.setEnabled(not value)
        self.buttons.setEnabled(not value)

    def reject(self):
        if not self.saving:super().reject()


def write_analysis_csv(path,headers,rows):
    """Write a spreadsheet-safe snapshot without exposing a partial export."""
    temporary=None
    def cell(value):
        return "'"+value if value.lstrip().startswith(('=','+','-','@')) or value.startswith(('\t','\r','\n')) else value
    try:
        with tempfile.NamedTemporaryFile(mode='w',encoding='utf-8-sig',newline='',
                dir=path.parent,prefix='.linker-csv-',delete=False) as output:
            temporary=Path(output.name)
            writer=csv.writer(output)
            writer.writerow(headers)
            writer.writerows([[cell(value) for value in row] for row in rows])
        os.replace(temporary,path)
    except (OSError,UnicodeError):
        raise CollectorError('Could not export CSV. Check the folder permissions and close the file if it is open.') from None
    finally:
        if temporary is not None:temporary.unlink(missing_ok=True)
    return dict(rows=len(rows),path=str(path))


class ColumnFilterDialog(QDialog):
    filter_applied=Signal(object)

    def __init__(self,parent,title,values,selected):
        super().__init__(parent,Qt.WindowType.Popup)
        self.setWindowTitle('Filter '+title)
        self.setWindowModality(Qt.WindowModality.WindowModal)
        self.resize(360,420)
        box=QVBoxLayout(self)
        box.addWidget(label('Filter '+title,'sectionTitle',True))
        self.search=QLineEdit()
        self.search.setPlaceholderText('Search column values')
        self.search.setClearButtonEnabled(True)
        self.search.setAccessibleName('Search column values')
        box.addWidget(self.search)
        self.select_all=QCheckBox('Select all shown')
        self.select_all.setTristate(True)
        box.addWidget(self.select_all)
        self.values=QListWidget()
        for value in sorted(values,key=lambda value:(value.casefold(),value)):
            item=QListWidgetItem(value or '(Blank)')
            item.setData(Qt.ItemDataRole.UserRole,value)
            item.setToolTip(value)
            item.setFlags(item.flags()|Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if selected is None or value in selected else Qt.CheckState.Unchecked)
            self.values.addItem(item)
        box.addWidget(self.values,1)
        self.buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Apply|QDialogButtonBox.StandardButton.Cancel)
        self.clear_button=self.buttons.addButton('Clear filter',QDialogButtonBox.ButtonRole.ResetRole)
        self.buttons.button(QDialogButtonBox.StandardButton.Apply).clicked.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        self.clear_button.clicked.connect(self.clear_filter)
        box.addWidget(self.buttons)
        self.search.textChanged.connect(self._search_changed)
        self.select_all.clicked.connect(self._select_shown)
        self.values.itemChanged.connect(self._sync_select_all)
        self._sync_select_all()

    def _shown(self):
        return [self.values.item(index) for index in range(self.values.count()) if not self.values.item(index).isHidden()]

    def _search_changed(self,value):
        query=value.strip().casefold()
        for index in range(self.values.count()):
            item=self.values.item(index)
            item.setHidden(query not in item.text().casefold())
        self._sync_select_all()

    def _select_shown(self,checked):
        self.values.blockSignals(True)
        for item in self._shown():item.setCheckState(Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)
        self.values.blockSignals(False)
        self._sync_select_all()

    def _sync_select_all(self,*args):
        shown=self._shown()
        checked=sum(item.checkState()==Qt.CheckState.Checked for item in shown)
        self.select_all.setCheckState(Qt.CheckState.Checked if shown and checked==len(shown)
            else Qt.CheckState.PartiallyChecked if checked else Qt.CheckState.Unchecked)

    def accept(self):
        selected={item.data(Qt.ItemDataRole.UserRole) for item in self._shown() if item.checkState()==Qt.CheckState.Checked}
        self.filter_applied.emit(None if len(selected)==self.values.count() else selected)
        super().accept()

    def clear_filter(self):
        self.filter_applied.emit(None)
        super().accept()


class DockerManagerWindow(QMainWindow):
    def __init__(self, service, auto_refresh=True, auto_start=False):
        super().__init__()
        self.service = service
        self.busy = False
        self.closing = False
        self.form_dirty = False
        self._ai_saved_model = None
        self._ai_enabled = None
        self._ai_pending = False
        self._analysis_pending = False
        self.analysis_rows=[]
        self._analysis_column_filters={'analysis_issues':{},'analysis_daily':{}}
        self._analysis_headers={}
        self._column_filter_dialog=None
        self._equipment_dialog=None
        self._equipment_editing_available=False
        self._work = None
        self._done = None
        self._quiet_feedback = None
        self._refresh_preferences_loaded = False
        self._saved_refresh_interval = 0
        self.refresh_timer = QTimer(self)
        self.refresh_timer.setSingleShot(True)
        self.refresh_timer.setTimerType(Qt.TimerType.PreciseTimer)
        self.refresh_timer.timeout.connect(self._automatic_refresh)
        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(1)
        self.controls = []
        self.registry = {key: [] for key in ('customers', 'sites', 'projects', 'machines')}
        self.source_rows = []
        self.status = {}
        self.runtime_caption = runtime_caption()
        self.setWindowTitle('Central Server - '+self.runtime_caption)
        self.setWindowIcon(application_icon())
        self.resize(1320, 860)
        self.setMinimumSize(1100, 740)
        self.setStyleSheet(STYLESHEET)
        self._build()
        self._sync_controls()
        if auto_start:
            QTimer.singleShot(0, self.startup_server)
        elif auto_refresh:
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
            button = QPushButton(title.replace('&', '&&'))
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
        self.sidebar_environment = label('NETWORK SERVER' if self.service.settings.mode == 'network' else 'LOCAL ENVIRONMENT', 'sidebarCaption')
        side.addWidget(self.sidebar_environment)
        side.addWidget(label(self.runtime_caption, 'sidebarNote'))
        self.sidebar_status = label('Checking server…', 'sidebarNote')
        side.addWidget(self.sidebar_status)
        side.addSpacing(15)
        side.addWidget(label('Linker  ·  v' + __version__, 'sidebarNote'))
        root.addWidget(sidebar)
        for button in self.nav_buttons:button.ensurePolished()
        sidebar.setFixedWidth(max(224,max(button.sizeHint().width() for button in self.nav_buttons)+36))
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
        environment = label(('NETWORK' if self.service.settings.mode == 'network' else 'LOCAL') + '  ·  '+self.runtime_caption.upper(), 'pill')
        self.environment_badge = environment
        top.addWidget(environment, 0, Qt.AlignmentFlag.AlignTop)
        content.addWidget(heading)
        self.pages = QStackedWidget()
        content.addWidget(self.pages, 1)
        for builder in (self._overview_page, self._register_page, self._sources_page,
                        self._deployment_page, self._analysis_page):
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
                                 ('revisions', 'Saved record versions', 'Includes first copies')):
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
        box.addWidget(label('Import the encrypted server setup on each Collector. It supplies the saved connection and upload key.', 'muted', True))
        endpoint_box = QFrame()
        endpoint_box.setObjectName('endpointBox')
        endpoint_row = QHBoxLayout(endpoint_box)
        endpoint_row.setContentsMargins(15, 4, 6, 4)
        self.overview_endpoint = label('Connection included in encrypted collector setup', 'endpoint')
        endpoint_row.addWidget(self.overview_endpoint, 1)
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
        for index, name in enumerate(('customer', 'site', 'project')):
            row = index * 3
            title = name.title()
            grid.addWidget(label(title, 'fieldLabel'), row, 0)
            combo = QComboBox()
            combo.addItem('Create new ' + name, None)
            grid.addWidget(combo, row + 1, 0)
            grid.addWidget(label('New ' + title.lower(), 'fieldLabel'), row, 1)
            entry = QLineEdit()
            entry.setPlaceholderText('Enter ' + title.lower())
            grid.addWidget(entry, row + 1, 1)
            self.names[name] = entry
            self.controls.append(entry)
            entry.textChanged.connect(self._form_edited)
            grid.setRowMinimumHeight(row + 2, 10)
            self.choices[name] = combo
            self.controls.append(combo)
            combo.currentIndexChanged.connect(lambda index, field=name: self._choice_changed(field))
        grid.addWidget(label('SCADA PC / database source name', 'fieldLabel'), 9, 0, 1, 2)
        self.names['source'] = QLineEdit()
        self.names['source'].setPlaceholderText('A clear name for this SCADA database source')
        self.names['source'].textChanged.connect(self._form_edited)
        self.controls.append(self.names['source'])
        grid.addWidget(self.names['source'], 10, 0, 1, 2)
        box.addLayout(grid)
        actions = QHBoxLayout()
        self.register_button = self.button('Register source & generate IDs', self.register_source, 'primary', 'register')
        actions.addWidget(self.register_button)
        actions.addStretch()
        box.addLayout(actions)
        box.addWidget(label('Database credentials, collection history and schedules stay on the Collector PC.', 'help', True))
        box.addWidget(label('Equipment assignments remain unassigned until approved separately.', 'help', True))
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
        self.source_table = self._table(('SOURCE', 'CUSTOMER', 'SITE', 'PROJECT', 'LAST RECEIVED'))
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
        refresh_frame, refresh_box = card()
        refresh_box.addWidget(label('Automatic display refresh', 'sectionTitle'))
        refresh_row = QHBoxLayout()
        refresh_row.addWidget(label('Refresh every', 'fieldLabel'))
        self.refresh_interval = QDoubleSpinBox()
        self.refresh_interval.setRange(0, 60)
        self.refresh_interval.setDecimals(2)
        self.refresh_interval.setSingleStep(1)
        self.refresh_interval.setSpecialValueText('Off')
        self.refresh_interval.setSuffix(' minutes')
        self.controls.append(self.refresh_interval)
        refresh_row.addWidget(self.refresh_interval)
        refresh_row.addWidget(self.button('Save refresh setting', self.save_refresh_preference))
        refresh_row.addStretch()
        refresh_box.addLayout(refresh_row)
        self.refresh_note = label('Loading saved refresh interval…', 'help', True)
        refresh_box.addWidget(self.refresh_note)
        refresh_box.addWidget(label('Choose Off, or up to 60 minutes (default: 1). Existing saved intervals are retained. The interval starts after each refresh finishes. Updates health, received-data counts, sources, saved AI settings and the current alarm analysis while this window is open. '
                                    'Refresh waits during other work or unsaved edits. Collector upload schedules are configured separately.', 'help', True))
        layout.addWidget(refresh_frame)
        frame, box = card()
        row = QHBoxLayout()
        row.addWidget(label('A separate Linux workspace', 'sectionTitle'))
        row.addStretch()
        self.deployment_badge = label('NETWORK DEPLOYMENT' if self.service.settings.mode == 'network' else 'LOCAL DEPLOYMENT', 'pill')
        row.addWidget(self.deployment_badge)
        box.addLayout(row)
        box.addWidget(label('Configure this Central Server here. Database files, credentials and certificates stay in their existing Docker volumes.', 'muted', True))
        form = QGridLayout()
        self.deployment_mode = QComboBox()
        self.deployment_mode.addItem('Local testing (one PC)', 'local')
        self.deployment_mode.addItem('Network server (multiple collector PCs)', 'network')
        self.deployment_fields = {name: QLineEdit() for name in ('server_host', 'listen_address', 'https_port', 'http_port')}
        fields = [('Connection mode', self.deployment_mode)] + [(title, self.deployment_fields[name]) for name, title in (
            ('server_host', 'Central PC hostname / IPv4'), ('listen_address', 'HTTPS listen IPv4 address'),
            ('https_port', 'HTTPS port'), ('http_port', 'Local HTTP redirect port'))]
        for index, (title, widget) in enumerate(fields):
            form.addWidget(label(title, 'fieldLabel'), index, 0)
            form.addWidget(widget, index, 1)
            self.controls.append(widget)
        box.addLayout(form)
        self.deployment_preview = label('', 'endpoint', True)
        box.addWidget(self.deployment_preview)
        actions = QHBoxLayout()
        self.validate_deployment_button = self.button('Validate settings', self.validate_deployment)
        self.save_deployment_button = self.button('Save settings', self.save_deployment, 'primary')
        self.apply_deployment_button = self.button('Apply and restart', lambda: self.save_deployment(restart=True))
        for button in (self.validate_deployment_button, self.save_deployment_button, self.apply_deployment_button):
            actions.addWidget(button)
        actions.addStretch()
        box.addLayout(actions)
        box.addWidget(label('Save requires this server to be stopped. Apply and restart stops only this project before saving. '
                            'After changing the endpoint, export fresh setup files for your Collectors.', 'help', True))
        self._populate_deployment()
        self.deployment_mode.currentIndexChanged.connect(self._deployment_mode_changed)
        for entry in self.deployment_fields.values():
            entry.textChanged.connect(self._deployment_changed)
        self.saved_deployment_labels = {}
        for title, value in (('Connection mode', 'Network server (multiple collector PCs)' if self.service.settings.mode == 'network' else 'Local testing (one PC)'),
                             ('HTTPS listen address', self.service.settings.listen_address),
                             ('Compose project', self.service.settings.project),
                             ('Linux workspace', str(self.service.settings.workspace)),
                             ('Encrypted setup exports', str(self.service.export_directory))):
            box.addSpacing(7)
            box.addWidget(label(title.upper(), 'eyebrow'))
            value_label = label(value, 'endpoint', True)
            self.saved_deployment_labels[title] = value_label
            value_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            box.addWidget(value_label)
        layout.addWidget(frame)
        note, box = card()
        box.addWidget(label('Connection & operation', 'sectionTitle'))
        box.addWidget(label('The Windows launcher starts Docker Desktop if needed; opening this manager starts its configured server containers. PostgreSQL is private inside Docker. '
                            'Collectors receive the saved connection through their encrypted setup.', 'muted', True))
        box.addWidget(label('Verify Test server on every intended Collector PC. Network mode requires a matching certificate and firewall access.', 'help', True))
        box.addWidget(label('Closing this window leaves the server running. Stop server pauses this Docker project and preserves its data.', 'help', True))
        layout.addWidget(note)
        layout.addStretch()
        return page

    def _analysis_ai_controls(self,box):
        summary=QHBoxLayout()
        self.ai_config_state=label('Reading saved local AI settings...','help',True)
        summary.addWidget(self.ai_config_state,1)
        summary.addWidget(self.button('AI settings',lambda:self.ai_settings_panel.setVisible(not self.ai_settings_panel.isVisible()),'quiet'))
        box.addLayout(summary)
        self.ai_settings_panel=QFrame()
        settings=QVBoxLayout(self.ai_settings_panel)
        controls=QHBoxLayout()
        self.ai_model=QLineEdit('qwen3:4b')
        self.ai_model.setPlaceholderText('Installed local Ollama model')
        self.controls.append(self.ai_model)
        controls.addWidget(label('Local model','fieldLabel'))
        controls.addWidget(self.ai_model,1)
        self.enable_ai_button=self.button('Enable local AI',self.enable_machine_ai,'primary')
        self.enable_ai_button.setProperty('aiToggle',True)
        self.disable_ai_button=self.button('Disable',self.disable_machine_ai)
        controls.addWidget(self.enable_ai_button)
        controls.addWidget(self.disable_ai_button)
        settings.addLayout(controls)
        self.ai_note=label('AI supplies saved equipment suggestions. Your equipment edits are kept separately.','help',True)
        settings.addWidget(self.ai_note)
        box.addWidget(self.ai_settings_panel)
        self.ai_settings_panel.hide()

    def _analysis_page(self):
        page, layout = self._page()
        frame, box = card()
        row = QHBoxLayout()
        self.analysis_customer = QComboBox()
        self.analysis_customer.addItem('All customers', None)
        self.analysis_source = QComboBox()
        self.analysis_source.addItem('All sources', None)
        self.analysis_days = QComboBox()
        for days in (7, 30, 90, 365, 0):
            self.analysis_days.addItem(f'First saved in last {days} days' if days else 'All saved alarms / events', days)
        self.analysis_days.setCurrentIndex(1)
        for widget in (self.analysis_customer, self.analysis_source, self.analysis_days):
            self.controls.append(widget)
            row.addWidget(widget)
            widget.currentIndexChanged.connect(self._analysis_filter_changed)
        row.addWidget(self.button('Analyze saved alarms', self.refresh_analysis, 'primary'))
        box.addLayout(row)
        self.analysis_summary = label('Choose a scope and analyze the saved alarms.', 'sectionTitle', True)
        box.addWidget(self.analysis_summary)
        self.analysis_freshness = label('', 'help', True)
        box.addWidget(self.analysis_freshness)
        self.analysis_note = label('Each source/generation/record ID counts once. No machine mapping is required. '
                                   'AI equipment suggestions are unverified and do not diagnose causes.', 'help', True)
        box.addWidget(self.analysis_note)
        self._analysis_ai_controls(box)
        box.addWidget(label('RECURRING ALARMS · TOP 50 EXACT MESSAGE / TAG GROUPS', 'eyebrow'))
        self._analysis_search(box,'analysis_issues','Search loaded alarms: source, tag, description or equipment')
        self.analysis_issues = self._table(('SOURCE', 'TAG', 'ORIGINAL MESSAGE', 'OCCURRENCES',
                                          'EQUIPMENT', 'AI SUGGESTIONS · UNVERIFIED'))
        self.analysis_issues.itemSelectionChanged.connect(self._sync_controls)
        self.analysis_issues.setMinimumHeight(190)
        self._analysis_header_filters('analysis_issues')
        box.addWidget(self.analysis_issues, 2)
        self.edit_equipment_button=self.button('Edit / override equipment',self.edit_equipment,'primary')
        box.addWidget(self.edit_equipment_button)
        box.addWidget(label('DAILY ALARM / EVENT OCCURRENCES', 'eyebrow'))
        self._analysis_search(box,'analysis_daily','Search loaded daily rows: date, type, source, description or equipment')
        self.analysis_daily = self._table(('UTC DAY', 'TYPE', 'SOURCE', 'ALARM / EVENT DESCRIPTION',
                                           'EQUIPMENT NAME', 'OCCURRENCES', 'RELATIVE ACTIVITY'))
        self.analysis_daily.setMinimumHeight(125)
        self._analysis_header_filters('analysis_daily')
        box.addWidget(self.analysis_daily, 1)
        box.addWidget(label('The time filter uses when an occurrence was first saved by Central Server. '
                            'Daily rows use verified source dates; unknown or conflicting times appear as Uncertain date. '
                            'Up to 1,000 groups are shown, newest known dates first. Hover over equipment for its origin. '
                            'Backfilled records may have older source dates. No durations or current states are inferred. '
                            'Retained history from removed sources is included in all-source totals.', 'help', True))
        layout.addWidget(frame)
        return page

    def _analysis_search(self,box,name,placeholder):
        row=QHBoxLayout()
        search=QLineEdit()
        search.setPlaceholderText(placeholder)
        search.setAccessibleName('Filter recurring alarm table' if name=='analysis_issues' else 'Filter daily occurrence table')
        search.setToolTip('Search the loaded rows only. Customer, source and time filters set the report scope. '
                          'Clear the search to show all loaded groups.')
        search.setClearButtonEnabled(True)
        count=label('0 of 0 loaded groups','help')
        setattr(self,name+'_search',search)
        setattr(self,name+'_count',count)
        row.addWidget(search,1)
        row.addWidget(count)
        clear=self.button('Clear column filters',lambda:self._clear_analysis_columns(name))
        export=self.button('Export .csv',lambda:self.export_analysis_csv(name))
        setattr(self,name+'_clear_columns',clear)
        setattr(self,name+'_export',export)
        row.addWidget(clear)
        row.addWidget(export)
        box.addLayout(row)
        search.textChanged.connect(self._filter_analysis_tables)

    def _analysis_header_filters(self,name):
        table=getattr(self,name)
        count=table.columnCount()-(1 if name=='analysis_daily' else 0)
        self._analysis_headers[name]=[table.horizontalHeaderItem(column).text() for column in range(count)]
        for column,title in enumerate(self._analysis_headers[name]):
            table.horizontalHeaderItem(column).setText(title+' ▾')
            table.horizontalHeaderItem(column).setToolTip('Click to filter this column')
        table.horizontalHeader().setSectionsClickable(True)
        table.horizontalHeader().sectionClicked.connect(lambda column:self._open_analysis_column_filter(name,column))

    def _analysis_row_matches(self,name,index,skip_column=None):
        table=getattr(self,name)
        query=getattr(self,name+'_search').text().strip().casefold()
        values={column:item.text() for column in range(table.columnCount())
                if (item:=table.item(index,column)) is not None}
        return (not query or query in ' '.join(values.values()).casefold()) and all(
            column==skip_column or values.get(column,'') in selected
            for column,selected in self._analysis_column_filters[name].items())

    def _open_analysis_column_filter(self,name,column):
        if self.busy or self._column_filter_dialog is not None or column>=len(self._analysis_headers[name]):return
        table=getattr(self,name)
        selected=self._analysis_column_filters[name].get(column)
        values={table.item(index,column).text() for index in range(table.rowCount())
                if self._analysis_row_matches(name,index,skip_column=column)}
        if selected is not None:values.update(selected)
        dialog=ColumnFilterDialog(self,self._analysis_headers[name][column],values,selected)
        self._column_filter_dialog=dialog
        self.refresh_timer.stop()
        dialog.filter_applied.connect(lambda selected:self._set_analysis_column_filter(name,column,selected))
        dialog.finished.connect(self._column_filter_closed)
        dialog.finished.connect(dialog.deleteLater)
        header=table.horizontalHeader()
        dialog.move(header.mapToGlobal(QPoint(header.sectionViewportPosition(column),header.height())))
        dialog.open()

    def _column_filter_closed(self,*args):
        self._column_filter_dialog=None
        self._arm_refresh_timer()

    def _set_analysis_column_filter(self,name,column,selected):
        if selected is None:self._analysis_column_filters[name].pop(column,None)
        else:self._analysis_column_filters[name][column]=set(selected)
        self._filter_analysis_tables()

    def _clear_analysis_columns(self,name):
        self._analysis_column_filters[name].clear()
        self._filter_analysis_tables()

    def _filter_analysis_tables(self,*args):
        for name in ('analysis_issues','analysis_daily'):
            table=getattr(self,name)
            visible=0
            for index in range(table.rowCount()):
                hidden=not self._analysis_row_matches(name,index)
                table.setRowHidden(index,hidden)
                visible+=not hidden
            if table.currentRow()>=0 and table.isRowHidden(table.currentRow()):
                table.clearSelection()
            getattr(self,name+'_count').setText(f'{visible:,} of {table.rowCount():,} loaded groups')
            for column,title in enumerate(self._analysis_headers[name]):
                active=column in self._analysis_column_filters[name]
                table.horizontalHeaderItem(column).setText(title+(' • ▾' if active else ' ▾'))
                table.horizontalHeaderItem(column).setToolTip('Click to filter this column'+(' (filter active)' if active else ''))
        self._sync_controls()

    def export_analysis_csv(self,name):
        if self.busy:return
        table=getattr(self,name)
        headers=list(self._analysis_headers[name])+['EQUIPMENT ORIGIN']
        equipment_column=4
        rows=[[table.item(index,column).text() for column in range(len(headers)-1)]+
              [table.item(index,equipment_column).toolTip()]
              for index in range(table.rowCount()) if not table.isRowHidden(index)]
        if not rows:return
        self.refresh_timer.stop()
        try:
            path,_=QFileDialog.getSaveFileName(self,'Export visible analysis rows',
                str(self.service.export_directory/(name+'-'+datetime.now().strftime('%Y%m%d-%H%M%S')+'.csv')),
                'CSV files (*.csv)',options=QFileDialog.Option.DontUseNativeDialog)
        finally:self._arm_refresh_timer()
        if not path:return
        if not path.lower().endswith('.csv'):path+='.csv'
        self._start('Exporting visible rows to CSV…',lambda:write_analysis_csv(Path(path),headers,rows),
            lambda result:self.footer.setText(f"Exported {result['rows']:,} rows to {result['path']}"))

    def _analysis_filter_changed(self, *args):
        self.analysis_freshness.clear()
        self.analysis_issues.setRowCount(0)
        self.analysis_daily.setRowCount(0)
        self._filter_analysis_tables()
        self.analysis_summary.setText('Scope changed. Analyze saved alarms to update the results.')

    def _analysis_filters(self):
        for widget, title, rows, key in (
                (self.analysis_customer, 'All customers', self.registry['customers'], 'customer_id'),
                (self.analysis_source, 'All sources', self.source_rows, 'source_id')):
            selected = widget.currentData()
            widget.blockSignals(True)
            widget.clear()
            widget.addItem(title, None)
            for row in rows:
                widget.addItem(row['name'], str(row[key]))
            widget.setCurrentIndex(max(0, widget.findData(selected)))
            widget.blockSignals(False)

    def refresh_analysis(self, preserve_feedback=False):
        if self.busy:
            self._analysis_pending = True
            return
        if not self.status.get('database_ready'):
            self.analysis_summary.setText('Start the server to analyze its saved alarms.')
            self.analysis_issues.setRowCount(0)
            self.analysis_daily.setRowCount(0)
            self._filter_analysis_tables()
            return
        days, source, customer = (self.analysis_days.currentData(), self.analysis_source.currentData(),
                                  self.analysis_customer.currentData())
        previous = self.footer.text()
        def operation():
            try:
                return self.service.alarm_analysis(days=days, source_id=source, customer_id=customer)
            except CollectorError as error:
                return dict(error=str(error))
        def shown(result):
            self._show_analysis(result)
            if preserve_feedback:
                self.footer.setText(previous)
        self._start('Analyzing saved alarm occurrences…', operation, shown)

    def _show_analysis(self, result):
        selected=self.selected_alarm_group()
        self.analysis_issues.setRowCount(0)
        self.analysis_daily.setRowCount(0)
        self.analysis_rows=[]
        self._equipment_editing_available=result.get('equipment_editing_available',False)
        if 'error' in result:
            self._filter_analysis_tables()
            self.analysis_freshness.clear()
            self.analysis_summary.setText(result['error'])
            self.footer.setText('Alarm analysis could not be loaded. Saved records are retained.')
            return
        freshness = result.get('freshness')
        if freshness and freshness.get('mode') == 'stored':
            updated = freshness.get('last_updated_at') or 'No processed records yet'
            self.analysis_freshness.setText(
                f"Warehouse updated: {updated} · {freshness['pending_occurrences']:,} record updates pending · "
                f"{freshness['pending_summaries']:,} summaries pending · {freshness['retrying_updates']:,} retrying.")
        else:
            self.analysis_freshness.setText('Analysis reads the saved source history directly.')
        summary = result['summary']
        self.analysis_summary.setText(f"{summary['occurrences']:,} alarm occurrences · "
                                      f"{summary['saved_versions']:,} saved versions")
        self.analysis_note.setText(f"{summary['uncertain_time']:,} occurrences have uncertain source times; "
                                   f"{summary['uncertain_order']:,} have uncertain revision order. "
                                   'AI suggestions are unverified equipment labels, not diagnosed causes.' +
                                   (' Daily rows are limited to 1,000 groups; narrow the filters to see more.'
                                    if result.get('daily_truncated') else ''))
        self.analysis_issues.setRowCount(len(result['issues']))
        self.analysis_rows=result['issues']
        for index, row in enumerate(result['issues']):
            for column, value in enumerate((row['source_name'], row['tag'], row['message'], row['occurrences'],
                                            row.get('equipment_name') or row['ai_suggestions'],row['ai_suggestions'])):
                self.analysis_issues.setItem(index, column, QTableWidgetItem(str(value) if value is not None else 'Uncertain / unavailable'))
            self.analysis_issues.item(index,4).setToolTip('Edited by user' if row.get('equipment_origin')=='manual'
                else 'Unverified saved AI suggestion' if row.get('equipment_name') or row.get('ai_suggestions') else 'Uncertain / unavailable')
            if selected and row.get('condition_key')==selected.get('condition_key') and row.get('source_id')==selected.get('source_id'):
                self.analysis_issues.selectRow(index)
        self._sync_controls()
        self.analysis_daily.setRowCount(len(result['daily']))
        largest = max((row['occurrences'] for row in result['daily']), default=1)
        for index, row in enumerate(result['daily']):
            values=(row['day'] or 'Uncertain date',row.get('record_type','Alarm'),
                    row.get('source_name'),row.get('description'),row.get('equipment_name'),row['occurrences'])
            for column,value in enumerate(values):
                item=QTableWidgetItem(str(value) if value is not None else 'Uncertain / unavailable')
                item.setToolTip(item.text())
                self.analysis_daily.setItem(index,column,item)
            origin={'manual':'Edited by user','ai':'Unverified saved AI suggestion',
                    'registered':'Registered source machine tag','unavailable':'Uncertain / unavailable'}
            self.analysis_daily.item(index,4).setToolTip(origin.get(row.get('equipment_origin'),'Uncertain / unavailable'))
            bar = QProgressBar()
            bar.setRange(0, 1000)
            bar.setValue(round(row['occurrences'] * 1000 / largest))
            bar.setTextVisible(False)
            self.analysis_daily.setCellWidget(index, 6, bar)
        self._filter_analysis_tables()
        self.footer.setText('Alarm analysis updated from saved records. AI settings are unchanged.')

    def selected_alarm_group(self):
        if not hasattr(self,'analysis_issues'):return None
        index=self.analysis_issues.currentRow()
        return self.analysis_rows[index] if (0<=index<len(self.analysis_rows)
            and not self.analysis_issues.isRowHidden(index) and self.analysis_issues.selectedItems()) else None

    def edit_equipment(self):
        row=self.selected_alarm_group()
        if self.busy or not row or not self._equipment_editing_available or not row.get('equipment_editable',True):return
        if self._equipment_dialog is not None:
            self._equipment_dialog.raise_();return
        captured=dict(row)
        dialog=EquipmentOverrideDialog(self,captured)
        self._equipment_dialog=dialog
        self.refresh_timer.stop()
        dialog.finished.connect(self._equipment_editor_closed)
        dialog.finished.connect(dialog.deleteLater)
        dialog.save_requested.connect(lambda value:self._save_equipment(captured,dialog,value))
        dialog.open()

    def _equipment_editor_closed(self,*args):
        self._equipment_dialog=None
        self._arm_refresh_timer()
        self._sync_controls()

    def _save_equipment(self,row,dialog,value):
        if self.busy:return
        dialog.error.setText('Saving equipment…')
        dialog.set_saving(True)
        def operation():
            try:
                return self.service.save_equipment_override(customer_id=row['customer_id'],source_id=row['source_id'],
                    condition_key=row['condition_key'],equipment_label=value,expected_version=row.get('override_version',0))
            except CollectorError as error:return dict(error=str(error))
        def saved(result):
            dialog.set_saving(False)
            if 'error' in result:
                dialog.error.setText(result['error'])
                self.footer.setText('Equipment was not saved. Your edit is retained in the editor.')
                return
            QDialog.accept(dialog)
            self.footer.setText('Equipment override saved.' if value is not None else 'Equipment override cleared. Saved AI suggestions are shown again.')
            self.refresh_analysis(preserve_feedback=True)
        self._start('Saving equipment override…',operation,saved)

    def navigate(self, index):
        self.pages.setCurrentIndex(index)
        self.nav_buttons[index].setChecked(True)
        self.page_title.setText(PAGES[index][0])
        self.page_subtitle.setText(PAGES[index][1])
        if index == 4:
            self._analysis_pending=True
            if self.busy:
                self._ai_pending=True
            elif self.status:
                self.refresh_ai_settings()

    def _form_edited(self, *args):
        self.form_dirty = True

    def _populate_deployment(self):
        self.deployment_mode.blockSignals(True)
        self.deployment_mode.setCurrentIndex(1 if self.service.settings.mode == 'network' else 0)
        self.deployment_mode.blockSignals(False)
        for name, entry in self.deployment_fields.items():
            entry.blockSignals(True)
            entry.setText(str(getattr(self.service.settings, name)))
            entry.blockSignals(False)
        self._update_deployment_preview()
        network = self.service.settings.mode == 'network'
        if hasattr(self, 'saved_deployment_labels'):
            self.saved_deployment_labels['Connection mode'].setText('Network server (multiple collector PCs)' if network else 'Local testing (one PC)')
            self.saved_deployment_labels['HTTPS listen address'].setText(self.service.settings.listen_address)
        self.deployment_badge.setText('NETWORK DEPLOYMENT' if network else 'LOCAL DEPLOYMENT')
        self.sidebar_environment.setText('NETWORK SERVER' if network else 'LOCAL ENVIRONMENT')
        self.environment_badge.setText(('NETWORK' if network else 'LOCAL') + '  ·  '+self.runtime_caption.upper())

    def _update_deployment_preview(self):
        self.deployment_preview.setText('Collector connection will be included in encrypted setup exports after saving.')
        self.deployment_fields['http_port'].setEnabled(not self.busy and self.deployment_mode.currentData() == 'local')

    def _deployment_mode_changed(self, *args):
        local = self.deployment_mode.currentData() == 'local'
        self.deployment_fields['listen_address'].setText('127.0.0.1' if local else '0.0.0.0')
        if local:
            self.deployment_fields['server_host'].setText('localhost')
        elif self.deployment_fields['server_host'].text() == 'localhost':
            self.deployment_fields['server_host'].clear()
        self._deployment_changed()

    def _deployment_changed(self, *args):
        self._update_deployment_preview()
        self.footer.setText('Unsaved deployment settings. Validate, then Save or Apply and restart.')

    def _deployment_dirty(self):
        return (self.deployment_mode.currentData() != self.service.settings.mode or
                any(entry.text() != str(getattr(self.service.settings, name)) for name, entry in self.deployment_fields.items()))

    def _deployment_candidate(self):
        try:
            return replace(self.service.settings, mode=self.deployment_mode.currentData(),
                           server_host=self.deployment_fields['server_host'].text().strip().lower(),
                           listen_address=self.deployment_fields['listen_address'].text().strip(),
                           https_port=int(self.deployment_fields['https_port'].text()),
                           http_port=int(self.deployment_fields['http_port'].text()))
        except ValueError:
            raise CollectorError('Enter different valid whole-number HTTP and HTTPS ports.') from None

    def validate_deployment(self):
        if self.busy:
            return
        try:
            candidate = self._deployment_candidate()
        except CollectorError as error:
            QMessageBox.warning(self, 'Deployment settings', str(error))
            return
        self._start('Validating the server address and ports…', lambda: self.service.validate_settings(candidate),
                    lambda result: self.footer.setText('Deployment settings are valid. Nothing has been changed.'))

    def save_deployment(self, restart=False):
        if self.busy:
            return
        try:
            candidate = self._deployment_candidate()
        except CollectorError as error:
            QMessageBox.warning(self, 'Deployment settings', str(error))
            return
        if restart and not self.confirm('Apply server settings?', 'Stop this Docker project, save the connection settings and restart it? '
                                       'Collectors retain pending uploads during the interruption. Existing data and credentials are preserved.'):
            return
        def saved(result):
            self._populate_deployment()
            self.refresh('Server settings saved successfully.' + (' Docker server restarted.' if restart else ' Start the server when ready.'))
        action = self.service.apply_settings if restart else self.service.save_settings
        self._start('Applying deployment settings…' if restart else 'Saving deployment settings…', lambda: action(candidate), saved)

    def _choice_changed(self, field):
        self.form_dirty = True
        self._cascade(field)

    def _cascade(self, changed=None):
        order = ('customer', 'site', 'project')
        tables = dict(customer='customers', site='sites', project='projects')
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
                box.addItem(record['name'], record)
                if previous and str(previous[name + '_id']) == str(record[name + '_id']):
                    box.setCurrentIndex(box.count() - 1)
            box.blockSignals(False)
        self._sync_controls()

    def _sync_controls(self):
        for control in self.controls:
            control.setEnabled(not self.busy)
        for name in ('analysis_issues','analysis_daily'):
            table=getattr(self,name)
            getattr(self,name+'_export').setEnabled(not self.busy and any(
                not table.isRowHidden(index) for index in range(table.rowCount())))
            getattr(self,name+'_clear_columns').setEnabled(not self.busy and bool(self._analysis_column_filters[name]))
        self.enable_ai_button.setEnabled(not self.busy and self._ai_enabled is False)
        self.disable_ai_button.setEnabled(not self.busy and self._ai_enabled is True)
        self.enable_ai_button.setToolTip('AI is already enabled. Disable it first to change the active model.'
                                        if self._ai_enabled is True else 'Enable the saved local AI model.')
        for name, choice in getattr(self, 'choices', {}).items():
            if name in self.names:
                self.names[name].setEnabled(not self.busy and choice.currentData() is None)
        ready = all(self.status.get(key, False) for key in ('api_ready', 'database_ready', 'worker_running'))
        self.start_button.setEnabled(not self.busy and not ready)
        self.stop_button.setEnabled(not self.busy and any(self.status.get(key, False) for key in ('initialized', 'api_ready', 'database_ready', 'worker_running')))
        self.register_button.setEnabled(not self.busy and self.status.get('database_ready', False))
        selected = self.selected_source() is not None and self.status.get('database_ready', False)
        for control in (self.export_button, self.rotate_button, self.delete_button):
            control.setEnabled(not self.busy and selected)
        row=self.selected_alarm_group()
        self.edit_equipment_button.setEnabled(not self.busy and self.status.get('database_ready',False)
            and self._equipment_editing_available and row is not None and bool(row.get('message') or row.get('tag'))
            and row.get('equipment_editable',True)
            and self._equipment_dialog is None)
        self._update_deployment_preview()

    def _start(self, message, operation, done, quiet=False):
        if self.busy or self.closing:
            return False
        self.busy = True
        self.refresh_timer.stop()
        self._quiet_feedback = self.footer.text() if quiet else None
        if not quiet:
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
        quiet_feedback = self._quiet_feedback
        self._quiet_feedback = None
        self._done = None
        self._work = None
        self.busy = False
        self.progress.setRange(0, 1)
        self.progress.setValue(0)
        self._sync_controls()
        if success:
            done(result)
        else:
            if quiet_feedback is not None:
                self.refresh_note.setText('Automatic refresh failed: ' + result + ' The next interval will retry.')
            else:
                self.footer.setText(result)
            if not self.closing and quiet_feedback is None:
                QMessageBox.critical(self, 'Central Server', result)
        if quiet_feedback is not None:
            self.footer.setText(quiet_feedback)
        if self.closing:
            QTimer.singleShot(0, self.close)
        elif self._ai_pending and not self.busy:
            self._ai_pending = False
            self.refresh_ai_settings(preserve_feedback=True)
        elif self._analysis_pending and not self.busy:
            self._analysis_pending = False
            self.refresh_analysis(preserve_feedback=True)
        if not self.busy:
            self._arm_refresh_timer()

    def refresh(self, success_message=None, quiet=False):
        def operation():
            status = self.service.status()
            result = dict(status=status, catalog=self.service.catalog() if status['database_ready'] else {key: [] for key in self.registry},
                          sources=self.service.sources() if status['database_ready'] else [])
            try:
                result['ai'] = self.service.machine_interpretations(include_records=False)
            except CollectorError as error:
                result['ai_error'] = str(error)
            if not self._refresh_preferences_loaded:
                try:
                    result['refresh_preferences'] = self.service.load_refresh_settings()
                except CollectorError as error:
                    result['refresh_preferences_error'] = str(error)
            return result
        self._start(success_message or 'Refreshing server health and sources…', operation,
                    lambda result: self._show_snapshot(result, success_message), quiet=quiet)

    def _set_refresh_preference(self, settings):
        seconds = settings['interval_seconds']
        self._saved_refresh_interval = seconds
        self._refresh_preferences_loaded = True
        self.refresh_interval.setValue(seconds / 60)
        self.refresh_timer.stop()
        self._arm_refresh_timer()
        self.refresh_note.setText(self._refresh_description())

    def _refresh_seconds(self):
        return round(self.refresh_interval.value() * 60)

    def _refresh_description(self):
        return ('Automatic refresh is off.' if not self._saved_refresh_interval else
                f'Automatic refresh every {self._saved_refresh_interval / 60:.2f} minutes.')

    def save_refresh_preference(self):
        if self.busy:
            return
        seconds = self._refresh_seconds()
        def saved(result):
            self._set_refresh_preference(result)
            self.footer.setText('Automatic refresh setting saved successfully.')
        self._start('Saving automatic refresh setting…', lambda: self.service.save_refresh_settings(seconds), saved)

    def _automatic_refresh(self):
        self.refresh_timer.stop()
        if (not self._saved_refresh_interval or self.busy or self.closing or self._equipment_dialog is not None or self._column_filter_dialog is not None or not self.isVisible() or self.form_dirty or self._deployment_dirty()
                or self._refresh_seconds() != self._saved_refresh_interval
                or (self._ai_saved_model is not None and self.ai_model.text() != self._ai_saved_model)):
            self._arm_refresh_timer()
            return
        self.refresh(quiet=True)

    def _arm_refresh_timer(self):
        if self._saved_refresh_interval and not self.busy and not self.closing and self._equipment_dialog is None:
            self.refresh_timer.start(self._saved_refresh_interval * 1000)

    def _show_snapshot(self, result, success_message=None):
        if 'refresh_preferences' in result:
            self._set_refresh_preference(result['refresh_preferences'])
        elif 'refresh_preferences_error' in result:
            self._refresh_preferences_loaded = True
            self.refresh_note.setText(result['refresh_preferences_error'])
        else:
            self.refresh_note.setText(self._refresh_description() + ' Last refresh: ' + datetime.now().strftime('%H:%M:%S'))
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
            self.next_hint.setText('Manage sources, export setup files and review alarm analysis.')
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
                      str(source['last_received'] or 'No uploads yet'))
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
        self._analysis_filters()
        if self.pages.currentIndex() == 4:
            self._analysis_pending = True
        if 'ai' in result:
            self._show_ai_settings(result['ai'])
        elif result.get('ai_error'):
            self.ai_note.setText(result['ai_error'])
        self._sync_controls()
        self.footer.setText(success_message or self.status.get('error') or 'Server status is up to date.')

    def start_server(self):
        if self._deployment_dirty():
            self.footer.setText('Save the deployment settings before starting, or use Apply and restart.')
            return
        self._start('Starting the Docker server…', self.service.start,
                    lambda result: self.refresh('Docker server started successfully.'))

    def startup_server(self):
        self._start('Checking and starting the configured Docker server…', self.service.start_if_needed,
                    lambda result: self.refresh('Docker server is ready.'))

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
                                            ('project', 'project_name', 'project name')):
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
                f"Remove {source['name']}?\n\nThis revokes all its upload credentials. Received data and audit history remain saved. "
                'Unsent batches stay on the Collector. This registration cannot be restored from this window.'):
            self._start('Removing the source registration…', lambda: self.service.delete_source(source['source_id']),
                        lambda result: self.refresh('Source removed. Upload credentials revoked; received history retained.'))

    def refresh_ai_settings(self, preserve_feedback=False):
        previous = self.footer.text()
        def operation():
            try:
                return self.service.machine_interpretations(include_records=False)
            except CollectorError as error:
                return dict(error=str(error))
        def shown(result):
            if 'error' in result:
                self.ai_note.setText(result['error'])
            else:
                self._show_ai_settings(result)
            self.footer.setText(previous if preserve_feedback else 'Saved AI settings refreshed.')
        self._start('Reading saved AI settings...', operation, shown)

    def _show_ai_settings(self,result):
        if 'configuration' in result:self._show_ai_configuration(result['configuration'])
        self.ai_note.setText('AI supplies saved equipment suggestions. Your equipment edits are kept separately.')

    def _show_ai_configuration(self, configuration):
        saved = configuration['model']
        self._ai_enabled = configuration['enabled']
        if self._ai_saved_model is None or self.ai_model.text() == self._ai_saved_model:
            self.ai_model.setText(saved)
        self._ai_saved_model = saved
        runtime = 'Private Docker Ollama service.' if getattr(self.service, 'ai_provider', '1') == 'container' else 'Ollama on this Central Server PC.'
        self.ai_config_state.setText(('Enabled' if configuration['enabled'] else 'Disabled') + ' · Saved model: ' + saved +
                                     '. ' + runtime)
        self._sync_controls()

    def enable_machine_ai(self):
        if self.busy or self._ai_enabled is not False:
            return
        model = self.ai_model.text().strip()
        def enabled(result):
            self._show_ai_configuration(result)
            self.footer.setText('Local AI enabled. Alarm equipment suggestions use the saved local model.')
            self._analysis_pending=self.pages.currentIndex()==4
            self.refresh_ai_settings(preserve_feedback=True)
        self._start('Checking the installed local model and enabling AI…', lambda: self.service.enable_machine_ai(model), enabled)

    def disable_machine_ai(self):
        if self.busy or self._ai_enabled is not True:
            return
        def disabled(result):
            self._show_ai_configuration(result)
            self.footer.setText('Local AI disabled. Saved results are retained.')
            self._analysis_pending=self.pages.currentIndex()==4
            self.refresh_ai_settings(preserve_feedback=True)
        self._start('Disabling local AI…', self.service.disable_machine_ai, disabled)

    def closeEvent(self, event):
        if self._column_filter_dialog is not None:
            self._column_filter_dialog.raise_()
            self.footer.setText('Finish or cancel the column filter before closing.')
            event.ignore()
            return
        if self._equipment_dialog is not None and self._equipment_dialog.isVisible():
            self._equipment_dialog.raise_()
            self.footer.setText('Finish or cancel the equipment editor before closing.')
            event.ignore()
            return
        if self.busy:
            self.closing = True
            self.footer.setText('Finishing the current operation before closing…')
            event.ignore()
        elif (self.form_dirty or self._deployment_dirty() or
              self._refresh_seconds() != self._saved_refresh_interval or
              (self._ai_saved_model is not None and self.ai_model.text() != self._ai_saved_model)) and not self.confirm(
                  'Close manager?', 'Discard unsaved registration, deployment or model edits and close this window? The server stays running.'):
            self.closing = False
            event.ignore()
        else:
            self.refresh_timer.stop()
            event.accept()


def main(argv=None):
    parser = argparse.ArgumentParser(description='Linux / Docker Central Server manager')
    parser.add_argument('--workspace', type=Path, default=Path.home() / 'central-server')
    parser.add_argument('--project', default='linker-scada-wsl')
    args = parser.parse_args(argv)
    app = QApplication.instance() or QApplication([])
    app.setApplicationName('Linker Central Server')
    app.setDesktopFileName('linker-central-server')
    app.setWindowIcon(application_icon())
    app.setStyle('Fusion')
    app.setFont(QFont('Ubuntu Sans', 10))
    try:
        service = DockerManagerService(args.workspace, args.project)
    except (CollectorError, OSError, ValueError):
        QMessageBox.critical(None, 'Central Server - '+runtime_caption(), 'Cannot open this workspace. Check its private .env, saved connection mode/address and Compose files.')
        return 1
    window = DockerManagerWindow(service, auto_start=True)
    from server.management.desktop_identity import install_desktop_entry
    try:
        install_desktop_entry(service.settings.workspace, service.settings.project)
    except (OSError, ValueError, CollectorError):
        pass  # Optional shell artwork must not prevent server management.
    window.show()
    return app.exec()


if __name__ == '__main__':
    raise SystemExit(main())
