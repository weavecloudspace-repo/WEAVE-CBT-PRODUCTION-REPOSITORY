"""Regressions for Windows Desktop self-update process/installer handoff.

Static assertions supplement Windows CI's actual Inno Setup compilation and
end-to-end CLI mock tests; no Windows process is terminated in this suite.
"""
from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
GUI = ROOT / "deployment" / "gui" / "main.py"
INNO = ROOT / "deployment" / "packaging" / "windows" / "desktop.iss"


class UpdateHandoffContracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.gui = GUI.read_text(encoding="utf-8")
        cls.installer = INNO.read_text(encoding="utf-8")

    def test_gui_emits_actual_manager_pid_only_during_update_install(self):
        self.assertIn('if command == "self-update" and args == ["--yes"] and sys.platform == "win32":', self.gui)
        self.assertIn('args.extend(["--manager-pid", str(os.getpid())])', self.gui)
        self.assertIn('"WEAVE_MANAGER_INSTALLER_LAUNCHED" in self.output_tail', self.gui)
        self.assertIn('QTimer.singleShot(0, self._close_for_manager_update)', self.gui)
        self.assertIn("self.process.state() != QProcess.NotRunning", self.gui)
        self.assertIn("if self.close():", self.gui)

    def test_installer_requires_admin_and_waits_for_known_process(self):
        self.assertIn("PrivilegesRequired=admin", self.installer)
        self.assertIn("CloseApplications=yes", self.installer)
        self.assertIn("RestartApplications=no", self.installer)
        self.assertIn("function PrepareToInstall(var NeedsRestart: Boolean): String;", self.installer)
        self.assertIn("WinOpenProcess(SYNCHRONIZE_ACCESS", self.installer)
        self.assertIn("WinWaitForSingleObject(ProcessHandle, 30000)", self.installer)
        self.assertIn("if WaitResult <> 0 then", self.installer)
        self.assertIn("Cannot verify that the previous WEAVE manager exited", self.installer)
        self.assertNotIn("taskkill /F", self.installer)
        self.assertNotIn("CloseApplications=force", self.installer)


if __name__ == "__main__":
    unittest.main()
