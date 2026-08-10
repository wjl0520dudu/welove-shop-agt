"""Compatibility export for the Chitchat prompt.

The complete, reviewable prompt contract lives in ``app.prompts.prompts`` with
its context placeholders.  Keep this module so older imports remain valid.
"""

from app.prompts.prompts import CHITCHAT_PROMPT

__all__ = ["CHITCHAT_PROMPT"]
