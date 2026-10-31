"""Ensure WEAVE CBT's LAN and ngrok reverse proxy preserves AI responses."""

from pathlib import Path


def test_nginx_has_dedicated_long_running_ai_proxy_in_both_vhosts() -> None:
    config = (
        Path(__file__).resolve().parents[2] / "deployment" / "nginx" / "nginx.conf"
    ).read_text(encoding="utf-8")

    assert config.count("proxy_read_timeout 1300s;") == 2
    assert config.count("proxy_send_timeout 1300s;") == 2
    assert config.count("proxy_next_upstream off;") == 2
    assert config.count("banks/[^/]+/ai/(?:generate|regenerate)") == 2
    # Normal routes must retain their existing short proxy timeouts.
    assert config.count("proxy_read_timeout 120s;") == 2
    assert config.count("proxy_send_timeout 120s;") == 2
