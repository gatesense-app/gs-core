"""flat occupancy + resident role (owner / tenant)

Revision ID: e2fb68b7676a
Revises: 38844517d3e5
Create Date: 2026-07-21

A flat is occupied by its owner or by a tenant; each resident is labelled owner
or tenant. Occupancy decides which role the gate reaches. Existing residents are
backfilled: the current primary of a flat becomes its owner, everyone else a
tenant, matching how those flats already resolved.

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'e2fb68b7676a'
down_revision: Union[str, Sequence[str], None] = '38844517d3e5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('flats', sa.Column(
        'occupancy', sa.String(length=16), nullable=False, server_default='owner'))
    op.add_column('residents', sa.Column(
        'role', sa.String(length=16), nullable=False, server_default='owner'))

    # Backfill: the person a flat already contacts is its owner; the rest are
    # tenants. Leaves single-resident flats as owners (the default).
    op.execute("UPDATE residents SET role = 'tenant' WHERE is_primary = false")


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('residents', 'role')
    op.drop_column('flats', 'occupancy')
