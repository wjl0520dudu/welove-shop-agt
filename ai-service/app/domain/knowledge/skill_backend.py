"""Read-only filesystem backend for KnowledgeAgent Skills."""

from __future__ import annotations

from pathlib import Path

from deepagents.backends import FilesystemBackend


AI_SERVICE_ROOT = Path(__file__).resolve().parents[3]
KNOWLEDGE_SKILL_SOURCE = "/skills/knowledge-agent/"


def normalise_knowledge_skill_source(value: str | None) -> str:
    """Return the only virtual Skill namespace visible to KnowledgeAgent."""
    source = str(value or KNOWLEDGE_SKILL_SOURCE).strip().replace("\\", "/")
    if not source.startswith("/"):
        source = f"/{source}"
    source = f"{source.rstrip('/')}/"
    if source != KNOWLEDGE_SKILL_SOURCE:
        raise ValueError(
            "KNOWLEDGE_SKILLS_ROOT must resolve to /skills/knowledge-agent/."
        )
    return source


def build_knowledge_skill_backend(
    *,
    root_dir: str | Path | None = None,
) -> FilesystemBackend:
    """Map virtual Knowledge Skill paths into the ai-service repository."""
    root = Path(root_dir).resolve() if root_dir else AI_SERVICE_ROOT
    skill_dir = root / KNOWLEDGE_SKILL_SOURCE.strip("/")
    if not skill_dir.is_dir():
        raise FileNotFoundError(f"Knowledge Skill directory not found: {skill_dir}")
    return FilesystemBackend(root_dir=root, virtual_mode=True)


__all__ = [
    "AI_SERVICE_ROOT",
    "KNOWLEDGE_SKILL_SOURCE",
    "build_knowledge_skill_backend",
    "normalise_knowledge_skill_source",
]
