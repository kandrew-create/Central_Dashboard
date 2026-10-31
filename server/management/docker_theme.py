"""Presentation for the native Docker manager; no application or database behavior."""
from PySide6.QtCore import Qt, QRectF
from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap


STYLESHEET = '''
QWidget { color: #26334a; font-family: "Ubuntu Sans", "DejaVu Sans"; font-size: 13px; }
QMainWindow, QWidget#workspace { background: #f4f6fb; }
QWidget#sidebar { background: #101c32; }
QLabel#brand { color: #ffffff; font-size: 23px; font-weight: 700; }
QLabel#brandCaption { color: #8294b3; font-size: 11px; }
QLabel#sidebarCaption { color: #8397b5; font-size: 10px; font-weight: 700; letter-spacing: 2px; }
QLabel#sidebarNote { color: #91a3bf; font-size: 11px; }
QPushButton#nav { color: #a8b8d0; background: transparent; border: 0; border-radius: 8px;
  padding: 12px 13px; text-align: left; font-weight: 500; }
QPushButton#nav:hover { background: #192a46; color: white; }
QPushButton#nav:checked { background: #233a5d; color: #ffffff; }
QFrame#sidebarRule { background: #26344e; max-height: 1px; border: none; }
QLabel#eyebrow { color: #63758f; font-size: 10px; letter-spacing: 2px; font-weight: 700; }
QLabel#pageTitle { color: #182742; font-size: 27px; font-weight: 700; }
QLabel#pageSubtitle, QLabel#muted { color: #5f6f86; }
QLabel#heroTitle { color: #172a48; font-size: 23px; font-weight: 700; }
QLabel#sectionTitle { color: #21324e; font-size: 15px; font-weight: 700; }
QLabel#metricNumber { color: #182b49; font-size: 32px; font-weight: 700; }
QLabel#metricLabel { color: #62738c; font-size: 11px; font-weight: 500; }
QLabel#metricHint { color: #64748b; font-size: 10px; }
QFrame#card { background: #ffffff; border: 1px solid #e4e9f2; border-radius: 12px; }
QFrame#endpointBox { background: #f6f8fc; border: 1px solid #e9edf5; border-radius: 8px; }
QFrame#emptyState { background: #f8faff; border: 1px dashed #d9e3f3; border-radius: 9px; }
QLabel#endpoint { color: #38577f; font-family: "Ubuntu Sans Mono", monospace; font-size: 12px; }
QLabel#pill { color: #526883; background: #edf1f8; border-radius: 12px; padding: 5px 12px; font-size: 11px; font-weight: 600; }
QLabel#pill[tone="good"] { color: #19835f; background: #e8f7ef; }
QLabel#pill[tone="warning"] { color: #ab7520; background: #fff5df; }
QLabel#pill[tone="stopped"] { color: #748094; background: #edf0f5; }
QLabel#serviceDot { color: #a1afc1; font-size: 19px; }
QLabel#serviceDot[ready="true"] { color: #24ad7c; }
QLabel#fieldLabel { color: #42536d; font-size: 12px; font-weight: 600; }
QLabel#help { color: #5f6f86; font-size: 11px; }
QPushButton { background: #ffffff; border: 1px solid #dce3ef; border-radius: 7px;
  padding: 9px 15px; color: #40526e; font-weight: 600; }
QPushButton:hover { background: #f1f5fc; border-color: #bacbe4; }
QPushButton:pressed { background: #e7eef9; }
QPushButton:disabled { color: #a7b2c4; background: #f4f6fa; border-color: #e8edf5; }
QPushButton#primary { color: white; background: #356ff0; border-color: #356ff0; }
QPushButton#primary:hover { background: #255bd3; border-color: #255bd3; }
QPushButton#primary:disabled { background: #b5c8f4; border-color: #b5c8f4; }
QPushButton#danger { color: #c45b60; background: #fffafa; border-color: #efd7da; }
QPushButton#danger:hover { background: #fff0f1; }
QPushButton#quiet { color: #607795; background: transparent; border-color: transparent; }
QPushButton#quiet:hover { background: #eef3fb; }
QLineEdit, QComboBox { background: #fbfcfe; border: 1px solid #dde5f0; border-radius: 7px;
  padding: 9px 11px; min-height: 17px; selection-background-color: #d5e4ff; }
QLineEdit:focus, QComboBox:focus { border-color: #6d9aee; background: white; }
QLineEdit:disabled { color: #9ba7b8; background: #f2f5fa; }
QComboBox::drop-down { border: 0; width: 25px; }
QComboBox QAbstractItemView { background: white; selection-background-color: #eaf1ff; selection-color: #264c8c; }
QTableWidget { background: white; border: 0; gridline-color: #f0f3f8; outline: none;
  selection-background-color: #eaf1ff; selection-color: #284f88; }
QTableWidget::item { border-bottom: 1px solid #edf1f7; padding: 7px; }
QHeaderView::section { background: #f7f9fc; color: #5e6f86; border: 0; border-bottom: 1px solid #e8edf5;
  padding: 12px 8px; font-size: 10px; font-weight: 600; }
QTableCornerButton::section { background: #f7f9fc; border: none; }
QTextEdit { color: #63728a; background: #f8fafd; border: 1px solid #e7edf5; border-radius: 7px; padding: 8px; }
QScrollArea { background: transparent; border: 0; }
QScrollBar:vertical { background: transparent; width: 7px; margin: 2px; }
QScrollBar::handle:vertical { background: #cbd5e5; border-radius: 3px; min-height: 24px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }
QFrame#footer { background: #ffffff; border-top: 1px solid #e6ebf3; }
QLabel#footerText { color: #64748b; font-size: 11px; }
QProgressBar { border: 0; background: #eaf0fc; border-radius: 3px; max-height: 5px; }
QProgressBar::chunk { background: #4e83ef; border-radius: 3px; }
QDialog, QMessageBox { background: #f7f9fd; }
QToolTip { background: #223652; color: white; border: 0; padding: 7px; }
'''


