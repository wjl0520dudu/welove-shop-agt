-- One user turn may have one user message and one assistant message.  The
-- identifier is supplied by the client for idempotent network retries.
SET search_path TO chat_svc;

ALTER TABLE message
    ADD COLUMN IF NOT EXISTS turn_id VARCHAR(64);

CREATE INDEX IF NOT EXISTS idx_message_conversation_turn
    ON message(conversation_id, turn_id)
    WHERE turn_id IS NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS uk_message_conversation_turn_role
    ON message(conversation_id, turn_id, role)
    WHERE turn_id IS NOT NULL;
