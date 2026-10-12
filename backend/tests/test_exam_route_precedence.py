from starlette.routing import Match

from app.main import app


def _first_full_match_scope(path: str, method: str = "GET") -> dict:
    scope = {
        "type": "http",
        "path": path,
        "method": method.upper(),
        "root_path": "",
        "scheme": "http",
        "server": ("testserver", 80),
        "client": ("testclient", 50000),
        "headers": [],
        "query_string": b"",
    }

    for route in app.routes:
        match, child_scope = route.matches(scope)
        if match == Match.FULL:
            return child_scope

    raise AssertionError(f"No route matched {method.upper()} {path}")


def test_static_exam_routes_precede_generic_exam_detail_route() -> None:
    openapi_paths = app.openapi()["paths"]

    for path in (
        "/api/v1/exams/lead-candidates",
        "/api/v1/exams/invigilators/available",
    ):
        assert path in openapi_paths
        matched_scope = _first_full_match_scope(path)
        assert "exam_id" not in matched_scope.get("path_params", {})
