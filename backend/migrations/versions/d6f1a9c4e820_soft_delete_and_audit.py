"""soft delete + layout audit trail

Revision ID: d6f1a9c4e820
Revises: c5e83b1d2a47
Create Date: 2026-07-17

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'd6f1a9c4e820'
down_revision: Union[str, Sequence[str], None] = 'c5e83b1d2a47'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # --- Soft delete: keep the row, mark it gone --------------------------
    op.add_column('flats', sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('residents', sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True))

    # The flat-code uniqueness must ignore deleted rows, or a soft-deleted
    # A-101 would forever block creating A-101 again. Swap the plain constraint
    # for a partial unique index.
    op.drop_constraint('uq_flats_society_code', 'flats', type_='unique')
    op.execute(
        "CREATE UNIQUE INDEX uq_flats_society_code ON flats (society_id, code) "
        "WHERE deleted_at IS NULL;"
    )

    # "One primary per flat" must likewise ignore a soft-deleted primary, so a
    # live resident can take the slot a removed one vacated.
    op.drop_index('uq_residents_primary_per_flat', table_name='residents')
    op.execute(
        "CREATE UNIQUE INDEX uq_residents_primary_per_flat ON residents "
        "(society_id, flat_number) WHERE is_primary AND deleted_at IS NULL;"
    )

    # --- Audit trail (the timeline) ---------------------------------------
    op.create_table(
        'layout_events',
        sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('society_id', sa.UUID(), nullable=False),
        sa.Column('flat_id', sa.UUID(), nullable=True),
        sa.Column('flat_code', sa.String(length=64), nullable=True),
        sa.Column('entity_type', sa.String(length=16), nullable=False),
        sa.Column('entity_id', sa.UUID(), nullable=False),
        sa.Column('action', sa.String(length=40), nullable=False),
        sa.Column('summary', sa.Text(), nullable=False),
        sa.Column('detail', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('actor_user_id', sa.UUID(), nullable=True),
        sa.Column('actor_email', sa.String(length=255), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['society_id'], ['societies.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    # Timeline reads are "this flat, newest first".
    op.create_index('ix_layout_events_flat', 'layout_events', ['flat_id', 'created_at'])

    # RLS: a tenant table without a policy is a silent cross-society leak. New
    # tables also need the grant (the initial ON ALL TABLES only covered what
    # existed then).
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON layout_events TO app_rls;")
    op.execute("ALTER TABLE layout_events ENABLE ROW LEVEL SECURITY;")
    op.execute(
        """
        CREATE POLICY tenant_isolation ON layout_events
        USING (
            current_setting('app.bypass_rls', true) = 'on'
            OR society_id::text = current_setting('app.current_society_id', true)
        )
        WITH CHECK (
            current_setting('app.bypass_rls', true) = 'on'
            OR society_id::text = current_setting('app.current_society_id', true)
        );
        """
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('layout_events')  # policy drops with the table

    op.drop_index('uq_residents_primary_per_flat', table_name='residents')
    op.execute(
        "CREATE UNIQUE INDEX uq_residents_primary_per_flat ON residents "
        "(society_id, flat_number) WHERE is_primary;"
    )
    op.drop_index('uq_flats_society_code', table_name='flats')
    op.create_unique_constraint('uq_flats_society_code', 'flats', ['society_id', 'code'])

    op.drop_column('residents', 'deleted_at')
    op.drop_column('flats', 'deleted_at')
