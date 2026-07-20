"""link a re-created flat to its prior soft-deleted flat

Revision ID: 38844517d3e5
Revises: d6f1a9c4e820
Create Date: 2026-07-20

When a flat is created with the same code as a soft-deleted one, the admin may
link the new flat to that prior flat so its history surfaces on the new
timeline. This adds the self-referential pointer that records the link.

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '38844517d3e5'
down_revision: Union[str, Sequence[str], None] = 'd6f1a9c4e820'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        'flats',
        sa.Column('prior_flat_id', postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        'fk_flats_prior_flat_id',
        'flats', 'flats',
        ['prior_flat_id'], ['id'],
        ondelete='SET NULL',
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint('fk_flats_prior_flat_id', 'flats', type_='foreignkey')
    op.drop_column('flats', 'prior_flat_id')
