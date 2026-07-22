"""assign a vehicle to a parking number

Revision ID: 9fd5de51a88c
Revises: 4e703fd7aff7
Create Date: 2026-07-22

A vehicle may be assigned to one of its flat's parking numbers.

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '9fd5de51a88c'
down_revision: Union[str, Sequence[str], None] = '4e703fd7aff7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('vehicles', sa.Column('parking_slot_id', sa.UUID(), nullable=True))
    op.create_foreign_key(
        'fk_vehicles_parking_slot_id', 'vehicles', 'parking_slots',
        ['parking_slot_id'], ['id'], ondelete='SET NULL',
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint('fk_vehicles_parking_slot_id', 'vehicles', type_='foreignkey')
    op.drop_column('vehicles', 'parking_slot_id')
