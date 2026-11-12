"""Database-level enforcement installed after every migrate (ADR-02).

Rules are enforced twice: in services and again in PostgreSQL. Triggers live
here, not in migrations, so they are always current and migrations stay
plain. A module adds its own statements in `<module>/dbsql.py` as a list
`SQL = ["CREATE OR REPLACE ...", ...]`; they must be idempotent.
"""
import importlib
import logging

from django.apps import apps
from django.db import connection

log = logging.getLogger(__name__)

CORE_SQL = [
    """
    CREATE OR REPLACE FUNCTION core_enforce_transition() RETURNS trigger AS $$
    DECLARE frm text; tov text;
    BEGIN
      frm := to_jsonb(OLD) ->> TG_ARGV[1];
      tov := to_jsonb(NEW) ->> TG_ARGV[1];
      IF tov IS DISTINCT FROM frm AND NOT EXISTS (
        SELECT 1 FROM core_allowed_transition
         WHERE entity = TG_ARGV[0] AND from_status = frm AND to_status = tov) THEN
        RAISE EXCEPTION 'Transition % -> % is not allowed for %', frm, tov, TG_ARGV[0]
          USING ERRCODE = 'check_violation';
      END IF;
      RETURN NEW;
    END $$ LANGUAGE plpgsql;
    """,
    """
    CREATE OR REPLACE FUNCTION core_approval_not_preparer() RETURNS trigger AS $$
    BEGIN
      IF EXISTS (SELECT 1 FROM core_approval_request r
                  WHERE r.id = NEW.request_id AND r.prepared_by_id = NEW.approver_id) THEN
        RAISE EXCEPTION 'The preparer cannot approve' USING ERRCODE = 'check_violation';
      END IF;
      IF NEW.approved_at - NEW.mfa_at > interval '5 minutes' THEN
        RAISE EXCEPTION 'MFA step-up is not fresh' USING ERRCODE = 'check_violation';
      END IF;
      RETURN NEW;
    END $$ LANGUAGE plpgsql;
    """,
    "DROP TRIGGER IF EXISTS trg_core_approval_not_preparer ON core_approval;",
    """CREATE TRIGGER trg_core_approval_not_preparer BEFORE INSERT ON core_approval
       FOR EACH ROW EXECUTE FUNCTION core_approval_not_preparer();""",
    """
    CREATE OR REPLACE FUNCTION core_append_only() RETURNS trigger AS $$
    BEGIN
      RAISE EXCEPTION '% is append-only', TG_TABLE_NAME USING ERRCODE = 'insufficient_privilege';
    END $$ LANGUAGE plpgsql;
    """,
]


def append_only(table: str) -> list[str]:
    """SQL that makes `table` append-only (no UPDATE, no DELETE)."""
    return [
        f"DROP TRIGGER IF EXISTS trg_{table}_append_only ON {table};",
        f"""CREATE TRIGGER trg_{table}_append_only BEFORE UPDATE OR DELETE ON {table}
            FOR EACH ROW EXECUTE FUNCTION core_append_only();""",
    ]


def _transition_sql():
    from . import state

    stmts, rows = [], []
    for m in state.REGISTRY.values():
        stmts.append(f"DROP TRIGGER IF EXISTS trg_{m.entity}_transition ON {m.table};")
        stmts.append(
            f"CREATE TRIGGER trg_{m.entity}_transition BEFORE UPDATE ON {m.table} FOR EACH ROW "
            f"EXECUTE FUNCTION core_enforce_transition('{m.entity}', '{m.field}');"
        )
        for frm, tos in m.transitions.items():
            rows.extend((m.entity, frm, to) for to in tos)
    return stmts, rows


def install():
    from . import state

    module_sql = []
    for cfg in apps.get_app_configs():
        try:
            mod = importlib.import_module(f"{cfg.name}.dbsql")
        except ModuleNotFoundError:
            continue
        if cfg.name != "core":
            module_sql.extend(getattr(mod, "SQL", []))
    stmts, rows = _transition_sql()
    existing = set(connection.introspection.table_names())
    with connection.cursor() as cur:
        for s in CORE_SQL:
            cur.execute(s)
        cur.execute("DELETE FROM core_allowed_transition WHERE entity = ANY(%s)", [list(state.REGISTRY)])
        for r in rows:
            cur.execute(
                "INSERT INTO core_allowed_transition (entity, from_status, to_status) VALUES (%s, %s, %s)", r)
        for s in stmts + module_sql:
            table_hint = s.split(" ON ")[-1].split()[0].rstrip(";") if " ON " in s else None
            if table_hint and table_hint not in existing:
                continue
            cur.execute(s)


def install_after_migrate(sender, **kwargs):
    if sender.name == "core":
        install()
