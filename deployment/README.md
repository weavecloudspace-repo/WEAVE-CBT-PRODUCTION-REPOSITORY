# WEAVE deployment tooling

The Python package is `weave_cli`; `cli/src` is its source directory and is
not part of an import path. Use imports such as:

```python
from weave_cli.platforms.base import BasePlatform
from weave_cli.docker.runtime import DockerRuntime
from weave_cli.docker.compose import DockerCompose
```

From the repository root, install the deployment project and run its tests:

```powershell
uv sync --project deployment
uv run --project deployment python -m unittest discover -s deployment/cli/tests -v
```

Run a package module with `uv run --project deployment python -m weave_cli.<module>`.
When working inside `deployment`, omit `--project deployment`. Running
`weave_cli.docker.compose` currently follows the configured API container logs.

Build the installable distributions with `uv build deployment`.
Use the deployment Python environment (`deployment/.venv`) in your editor
when working on this package so it can resolve these installed imports.

On Windows, `install`, `start`, and `restart` ensure a hidden scheduled task
named `WEAVE CBT Runtime - WeaveCBT` holds a WSL session open. Docker's systemd
service alone does not keep WSL alive. The task starts immediately and at the
installation owner's Windows sign-in, and retries when the WSL process exits.
Run `uv run weave start` from Administrator PowerShell once to configure this
for an existing installation. You can then close the WSL terminal.

The task runs under the Windows user who owns the WSL distribution, not SYSTEM.
It requires that user to be signed in; it does not provide service availability
before sign-in or after sign-out. `uninstall` removes the task, while `stop`
stops application containers and leaves runtime management in place. Native
Linux continues to use its existing systemd Docker service.
