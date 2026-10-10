"""WEAVE CBT Desktop Control Center.

All privileged mutations remain in the verified CLI. The UI reflects real
status from --json and never equates installation with service health.
"""
from __future__ import annotations

import ipaddress
import json
import os
import sys
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt, QProcess, QSettings, QTimer, QUrl, QSize
from PySide6.QtGui import QDesktopServices, QFont, QIcon, QPixmap
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QFileDialog, QFrame,
    QGridLayout, QHBoxLayout, QLabel, QLineEdit, QMainWindow,
    QMessageBox, QPlainTextEdit, QPushButton, QScrollArea,
    QStackedWidget, QVBoxLayout, QWidget,
)

from bridge import discover, elevate_gui, is_admin, state_path
from setup_wizard import SetupWizard

ROOT = Path(__file__).resolve().parent
RELEASES_URL = "https://github.com/weavecloudspace-repo/WEAVE-CBT-PRODUCTION-REPOSITORY/releases"
PAGES = ["Overview", "Server", "Network", "Updates", "Diagnostics", "Logs", "Settings"]
MUTATIONS = {"install", "start", "stop", "restart", "update", "lan", "tls"}
SERVICES = ("api", "worker", "postgres", "redis", "nginx", "bootstrap")


def resource(name: str) -> Path:
    paths = (ROOT / "resources" / name, Path(sys.argv[0]).resolve().parent / "resources" / name)
    return next((path for path in paths if path.is_file()), paths[0])


def label(text="", kind="normal", wrap=False):
    widget = QLabel(str(text))
    widget.setProperty("kind", kind)
    widget.setWordWrap(wrap)
    return widget


def heading(text, size=20):
    item = QLabel(text)
    item.setObjectName("heading")
    item.setFont(QFont("Segoe UI", size, QFont.DemiBold))
    return item


def action(text, handler, style="secondary"):
    widget = QPushButton(text)
    widget.setProperty("kind", style)
    widget.setCursor(Qt.PointingHandCursor)
    widget.setMinimumHeight(39)
    widget.clicked.connect(handler)
    return widget


def panel(kind="card"):
    frame = QFrame()
    frame.setProperty("surface", kind)
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(22, 20, 22, 20)
    layout.setSpacing(12)
    return frame, layout


def line_button(text, handler, kind="secondary"):
    return action(text, handler, kind)


