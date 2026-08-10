-- One authoritative rolling-context row per conversation.  Earlier versions
-- inserted an empty row per message, so keep the most recently updated row
-- before enforcing the invariant.
SET search_path TO chat_svc;

WITH ranked AS (
    SELECT id,
           row_number() OVER (
               PARTITION BY conversation_id
               ORDER BY update_time DESC NULLS LAST, create_time DESC NULLS LAST, id DESC
           ) AS rn
    FROM conversation_context
    WHERE conversation_id IS NOT NULL
)
DELETE FROM conversation_context c
USING ranked r
WHERE c.id = r.id AND r.rn > 1;

CREATE UNIQUE INDEX IF NOT EXISTS uk_conversation_context_conversation_id
    ON conversation_context(conversation_id)
    WHERE conversation_id IS NOT NULL;
