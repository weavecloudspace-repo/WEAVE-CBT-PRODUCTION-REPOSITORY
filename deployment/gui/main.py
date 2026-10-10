"""WEAVE CBT Desktop Control Center.

All privileged mutations remain in the verified CLI. The UI reflects real
status from --json and never equates installation with service health.
"""
from __future__ import annotations

import ipaddress
import json
import sys
from datetime import datetime
from itertools import pairwise
from pathlib import Path

from bridge import discover, elevate_gui, is_admin, state_path
from PySide6.QtCore import QPointF, QProcess, QRectF, QSettings, QSize, Qt, QTimer, QUrl
from PySide6.QtGui import (
    QColor,
    QDesktopServices,
    QFont,
    QIcon,
    QPainter,
    QPalette,
    QPen,
    QPixmap,
)
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QStyledItemDelegate,
    QVBoxLayout,
    QWidget,
)
from setup_wizard import SetupWizard

ROOT = Path(__file__).resolve().parent
RELEASES_URL = "https://github.com/weavecloudspace-repo/WEAVE-CBT-PRODUCTION-REPOSITORY/releases"
PAGES = ["Overview", "Server", "Network", "Updates", "Diagnostics", "Logs", "Settings"]
MUTATIONS = {"install", "start", "stop", "restart", "update", "lan", "tls"}
SERVICES = ("api", "worker", "postgres", "redis", "nginx", "bootstrap")
SERVICE_DETAILS = {
    "api": ("FastAPI", "Examination API", "services/fastapi.svg"),
    "worker": ("WEAVE worker", "Background jobs", "weave-logo-blue.png"),
    "postgres": ("PostgreSQL", "Examination database", "services/postgresql.svg"),
    "redis": ("Redis", "Cache & job queue", "services/redis.svg"),
    "nginx": ("NGINX", "Web gateway", "services/nginx.svg"),
    "bootstrap": ("WEAVE bootstrap", "Startup & migrations", "weave-logo-blue.png"),
}


def resource(name: str) -> Path:
    paths = (ROOT / "resources" / name, Path(sys.argv[0]).resolve().parent / "resources" / name)
    return next((path for path in paths if path.is_file()), paths[0])


def desktop_palette():
    """Keep native control text readable even when the OS uses a dark theme."""
    palette = QPalette()
    colors = {
        QPalette.Window: "#ffffff", QPalette.WindowText: "#10213b",
        QPalette.Base: "#ffffff", QPalette.AlternateBase: "#f4f6fa",
        QPalette.Text: "#10213b", QPalette.Button: "#ffffff",
        QPalette.ButtonText: "#10213b", QPalette.BrightText: "#ffffff",
        QPalette.ToolTipBase: "#ffffff", QPalette.ToolTipText: "#10213b",
        QPalette.Highlight: "#2052d4", QPalette.HighlightedText: "#ffffff",
        QPalette.PlaceholderText: "#546782",
    }
    for role, color in colors.items():
        palette.setColor(role, QColor(color))
    for role in (QPalette.Text, QPalette.WindowText, QPalette.ButtonText):
        palette.setColor(QPalette.Disabled, role, QColor("#52657f"))
    return palette


def label(text="", kind="normal", wrap=False):
    widget = QLabel(str(text))
    widget.setProperty("kind", kind)
    widget.setWordWrap(wrap)
    return widget


def logo_widget(filename, size=36):
    image = QLabel()
    image.setFixedSize(size + 12, size + 12)
    image.setAlignment(Qt.AlignCenter)
    image.setProperty("kind", "serviceLogo")
    pixmap = QIcon(str(resource(filename))).pixmap(QSize(size, size))
    if not pixmap.isNull():
        image.setPixmap(pixmap)
    return image


def heading(text, size=20):
    item = QLabel(text)
    item.setObjectName("heading")
    item.setFont(QFont("Segoe UI", size, QFont.DemiBold))
    item.setStyleSheet(f"font-size: {size}px; font-weight: 600;")
    item.setWordWrap(True)
    return item


