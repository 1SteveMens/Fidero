"""PTR rules enforced again in PostgreSQL: the metering log is append-only (FR-PTR-004)."""
from core.dbsql import append_only

SQL = [*append_only("ptr_usage_event")]
