from __future__ import annotations

import os
import unittest

os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://weave:weave@localhost:5432/weave_cbt_test",
)
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")

from app.domains.branding.service import (
    DEFAULT_LIGHT_TOKENS,
    BrandingContractError,
    BrandingService,
)


class BrandingTokenContractTests(unittest.TestCase):
    def test_default_theme_is_weave_blue(self) -> None:
        self.assertEqual(DEFAULT_LIGHT_TOKENS["--color-primary"], "29 78 216")
        self.assertEqual(DEFAULT_LIGHT_TOKENS["--color-on-primary"], "255 255 255")

    def test_cloud_tokens_override_only_supported_semantic_tokens(self) -> None:
        normalized = BrandingService.normalize_light_tokens(
            {
                "--color-primary": "4 120 87",
                "--color-accent": "217 119 6",
                "--unsupported-injected-value": "url(javascript:bad)",
            }
        )

        self.assertEqual(normalized["--color-primary"], "4 120 87")
        self.assertEqual(normalized["--color-accent"], "217 119 6")
        self.assertNotIn("--unsupported-injected-value", normalized)
        self.assertEqual(
            normalized["--color-background"],
            DEFAULT_LIGHT_TOKENS["--color-background"],
        )

    def test_invalid_rgb_channels_are_rejected(self) -> None:
        with self.assertRaises(BrandingContractError):
            BrandingService.normalize_light_tokens({"--color-primary": "999 0 0"})


if __name__ == "__main__":
    unittest.main()
