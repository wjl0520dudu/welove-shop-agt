-- P2: server-owned, auditable action proposals.  A proposal is intent only
-- until the authenticated user confirms it through chat-service.
SET search_path TO chat_svc;

CREATE TABLE agent_action_proposal (
    id                   VARCHAR(64) PRIMARY KEY,
    user_id              BIGINT NOT NULL,
    conversation_id      BIGINT NOT NULL,
    assistant_message_id BIGINT,
    action_type          VARCHAR(32) NOT NULL,
    product_id           BIGINT NOT NULL,
    requested_sku_id     BIGINT,
    requested_quantity   INTEGER NOT NULL DEFAULT 1,
    status               VARCHAR(24) NOT NULL DEFAULT 'PENDING',
    expires_at           TIMESTAMP NOT NULL,
    confirmed_at         TIMESTAMP,
    executed_at          TIMESTAMP,
    failure_code         VARCHAR(64),
    display_json         JSONB,
    result_json          JSONB,
    created_at           TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at           TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT ck_agent_action_proposal_type CHECK (action_type IN ('ADD_TO_CART')),
    CONSTRAINT ck_agent_action_proposal_status CHECK (status IN ('PENDING', 'EXECUTING', 'EXECUTED', 'CANCELLED', 'EXPIRED', 'FAILED')),
    CONSTRAINT ck_agent_action_proposal_quantity CHECK (requested_quantity BETWEEN 1 AND 99)
);

CREATE INDEX idx_agent_action_proposal_user_status_expiry
    ON agent_action_proposal(user_id, status, expires_at);
CREATE INDEX idx_agent_action_proposal_conversation_created
    ON agent_action_proposal(conversation_id, created_at DESC);
