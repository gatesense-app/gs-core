"""per-society toggle to mask resident phone numbers

Revision ID: 461519e4bd96
Revises: 7782188daa99
Create Date: 2026-07-23

When on, resident mobile numbers are masked (last 4 only) in admin-facing
responses. Off by default, so existing behaviour is unchanged.

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '461519e4bd96'
down_revision: Union[str, Sequence[str], None] = '7782188daa99'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('societies', sa.Column(
        'hide_resident_phones', sa.Boolean(), nullable=False, server_default=sa.text('false')))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('societies', 'hide_resident_phones')
