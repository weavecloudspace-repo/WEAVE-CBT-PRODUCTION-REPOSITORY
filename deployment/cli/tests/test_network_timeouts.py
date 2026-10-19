"""Regression tests for slow Windows network inventory."""
from __future__ import annotations

import subprocess
from unittest.mock import patch

import pytest

from weave_cli.commands import network
from weave_cli.commands.lan import LanError


def test_windows_network_inventory_retries_one_timeout():
    success = subprocess.CompletedProcess(["powershell.exe"], 0, "[]", "")
    with (
        patch.object(network.sys, "platform", "win32"),
        patch.object(network.time, "sleep") as sleep,
        patch.object(
            network.subprocess,
            "run",
            side_effect=[subprocess.TimeoutExpired(["powershell.exe"], 60), success],
        ) as run,
    ):
        assert network._run(["powershell.exe"]) == "[]"
    assert run.call_count == 2
    assert run.call_args.kwargs["timeout"] == 60
    sleep.assert_called_once_with(1)


def test_windows_network_inventory_exhausted_timeout_is_actionable():
    with (
        patch.object(network.sys, "platform", "win32"),
        patch.object(network.time, "sleep"),
        patch.object(
            network.subprocess,
            "run",
            side_effect=subprocess.TimeoutExpired(["powershell.exe"], 60),
        ) as run,
    ):
        with pytest.raises(LanError, match="60s per attempt.*2 attempt"):
            network._run(["powershell.exe"])
    assert run.call_count == 2


def test_linux_inventory_does_not_retry_timeout():
    with (
        patch.object(network.sys, "platform", "linux"),
        patch.object(network.time, "sleep") as sleep,
        patch.object(
            network.subprocess,
            "run",
            side_effect=subprocess.TimeoutExpired(["ip"], 60),
        ) as run,
    ):
        with pytest.raises(LanError, match="1 attempt"):
            network._run(["ip"])
    assert run.call_count == 1
    sleep.assert_not_called()


def test_network_inventory_command_failure_is_not_retried():
    failure = subprocess.CompletedProcess(["powershell.exe"], 1, "", "Access denied")
    with (
        patch.object(network.sys, "platform", "win32"),
        patch.object(network.subprocess, "run", return_value=failure) as run,
    ):
        with pytest.raises(LanError, match="Access denied"):
            network._run(["powershell.exe"])
    run.assert_called_once()
