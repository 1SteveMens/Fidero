"""ANL rules enforced again in PostgreSQL: the export log is append-only (FR-ANL-002)."""
from core.dbsql import append_only

SQL = append_only("anl_export_log")
