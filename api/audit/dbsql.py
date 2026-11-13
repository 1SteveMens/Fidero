"""FR-AUD-002: no application path edits or deletes audit entries, anchors or
chain checks. The trigger refuses UPDATE and DELETE for every role."""
from core.dbsql import append_only

SQL = append_only("aud_event") + append_only("aud_anchor") + append_only("aud_chain_check")
