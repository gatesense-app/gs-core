"""primary contact per flat + flat-level rules (E6-S3)

Revision ID: c5e83b1d2a47
Revises: b2d47ac91f30
Create Date: 2026-07-16

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'c5e83b1d2a47'
down_revision: Union[str, Sequence[str], None] = 'b2d47ac91f30'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # --- Flat-level rules (E6-S3) ------------------------------------------
    # Nullable on purpose: NULL = "not set, fall back to the primary resident",
    # which is a different statement from [] = "explicitly no rules". Defaulting
    # these to []/{} would mean a society's first reconcile silently overruled
    # every resident's real standing rules — a gate behaviour change shipped by
    # a migration. See backend/tools/resolve.py.
    op.add_column('flats', sa.Column(
        'standing_rules', postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.add_column('flats', sa.Column(
        'delivery_preferences', postgresql.JSONB(astext_type=sa.Text()), nullable=True))

    # --- Primary contact per flat (Q3) -------------------------------------
    op.add_column('residents', sa.Column(
        'is_primary', sa.Boolean(), server_default=sa.text('false'), nullable=False))

    # Backfill BEFORE the unique index exists, so the data can't violate it.
    # The oldest resident of each flat becomes primary — Q3's "first added",
    # and the row today's unordered .first() almost always returned, so this
    # backfill preserves current behaviour rather than reshuffling it.
    # id is the tiebreak: created_at alone is not unique enough to be a total
    # order, and a partial-unique index does not forgive a tie.
    op.execute(
        """
        UPDATE residents r
        SET is_primary = true
        WHERE r.id = (
            SELECT r2.id FROM residents r2
            WHERE r2.society_id = r.society_id
              AND r2.flat_number = r.flat_number
            ORDER BY r2.created_at, r2.id
            LIMIT 1
        );
        """
    )

    # At most one primary per flat, enforced by Postgres. Keyed on flat_number
    # rather than flat_id: it has to hold for unreconciled residents too, whose
    # flat_id is NULL and whose flat_number is what the agents resolve on.
    op.execute(
        """
        CREATE UNIQUE INDEX uq_residents_primary_per_flat
        ON residents (society_id, flat_number)
        WHERE is_primary;
        """
    )

    # --- Escalation is now "another resident of this flat" ------------------
    # The backup contact is no longer a linked resident but whoever else lives
    # behind the same door, so the FK has no reader left. Dropping it rather
    # than leaving a column the API can still set to no effect.
    op.drop_constraint('residents_backup_contact_id_fkey', 'residents', type_='foreignkey')
    op.drop_column('residents', 'backup_contact_id')


def downgrade() -> None:
    """Downgrade schema."""
    op.add_column('residents', sa.Column('backup_contact_id', sa.UUID(), nullable=True))
    op.create_foreign_key(
        'residents_backup_contact_id_fkey', 'residents', 'residents',
        ['backup_contact_id'], ['id'], ondelete='SET NULL',
    )
    op.drop_index('uq_residents_primary_per_flat', table_name='residents')
    op.drop_column('residents', 'is_primary')
    op.drop_column('flats', 'delivery_preferences')
    op.drop_column('flats', 'standing_rules')
