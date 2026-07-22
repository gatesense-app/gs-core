"""vehicle records and parking numbers per flat

Revision ID: 4e703fd7aff7
Revises: b8cc5d53b2b3
Create Date: 2026-07-22

Each flat keeps vehicle records (registration number, type, RC-book owner) and a
list of parking numbers allotted by the society. Both are soft-deleted for
history and reported onto the flat timeline.

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '4e703fd7aff7'
down_revision: Union[str, Sequence[str], None] = 'b8cc5d53b2b3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _rls(table: str) -> None:
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO app_rls;")
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


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'vehicles',
        sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('society_id', sa.UUID(), nullable=False),
        sa.Column('flat_id', sa.UUID(), nullable=False),
        sa.Column('flat_code', sa.String(length=64), nullable=False),
        sa.Column('registration_number', sa.String(length=20), nullable=False),
        sa.Column('vehicle_type', sa.String(length=16), nullable=False),
        sa.Column('owner_name', sa.String(length=200), nullable=False),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['society_id'], ['societies.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['flat_id'], ['flats.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_vehicles_flat', 'vehicles', ['flat_id'])
    op.execute(
        "CREATE UNIQUE INDEX uq_vehicle_reg_per_society ON vehicles "
        "(society_id, registration_number) WHERE deleted_at IS NULL;"
    )

    op.create_table(
        'parking_slots',
        sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('society_id', sa.UUID(), nullable=False),
        sa.Column('flat_id', sa.UUID(), nullable=False),
        sa.Column('flat_code', sa.String(length=64), nullable=False),
        sa.Column('parking_number', sa.String(length=32), nullable=False),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['society_id'], ['societies.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['flat_id'], ['flats.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_parking_slots_flat', 'parking_slots', ['flat_id'])
    op.execute(
        "CREATE UNIQUE INDEX uq_parking_number_per_society ON parking_slots "
        "(society_id, parking_number) WHERE deleted_at IS NULL;"
    )

    _rls('vehicles')
    _rls('parking_slots')


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('parking_slots')  # policy + indexes drop with the table
    op.drop_table('vehicles')
