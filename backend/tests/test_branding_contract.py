from __future__ import annotations

import os
import unittest
from uuid import uuid4

os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://weave:weave@localhost:5432/weave_cbt_test",
)
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")

import app.model_registry  # noqa: F401
from app.core.database import Base
from app.integrations.weave.branding import (
    BRANDING_PATH,
    WeaveBrandingProjection,
)


class BrandingProjectionContractTests(unittest.TestCase):
    def test_branding_table_is_registered(self) -> None:
        self.assertIn("branding_states", Base.metadata.tables)

    def test_gateway_uses_weave_cbt_branding_route(self) -> None:
        self.assertEqual(BRANDING_PATH, "/api/v1/cbt/branding")

    def test_projection_accepts_light_and_dark_tokens_but_cbt_can_use_light_only(
        self,
    ) -> None:
        projection = WeaveBrandingProjection.model_validate(
            {
                "tenant_id": str(uuid4()),
                "school_name": "Brightfield Academy",
                "logo_url": None,
                "logo_revision": None,
                "is_enabled": True,
                "is_default_theme": False,
                "theme_version": 3,
                "token_schema_version": 4,
                "light_tokens": {"--color-primary": "4 120 87"},
                "dark_tokens": {"--color-primary": "16 185 129"},
            }
        )
        self.assertEqual(projection.light_tokens["--color-primary"], "4 120 87")


if __name__ == "__main__":
    unittest.main()