class Metric(QFrame):
    def __init__(self, title_text, value="Checking", hint=""):
        super().__init__()
        self.setProperty("surface", "metric")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(6)
        layout.addWidget(label(title_text.upper(), "eyebrow"))
        self.value = heading(value, 17)
        self.value.setProperty("status", "muted")
        layout.addWidget(self.value)
        self.hint = label(hint, "muted", True)
        layout.addWidget(self.hint)

    def set_value(self, text, hint="", state="muted"):
        self.value.setText(text)
        self.value.setProperty("status", state)
        self.value.style().unpolish(self.value)
        self.value.style().polish(self.value)
        self.hint.setText(hint)


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
        side.setContentsMargins(17, 30, 17, 22)
        side.setSpacing(8)

        brand = QHBoxLayout()
        image = QLabel()
        pix = QPixmap(str(resource("weave-logo-blue.png")))
        if not pix.isNull():
            image.setPixmap(pix.scaled(QSize(48, 38), Qt.KeepAspectRatio, Qt.SmoothTransformation))
        brand.addWidget(image)
        brand.addWidget(heading("WEAVE CBT", 15))
        brand.addStretch()
        side.addLayout(brand)
        side.addWidget(label("SERVER CONTROL CENTER", "eyebrow"))
        side.addSpacing(26)
        self.nav = {}
        for i, page_name in enumerate(PAGES):
            control = action(page_name, lambda checked=False, index=i: self.navigate(index), "nav")
            control.setCheckable(True)
            self.nav[i] = control
            side.addWidget(control)
        side.addStretch()
        side.addWidget(label("LOCAL EXAM INFRASTRUCTURE", "eyebrow", True))
        shell.addWidget(sidebar)

        right = QWidget()
        body = QVBoxLayout(right)
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)
        header = QFrame()
        header.setObjectName("topbar")
        bar = QHBoxLayout(header)
        bar.setContentsMargins(30, 16, 30, 16)
        self.page_name = heading("Overview", 19)
        bar.addWidget(self.page_name)
        bar.addStretch()
        self.channel = label("Checking release", "chip")
        self.connection = label("Checking server", "chip")
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
            self.setStyleSheet(css.read_text(encoding="utf-8"))

    def page(self, name, description):
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(34, 28, 34, 35)
        layout.setSpacing(17)
        layout.addWidget(heading(name, 24))
        layout.addWidget(label(description, "muted", True))
        layout.addSpacing(6)
        return content, layout

    def row(self, *widgets):
        row = QHBoxLayout()
        row.setSpacing(10)
        for widget in widgets:
            row.addWidget(widget)
        return row

    def overview_page(self):
        page, body = self.page("Overview", "One place to operate and monitor this computer's examination infrastructure.")

        hero, box = panel("hero")
        box.addWidget(label("WEAVE CBT  /  SERVER READINESS", "eyebrow"))
        box.addWidget(heading("Your examination server, at a glance", 21))
        self.summary = label("Checking the local installation and services...", "muted", True)
        box.addWidget(self.summary)
        body.addWidget(hero)

        metrics = QGridLayout()
        metrics.setHorizontalSpacing(12)
        metrics.setVerticalSpacing(12)
        self.metric_server = Metric("CBT server")
        self.metric_docker = Metric("Docker runtime")
        self.metric_database = Metric("PostgreSQL")
        self.metric_lan = Metric("School network")
        for i, widget in enumerate((self.metric_server, self.metric_docker, self.metric_database, self.metric_lan)):
            metrics.addWidget(widget, 0, i)
        body.addLayout(metrics)

        shortcuts, quick = panel()
        quick.addWidget(heading("Quick actions", 17))
        quick.addWidget(label("Only the commands available for this installation are enabled.", "muted"))
        self.start_btn = action("Start server", lambda: self.run("start"), "primary")
        self.stop_btn = action("Stop server", lambda: self.confirm_operation("stop"), "danger")
        self.restart_btn = action("Restart", lambda: self.confirm_operation("restart"))
        self.install_shortcut = action("Install server", lambda: self.navigate(1), "primary")
        first = QGridLayout()
        first.setSpacing(10)
        for index, control in enumerate((self.install_shortcut, self.start_btn, self.stop_btn, self.restart_btn)):
            first.addWidget(control, index // 2, index % 2)
        quick.addLayout(first)
        second = QGridLayout()
        second.setSpacing(10)
        for index, control in enumerate((
            action("Check updates", lambda: self.navigate(3)),
            action("Run diagnostics", lambda: self.run("doctor")),
            action("Network setup", lambda: self.navigate(2)),
            action("View logs", lambda: self.navigate(5)),
        )):
            second.addWidget(control, index // 2, index % 2)
        quick.addLayout(second)
        body.addWidget(shortcuts)

        access, links = panel()
        links.addWidget(heading("Open the examination portal", 17))
        links.addWidget(label("Local access is on this computer. LAN access must be tested from another device.", "muted", True))
        links.addLayout(self.row(
            action("Open staff portal", lambda: self.open_url("http://127.0.0.1/staff")),
            action("Open student portal", lambda: self.open_url("http://127.0.0.1/student")),
            action("Copy LAN address", self.copy_lan_url),
        ))
        body.addWidget(access)

        recent, activity = panel()
        activity.addWidget(heading("Recent manager activity", 17))
        self.last_activity = label("No actions in this session.", "muted", True)
        activity.addWidget(self.last_activity)
        body.addWidget(recent)
        body.addStretch()
        return page

    def server_page(self):
        page, body = self.page("Server management", "Lifecycle controls and live service observations, sourced from the WEAVE CLI.")
        overview, group = panel()
        group.addWidget(heading("Server installation", 17))
        self.install_detail = label("Checking local installation state...", "muted", True)
        group.addWidget(self.install_detail)
        self.install_btn = action("Install WEAVE CBT", self.prepare_install, "primary")
        self.server_start = action("Start", lambda: self.run("start"), "primary")
        self.server_stop = action("Stop", lambda: self.confirm_operation("stop"), "danger")
        self.server_restart = action("Restart", lambda: self.confirm_operation("restart"))
        group.addLayout(self.row(self.install_btn, self.server_start, self.server_stop, self.server_restart))
        body.addWidget(overview)

        services, list_layout = panel()
        list_layout.addWidget(heading("Docker services", 17))
        list_layout.addWidget(label("State and health come from Docker Compose; an unavailable service is never shown as healthy.", "muted", True))
        self.service_labels = {}
        for name in SERVICES:
            line = QHBoxLayout()
            line.addWidget(label(name.capitalize(), "service"))
            line.addStretch()
            value = label("Unknown", "chip")
            line.addWidget(value)
            list_layout.addLayout(line)
            self.service_labels[name] = value
        body.addWidget(services)

        install, install_layout = panel()
        install_layout.addWidget(heading("Operation progress", 17))
        install_layout.addWidget(label("Commands execute in the background. This panel displays real CLI output.", "muted"))
        self.activity_console = QPlainTextEdit()
        self.activity_console.setReadOnly(True)
        self.activity_console.setMinimumHeight(160)
        self.activity_console.setPlaceholderText("Server operations will appear here.")
        install_layout.addWidget(self.activity_console)
        body.addWidget(install)
        body.addStretch()
        return page

    def network_page(self):
        page, body = self.page("School network", "Configure restricted Windows-to-WSL forwarding for the school's private LAN.")
        description, info = panel()
        info.addWidget(heading("LAN access", 17))
        self.network_details = label("Checking network configuration...", "muted", True)
        info.addWidget(self.network_details)
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
