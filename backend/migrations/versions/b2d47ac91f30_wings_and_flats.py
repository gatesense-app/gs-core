"""wings and flats (E4-S1 / E4-S2)

Revision ID: b2d47ac91f30
Revises: f716e16ce78b
Create Date: 2026-07-16

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'b2d47ac91f30'
down_revision: Union[str, Sequence[str], None] = 'f716e16ce78b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('wings',
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('society_id', sa.UUID(), nullable=False),
    sa.Column('name', sa.String(length=64), nullable=False),
    sa.Column('floors', sa.Integer(), nullable=False),
    sa.Column('flats_per_floor', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['society_id'], ['societies.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('society_id', 'name', name='uq_wings_society_name')
    )
    op.create_table('flats',
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('society_id', sa.UUID(), nullable=False),
    sa.Column('wing_id', sa.UUID(), nullable=False),
    sa.Column('flat_number', sa.String(length=32), nullable=False),
    sa.Column('floor', sa.Integer(), nullable=False),
    sa.Column('code', sa.String(length=64), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['society_id'], ['societies.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['wing_id'], ['wings.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('society_id', 'code', name='uq_flats_society_code')
    )
    # The guard types a flat code; this is the index that lookup rides on (D1).
    op.create_index('ix_flats_society_code', 'flats', ['society_id', 'code'])

    # Nullable: existing free-text residents are linked by E4-S4 (reconcile).
    op.add_column('residents', sa.Column('flat_id', sa.UUID(), nullable=True))
    op.create_foreign_key(
        'fk_residents_flat_id', 'residents', 'flats', ['flat_id'], ['id'], ondelete='SET NULL'
    )

    # --- Row-Level Security ------------------------------------------------
    # Without a policy a tenant table is a silent cross-society leak. New tables
    # also need the grant: the initial migration's GRANT ... ON ALL TABLES only
    # covered the tables that existed when it ran.
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON wings, flats TO app_rls;")
    for table in ("wings", "flats"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;")
        op.execute(
            f"""
            CREATE POLICY tenant_isolation ON {table}
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
    op.drop_constraint('fk_residents_flat_id', 'residents', type_='foreignkey')
    op.drop_column('residents', 'flat_id')
    op.drop_index('ix_flats_society_code', table_name='flats')
    # Policies drop with their tables.
    op.drop_table('flats')
    op.drop_table('wings')
