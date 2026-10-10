"""First-launch installation wizard shared by Windows and Linux desktop builds.

OS packaging installs GUI + version-matched CLI. This wizard then introduces the
user to installing the CBT *server*. It never duplicates CLI installer logic.
"""
from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QFont, QPixmap
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWizard, QWizardPage,
)

BLUE = "#1d4ed8"
INK = "#0f172a"
MUTED = "#64748b"


def heading(text: str, size: int = 19) -> QLabel:
    result = QLabel(text)
    result.setFont(QFont("Segoe UI", size, QFont.Bold))
    result.setStyleSheet(f"color: {INK};")
    result.setWordWrap(True)
    return result


def paragraph(text: str) -> QLabel:
    result = QLabel(text)
    result.setWordWrap(True)
    result.setStyleSheet(f"color: {MUTED}; font-size: 13px; line-height: 1.4;")
    return result


def page() -> tuple[QWizardPage, QVBoxLayout]:
    widget = QWizardPage()
    layout = QVBoxLayout(widget)
    layout.setContentsMargins(18, 24, 18, 18)
    layout.setSpacing(14)
    return widget, layout


class ReadinessPage(QWizardPage):
    def __init__(self, owner):
        super().__init__()
        self.owner = owner
        self.setTitle("Check your computer")
        self.setSubTitle("We'll verify the existing manager before changing anything.")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 22, 18, 20)
        layout.setSpacing(16)

        self.cli = QLabel()
        self.cli.setWordWrap(True)
        layout.addWidget(self.cli)

        self.server = QLabel()
        self.server.setWordWrap(True)
        layout.addWidget(self.server)

        self.note = paragraph(
            "Nothing is removed or modified during this check. Your existing "
            "examinations and school data will be preserved.")
        layout.addWidget(self.note)
        layout.addStretch()

    def initializePage(self):
        from bridge import discover
        state = discover()
        if state.manager_installed:
            self.cli.setText("✓ WEAVE CLI manager detected and verified.")
        else:
            self.cli.setText("! WEAVE CLI is missing. Repair the Desktop Manager package before installing CBT.")
        if state.server_installed:
            self.server.setText("✓ CBT server installation detected. Existing data will not be modified.")
        else:
            self.server.setText("• No CBT server installation was detected.")
        if state.problem:
            self.note.setText(state.problem + "\nOpen Diagnostics after finishing this wizard.")

        self.cli.setStyleSheet(
            "font-weight: 600; color: " + ("#047857" if state.manager_installed else "#b45309") + ";")
        self.server.setStyleSheet(
            "font-weight: 600; color: " + ("#047857" if state.server_installed else MUTED) + ";")


class SetupWizard(QWizard):
    def __init__(self, owner, resource_dir: Path):
        super().__init__(owner)
        self.owner = owner
        self.setWindowTitle("Welcome to WEAVE CBT")
        self.setWizardStyle(QWizard.ModernStyle)
        self.setFixedSize(700, 485)
        self.setOption(QWizard.NoBackButtonOnStartPage, True)
        self.setButtonText(QWizard.NextButton, "Continue")
        self.setButtonText(QWizard.FinishButton, "Open Desktop Manager")
        self.setButtonText(QWizard.CancelButton, "Not now")
        self.setStyleSheet("""
            QWizard { background: #ffffff; }
            QWizardPage { background: #ffffff; }
            QLabel { background: transparent; }
            QPushButton { min-width: 104px; min-height: 35px; padding: 4px 15px;
                border: 1px solid #cbd5e1; border-radius: 7px;
                background: #ffffff; color: #1e40af; font-weight: 600; }
            QPushButton:hover { background: #eff6ff; }
            QPushButton:disabled { color: #94a3b8; }
        """)

        first, layout = page()
        brand = QHBoxLayout()
        logo = QLabel()
        source = resource_dir / "weave-logo-blue.png"
        if source.is_file():
            pix = QPixmap(str(source))
            if not pix.isNull():
                logo.setPixmap(pix.scaled(
                    QSize(80, 66), Qt.KeepAspectRatio, Qt.SmoothTransformation))
        brand.addWidget(logo)
        brand.addWidget(heading("WEAVE CBT", 17))
        brand.addStretch()
        layout.addLayout(brand)
        layout.addSpacing(14)
        layout.addWidget(heading("Set up your school's CBT server", 23))
        layout.addWidget(paragraph(
            "The WEAVE Desktop Manager makes your examination server simple to "
            "install and operate. You don't need to use a terminal."))
        layout.addSpacing(15)
        layout.addWidget(paragraph(
            "1. Check this computer and your existing installation\n"
            "2. Set up the local CBT server through the WEAVE CLI\n"
            "3. Manage exams using the desktop dashboard"))
        layout.addStretch()
        self.addPage(first)
        self.addPage(ReadinessPage(owner))

        last, last_layout = page()
        last_layout.addWidget(heading("You're ready to begin", 23))
        last_layout.addWidget(paragraph(
            "Next, click Install WEAVE CBT in the Desktop Manager. "
            "Installation runs in the background, while you see progress and logs."))
        last_layout.addSpacing(8)
        last_layout.addWidget(paragraph(
            "If Windows needs to restart to finish WSL setup, WEAVE will "
            "explain the next step. After restarting, reopen the manager to resume."))
        last_layout.addWidget(paragraph(
            "Your CBT server will continue running even when this window is closed."))
        last_layout.addStretch()
        self.addPage(last)
