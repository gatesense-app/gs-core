"""tenancy agreements for tenant-occupied flats

Revision ID: b8cc5d53b2b3
Revises: e2fb68b7676a
Create Date: 2026-07-21

A tenant-occupied flat manages a tenancy: start/end dates, renewable (cloned into
a new tenancy), endable early. Tenants are residents (role='tenant') linked to the
tenancy. At most one tenancy is active per flat.

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'b8cc5d53b2b3'
down_revision: Union[str, Sequence[str], None] = 'e2fb68b7676a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'tenancies',
        sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('society_id', sa.UUID(), nullable=False),
        sa.Column('flat_id', sa.UUID(), nullable=False),
        sa.Column('flat_code', sa.String(length=64), nullable=False),
        sa.Column('start_date', sa.Date(), nullable=True),
        sa.Column('end_date', sa.Date(), nullable=True),
        sa.Column('ended_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('prior_tenancy_id', sa.UUID(), nullable=True),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['society_id'], ['societies.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['flat_id'], ['flats.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['prior_tenancy_id'], ['tenancies.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_tenancies_flat', 'tenancies', ['flat_id'])
    # One active tenancy per flat.
    op.execute(
        "CREATE UNIQUE INDEX uq_active_tenancy_per_flat ON tenancies "
        "(society_id, flat_id) WHERE ended_at IS NULL AND deleted_at IS NULL;"
    )

    # A tenant resident points back at its tenancy.
    op.add_column('residents', sa.Column('tenancy_id', sa.UUID(), nullable=True))
    op.create_foreign_key(
        'fk_residents_tenancy_id', 'residents', 'tenancies',
        ['tenancy_id'], ['id'], ondelete='SET NULL',
    )

    # RLS: a tenant table without a policy is a silent cross-society leak. New
    # tables also need the grant (mirrors layout_events).
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON tenancies TO app_rls;")
    op.execute("ALTER TABLE tenancies ENABLE ROW LEVEL SECURITY;")
    op.execute(
        """
        CREATE POLICY tenant_isolation ON tenancies
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
    op.drop_constraint('fk_residents_tenancy_id', 'residents', type_='foreignkey')
    op.drop_column('residents', 'tenancy_id')
    op.drop_table('tenancies')  # policy + indexes drop with the table
