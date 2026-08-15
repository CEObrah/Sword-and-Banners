"""Safe Railway checkout bootstrap followed by the private ASGI service.

Railway build files are ephemeral. Campaign commits live in a Git checkout on
the mounted volume, while WAL and receipts live in a separate runtime root.
"""
from __future__ import annotations
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Optional, Sequence
from urllib.parse import urlsplit

_SAFE_REF = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,127}$")
_CAMPAIGN_AUTHORITY_PATHS = ("state",)

class BootstrapError(RuntimeError):
    """The persistent campaign checkout cannot be established safely."""

def _required_text(value: Optional[str], name: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip() or any(c in value for c in ("\x00", "\r", "\n")):
        raise BootstrapError(f"{name} must be non-empty bounded text")
    return value

def _safe_ref(value: Optional[str], name: str) -> str:
    value = _required_text(value, name)
    if not _SAFE_REF.fullmatch(value) or value.startswith("-") or ".." in value:
        raise BootstrapError(f"{name} is not a safe Git ref component")
    return value

@dataclass(frozen=True)
class CheckoutSettings:
    campaign_root: Path
    runtime_root: Path
    git_url: str
    remote: str = "origin"
    branch: str = "main"
    git_token: Optional[str] = None
    git_binary: str = "git"

    def __post_init__(self) -> None:
        campaign_root = Path(self.campaign_root).expanduser().resolve()
        runtime_root = Path(self.runtime_root).expanduser().resolve()
        if campaign_root == runtime_root or campaign_root in runtime_root.parents:
            raise BootstrapError("runtime root may not be inside the campaign checkout")
        if runtime_root in campaign_root.parents:
            raise BootstrapError("campaign checkout may not contain the runtime root")
        git_url = _required_text(self.git_url, "SWORD_GIT_URL")
        if len(git_url) > 2048:
            raise BootstrapError("SWORD_GIT_URL is too long")
        parsed = urlsplit(git_url)
        if parsed.scheme in ("http", "https") and (parsed.username is not None or parsed.password is not None):
            raise BootstrapError("SWORD_GIT_URL may not embed credentials; use SWORD_GIT_TOKEN")
        if self.git_token is not None:
            token = _required_text(self.git_token, "SWORD_GIT_TOKEN")
            if len(token) > 4096:
                raise BootstrapError("SWORD_GIT_TOKEN is too long")
            if not git_url.startswith("https://"):
                raise BootstrapError("token authentication requires an HTTPS Git URL")
        _safe_ref(self.remote, "SWORD_GIT_REMOTE")
        _safe_ref(self.branch, "SWORD_GIT_BRANCH")
        _required_text(self.git_binary, "git binary")
        object.__setattr__(self, "campaign_root", campaign_root)
        object.__setattr__(self, "runtime_root", runtime_root)

    @classmethod
    def from_env(cls) -> "CheckoutSettings":
        return cls(
            campaign_root=Path(_required_text(os.environ.get("SWORD_CAMPAIGN_ROOT"), "SWORD_CAMPAIGN_ROOT")),
            runtime_root=Path(_required_text(os.environ.get("SWORD_RUNTIME_ROOT"), "SWORD_RUNTIME_ROOT")),
            git_url=_required_text(os.environ.get("SWORD_GIT_URL"), "SWORD_GIT_URL"),
            remote=os.environ.get("SWORD_GIT_REMOTE", "origin"),
            branch=os.environ.get("SWORD_GIT_BRANCH", "main"),
            git_token=os.environ.get("SWORD_GIT_TOKEN"),
            git_binary=os.environ.get("SWORD_GIT_BINARY", "git"),
        )

def _askpass_environment(settings: CheckoutSettings) -> Mapping[str, str]:
    environment = dict(os.environ)
    environment["GIT_TERMINAL_PROMPT"] = "0"
    if settings.git_token is None:
        return environment
    settings.runtime_root.mkdir(parents=True, exist_ok=True)
    wrapper = settings.runtime_root / "git-askpass"
    wrapper.write_text(
        "#!/bin/sh\nexec \"%s\" -m sword_runtime.git_askpass \"$@\"\n" % sys.executable.replace('"', '\\"'),
        encoding="utf-8",
    )
    wrapper.chmod(0o700)
    environment["GIT_ASKPASS"] = str(wrapper)
    environment["GIT_ASKPASS_REQUIRE"] = "force"
    environment["SWORD_GIT_TOKEN"] = settings.git_token
    return environment

def _run(settings: CheckoutSettings, arguments: Sequence[str], *, cwd: Optional[Path] = None) -> str:
    completed = subprocess.run(
        [settings.git_binary] + list(arguments),
        cwd=None if cwd is None else str(cwd),
        env=_askpass_environment(settings),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    if completed.returncode:
        raise BootstrapError("Git bootstrap operation failed with exit code %d" % completed.returncode)
    return completed.stdout.strip()

def _checkout_status(settings: CheckoutSettings) -> str:
    return _run(settings, ("status", "--porcelain=v1", "--untracked-files=all"), cwd=settings.campaign_root)

def _assert_clean(settings: CheckoutSettings) -> None:
    if _checkout_status(settings):
        raise BootstrapError("persistent campaign checkout is dirty")

def _is_ancestor(settings: CheckoutSettings, older: str, newer: str) -> bool:
    completed = subprocess.run(
        [settings.git_binary, "merge-base", "--is-ancestor", older, newer],
        cwd=str(settings.campaign_root),
        env=_askpass_environment(settings),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    if completed.returncode not in (0, 1):
        raise BootstrapError("Git ancestry check failed")
    return completed.returncode == 0

def _campaign_authority_matches(settings: CheckoutSettings, local_head: str, remote_head: str) -> bool:
    """Compare committed campaign truth before adopting a replacement Git lineage."""
    completed = subprocess.run(
        [
            settings.git_binary,
            "diff",
            "--quiet",
            "--exit-code",
            local_head,
            remote_head,
            "--",
            *_CAMPAIGN_AUTHORITY_PATHS,
        ],
        cwd=str(settings.campaign_root),
        env=_askpass_environment(settings),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    if completed.returncode not in (0, 1):
        raise BootstrapError("Git campaign-authority comparison failed")
    return completed.returncode == 0

def ensure_checkout(settings: CheckoutSettings) -> Path:
    settings.runtime_root.mkdir(parents=True, exist_ok=True)
    git_directory = settings.campaign_root / ".git"
    if not git_directory.is_dir():
        if settings.campaign_root.exists() and any(settings.campaign_root.iterdir()):
            raise BootstrapError("campaign root exists but is not an empty Git checkout")
        settings.campaign_root.parent.mkdir(parents=True, exist_ok=True)
        _run(
            settings,
            (
                "clone", "--single-branch", "--branch", settings.branch,
                "--origin", settings.remote, "--", settings.git_url,
                str(settings.campaign_root),
            ),
        )

    configured_url = _run(settings, ("remote", "get-url", settings.remote), cwd=settings.campaign_root)
    if configured_url != settings.git_url:
        raise BootstrapError("configured Git remote URL differs from SWORD_GIT_URL")
    _run(settings, ("fetch", "--no-tags", settings.remote, settings.branch), cwd=settings.campaign_root)
    local_head = _run(settings, ("rev-parse", "HEAD"), cwd=settings.campaign_root)
    remote_ref = f"refs/remotes/{settings.remote}/{settings.branch}"
    remote_head = _run(settings, ("rev-parse", "--verify", remote_ref), cwd=settings.campaign_root)

    if _checkout_status(settings):
        if local_head != remote_head:
            raise BootstrapError("dirty campaign checkout does not match the remote branch")
        return settings.campaign_root
    if local_head == remote_head:
        return settings.campaign_root
    if _is_ancestor(settings, local_head, remote_head):
        _run(settings, ("merge", "--ff-only", remote_ref), cwd=settings.campaign_root)
        _assert_clean(settings)
        return settings.campaign_root
    if _is_ancestor(settings, remote_head, local_head):
        # A crash can leave a local transaction commit waiting for coordinator
        # recovery to push it. Never throw that commit away here.
        return settings.campaign_root

    # A clean Railway volume can outlive an intentional repository-history
    # replacement. Source history may be safely rehomed only when the complete
    # committed state/ tree is byte-identical between both lineages.
    if _campaign_authority_matches(settings, local_head, remote_head):
        _run(settings, ("reset", "--hard", remote_ref), cwd=settings.campaign_root)
        _assert_clean(settings)
        print(
            "Sword bootstrap: adopted remote Git history after verifying identical campaign authority",
            file=sys.stderr,
        )
        return settings.campaign_root
    raise BootstrapError("local and remote campaign histories diverged with different campaign authority")

def main() -> int:
    settings = CheckoutSettings.from_env()
    ensure_checkout(settings)
    git_environment = _askpass_environment(settings)
    for name in ("GIT_TERMINAL_PROMPT", "GIT_ASKPASS", "GIT_ASKPASS_REQUIRE"):
        if name in git_environment:
            os.environ[name] = git_environment[name]
    port = os.environ.get("PORT", "8000")
    if not port.isdigit() or not 1 <= int(port) <= 65535:
        raise BootstrapError("PORT must be in 1..65535")
    os.execvp(
        "uvicorn",
        ("uvicorn", "sword_runtime.api.entrypoint:app", "--host", "0.0.0.0", "--port", port),
    )
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
