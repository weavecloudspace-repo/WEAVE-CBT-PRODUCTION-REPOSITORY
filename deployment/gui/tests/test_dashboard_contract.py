"""UI shell contracts: no non-functional dashboard placeholders."""
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAIN = (ROOT / "main.py").read_text(encoding="utf-8")
THEME = (ROOT / "resources" / "theme.qss").read_text(encoding="utf-8")


class DashboardContracts(unittest.TestCase):
    def test_all_pages_are_real_widgets(self):
        for widget in ("overview_page", "server_page", "network_page", "updates_page",
                       "diagnostics_page", "logs_page", "settings_page"):
            self.assertIn("def " + widget + "(", MAIN)
        self.assertIn("self.pages.addWidget(scroll)", MAIN)

    def test_actions_use_cli_not_placeholder_status(self):
        self.assertIn('["status", "--json"]', MAIN)
        self.assertIn('self.run("update", ["--yes"])', MAIN)
        self.assertIn('self.run("lan", ["--remove"])', MAIN)
        self.assertIn('self.run("lan", ["--refresh"])', MAIN)
        self.assertIn('self.run("doctor")', MAIN)

    def test_dialog_readability(self):
        self.assertIn("QMessageBox QLabel", THEME)
        self.assertIn("color: #10213b", THEME)
        self.assertIn("QMessageBox, QDialog { background: #ffffff;", THEME)

    def test_official_brand_used_on_window_and_taskbar(self):
        self.assertIn('weave-logo-blue.png', MAIN)
        self.assertIn("SetCurrentProcessExplicitAppUserModelID", MAIN)

    def test_manager_update_does_not_claim_unsigned_autoupdates(self):
        self.assertIn("View official releases", MAIN)
        self.assertIn("The desktop executable cannot safely overwrite itself", MAIN)


if __name__ == "__main__":
    unittest.main()
