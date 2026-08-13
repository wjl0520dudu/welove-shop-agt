SET search_path TO chat_svc;

-- Keep original answers for audit, while transcript and AI context only use
-- the response that was not replaced by a regeneration.
ALTER TABLE message
    ADD COLUMN IF NOT EXISTS superseded_by_message_id BIGINT;

CREATE INDEX IF NOT EXISTS idx_message_superseded_by
    ON message(superseded_by_message_id)
    WHERE superseded_by_message_id IS NOT NULL;

-- A replacement invalidates summary content that may mention the old answer.
-- Revisioning prevents already-queued async summary work from writing stale
-- data after the reset.
ALTER TABLE conversation_context
    ADD COLUMN IF NOT EXISTS summary_revision BIGINT NOT NULL DEFAULT 0;
