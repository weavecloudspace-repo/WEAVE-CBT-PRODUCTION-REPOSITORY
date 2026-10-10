"""WEAVE CBT Desktop Manager. Qt Widgets intentionally keep memory and CPU overhead low."""
from __future__ import annotations

import os
import sys
from pathlib import Path

from PySide6.QtCore import Qt, QProcess, QTimer, QSize
from PySide6.QtGui import QColor, QFont, QIcon, QPixmap
from PySide6.QtWidgets import (
    QApplication, QFrame, QHBoxLayout, QLabel, QMainWindow, QMessageBox,
    QPushButton, QPlainTextEdit, QProgressBar, QScrollArea,
    QStackedWidget, QVBoxLayout, QWidget
)

from bridge import discover, elevate_gui, is_admin

ROOT = Path(__file__).resolve().parent
BLUE = "#1d4ed8"
BG = "#f8fafc"
DARK = "#0f172a"
DANGEROUS = {"stop", "restart"}
OPERATIONS = {"install", "start", "stop", "restart", "status", "doctor", "release", "lan_refresh"}


def resource(name: str) -> Path:
    """Locate installed data files in a source checkout or Nuitka standalone bundle."""
    locations = [ROOT / "resources" / name, Path(sys.argv[0]).resolve().parent / "resources" / name]
    return next((p for p in locations if p.is_file()), locations[0])


def button(text: str, callback, kind: str = "outline") -> QPushButton:
    widget = QPushButton(text)
    widget.setProperty("kind", kind)
    widget.setCursor(Qt.PointingHandCursor)
    widget.setMinimumHeight(42)
    widget.clicked.connect(callback)
    return widget


def title(text: str, size: int = 22, color: str = DARK) -> QLabel:
    widget = QLabel(text)
    f = QFont("Segoe UI", size, QFont.Bold)
    widget.setFont(f)
    widget.setStyleSheet(f"color: {color}; background: transparent;")
    return widget


