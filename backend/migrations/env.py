from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from app.core.config import settings
from app.core.database import Base

# Import every model module here so Base.metadata is fully populated before
# autogenerate runs. Add new modules to this list as they're built.
from app.companies import models as companies_models  # noqa: F401
from app.users import models as users_models  # noqa: F401
from app.inventory import models as inventory_models  # noqa: F401
from app.inventory import stock as stock_models  # noqa: F401
from app.partners import models as partner_models  # noqa: F401
from app.sales import models as sales_models  # noqa: F401
from app.gatepass import models as gatepass_models  # noqa: F401
from app.procurement import models as procurement_models  # noqa: F401
from app.common import numbering as numbering_models  # noqa: F401
from app.finance import models as finance_models  # noqa: F401
from app.audit import models as audit_models  # noqa: F401
from app.receivables import models as receivables_models  # noqa: F401
from app.hrms import models as hrms_models  # noqa: F401

config = context.config
config.set_main_option("sqlalchemy.url", settings.DATABASE_URL)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=settings.DATABASE_URL,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
