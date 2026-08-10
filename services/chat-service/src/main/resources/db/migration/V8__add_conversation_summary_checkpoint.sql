SET search_path TO chat_svc;

-- ``summary_covered_message_id`` records the last message actually folded
-- into the textual summary.  The checkpoint records the newest message seen
-- when that batch was triggered, so keeping recent verbatim messages does not
-- accidentally shorten the next configured 20-message batch.
ALTER TABLE conversation_context
    ADD COLUMN IF NOT EXISTS summary_checkpoint_message_id BIGINT;