class Desktop(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("WEAVE CBT Desktop Manager")
        self.resize(1030, 690)
        self.setMinimumSize(820, 560)
        logo = resource("weave-logo-blue.png")
        if logo.is_file():
            self.setWindowIcon(QIcon(str(logo)))
        self.process = QProcess(self)
        self.process.setProcessChannelMode(QProcess.MergedChannels)
        self.process.readyReadStandardOutput.connect(self.consume)
        self.process.finished.connect(self.finished)
        self.process.errorOccurred.connect(self.process_error)
        self.busy = False
        self.last_command = ""
        self.line_tail = ""
        self.desktop = discover(packaged=ROOT)
        self.setup_ui()
        self.refresh()
        self.poll = QTimer(self)
        self.poll.timeout.connect(self.refresh)
        self.poll.start(10000)

    def setup_ui(self):
        shell = QWidget()
        shell.setObjectName("shell")
        self.setCentralWidget(shell)
        outer = QHBoxLayout(shell)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(226)
        navigation = QVBoxLayout(sidebar)
        navigation.setContentsMargins(18, 30, 18, 20)
        navigation.setSpacing(8)
        brand = QHBoxLayout()
        icon = QLabel()
        pix = QPixmap(str(resource("weave-logo-blue.png")))
        if not pix.isNull():
            icon.setPixmap(pix.scaled(QSize(48, 34), Qt.KeepAspectRatio, Qt.SmoothTransformation))
        brand.addWidget(icon)
        brand.addWidget(title("WEAVE CBT", 15))
        navigation.addLayout(brand)
        subtitle = QLabel("DESKTOP MANAGER")
        subtitle.setObjectName("eyebrow")
        navigation.addWidget(subtitle)
        navigation.addSpacing(26)
        self.nav = {}
        for label, index in [("Overview", 0), ("Installation", 1), ("Diagnostics & logs", 2), ("About", 3)]:
            item = button(label, lambda checked=False, page=index: self.navigate(page), "nav")
            item.setObjectName("navButton")
            item.setCheckable(True)
            self.nav[index] = item
            navigation.addWidget(item)
        navigation.addStretch()
        navigation.addWidget(QLabel("WEAVE CBT  •  Local Server"))
        outer.addWidget(sidebar)

        self.pages = QStackedWidget()
        self.pages.addWidget(self.overview_page())
        self.pages.addWidget(self.install_page())
        self.pages.addWidget(self.logs_page())
        self.pages.addWidget(self.about_page())
        outer.addWidget(self.pages, 1)
        self.navigate(0)
        css = resource("theme.qss")
        if css.is_file():
            self.setStyleSheet(css.read_text(encoding="utf-8"))

    def page(self, heading: str, sub: str) -> tuple[QWidget, QVBoxLayout]:
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(42, 38, 42, 38)
        layout.setSpacing(16)
        layout.addWidget(title(heading))
        explanation = QLabel(sub)
        explanation.setWordWrap(True)
        explanation.setObjectName("subtitle")
        layout.addWidget(explanation)
        layout.addSpacing(12)
        return container, layout

    def card(self) -> tuple[QFrame, QVBoxLayout]:
        frame = QFrame()
        frame.setObjectName("card")
        lay = QVBoxLayout(frame)
        lay.setContentsMargins(24, 22, 24, 22)
        lay.setSpacing(14)
        return frame, lay

    def overview_page(self) -> QWidget:
        page, lay = self.page("Your CBT server", "Manage your school's computer-based testing server in one place.")
        box, inner = self.card()
        header = QHBoxLayout()
        header.addWidget(title("System overview", 17))
        header.addStretch()
        self.status_tag = QLabel("Checking...")
        self.status_tag.setObjectName("statusTag")
        header.addWidget(self.status_tag)
        inner.addLayout(header)
        self.server_description = QLabel("Checking local installation...")
        self.server_description.setWordWrap(True)
        inner.addWidget(self.server_description)
        self.version = QLabel("")
        self.version.setObjectName("subtitle")
        inner.addWidget(self.version)
        lay.addWidget(box)

        action, controls = self.card()
        controls.addWidget(title("Quick actions", 16))
        row = QHBoxLayout()
        self.install_action = button("Install WEAVE CBT", lambda: self.navigate(1), "primary")
        self.start_action = button("Start server", lambda: self.run("start"), "primary")
        self.stop_action = button("Stop server", lambda: self.confirm_run("stop"), "danger")
        self.restart_action = button("Restart", lambda: self.confirm_run("restart"))
        for obj in [self.install_action, self.start_action, self.stop_action, self.restart_action]:
            row.addWidget(obj)
        controls.addLayout(row)
        lay.addWidget(action)
        misc, util = self.card()
        util.addWidget(title("Server access", 16))
        util.addWidget(QLabel("Local: http://localhost/staff  ·  http://localhost/student"))
        caution = QLabel("LAN access must be verified from a separate student computer. Local health does not prove network reachability.")
        caution.setWordWrap(True)
        caution.setObjectName("subtitle")
        util.addWidget(caution)
        self.diagnostics = button("Run system diagnostics", lambda: self.run("doctor"))
        util.addWidget(self.diagnostics)
        lay.addWidget(misc)
        lay.addStretch()
        return page

    def install_page(self) -> QWidget:
        page, lay = self.page("Install WEAVE CBT", "Set up the local examination server using the verified CLI manager.")
        box, inner = self.card()
        inner.addWidget(title("Ready to get started", 17))
        self.preflight = QLabel("Checking installation prerequisites and existing manager...")
        self.preflight.setWordWrap(True)
        inner.addWidget(self.preflight)
        self.install_progress = QProgressBar()
        self.install_progress.setRange(0, 0)
        self.install_progress.setVisible(False)
        inner.addWidget(self.install_progress)
        self.install_btn = button("Install WEAVE CBT", lambda: self.run("install"), "primary")
        inner.addWidget(self.install_btn)
        lay.addWidget(box)
        logcard, logs = self.card()
        logs.addWidget(title("Installation activity", 15))
        self.install_output = QPlainTextEdit()
        self.install_output.setReadOnly(True)
        self.install_output.setPlaceholderText("Installation steps will appear here...")
        self.install_output.setMinimumHeight(190)
        logs.addWidget(self.install_output)
        lay.addWidget(logcard, 1)
        return page

    def logs_page(self) -> QWidget:
        page, lay = self.page("Diagnostics & logs", "Live output from the local management CLI.")
        box, inner = self.card()
        self.log_widget = QPlainTextEdit()
        self.log_widget.setReadOnly(True)
        self.log_widget.setPlaceholderText("Click a diagnostic action to inspect WEAVE CBT.")
        self.log_widget.setMinimumHeight(320)
        inner.addWidget(self.log_widget)
        row = QHBoxLayout()
        row.addWidget(button("Check status", lambda: self.run("status"), "primary"))
        row.addWidget(button("Diagnose", lambda: self.run("doctor")))
        row.addWidget(button("Clear display", self.log_widget.clear))
        inner.addLayout(row)
        lay.addWidget(box, 1)
        return page

    def about_page(self) -> QWidget:
        page, lay = self.page("About", "WEAVE CBT Desktop Manager")
        box, inner = self.card()
        inner.addWidget(title("WEAVE CBT", 19))
        inner.addWidget(QLabel("Cross-platform local examination server management."))
        inner.addWidget(QLabel("The CLI performs all lifecycle operations. The desktop app provides a visual interface."))
        inner.addWidget(QLabel("Windows: WSL2/Docker  ·  Linux: native Docker"))
        lay.addWidget(box)
        lay.addStretch()
        return page

    def navigate(self, page: int):
        self.pages.setCurrentIndex(page)
        for index, obj in self.nav.items():
            obj.setChecked(index == page)

    def refresh(self):
        if self.busy:
            return
        self.desktop = discover(packaged=ROOT)
        present = self.desktop.server_installed
        manager = self.desktop.manager_installed
        self.status_tag.setText("Installed" if present else "Not installed")
        self.status_tag.setProperty("healthy", present)
        self.status_tag.style().unpolish(self.status_tag)
        self.status_tag.style().polish(self.status_tag)
        self.server_description.setText(
            "WEAVE CBT is registered on this computer. Use status or diagnostics to verify running services."
            if present else "No WEAVE CBT server installation was found. You can install it here.")
        self.version.setText(
            f"Installed version: {self.desktop.installation.get('installed_version', 'Unknown')}" if present
            else ("CLI manager detected: " + str(self.desktop.cli) if manager else "CLI manager not found. Install the desktop distribution's bundled manager first."))
        self.preflight.setText(
            ("An existing CBT installation was detected. Reinstallation is disabled to protect examination data." if present
             else "The CLI manager is ready. Installation will download Docker dependencies and the pinned application image."
             if manager else "CLI manager missing. Repair the desktop package to install the verified bundled CLI.")
            + (f"\n{self.desktop.problem}" if self.desktop.problem else "")
        )
        self.install_btn.setEnabled(manager and not present and not self.busy)
        self.install_action.setVisible(not present)
        self.start_action.setEnabled(present and not self.busy)
        self.stop_action.setEnabled(present and not self.busy)
        self.restart_action.setEnabled(present and not self.busy)

    def confirm_run(self, command: str):
        if QMessageBox.question(self, "Confirm operation",
                f"Do you want to {command} the WEAVE CBT server? This could interrupt an exam session.",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No) == QMessageBox.Yes:
            self.run(command)

    def run(self, command: str):
        if command not in OPERATIONS or self.busy:
            return
        self.desktop = discover(packaged=ROOT)
        if not self.desktop.cli:
            QMessageBox.warning(self, "Manager missing", "The verified CLI manager was not found. Repair WEAVE CBT Desktop Manager.")
            return
        if command == "install" and self.desktop.server_installed:
            QMessageBox.information(self, "Already installed", "WEAVE CBT is already installed. Your data is preserved.")
            return
        if command in {"install", "start", "stop", "restart", "lan_refresh"} and not is_admin():
            outcome = QMessageBox.question(
                self, "Administrator permission required",
                "This operation changes local services and requires administrator permission. Relaunch with elevated privileges?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if outcome == QMessageBox.Yes and elevate_gui():
                QApplication.quit()
            return
        args = ["lan", "--refresh"] if command == "lan_refresh" else [command]
        self.last_command = command
        self.busy = True
        self.line_tail = ""
        self.poll.stop()
        self.log_widget.appendPlainText(f"\n── WEAVE {command} ──")
        self.install_output.appendPlainText(f"\nStarting: {command}")
        self.install_progress.setVisible(command == "install")
        self.install_btn.setEnabled(False)
        self.process.setProgram(str(self.desktop.cli))
        self.process.setArguments(args)
        self.process.start()
        if not self.process.waitForStarted(2500):
            self.finished(1, QProcess.CrashExit)

    def consume(self):
        chunk = bytes(self.process.readAllStandardOutput()).decode("utf-8", "replace")
        if not chunk:
            return
        self.log_widget.appendPlainText(chunk.rstrip("\r\n"))
        if self.last_command == "install":
            self.install_output.appendPlainText(chunk.rstrip("\r\n"))
        # Truncate extremely large output to bound memory when installing Docker.
        for widget in (self.log_widget, self.install_output):
            if widget.document().blockCount() > 1500:
                widget.setPlainText("\n".join(widget.toPlainText().splitlines()[-900:]))

    def process_error(self, error):
        self.log_widget.appendPlainText(f"Process error: {self.process.errorString()}")

    def finished(self, code: int, _status):
        if not self.busy:
            return
        self.consume()
        self.busy = False
        self.install_progress.setVisible(False)
        self.log_widget.appendPlainText(f"Operation completed with exit code {code}.")
        if self.last_command == "install":
            self.install_output.appendPlainText(f"Exit code: {code}")
        self.poll.start(10000)
        self.refresh()
        if code == 10 and self.last_command == "install":
            QMessageBox.warning(self, "Restart required",
                "Windows requires a reboot to finish WSL setup. Save your work, restart Windows, then reopen this manager and click Install to resume.")
        elif code == 0 and self.last_command == "install":
            QMessageBox.information(self, "Installation complete",
                "WEAVE CBT was installed. Run diagnostics and test the CBT site from a separate computer before an exam.")
            self.navigate(0)
        elif code != 0:
            QMessageBox.warning(self, "Operation failed",
                f"WEAVE {self.last_command} exited with code {code}. Open Diagnostics & logs for details.")


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("WEAVE CBT Desktop Manager")
    app.setFont(QFont("Segoe UI", 10))
    ui = Desktop()
    if "--smoke-test" in sys.argv:
        print("WEAVE GUI ready", flush=True)
        ui.close()
        return
    ui.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
