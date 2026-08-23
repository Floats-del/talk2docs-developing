"""add multi index vdb statuses

Revision ID: 80e71439ccf1
Revises: d391a5a8a2a7
Create Date: 2026-08-15 01:03:05.565367
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "80e71439ccf1"
down_revision = "d391a5a8a2a7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Upgrade schema."""

    multi_index_status = sa.Enum(
        "PENDING",
        "PROCESSING",
        "READY",
        "FAILED",
        name="multiindexstatus",
    )

    # Create PostgreSQL enum type
    multi_index_status.create(
        op.get_bind(),
        checkfirst=True,
    )

    # Add summary VDB status
    op.add_column(
        "documents",
        sa.Column(
            "summary_vdb_status",
            multi_index_status,
            nullable=False,
            server_default="PENDING",
        ),
    )

    # Add explanation VDB status
    op.add_column(
        "documents",
        sa.Column(
            "explanation_vdb_status",
            multi_index_status,
            nullable=False,
            server_default="PENDING",
        ),
    )

    # Create indexes
    op.create_index(
        "ix_documents_summary_vdb_status",
        "documents",
        ["summary_vdb_status"],
    )

    op.create_index(
        "ix_documents_explanation_vdb_status",
        "documents",
        ["explanation_vdb_status"],
    )


def downgrade() -> None:
    """Downgrade schema."""

    # Drop indexes first
    op.drop_index(
        "ix_documents_explanation_vdb_status",
        table_name="documents",
    )

    op.drop_index(
        "ix_documents_summary_vdb_status",
        table_name="documents",
    )

    # Drop columns
    op.drop_column(
        "documents",
        "explanation_vdb_status",
    )

    op.drop_column(
        "documents",
        "summary_vdb_status",
    )

    # Drop PostgreSQL enum type
    multi_index_status = sa.Enum(
        "PENDING",
        "PROCESSING",
        "READY",
        "FAILED",
        name="multiindexstatus",
    )

    multi_index_status.drop(
        op.get_bind(),
        checkfirst=True,
    )