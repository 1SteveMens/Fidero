from rest_framework.pagination import CursorPagination as _Cursor
from rest_framework.response import Response


class CursorPagination(_Cursor):
    """`?limit=25&cursor=...`, response {items, next_cursor} (7.1)."""

    page_size = 25
    page_size_query_param = "limit"
    max_page_size = 100
    ordering = "-created_at"

    def get_paginated_response(self, data):
        nxt = self.get_next_link()
        cursor = None
        if nxt:
            from urllib.parse import parse_qs, urlparse

            cursor = parse_qs(urlparse(nxt).query).get("cursor", [None])[0]
        return Response({"items": data, "next_cursor": cursor})

    def get_paginated_response_schema(self, schema):
        return {"type": "object", "properties": {"items": schema, "next_cursor": {"type": "string", "nullable": True}}}
