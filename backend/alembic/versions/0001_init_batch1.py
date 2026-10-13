"""批次1地基：空初始迁移

T01 不建业务表，本迁移仅建立 Alembic 版本表（alembic_version），
为后续批次的 autogenerate 迁移定好 revision 链起点。

Revision ID: 0001
Revises: -
Create Date: 2026-10-14

"""
from typing import Sequence, Union

# revision identifiers, used by Alembic.
revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """T01 无业务表；业务表自批次 2（T02）起以新迁移文件加入，不改本文件。"""
    pass


def downgrade() -> None:
    """与 upgrade 对称：无可回退对象。"""
    pass
