"""Add administrator roles and support ordinary control-plane users."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0015_system_users"
down_revision: str | Sequence[str] | None = "0014_agent4api_brand"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("admin_users") as batch_op:
        batch_op.drop_constraint("ck_single_admin", type_="check")
        batch_op.add_column(
            sa.Column("role", sa.String(16), nullable=False, server_default="user")
        )
        batch_op.create_check_constraint(
            "ck_admin_user_role", "role IN ('admin', 'user')"
        )
    op.execute("UPDATE admin_users SET role = 'admin' WHERE id = 1")


def downgrade() -> None:
    op.execute("DELETE FROM admin_users WHERE id <> 1")
    with op.batch_alter_table("admin_users") as batch_op:
        batch_op.drop_constraint("ck_admin_user_role", type_="check")
        batch_op.drop_column("role")
        batch_op.create_check_constraint("ck_single_admin", "id = 1")
