"""Add AI planning runs, proposal, approval, job, event and outbox tables.

Revision ID: 0006
Revises: 0005
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0006"
down_revision: str | Sequence[str] | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TENANT_PREDICATE = (
    "organization_id = NULLIF(current_setting('app.organization_id', true), '')::uuid"
)


def _enable_rls(table_name: str) -> None:
    op.execute(sa.text(f'ALTER TABLE "{table_name}" ENABLE ROW LEVEL SECURITY'))
    op.execute(sa.text(f'ALTER TABLE "{table_name}" FORCE ROW LEVEL SECURITY'))
    op.execute(
        sa.text(
            f'CREATE POLICY tenant_isolation ON "{table_name}" '
            f"USING ({_TENANT_PREDICATE}) WITH CHECK ({_TENANT_PREDICATE})"
        )
    )


def upgrade() -> None:
    # 1. workflow_runs
    op.create_table(
        "workflow_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("requested_by_membership_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=50), server_default="QUEUED", nullable=False),
        sa.Column("workflow_name", sa.String(length=100), nullable=False),
        sa.Column("workflow_version", sa.String(length=50), nullable=False),
        sa.Column("verifier_version", sa.String(length=50), nullable=False),
        sa.Column("input_goal_text", sa.Text(), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "project_id"],
            ["projects.organization_id", "projects.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "requested_by_membership_id"],
            ["memberships.organization_id", "memberships.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "id"),
        sa.CheckConstraint(
            "verifier_version ~ '[^[:space:]]'",
            name="ck_workflow_runs_verifier_version",
        ),
    )
    op.create_index(
        "ix_workflow_runs_project", "workflow_runs", ["organization_id", "project_id", "id"]
    )
    op.create_index("ix_workflow_runs_status", "workflow_runs", ["organization_id", "status", "id"])

    # 2. workflow_checkpoints
    op.create_table(
        "workflow_checkpoints",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("workflow_run_id", sa.Uuid(), nullable=False),
        sa.Column("node", sa.String(length=100), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("state", postgresql.JSONB(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "workflow_run_id"],
            ["workflow_runs.organization_id", "workflow_runs.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "id"),
        sa.UniqueConstraint("organization_id", "workflow_run_id", "sequence"),
    )
    op.create_index(
        "ix_workflow_checkpoints_run",
        "workflow_checkpoints",
        ["organization_id", "workflow_run_id", "sequence"],
    )

    # 3. proposals
    op.create_table(
        "proposals",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("workflow_run_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=50), server_default="DRAFT", nullable=False),
        sa.Column("current_version_number", sa.Integer(), server_default="1", nullable=False),
        sa.Column("approval_id", sa.Uuid(), nullable=True),
        sa.Column("superseded_approval_id", sa.Uuid(), nullable=True),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "workflow_run_id"],
            ["workflow_runs.organization_id", "workflow_runs.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "id"),
        sa.UniqueConstraint("organization_id", "id", "current_version_number"),
    )
    op.create_index("ix_proposals_run", "proposals", ["organization_id", "workflow_run_id", "id"])

    # 4. proposal_versions
    op.create_table(
        "proposal_versions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("proposal_id", sa.Uuid(), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("created_by_membership_id", sa.Uuid(), nullable=False),
        sa.Column("content", postgresql.JSONB(), nullable=False),
        sa.Column("assumptions", postgresql.JSONB(), server_default="[]", nullable=False),
        sa.Column("change_summary", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "proposal_id"],
            ["proposals.organization_id", "proposals.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "created_by_membership_id"],
            ["memberships.organization_id", "memberships.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "id"),
        sa.UniqueConstraint("organization_id", "proposal_id", "version_number"),
    )
    op.create_index(
        "ix_proposal_versions_proposal",
        "proposal_versions",
        ["organization_id", "proposal_id", "version_number"],
    )

    # 5. approvals
    op.create_table(
        "approvals",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("proposal_id", sa.Uuid(), nullable=False),
        sa.Column("proposal_version_number", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=50), server_default="PENDING", nullable=False),
        sa.Column("decided_by_membership_id", sa.Uuid(), nullable=True),
        sa.Column("decision_reason", sa.Text(), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "proposal_id"],
            ["proposals.organization_id", "proposals.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "proposal_id", "proposal_version_number"],
            [
                "proposal_versions.organization_id",
                "proposal_versions.proposal_id",
                "proposal_versions.version_number",
            ],
            ondelete="CASCADE",
            name="fk_approvals_proposal_version",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "decided_by_membership_id"],
            ["memberships.organization_id", "memberships.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "id"),
        sa.UniqueConstraint("organization_id", "proposal_id", "id"),
        sa.CheckConstraint(
            "status IN ('PENDING', 'APPROVED', 'REJECTED', 'SUPERSEDED')",
            name="ck_approvals_status",
        ),
        sa.CheckConstraint("version >= 1", name="ck_approvals_version"),
    )
    op.create_index("ix_approvals_proposal", "approvals", ["organization_id", "proposal_id", "id"])

    # Add foreign keys for proposals -> proposal_versions & approvals
    op.create_foreign_key(
        "fk_proposals_current_version",
        "proposals",
        "proposal_versions",
        ["organization_id", "id", "current_version_number"],
        ["organization_id", "proposal_id", "version_number"],
        ondelete="RESTRICT",
        deferrable=True,
        initially="DEFERRED",
    )
    op.create_foreign_key(
        "fk_proposals_approval",
        "proposals",
        "approvals",
        ["organization_id", "id", "approval_id"],
        ["organization_id", "proposal_id", "id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_proposals_superseded_approval",
        "proposals",
        "approvals",
        ["organization_id", "id", "superseded_approval_id"],
        ["organization_id", "proposal_id", "id"],
        ondelete="SET NULL",
    )

    # 6. workflow_jobs
    op.create_table(
        "workflow_jobs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("workflow_run_id", sa.Uuid(), nullable=False),
        sa.Column("job_type", sa.String(length=100), nullable=False),
        sa.Column("status", sa.String(length=50), server_default="QUEUED", nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("attempt_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("max_attempts", sa.Integer(), server_default="3", nullable=False),
        sa.Column(
            "available_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("locked_by_worker_id", sa.String(length=100), nullable=True),
        sa.Column("lease_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "workflow_run_id"],
            ["workflow_runs.organization_id", "workflow_runs.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "id"),
    )
    op.create_index(
        "ix_workflow_jobs_queue",
        "workflow_jobs",
        ["organization_id", "status", "available_at", "id"],
    )
    op.create_index(
        "ix_workflow_jobs_lease",
        "workflow_jobs",
        ["organization_id", "locked_by_worker_id", "lease_until"],
    )

    # 7. workflow_events
    op.create_table(
        "workflow_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("workflow_run_id", sa.Uuid(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(length=100), nullable=False),
        sa.Column("public_payload", postgresql.JSONB(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "workflow_run_id"],
            ["workflow_runs.organization_id", "workflow_runs.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "id"),
        sa.UniqueConstraint("organization_id", "workflow_run_id", "sequence"),
    )
    op.create_index(
        "ix_workflow_events_run",
        "workflow_events",
        ["organization_id", "workflow_run_id", "sequence"],
    )

    # 8. model_invocations
    op.create_table(
        "model_invocations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("workflow_run_id", sa.Uuid(), nullable=False),
        sa.Column("provider", sa.String(length=50), nullable=False),
        sa.Column("model_name", sa.String(length=100), nullable=False),
        sa.Column("prompt_version", sa.String(length=50), nullable=False),
        sa.Column("schema_version", sa.String(length=50), nullable=False),
        sa.Column("invocation_key", sa.String(length=100), nullable=False),
        sa.Column("prompt_tokens", sa.Integer(), nullable=True),
        sa.Column("completion_tokens", sa.Integer(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=50), server_default="SUCCESS", nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "workflow_run_id"],
            ["workflow_runs.organization_id", "workflow_runs.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "id"),
    )
    op.create_index(
        "ix_model_invocations_run",
        "model_invocations",
        ["organization_id", "workflow_run_id", "id"],
    )

    # 9. context_references
    op.create_table(
        "context_references",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("workflow_run_id", sa.Uuid(), nullable=False),
        sa.Column("resource_type", sa.String(length=50), nullable=False),
        sa.Column("resource_id", sa.Uuid(), nullable=False),
        sa.Column("provenance_notes", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "workflow_run_id"],
            ["workflow_runs.organization_id", "workflow_runs.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "id"),
    )
    op.create_index(
        "ix_context_references_run",
        "context_references",
        ["organization_id", "workflow_run_id", "id"],
    )

    # 10. outbox_events
    op.create_table(
        "outbox_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("event_id", sa.Uuid(), nullable=False),
        sa.Column("event_type", sa.String(length=100), nullable=False),
        sa.Column("aggregate_type", sa.String(length=100), nullable=False),
        sa.Column("aggregate_id", sa.Uuid(), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("status", sa.String(length=50), server_default="PENDING", nullable=False),
        sa.Column("attempt_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "available_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "id"),
        sa.UniqueConstraint("organization_id", "event_id"),
    )
    op.create_index(
        "ix_outbox_events_status",
        "outbox_events",
        ["organization_id", "status", "available_at", "id"],
    )

    # Enable RLS & Grants
    deletable_tables = (
        "workflow_checkpoints",
        "workflow_jobs",
    )
    stateful_update_tables = ("proposals",)
    update_only_tables = ("workflow_runs", "approvals", "outbox_events")
    append_only_tables = (
        "proposal_versions",
        "workflow_events",
        "model_invocations",
        "context_references",
    )

    all_tables = deletable_tables + stateful_update_tables + update_only_tables + append_only_tables

    for table_name in all_tables:
        _enable_rls(table_name)
        op.execute(sa.text(f'ALTER TABLE "{table_name}" OWNER TO migration_owner'))

    for table_name in deletable_tables:
        op.execute(
            sa.text(f'GRANT SELECT, INSERT, UPDATE, DELETE ON "{table_name}" TO app_runtime')
        )

    for table_name in stateful_update_tables:
        op.execute(sa.text(f'GRANT SELECT, INSERT, UPDATE ON "{table_name}" TO app_runtime'))

    for table_name in update_only_tables:
        op.execute(sa.text(f'GRANT SELECT, INSERT ON "{table_name}" TO app_runtime'))

    op.execute(
        sa.text(
            "GRANT UPDATE (status, error_message, version, updated_at) "
            "ON workflow_runs TO app_runtime"
        )
    )
    op.execute(
        sa.text(
            "GRANT UPDATE (status, decided_by_membership_id, decision_reason, decided_at, "
            "version, updated_at) ON approvals TO app_runtime"
        )
    )
    op.execute(
        sa.text(
            "GRANT UPDATE (status, attempt_count, available_at, processed_at, last_error) "
            "ON outbox_events TO app_runtime"
        )
    )

    for table_name in append_only_tables:
        op.execute(sa.text(f'GRANT SELECT, INSERT ON "{table_name}" TO app_runtime'))

    op.execute(
        sa.text(
            """
            CREATE FUNCTION protect_workflow_run_provenance() RETURNS trigger
            LANGUAGE plpgsql
            AS $function$
            BEGIN
                IF NEW.id IS DISTINCT FROM OLD.id
                   OR NEW.organization_id IS DISTINCT FROM OLD.organization_id
                   OR NEW.project_id IS DISTINCT FROM OLD.project_id
                   OR NEW.requested_by_membership_id IS DISTINCT FROM OLD.requested_by_membership_id
                   OR NEW.workflow_name IS DISTINCT FROM OLD.workflow_name
                   OR NEW.workflow_version IS DISTINCT FROM OLD.workflow_version
                   OR NEW.verifier_version IS DISTINCT FROM OLD.verifier_version
                   OR NEW.input_goal_text IS DISTINCT FROM OLD.input_goal_text
                   OR NEW.created_at IS DISTINCT FROM OLD.created_at THEN
                    RAISE EXCEPTION 'workflow run provenance cannot be changed';
                END IF;
                RETURN NEW;
            END;
            $function$
            """
        )
    )
    op.execute("ALTER FUNCTION protect_workflow_run_provenance() OWNER TO migration_owner")
    op.execute(
        "CREATE TRIGGER protect_workflow_run_provenance_before_update "
        "BEFORE UPDATE ON workflow_runs FOR EACH ROW "
        "EXECUTE FUNCTION protect_workflow_run_provenance()"
    )

    op.execute(
        sa.text(
            """
            CREATE FUNCTION protect_approval_evidence() RETURNS trigger
            LANGUAGE plpgsql
            AS $function$
            BEGIN
                IF TG_OP = 'INSERT' THEN
                    IF NEW.status <> 'PENDING'
                       OR NEW.version <> 1
                       OR NEW.decided_by_membership_id IS NOT NULL
                       OR NEW.decision_reason IS NOT NULL
                       OR NEW.decided_at IS NOT NULL THEN
                        RAISE EXCEPTION 'approval must be inserted as PENDING';
                    END IF;
                    RETURN NEW;
                END IF;
                IF NEW.id IS DISTINCT FROM OLD.id
                   OR NEW.organization_id IS DISTINCT FROM OLD.organization_id
                   OR NEW.proposal_id IS DISTINCT FROM OLD.proposal_id
                   OR NEW.proposal_version_number IS DISTINCT FROM OLD.proposal_version_number
                   OR NEW.created_at IS DISTINCT FROM OLD.created_at THEN
                    RAISE EXCEPTION 'approval immutable evidence cannot be changed';
                END IF;
                IF OLD.status <> 'PENDING' THEN
                    RAISE EXCEPTION 'terminal approval cannot be changed';
                END IF;
                IF NEW.status NOT IN ('APPROVED', 'REJECTED', 'SUPERSEDED')
                   OR NEW.version <> OLD.version + 1 THEN
                    RAISE EXCEPTION 'approval transition or version increment is invalid';
                END IF;
                IF NEW.status IN ('APPROVED', 'REJECTED')
                   AND (NEW.decided_by_membership_id IS NULL OR NEW.decided_at IS NULL) THEN
                    RAISE EXCEPTION 'approval decision actor and timestamp are required';
                END IF;
                IF current_user = 'app_runtime'
                   AND NEW.status IN ('APPROVED', 'REJECTED')
                   AND NEW.decided_by_membership_id IS DISTINCT FROM
                       NULLIF(current_setting('app.membership_id', true), '')::uuid THEN
                    RAISE EXCEPTION 'approval decision actor must match authenticated membership';
                END IF;
                RETURN NEW;
            END;
            $function$
            """
        )
    )
    op.execute("ALTER FUNCTION protect_approval_evidence() OWNER TO migration_owner")
    op.execute(
        "CREATE TRIGGER protect_approval_evidence_before_write "
        "BEFORE INSERT OR UPDATE ON approvals "
        "FOR EACH ROW EXECUTE FUNCTION protect_approval_evidence()"
    )

    op.execute(
        sa.text(
            """
            CREATE FUNCTION protect_outbox_event_evidence() RETURNS trigger
            LANGUAGE plpgsql
            AS $function$
            BEGIN
                IF NEW.id IS DISTINCT FROM OLD.id
                   OR NEW.organization_id IS DISTINCT FROM OLD.organization_id
                   OR NEW.event_id IS DISTINCT FROM OLD.event_id
                   OR NEW.event_type IS DISTINCT FROM OLD.event_type
                   OR NEW.aggregate_type IS DISTINCT FROM OLD.aggregate_type
                   OR NEW.aggregate_id IS DISTINCT FROM OLD.aggregate_id
                   OR NEW.payload IS DISTINCT FROM OLD.payload
                   OR NEW.created_at IS DISTINCT FROM OLD.created_at THEN
                    RAISE EXCEPTION 'outbox immutable evidence cannot be changed';
                END IF;
                RETURN NEW;
            END;
            $function$
            """
        )
    )
    op.execute("ALTER FUNCTION protect_outbox_event_evidence() OWNER TO migration_owner")
    op.execute(
        "CREATE TRIGGER protect_outbox_event_evidence_before_update "
        "BEFORE UPDATE ON outbox_events FOR EACH ROW "
        "EXECUTE FUNCTION protect_outbox_event_evidence()"
    )


def downgrade() -> None:
    tables = (
        "outbox_events",
        "context_references",
        "model_invocations",
        "workflow_events",
        "workflow_jobs",
        "approvals",
        "proposal_versions",
        "proposals",
        "workflow_checkpoints",
        "workflow_runs",
    )
    op.execute(
        sa.text(
            'ALTER TABLE IF EXISTS "proposals" '
            'DROP CONSTRAINT IF EXISTS "fk_proposals_current_version"'
        )
    )
    op.execute(
        sa.text(
            'ALTER TABLE IF EXISTS "proposals" '
            'DROP CONSTRAINT IF EXISTS "fk_proposals_superseded_approval"'
        )
    )
    op.execute(
        sa.text(
            'ALTER TABLE IF EXISTS "proposals" DROP CONSTRAINT IF EXISTS "fk_proposals_approval"'
        )
    )
    for table_name in tables:
        op.drop_table(table_name)
    op.execute("DROP FUNCTION IF EXISTS protect_outbox_event_evidence()")
    op.execute("DROP FUNCTION IF EXISTS protect_approval_evidence()")
    op.execute("DROP FUNCTION IF EXISTS protect_workflow_run_provenance()")
