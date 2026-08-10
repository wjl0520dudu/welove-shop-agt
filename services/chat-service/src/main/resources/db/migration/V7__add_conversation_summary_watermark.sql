SET search_path TO chat_svc;

-- The summary remains in the existing one-row conversation_context record.
-- This marker only records how far the summary already covers, so an async
-- summarizer never pays to compress the same message prefix twice.
ALTER TABLE conversation_context
    ADD COLUMN IF NOT EXISTS summary_covered_message_id BIGINT;