def icon(kind, color='#a6bbd9', size=20):
    pixmap = QPixmap(size * 2, size * 2)
    pixmap.setDevicePixelRatio(2)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.scale(size / 24, size / 24)
    painter.setPen(QPen(QColor(color), 1.7, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
    if kind == 'overview':
        for x, y in ((3, 3), (14, 3), (3, 14), (14, 14)):
            painter.drawRoundedRect(QRectF(x, y, 7, 7), 1.5, 1.5)
    elif kind == 'register':
        painter.drawEllipse(QRectF(3, 3, 18, 18))
        painter.drawLine(7, 12, 17, 12)
        painter.drawLine(12, 7, 12, 17)
    elif kind == 'sources':
        for y in (4, 13):
            painter.drawRoundedRect(QRectF(3, y, 18, 7), 2, 2)
            painter.drawPoint(7, y + 3)
            painter.drawLine(12, y + 3, 17, y + 3)
    elif kind == 'deployment':
        painter.drawRoundedRect(QRectF(3, 4, 18, 13), 2, 2)
        painter.drawLine(8, 21, 16, 21)
        painter.drawLine(12, 17, 12, 21)
    elif kind == 'identification':
        painter.drawRoundedRect(QRectF(5, 5, 14, 14), 3, 3)
        for point in (8, 16):
            painter.drawLine(point, 2, point, 5)
            painter.drawLine(point, 19, point, 22)
            painter.drawLine(2, point, 5, point)
            painter.drawLine(19, point, 22, point)
        painter.drawRoundedRect(QRectF(9, 9, 6, 6), 1, 1)
    elif kind == 'arrow':
        painter.drawLine(5, 12, 19, 12)
        painter.drawLine(14, 7, 19, 12)
        painter.drawLine(19, 12, 14, 17)
    elif kind == 'refresh':
        painter.drawArc(QRectF(4, 4, 16, 16), 40 * 16, 290 * 16)
        painter.drawLine(20, 4, 20, 10)
        painter.drawLine(14, 10, 20, 10)
    painter.end()
    return QIcon(pixmap)
