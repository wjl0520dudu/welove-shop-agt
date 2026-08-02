"""Read-only filesystem backend for ShoppingAgent Skills."""

from __future__ import annotations

from pathlib import Path

from deepagents.backends import FilesystemBackend

from app.domain.shopping.deep_agent_runtime import SHOPPING_SKILL_SOURCE


AI_SERVICE_ROOT = Path(__file__).resolve().parents[3]


def normalise_shopping_skill_source(value: str | None) -> str:
    """Return the canonical virtual Shopping Skill source.

    The environment setting is intentionally confined to the ShoppingAgent
    namespace.  A typo must not turn DeepAgent's read_file tool into access to
    application code, credentials, or another Agent's Skills.
    """
    source = str(value or SHOPPING_SKILL_SOURCE).strip().replace("\\", "/")
    if not source.startswith("/"):
        source = f"/{source}"
    source = f"{source.rstrip('/')}/"
    if source != SHOPPING_SKILL_SOURCE:
        raise ValueError(
            "SHOPPING_SKILLS_ROOT must resolve to /skills/shopping-agent/."
        )
    return source


def build_shopping_skill_backend(
    *,
    root_dir: str | Path | None = None,
) -> FilesystemBackend:
    """Build a virtual filesystem rooted at ai-service.

    With ``virtual_mode=True``, ``/skills/shopping-agent/...`` maps to the
    repository's ``ai-service/skills/shopping-agent/...`` directory without
    exposing host absolute paths to the model.
    """
    root = Path(root_dir).resolve() if root_dir else AI_SERVICE_ROOT
    skill_dir = root / SHOPPING_SKILL_SOURCE.strip("/")
    if not skill_dir.is_dir():
        raise FileNotFoundError(f"Shopping Skill directory not found: {skill_dir}")
    return FilesystemBackend(root_dir=root, virtual_mode=True)


__all__ = [
    "AI_SERVICE_ROOT",
    "build_shopping_skill_backend",
    "normalise_shopping_skill_source",
]