def navigation_icon(name):
    """Draw small vector icons without adding an asset or font dependency."""
    pixmap = QPixmap(20, 20)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setPen(QPen(QColor("#b9cbed"), 1.5, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    if name == "Overview":
        for x, y in ((3, 3), (12, 3), (3, 12), (12, 12)):
            painter.drawRoundedRect(QRectF(x, y, 5, 5), 1, 1)
    elif name == "Server":
        for y in (3, 11):
            painter.drawRoundedRect(QRectF(2, y, 16, 6), 1.5, 1.5)
            painter.drawPoint(QPointF(5, y + 3))
            painter.drawLine(QPointF(11, y + 3), QPointF(15, y + 3))
    elif name == "Network":
        painter.drawRoundedRect(QRectF(7, 2, 6, 5), 1, 1)
        painter.drawLine(10, 7, 10, 11)
        painter.drawLine(4, 11, 16, 11)
        for x in (1, 7, 13):
            painter.drawRoundedRect(QRectF(x, 13, 6, 5), 1, 1)
    elif name == "Updates":
        painter.drawArc(QRectF(3, 3, 14, 14), 30 * 16, 285 * 16)
        painter.drawLine(16, 2, 16, 7)
        painter.drawLine(12, 7, 16, 7)
    elif name == "Diagnostics":
        points = ((1, 10), (5, 10), (8, 4), (11, 16), (14, 10), (19, 10))
        for start, end in pairwise(points):
            painter.drawLine(QPointF(*start), QPointF(*end))
    elif name == "Logs":
        painter.drawRoundedRect(QRectF(4, 2, 12, 16), 1.5, 1.5)
        for y in (6, 10, 14):
            painter.drawLine(7, y, 13, y)
    else:
        for y, x in ((4, 7), (10, 13), (16, 7)):
            painter.drawLine(2, y, 18, y)
            painter.setBrush(QColor("#14243e"))
            painter.drawEllipse(QPointF(x, y), 2, 2)
    painter.end()
    return QIcon(pixmap)


def action(text, handler, style="secondary"):
    widget = QPushButton(text)
    widget.setProperty("kind", style)
    widget.setCursor(Qt.PointingHandCursor)
    widget.setMinimumHeight(38)
    widget.clicked.connect(handler)
    return widget


def panel(kind="card"):
    frame = QFrame()
    frame.setProperty("surface", kind)
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(20, 18, 20, 18)
    layout.setSpacing(12)
    return frame, layout


def line_button(text, handler, kind="secondary"):
    return action(text, handler, kind)


class Metric(QFrame):
    def __init__(self, title_text, value="Checking", hint="", logo=None, compact=False):
        super().__init__()
        self.setProperty("surface", "metric")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(6)
        if compact:
            layout.setContentsMargins(16, 12, 16, 12)
            layout.setSpacing(4)
        title = QHBoxLayout()
        title.addWidget(label(title_text.upper(), "eyebrow"), 1)
        if logo:
            image = logo_widget(logo, 24)
            if compact:
                image.setFixedSize(28, 28)
            title.addWidget(image)
        layout.addLayout(title)
        self.value = heading(value, 18 if compact else 20)
        self.value.setProperty("status", "muted")
        if compact:
            title.addWidget(self.value)
        else:
            layout.addWidget(self.value)
        self.hint = label(hint, "muted", True)
        if compact:
            self.hint.setStyleSheet("font-size: 12px;")
        layout.addWidget(self.hint)

    def set_value(self, text, hint="", state="muted"):
        self.value.setText(text)
        self.value.setProperty("status", state)
        self.value.style().unpolish(self.value)
        self.value.style().polish(self.value)
        self.hint.setText(hint)


class StatusBadge(QLabel):
    """Give the existing status text a matching, accessible visual treatment."""
    def __init__(self, text):
        super().__init__()
        self.setProperty("kind", "chip")
        self.setText(text)

    def setText(self, text):
        super().setText(text)
        tone = "ok" if text == "RUNNING" else "warning" if text in {
            "NEEDS ATTENTION", "STATUS UNAVAILABLE",
        } else "muted"
        self.setProperty("tone", tone)
        self.style().unpolish(self)
        self.style().polish(self)


class ServiceStatus(QLabel):
    """Mirror the existing service observation in both desktop pages."""
    def __init__(self, text="Unknown"):
        super().__init__()
        self.mirrors = []
        self.setProperty("kind", "chip")
        self.setText(text)

    def add_mirror(self, widget):
        self.mirrors.append(widget)
        self.setText(self.text())

    def setText(self, text):
        super().setText(text)
        if text == "Completed" or text == "Running / healthy":
            tone = "ok"
        elif "unhealthy" in text.lower() or text in {"Exited", "Dead", "Restarting"}:
            tone = "danger"
        elif text == "Running":
            # Container state alone does not establish a passed health check.
            tone = "info"
        elif text.endswith(" running"):
            active, _, total = text.split()[0].partition("/")
            tone = "info" if active == total else "warning"
        elif text == "Not reported" or text == "Unknown":
            tone = "muted"
        else:
            tone = "warning"
        for widget in (self, *self.mirrors):
            if widget is not self:
                widget.setText(text)
            widget.setProperty("tone", tone)
            widget.style().unpolish(widget)
            widget.style().polish(widget)


class ControlCenter(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("WEAVE CBT  |  Desktop Manager")
        self.resize(1230, 810)
        self.setMinimumSize(980, 640)
        icon_file = resource("weave-logo-blue.png")
        if icon_file.exists():
            self.setWindowIcon(QIcon(str(icon_file)))

        self.settings = QSettings("WEAVE", "CBTDesktop")
        self.desktop = discover(packaged=ROOT)
        self.manifest = {}
        self.status = None
        self.busy = False
        self.last_command = ""
        self.last_error = ""
        self.output_tail = ""
        self.operation_records = []

        self.process = QProcess(self)
        self.process.setProcessChannelMode(QProcess.MergedChannels)
        self.process.readyReadStandardOutput.connect(self.consume)
        self.process.finished.connect(self.finished)
        self.process.errorOccurred.connect(self.process_error)

        self.probe = QProcess(self)
        self.probe.setProcessChannelMode(QProcess.MergedChannels)
        self.probe.finished.connect(self.probe_finished)
        self.probe.errorOccurred.connect(self.probe_error)

        self.build()
        self.refresh()
        self.poll = QTimer(self)
        self.poll.timeout.connect(self.refresh)
        self.poll.start(20000)

    def build(self):
        root = QWidget()
        root.setObjectName("shell")
        self.setCentralWidget(root)
        shell = QHBoxLayout(root)
        shell.setContentsMargins(0, 0, 0, 0)
        shell.setSpacing(0)

        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(224)
        side = QVBoxLayout(sidebar)
        side.setContentsMargins(18, 28, 18, 22)
        side.setSpacing(8)

        brand = QHBoxLayout()
        image = QLabel()
        image.setObjectName("brandMark")
        image.setFixedSize(46, 42)
        image.setAlignment(Qt.AlignCenter)
        pix = QPixmap(str(resource("weave-logo-blue.png")))
        if not pix.isNull():
            image.setPixmap(pix.scaled(QSize(34, 28), Qt.KeepAspectRatio, Qt.SmoothTransformation))
        brand.addWidget(image)
        brand_text = QVBoxLayout()
        brand_text.setSpacing(3)
        brand_text.addWidget(heading("WEAVE CBT", 16))
        brand_text.addWidget(label("Desktop Manager", "brandCaption"))
        brand.addLayout(brand_text)
        brand.addStretch()
        side.addLayout(brand)
        side.addSpacing(26)
        side.addWidget(label("WORKSPACE", "eyebrow"))
        side.addSpacing(5)
        self.nav = {}
        for i, page_name in enumerate(PAGES):
            control = action(page_name, lambda checked=False, index=i: self.navigate(index), "nav")
            control.setCheckable(True)
            control.setIcon(navigation_icon(page_name))
            control.setIconSize(QSize(20, 20))
            self.nav[i] = control
            side.addWidget(control)
        side.addStretch()
        footer, footer_layout = panel("sidebarNote")
        footer_layout.setContentsMargins(14, 14, 14, 14)
        footer_layout.setSpacing(6)
        footer_layout.addWidget(label("LOCAL INFRASTRUCTURE", "eyebrow"))
        footer_layout.addWidget(label("Your server keeps running when this window is closed.", "sidebarHint", True))
        side.addWidget(footer)
        shell.addWidget(sidebar)

        right = QWidget()
        body = QVBoxLayout(right)
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)
        header = QFrame()
        header.setObjectName("topbar")
        bar = QHBoxLayout(header)
        bar.setContentsMargins(28, 14, 28, 14)
        bar.setSpacing(10)
        bar.addWidget(label("Workspace  /", "muted"))
        self.page_name = heading("Overview", 14)
        bar.addWidget(self.page_name)
        bar.addStretch()
        self.channel = label("Checking release", "chip")
        self.connection = StatusBadge("Checking server")
        bar.addWidget(self.channel)
        bar.addWidget(self.connection)
        bar.addWidget(action("Refresh", self.refresh))
        body.addWidget(header)

        self.pages = QStackedWidget()
        for creator in (
            self.overview_page, self.server_page, self.network_page,
            self.updates_page, self.diagnostics_page, self.logs_page,
            self.settings_page,
        ):
            scroll = QScrollArea()
            scroll.setObjectName("contentScroll")
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(QFrame.NoFrame)
            scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            scroll.setWidget(creator())
            self.pages.addWidget(scroll)
        body.addWidget(self.pages, 1)
        shell.addWidget(right, 1)
        self.navigate(0)

        css = resource("theme.qss")
        if css.is_file():
            self.setStyleSheet(css.read_text(encoding="utf-8").replace(
                "__chevron_down__", resource("chevron-down.svg").as_posix()))

    def page(self, name, description):
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(28, 26, 28, 28)
        layout.setSpacing(14)
        intro = QVBoxLayout()
        intro.setSpacing(6)
        intro.addWidget(heading(name, 28))
        intro.addWidget(label(description, "muted", True))
        layout.addLayout(intro)
        layout.addSpacing(2)
        return content, layout

    def row(self, *widgets):
        row = QHBoxLayout()
        row.setSpacing(10)
        for widget in widgets:
            row.addWidget(widget)
        return row

    def overview_page(self):
        page = QWidget()
        body = QVBoxLayout(page)
        body.setContentsMargins(28, 24, 28, 24)
        body.setSpacing(16)
        title = QHBoxLayout()
        title.addWidget(heading("Welcome back", 28))
        title.addStretch()
        self.start_btn = action("Start server", lambda: self.run("start"), "primary")
        self.stop_btn = action("Stop server", lambda: self.confirm_operation("stop"), "danger")
        self.restart_btn = action("Restart", lambda: self.confirm_operation("restart"))
        self.install_shortcut = action("Install server", lambda: self.navigate(1), "primary")
        self.lifecycle_grid = QGridLayout()
        self.lifecycle_grid.setSpacing(8)
        title.addLayout(self.lifecycle_grid)
        body.addLayout(title)

        self.metrics_grid = metrics = QGridLayout()
        metrics.setHorizontalSpacing(12)
        metrics.setVerticalSpacing(12)
        self.metric_server = Metric("CBT server", compact=True)
        self.metric_docker = Metric("Docker runtime", logo="services/docker.svg", compact=True)
        for i, widget in enumerate((self.metric_server, self.metric_docker)):
            widget.setMinimumHeight(94)
            widget.layout().setContentsMargins(18, 16, 18, 16)
            widget.layout().setSpacing(6)
            metrics.addWidget(widget, 0, i)
        body.addLayout(metrics)

        service_health, health = panel()
        health.setContentsMargins(20, 18, 20, 18)
        health.setSpacing(14)
        service_title = QHBoxLayout()
        service_title.addWidget(heading("Service health", 17))
        service_title.addStretch()
        details = action("Details", lambda: self.navigate(1), "disclosure")
        details.setMinimumHeight(26)
        details.setProperty("density", "compact")
        service_title.addWidget(details)
        health.addLayout(service_title)
        self.overview_service_grid = QGridLayout()
        self.overview_service_grid.setSpacing(12)
        self.overview_service_labels = {}
        self.overview_service_cards = []
        for name in SERVICES:
            title_text, description, logo = SERVICE_DETAILS[name]
            card, content = panel("serviceCard")
            card.setToolTip(description)
            card.setMinimumHeight(78)
            content.setContentsMargins(14, 12, 14, 12)
            identity = QHBoxLayout()
            identity.setSpacing(12)
            identity.addWidget(logo_widget(logo, 32))
            text = QVBoxLayout()
            text.setSpacing(6)
            text.addWidget(heading(title_text, 15))
            value = label("Unknown", "chip")
            value.setProperty("density", "compact")
            text.addWidget(value, 0, Qt.AlignLeft)
            identity.addLayout(text, 1)
            content.addLayout(identity)
            self.overview_service_labels[name] = value
            self.overview_service_cards.append(card)
        health.addLayout(self.overview_service_grid)
        body.addWidget(service_health)

        access, links = panel()
        links.setContentsMargins(18, 16, 18, 16)
        links.setSpacing(12)
        links.addWidget(heading("Examination portals", 17))
        copy_address = action("Copy LAN address", self.copy_lan_url)
        copy_address.setToolTip("LAN access must be tested from another device.")
        links.addLayout(self.row(
            action("Open staff portal", lambda: self.open_url("http://127.0.0.1/staff")),
            action("Open student portal", lambda: self.open_url("http://127.0.0.1/student")),
        ))
        links.addWidget(copy_address)

        maintenance, tools = panel()
        tools.setContentsMargins(18, 16, 18, 16)
        tools.setSpacing(12)
        tools.addWidget(heading("Tools & maintenance", 17))
        tool_actions = QGridLayout()
        tool_actions.setSpacing(10)
        for index, control in enumerate((
            action("Check updates", lambda: self.navigate(3)),
            action("Run diagnostics", lambda: self.run("doctor")),
            action("Network setup", lambda: self.navigate(2)),
            action("View logs", lambda: self.navigate(5)),
        )):
            tool_actions.addWidget(control, index // 2, index % 2)
        tools.addLayout(tool_actions)
        self.quick_access_grid = QGridLayout()
        self.quick_access_grid.setSpacing(16)
        self.quick_access_grid.addWidget(access, 0, 0)
        self.quick_access_grid.addWidget(maintenance, 0, 1)
        for column in range(2):
            self.quick_access_grid.setColumnStretch(column, 1)
        body.addLayout(self.quick_access_grid)

        self.last_activity = label("No actions in this session.", "muted", True)
        self.last_activity.hide()
        self.activity_toggle = QPushButton("Recent activity  +")
        self.activity_toggle.setProperty("kind", "disclosure")
        self.activity_toggle.setCursor(Qt.PointingHandCursor)
        self.activity_toggle.setCheckable(True)
        self.activity_toggle.toggled.connect(self.last_activity.setVisible)
        self.activity_toggle.toggled.connect(lambda expanded: self.activity_toggle.setText(
            "Recent activity  −" if expanded else "Recent activity  +"))
        body.addWidget(self.activity_toggle, 0, Qt.AlignLeft)
        body.addWidget(self.last_activity)
        self.arrange_overview()
        body.addStretch()
        return page

    def arrange_overview(self):
        """Reflow existing widgets only; their signals and state stay attached."""
        wide = self.width() >= 1130
        for i, card in enumerate(self.overview_service_cards):
            self.overview_service_grid.removeWidget(card)
            columns = 3
            self.overview_service_grid.addWidget(card, i // columns, i % columns)
        for i in range(3):
            self.overview_service_grid.setColumnStretch(i, 1)
        controls = (self.install_shortcut, self.start_btn, self.stop_btn, self.restart_btn)
        for widget in controls:
            self.lifecycle_grid.removeWidget(widget)
        if self.desktop.server_installed:
            # Keep the hidden installation button attached to its original card.
            self.lifecycle_grid.addWidget(self.install_shortcut, 1, 0)
            for i, widget in enumerate(controls[1:]):
                self.lifecycle_grid.addWidget(widget, 0, i)
        else:
            for i, widget in enumerate(controls):
                self.lifecycle_grid.addWidget(widget, i // 2, i % 2)
        for i in range(3):
            self.lifecycle_grid.setColumnStretch(i, 1 if self.desktop.server_installed or i < 2 else 0)
        for i, widget in enumerate((self.metric_server, self.metric_docker)):
            self.metrics_grid.removeWidget(widget)
            self.metrics_grid.addWidget(widget, 0, i)
            self.metrics_grid.setColumnStretch(i, 1)
        if hasattr(self, "server_cards"):
            services, progress = self.server_cards
            for widget in self.server_cards:
                self.server_grid.removeWidget(widget)
            self.server_grid.addWidget(services, 0, 0)
            self.server_grid.addWidget(progress, 0 if wide else 1, 1 if wide else 0)
            self.server_grid.setColumnStretch(0, 2 if wide else 1)
            self.server_grid.setColumnStretch(1, 3 if wide else 0)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "quick_access_grid"):
            self.arrange_overview()

    def server_page(self):
        page, body = self.page("Server management", "Lifecycle controls and live service observations, sourced from the WEAVE CLI.")
        overview, group = panel()
        group.addWidget(heading("Server installation", 17))
        self.install_detail = label("Checking local installation state...", "muted", True)
        group.addWidget(self.install_detail)
        self.summary = label("Checking the local installation and services...", "muted", True)
        group.addWidget(self.summary)
        self.install_btn = action("Install WEAVE CBT", self.prepare_install, "primary")
        self.server_start = action("Start", lambda: self.run("start"), "primary")
        self.server_stop = action("Stop", lambda: self.confirm_operation("stop"), "danger")
        self.server_restart = action("Restart", lambda: self.confirm_operation("restart"))
        group.addLayout(self.row(self.install_btn, self.server_start, self.server_stop, self.server_restart))
        body.addWidget(overview)

        services, list_layout = panel()
        list_layout.addWidget(heading("Docker services", 17))
        list_layout.addWidget(label("State and health come from Docker Compose; an unavailable service is never shown as healthy.", "muted", True))
        self.metric_database = Metric("PostgreSQL", logo="services/postgresql.svg", compact=True)
        list_layout.addWidget(self.metric_database)
        self.service_labels = {}
        for name in SERVICES:
            line = QHBoxLayout()
            line.setSpacing(10)
            line.addWidget(logo_widget(SERVICE_DETAILS[name][2], 24))
            line.addWidget(label(name.capitalize(), "service"))
            line.addStretch()
            value = ServiceStatus()
            value.add_mirror(self.overview_service_labels[name])
            line.addWidget(value)
            list_layout.addLayout(line)
            self.service_labels[name] = value

        install, install_layout = panel()
        install_layout.addWidget(heading("Operation progress", 17))
        install_layout.addWidget(label("Commands execute in the background. This panel displays real CLI output.", "muted", True))
        self.activity_console = QPlainTextEdit()
        self.activity_console.setReadOnly(True)
        self.activity_console.setMinimumHeight(160)
        self.activity_console.setPlaceholderText("Server operations will appear here.")
        install_layout.addWidget(self.activity_console)
        self.server_cards = (services, install)
        self.server_grid = QGridLayout()
        self.server_grid.setSpacing(16)
        body.addLayout(self.server_grid)
        self.arrange_overview()
        body.addStretch()
        return page

    def network_page(self):
        page, body = self.page("School network", "Configure restricted Windows-to-WSL forwarding for the school's private LAN.")
        description, info = panel()
        info.addWidget(heading("LAN access", 17))
        self.network_details = label("Checking network configuration...", "muted", True)
        info.addWidget(self.network_details)
        self.metric_lan = Metric("School network", compact=True)
        info.addWidget(self.metric_lan)
        info.addWidget(label(
            "WEAVE only manages its own TCP 80 firewall rule and forwarding entry. "
            "The host network must be Private or Domain. Test access from a student device.",
            "muted", True))
        body.addWidget(description)

        settings, form = panel()
        form.addWidget(heading("Windows LAN configuration", 17))
        form.addWidget(label("Windows host IPv4 address", "field"))
        self.ip_input = QLineEdit()
        self.ip_input.setPlaceholderText("192.168.1.12")
        form.addWidget(self.ip_input)
        form.addWidget(label("Allowed school client subnet (CIDR)", "field"))
        self.subnet_input = QLineEdit()
        self.subnet_input.setPlaceholderText("192.168.1.0/24")
        form.addWidget(self.subnet_input)
        self.lan_configure = action("Configure LAN", self.configure_lan, "primary")
        self.lan_refresh = action("Refresh forwarding", lambda: self.run("lan", ["--refresh"]))
        self.lan_remove = action("Remove WEAVE rule", self.remove_lan, "danger")
        form.addLayout(self.row(self.lan_configure, self.lan_refresh, self.lan_remove))
        body.addWidget(settings)

        certificate, tls_options = panel()
        tls_options.addWidget(heading("Secure HTTPS access", 17))
        self.https_details = label("Checking certificate configuration...", "muted", True)
        tls_options.addWidget(self.https_details)
        tls_options.addWidget(label(
            "A trusted certificate requires an assigned WEAVE hostname, initial internet "
            "access, and local DNS pointing that hostname to this server. "
            "An exam already running over HTTPS does not need internet.",
            "muted", True
        ))
        self.tls_dry_run = action("Test certificate", lambda: self.run("tls", ["--dry-run"]))
        self.tls_enable = action("Enable HTTPS", self.enable_https, "primary")
        self.tls_renew = action("Renew now", lambda: self.run("tls", ["--renew"]))
        tls_options.addLayout(self.row(self.tls_dry_run, self.tls_enable, self.tls_renew))
        body.addWidget(certificate)
        body.addStretch()
        return page

    def updates_page(self):
        page, body = self.page("Updates", "Manage the CBT server image separately from the installed desktop and CLI.")
        app_box, app = panel()
        app.addWidget(heading("CBT application release", 17))
        self.release_status = label("Reading installed release manifest...", "muted", True)
        app.addWidget(self.release_status)
        self.server_update = action("Update CBT server", self.update_server, "primary")
        app.addLayout(self.row(
            action("Compare installed release", self.refresh),
            self.server_update,
        ))
        app.addWidget(label(
            "An update pulls the pinned image and pauses services for a database snapshot and migrations. "
            "Never run it during an examination. The CLI retains a rollback snapshot.",
            "muted", True))
        body.addWidget(app_box)

        manager_box, manager = panel()
        manager.addWidget(heading("Desktop and CLI manager", 17))
        self.manager_version = label("Checking...", "muted", True)
        manager.addWidget(self.manager_version)
        manager.addWidget(label(
            "The desktop executable cannot safely overwrite itself while running. "
            "Manager updates are channel matched and verified before installation. The CBT server is not restarted.",
            "muted", True))
        manager.addLayout(self.row(
            action("Check manager updates", lambda: self.run("self-update", ["--check"]), "primary"),
            action("Install manager update", lambda: self.run("self-update", ["--yes"])),
            action("View official releases", lambda: self.open_url(RELEASES_URL)),
        ))
        body.addWidget(manager_box)
        body.addStretch()
        return page

    def diagnostics_page(self):
        page, body = self.page("System diagnostics", "Run validated CLI checks before opening an examination.")
        section, checks = panel()
        checks.addWidget(heading("Readiness checks", 17))
        checks.addWidget(label(
            "Diagnostics inspect local Docker, Compose, services, browser routes and owned LAN rules. "
            "They do not establish reachability from student computers.",
            "muted", True))
        checks.addLayout(self.row(
            action("Run full diagnostics", lambda: self.run("doctor"), "primary"),
            action("Get CLI status", lambda: self.run("status")),
            action("Refresh live health", self.refresh),
        ))
        self.diagnostic_log = QPlainTextEdit()
        self.diagnostic_log.setReadOnly(True)
        self.diagnostic_log.setMinimumHeight(280)
        self.diagnostic_log.setPlaceholderText("Run a check to see its complete output.")
        checks.addWidget(self.diagnostic_log)
        body.addWidget(section)
        body.addStretch()
        return page

    def logs_page(self):
        page, body = self.page("Service logs", "Review output from WEAVE CBT and individual Compose services.")
        card, layout = panel()
        layout.addWidget(heading("Logs viewer", 17))
        self.log_service = QComboBox()
        self.log_service.setItemDelegate(QStyledItemDelegate(self.log_service))
        self.log_service.addItem("All services", "")
        for service in SERVICES:
            self.log_service.addItem(service.capitalize(), service)
        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMinimumHeight(365)
        self.log_view.setPlaceholderText("Select a service and click Load logs.")
        layout.addLayout(self.row(
            self.log_service,
            action("Load logs", self.load_logs, "primary"),
            action("Save displayed logs", self.save_logs),
            action("Clear", self.log_view.clear),
        ))
        layout.addWidget(self.log_view)
        layout.addWidget(label("Exported logs may contain diagnostic or confidential data; share only with trusted administrators.", "muted", True))
        body.addWidget(card)
        body.addStretch()
        return page

    def settings_page(self):
        page, body = self.page("Settings", "Desktop preferences and local release details.")
        app_box, settings = panel()
        settings.addWidget(heading("Desktop preferences", 17))
        self.auto_refresh = QCheckBox("Automatically refresh local server state")
        self.auto_refresh.setChecked(self.settings.value("auto_refresh", True, type=bool))
        self.auto_refresh.toggled.connect(self.toggle_refresh)
        settings.addWidget(self.auto_refresh)
        settings.addWidget(label("Health is polled every 20 seconds. The desktop does not modify the CBT database to refresh.", "muted", True))
        body.addWidget(app_box)
        details, info = panel()
        info.addWidget(heading("About WEAVE CBT", 17))
        self.settings_detail = label("", "muted", True)
        info.addWidget(self.settings_detail)
        info.addWidget(label(
            "Manager: PySide6 / CLI\nWindows runtime: WSL2 with Docker\n"
            "Linux runtime: native Docker\nApplication data is kept separate from the desktop installer.",
            "muted", True))
        info.addWidget(action("Official releases", lambda: self.open_url(RELEASES_URL)))
        body.addWidget(details)
        body.addStretch()
        return page

    def navigate(self, index):
        self.pages.setCurrentIndex(index)
        self.page_name.setText(PAGES[index])
        for key, widget in self.nav.items():
            widget.setChecked(key == index)

    def _installed_image(self):
        if not self.desktop.server_installed:
            return ""
        path = Path(self.desktop.installation["data_directory"]) / "runtime.env"
        try:
            for line in path.read_text(encoding="utf-8-sig").splitlines():
                if line.startswith("WEAVE_IMAGE="):
                    return line.partition("=")[2].strip()
        except OSError:
            return ""
        return ""

    def _read_manifest(self):
        if not self.desktop.cli:
            return {}
        path = self.desktop.cli.parent / "assets" / "release-manifest.json"
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def _lan(self):
        if not self.desktop.server_installed:
            return None
        try:
            path = Path(self.desktop.installation["data_directory"]) / "lan.json"
            obj = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(obj, dict) and obj.get("listen_address") and obj.get("client_subnet"):
                return obj
        except (OSError, ValueError, KeyError):
            pass
        return None

    def refresh(self):
        if self.busy:
            return
        self.desktop = discover(packaged=ROOT)
        self.manifest = self._read_manifest()
        present = self.desktop.server_installed
        manager = self.desktop.manager_installed

        self.channel.setText(str(self.manifest.get("channel", "Unknown channel")).upper())
        self.manager_version.setText(
            "Installed manager: " + str(self.manifest.get("manager_version", "Unknown"))
            + "   |   Channel: " + str(self.manifest.get("channel", "Unknown"))
        )
        self.settings_detail.setText(
            "Manager version: " + str(self.manifest.get("manager_version", "Unknown"))
            + "\nRelease channel: " + str(self.manifest.get("channel", "Unknown"))
            + "\nCLI executable: " + str(self.desktop.cli or "Not installed")
            + "\nServer registered: " + ("Yes" if present else "No")
        )
        self.install_detail.setText(
            ("Server registered. Version: " + str(self.desktop.installation.get("installed_version", "Unknown"))
             + "\nData directory: " + str(self.desktop.installation.get("data_directory", "Unknown"))
             if present else "No completed CBT server installation was found. "
             "If reinstalling, pre-existing runtime.env may need to be reused explicitly.")
            + (("\nIssue: " + self.desktop.problem) if self.desktop.problem else "")
        )
        self.summary.setText(
            "Server is installed; checking actual container status..."
            if present else "WEAVE CBT is not installed on this computer. Start with Server Management."
        )
        self.metric_server.set_value(
            "Checking" if present else "Not installed", "Awaiting live services" if present else "No server registration"
        )
        self._enable_actions()

        lan = self._lan()
        is_windows = sys.platform == "win32"
        if is_windows:
            self.metric_lan.set_value("Configured" if lan else "Not configured", "Not verified from student device" if lan else "Windows forwarding not configured", "warning" if lan else "muted")
            self.network_details.setText(
                f"Saved listener: {lan['listen_address']}:80\nAllowed subnet: {lan['client_subnet']}\n"
                "Saved configuration does not prove current reachability."
                if lan else "No WEAVE-managed LAN mapping recorded."
            )
            if lan:
                self.ip_input.setText(lan["listen_address"])
                self.subnet_input.setText(lan["client_subnet"])
        else:
            self.metric_lan.set_value("Native", "No Windows NAT configuration required")
            self.network_details.setText("Native Linux Docker deployment. Windows WSL forwarding controls do not apply.")
        self.lan_configure.setEnabled(is_windows and present and not self.busy)
        self.lan_refresh.setEnabled(is_windows and present and bool(lan) and not self.busy)
        self.lan_remove.setEnabled(is_windows and present and bool(lan) and not self.busy)
        tls_marker = (
            Path(self.desktop.installation["data_directory"]) / "tls.enabled"
            if present else None
        )
        tls_enabled = bool(tls_marker and tls_marker.is_file())
        self.https_details.setText(
            "Certificate activation recorded. Verify HTTPS from a school device; "
            "automatic renewal requires internet before expiry."
            if tls_enabled else
            "No trusted certificate has been activated. Pair the server and "
            "configure school LAN DNS before enabling HTTPS."
        )
        self.tls_dry_run.setEnabled(present and manager and not self.busy)
        self.tls_enable.setEnabled(present and manager and not self.busy)
        self.tls_renew.setEnabled(present and manager and tls_enabled and not self.busy)

        existing = self._installed_image()
        desired = str(self.manifest.get("cbt_image", ""))
        valid_release = (desired.startswith("ghcr.io/") and "@sha256:" in desired)
        match = bool(existing and desired and existing == desired)
        self.release_status.setText(
            "Current server image:\n" + (existing or "Unknown")
            + "\n\nManager's pinned image:\n" + (desired or "Unknown")
            + "\n\n" + (
                "Installed server matches the manager release." if match else
                "A different pinned image is installed. An update may be available."
                if existing and valid_release else
                "Unable to compare releases until both the server and manager are installed."
            )
        )
        self.server_update.setEnabled(present and manager and valid_release and bool(existing) and not match and not self.busy)
        if not present:
            self.status = None
            self.connection.setText("NOT INSTALLED")
            self.metric_docker.set_value("Unknown", "No CBT server registered")
            self.metric_database.set_value("Unknown", "No health information")
            self._set_services([])
        elif manager and self.probe.state() == QProcess.NotRunning:
            self.probe.setProgram(str(self.desktop.cli))
            self.probe.setArguments(["status", "--json"])
            self.probe.start()
        else:
            self.connection.setText("STATUS UNAVAILABLE")

    def _set_services(self, services):
        by_name = {}
        for item in services:
            if isinstance(item, dict):
                by_name.setdefault(str(item.get("name", "")), []).append(item)
        for service, widget in self.service_labels.items():
            replicas = by_name.get(service, [])
            if not replicas:
                widget.setText("Not reported")
                continue
            active = sum(row.get("state") == "running" for row in replicas)
            if service == "bootstrap" and all(row.get("state") == "exited" for row in replicas):
                widget.setText("Completed")
            elif len(replicas) > 1:
                widget.setText(f"{active}/{len(replicas)} running")
            else:
                state = replicas[0].get("state", "unknown")
                health = replicas[0].get("health", "unknown")
                widget.setText(state.title() + (f" / {health}" if health not in ("", "unknown") else ""))

    def probe_finished(self, code, _status):
        raw = bytes(self.probe.readAllStandardOutput()).decode("utf-8", "replace")
        try:
            data = json.loads(raw)
            if code != 0 or not isinstance(data, dict) or data.get("schema") != 1:
                raise ValueError("Unrecognized status response")
        except (ValueError, TypeError):
            data = {"docker": False, "compose": False, "running": False,
                    "services": [], "error": "The CLI did not return valid structured status."}
        self.status = data
        running = bool(data.get("running"))
        engine = bool(data.get("docker"))
        postgres = next((item for item in data.get("services", []) if item.get("name") == "postgres"), None)
        database_running = bool(postgres and postgres.get("state") == "running")
        database_healthy = database_running and postgres.get("health") == "healthy"
        self.metric_server.set_value(
            "Running" if running else "Attention required",
            "Compose services reported running" if running else str(data.get("error") or "Check status and diagnostics"),
            "ok" if running else "warning"
        )
        self.metric_docker.set_value(
            "Running" if engine else "Unavailable",
            "Compose available" if data.get("compose") else "Compose not confirmed",
            "ok" if engine and data.get("compose") else "warning"
        )
        self.metric_database.set_value(
            "Healthy" if database_healthy else "Running" if database_running else "Unavailable",
            "Health check passed" if database_healthy else
            "Container up; health unverified" if database_running else "No running PostgreSQL container",
            "ok" if database_healthy else "warning"
        )
        self.connection.setText("RUNNING" if running else "NEEDS ATTENTION")
        self.summary.setText(
            "Docker Compose reports the CBT services running. Verify the web routes and school LAN before an examination."
            if running else str(data.get("error") or "The CBT server needs attention. Open Diagnostics.")
        )
        self._set_services(data.get("services", []))
        self._enable_actions()

    def probe_error(self, _error):
        if self.probe.state() == QProcess.NotRunning and self.desktop.server_installed:
            self.status = None
            self.connection.setText("STATUS UNAVAILABLE")
            self.metric_server.set_value("Unknown", "Unable to start CLI status check")
            self.metric_docker.set_value("Unknown", "No live status")
            self.metric_database.set_value("Unknown", "No live status")
            self._set_services([])

    def _enable_actions(self):
        present = self.desktop.server_installed
        ready = self.desktop.manager_installed and not self.busy
        for widget in (self.install_btn,):
            widget.setEnabled(ready and not present and not self.desktop.problem)
        self.install_shortcut.setVisible(not present)
        self.arrange_overview()
        self.start_btn.setEnabled(ready and present)
        self.stop_btn.setEnabled(ready and present)
        self.restart_btn.setEnabled(ready and present)
        for widget in (self.server_start, self.server_stop, self.server_restart):
            widget.setEnabled(ready and present)

    def _message(self, title_text, body, *, error=False, details=""):
        dialog = QMessageBox(self)
        dialog.setWindowTitle(title_text)
        dialog.setText(body)
        dialog.setIcon(QMessageBox.Warning if error else QMessageBox.Information)
        dialog.setStandardButtons(QMessageBox.Ok)
        if details:
            dialog.setDetailedText(details[-12000:])
        dialog.setMinimumWidth(440)
        dialog.exec()

    def confirm(self, title_text, text):
        dialog = QMessageBox(self)
        dialog.setWindowTitle(title_text)
        dialog.setText(text)
        dialog.setIcon(QMessageBox.Warning)
        dialog.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
        dialog.setDefaultButton(QMessageBox.No)
        return dialog.exec() == QMessageBox.Yes

    def confirm_operation(self, command):
        if self.confirm(
            "Confirm " + command,
            f"{command.capitalize()} the CBT server? This may interrupt an active examination. Continue?"
        ):
            self.run(command)

    def prepare_install(self):
        """Offer safe reuse of school configuration preserved by uninstall."""
        previous = state_path().parent / "runtime.env"
        if previous.is_file():
            if not self.confirm(
                "Reuse preserved CBT settings?",
                "A previous CBT runtime configuration is present.\n\n"
                "Reuse its database credentials, existing Docker volumes and "
                "previously pinned application image? This avoids overwriting "
                "school data. You may update the image through the Updates page "
                "after the server is running.\n\n"
                "The CLI will reject an incompatible release channel or API.",
            ):
                return
            self.run("install", ["--env-file", str(previous)])
        else:
            self.run("install")

    def update_server(self):
        if not self.server_update.isEnabled():
            self._message("No update required", "The installed server already matches this manager's pinned image, or release metadata is unavailable.")
            return
        if self.confirm(
            "Update CBT server",
            "Confirm that NO EXAMINATION IS RUNNING.\n\n"
            "This update will pull the release image, pause CBT services, snapshot PostgreSQL, "
            "then apply database migrations. Sufficient disk space and internet access are required.\n\n"
            "Do you want to proceed?"
        ):
            self.run("update", ["--yes"])

    def configure_lan(self):
        ip = self.ip_input.text().strip()
        subnet = self.subnet_input.text().strip()
        try:
            host = ipaddress.IPv4Address(ip)
            network = ipaddress.IPv4Network(subnet, strict=True)
            ranges = [ipaddress.IPv4Network(x) for x in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16")]
            if not any(host in parent for parent in ranges) or not any(network.subnet_of(parent) for parent in ranges):
                raise ValueError("Choose an RFC1918 private host address and subnet.")
            if network.prefixlen < 24 or host not in network:
                raise ValueError("The school subnet must be /24 or narrower and include the host IP.")
        except ValueError as exc:
            self._message("Invalid LAN scope", str(exc), error=True)
            return
        if self.confirm("Configure school LAN", f"Allow school subnet {subnet} to reach {ip}:80 via the WEAVE-managed Windows firewall rule?"):
            self.run("lan", ["--listen-address", ip, "--client-subnet", subnet])

    def enable_https(self):
        if self.confirm(
            "Enable school HTTPS",
            "Request a trusted Let's Encrypt certificate for this paired CBT server? "
            "The school must have internet for issuance, and local DNS must resolve "
            "the WEAVE hostname to this server before students use HTTPS.",
        ):
            self.run("tls")

    def remove_lan(self):
        if self.confirm("Remove WEAVE LAN forwarding", "Remove only the LAN forwarding and firewall rule owned by WEAVE CBT? This interrupts student LAN access."):
            self.run("lan", ["--remove"])

    def load_logs(self):
        service = self.log_service.currentData()
        self.log_view.clear()
        self.run("logs", [service] if service else [])

    def save_logs(self):
        if not self.log_view.toPlainText().strip():
            self._message("No logs", "Load logs before exporting.")
            return
        path, _ = QFileDialog.getSaveFileName(self, "Export displayed logs", "weave-cbt-logs.txt", "Text files (*.txt)")
        if path:
            try:
                Path(path).write_text(self.log_view.toPlainText(), encoding="utf-8")
            except OSError as exc:
                self._message("Export failed", str(exc), error=True)

    def copy_lan_url(self):
        lan = self._lan()
        if lan:
            QApplication.clipboard().setText(f"http://{lan['listen_address']}/student")
            self._message("Address copied", "LAN student address copied. Verify it from a school computer.")
        else:
            self._message("LAN not configured", "There is no saved WEAVE-managed LAN address. Configure it on the Network page.")

    def open_url(self, url):
        if not QDesktopServices.openUrl(QUrl(url)):
            self._message("Cannot open browser", "The system could not open the requested URL.", error=True)

    def toggle_refresh(self, enabled):
        self.settings.setValue("auto_refresh", enabled)
        if enabled and not self.busy:
            self.poll.start(20000)
            self.refresh()
        else:
            self.poll.stop()

    def run(self, command, arguments=None):
        args = list(arguments or [])
        if command not in MUTATIONS | {"status", "doctor", "logs", "release", "self-update"} or self.busy:
            return
        # Restrict the user-controlled GUI to known CLI arguments. All LAN
        # values are independently validated again by the CLI.
        if command == "lan" and args not in (["--refresh"], ["--remove"]):
            if len(args) != 4 or args[:1] != ["--listen-address"] or args[2] != "--client-subnet":
                return
        if command == "update" and args != ["--yes"]:
            return
        if command == "self-update" and args not in (["--yes"], ["--check"]):
            return
        if command == "tls" and args not in ([], ["--dry-run"], ["--renew"]):
            return
        if command == "install" and args and args != ["--env-file", str(state_path().parent / "runtime.env")]:
            return
        self.desktop = discover(packaged=ROOT)
        if not self.desktop.cli:
            self._message("CLI unavailable", "The WEAVE management CLI is missing or failed validation. Repair the desktop package.", error=True)
            return
        if command == "install" and self.desktop.server_installed:
            self._message("Already installed", "This CBT server is already registered. An installation will not overwrite examination data.")
            return
        privileged = command in MUTATIONS or (command == "self-update" and args == ["--yes"]) or (sys.platform.startswith("linux") and command in {"doctor", "status", "logs"})
        if privileged and not is_admin() and sys.platform == "win32":
            if self.confirm("Administrator permission", "This operation requires Administrator privileges. Relaunch the manager elevated?"):
                if elevate_gui(command, args):
                    QApplication.quit()
                else:
                    self._message("Elevation declined", "Windows did not start the elevated manager.", error=True)
            return
        self.busy = True
        self.last_command = command
        self.last_error = ""
        self.output_tail = ""
        self._enable_actions()
        self.server_update.setEnabled(False)
        self.lan_configure.setEnabled(False)
        self.lan_refresh.setEnabled(False)
        self.lan_remove.setEnabled(False)
        self.tls_dry_run.setEnabled(False)
        self.tls_enable.setEnabled(False)
        self.tls_renew.setEnabled(False)
        self.poll.stop()
        self.activity_console.appendPlainText(f"\n> weave {command} {' '.join(args)}")
        self.log_view.appendPlainText(f"\n> weave {command} {' '.join(args)}")
        if command == "doctor":
            self.diagnostic_log.clear()
        if privileged and not is_admin() and sys.platform.startswith("linux"):
            import shutil
            pkexec = shutil.which("pkexec")
            if not pkexec:
                self.busy = False
                self._message("Authorization unavailable", "A graphical Polkit authentication agent is required.", error=True)
                self.refresh()
                return
            self.process.setProgram(pkexec)
            self.process.setArguments([str(self.desktop.cli), command, *args])
        else:
            self.process.setProgram(str(self.desktop.cli))
            self.process.setArguments([command, *args])
        self.process.start()
        if not self.process.waitForStarted(2500):
            self.finished(1, QProcess.CrashExit)

    def consume(self):
        data = bytes(self.process.readAllStandardOutput()).decode("utf-8", "replace")
        if not data:
            return
        self.output_tail = (self.output_tail + data)[-12000:]
        for field in (self.activity_console, self.log_view):
            field.appendPlainText(data.rstrip("\r\n"))
            if field.document().blockCount() > 1100:
                field.setPlainText("\n".join(field.toPlainText().splitlines()[-700:]))
        if self.last_command == "doctor":
            self.diagnostic_log.appendPlainText(data.rstrip("\r\n"))
        if self.last_command == "logs":
            self.navigate(5)

    def process_error(self, _error):
        if self.busy:
            self.last_error = self.process.errorString()

    def finished(self, code, _status):
        if not self.busy:
            return
        self.consume()
        self.busy = False
        name = self.last_command
        result = "Succeeded" if code == 0 else "Failed"
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.operation_records.insert(0, f"{timestamp}  {name}  -  {result}")
        self.operation_records = self.operation_records[:6]
        self.last_activity.setText("\n".join(self.operation_records))
        self.activity_console.appendPlainText(f"Exit code: {code}")
        if self.auto_refresh.isChecked():
            self.poll.start(20000)
        self.refresh()
        if code == 10 and name == "install":
            self._message("Restart required", "Windows must restart to complete WSL setup. Save your work, reboot Windows and then resume installation.")
        elif code == 0:
            if name in {"install", "update", "lan"}:
                self._message("Operation successful", f"WEAVE {name} completed. Check Diagnostics and test the CBT endpoints before an examination.")
        elif name == "self-update" and code == 0:
            self._message("Manager update", "The official manager installer has been launched, or this release is already current. Complete the installer if prompted.")
        else:
            self._message(
                "Operation failed",
                f"WEAVE {name} failed (exit code {code}).\n\n"
                "The detailed CLI error is available below and in the Logs page.",
                error=True,
                details=self.output_tail or self.last_error,
            )

    def closeEvent(self, event):
        if self.busy:
            self._message("Operation in progress", "Wait for the active CLI operation to finish before closing the manager.", error=True)
            event.ignore()
            return
        super().closeEvent(event)


def main():
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("WEAVE.CBT.Desktop.Manager")
        except (OSError, AttributeError):
            pass
    app = QApplication(sys.argv)
    app.setApplicationName("WEAVE CBT Desktop Manager")
    app.setStyle("Fusion")
    app.setPalette(desktop_palette())
    app.setFont(QFont("Segoe UI", 10))
    brand = resource("weave-logo-blue.png")
    if brand.is_file():
        app.setWindowIcon(QIcon(str(brand)))
    ui = ControlCenter()
    if "--smoke-test" in sys.argv:
        wizard = SetupWizard(ui, resource("theme.qss").parent)
        if len(wizard.pageIds()) != 3 or ui.pages.count() != len(PAGES):
            raise RuntimeError("WEAVE GUI pages or setup wizard are incomplete")
        wizard.close()
        print("WEAVE desktop control center and setup wizard ready", flush=True)
        ui.close()
        return
    ui.show()
    if "--auto-command" not in sys.argv:
        if not ui.desktop.server_installed and not ui.settings.value("onboarding_complete", False, type=bool):
            wizard = SetupWizard(ui, resource("theme.qss").parent)
            if wizard.exec() == SetupWizard.Accepted:
                ui.settings.setValue("onboarding_complete", True)
                ui.navigate(1)
    else:
        position = sys.argv.index("--auto-command") + 1
        if position < len(sys.argv):
            command = sys.argv[position]
            args = sys.argv[position + 1:]
            if command in {"install", "start", "stop", "restart", "lan", "update", "tls", "self-update"}:
                QTimer.singleShot(0, lambda: ui.run(command, args))
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
