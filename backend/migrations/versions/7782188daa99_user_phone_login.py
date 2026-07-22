"""resident phone login: users.phone + nullable email

Revision ID: 7782188daa99
Revises: 9fd5de51a88c
Create Date: 2026-07-22

Resident logins provisioned in bulk from imported residents sign in by phone
(they have no email). Add a unique phone identifier and relax email to nullable.

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '7782188daa99'
down_revision: Union[str, Sequence[str], None] = '9fd5de51a88c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('users', sa.Column('phone', sa.String(length=32), nullable=True))
    op.execute(
        "CREATE UNIQUE INDEX uq_users_phone ON users (phone) WHERE phone IS NOT NULL;"
    )
    op.alter_column('users', 'email', existing_type=sa.String(length=255), nullable=True)


def downgrade() -> None:
    """Downgrade schema."""
    # A phone-only account has no email; give it one so the NOT NULL can return.
    op.execute("UPDATE users SET email = 'phone-' || id || '@invalid.local' WHERE email IS NULL;")
    op.alter_column('users', 'email', existing_type=sa.String(length=255), nullable=False)
    op.drop_index('uq_users_phone', table_name='users')
    op.drop_column('users', 'phone')
