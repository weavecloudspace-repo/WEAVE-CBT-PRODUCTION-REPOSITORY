from __future__ import annotations

import unittest
from types import SimpleNamespace

from fastapi import HTTPException

from app.domains.ai.router import _require_admin, router
from app.domains.auth.dependencies import LocalActorContext


class AIManagementRouteContractTests(unittest.TestCase):
    def test_non_authoring_route_surface_is_complete(self):
        routes = {
            (route.path, method)
            for route in router.routes
            for method in getattr(route, "methods", set())
        }
        expected = {
            ("/ai/quota", "GET"),
            ("/ai/quota/requests", "POST"),
            ("/ai/quota/requests", "GET"),
            ("/ai/quota/requests/{request_id}/cancel", "POST"),
            ("/ai/admin/quota/summary", "GET"),
            ("/ai/admin/quota/actors", "GET"),
            ("/ai/admin/quota/requests", "GET"),
            ("/ai/admin/quota/requests/{request_id}/approve", "POST"),
            ("/ai/admin/quota/requests/{request_id}/reject", "POST"),
            ("/ai/admin/quota/allocations", "POST"),
            ("/ai/admin/quota/allocations", "GET"),
            ("/ai/admin/quota/purchases/quote", "POST"),
            ("/ai/admin/quota/purchases/checkout", "POST"),
            ("/ai/admin/quota/purchases/{reference}/verify", "POST"),
            ("/ai/admin/quota/purchases", "GET"),
            ("/ai/admin/quota/purchases/{purchase_id}", "GET"),
        }
        self.assertTrue(expected.issubset(routes))
        self.assertFalse(any("questions/generate" in path for path, _ in routes))
        self.assertFalse(any("questions/regenerate" in path for path, _ in routes))

    def test_teacher_is_rejected_from_admin_surface_before_cloud_call(self):
        context = LocalActorContext(
            actor=SimpleNamespace(role="teacher"),
            session=SimpleNamespace(),
        )

        with self.assertRaises(HTTPException) as captured:
            _require_admin(context)

        self.assertEqual(captured.exception.status_code, 403)

    def test_admin_is_allowed_through_local_role_guard(self):
        context = LocalActorContext(
            actor=SimpleNamespace(role="admin"),
            session=SimpleNamespace(),
        )

        self.assertIsNone(_require_admin(context))


if __name__ == "__main__":
    unittest.main()
