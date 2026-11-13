"""Build forms.json for the back office ops screens from the API's OpenAPI schema.

Run after `pnpm --filter @tenmina/api-client generate`:
    /home/user/.venv-tenmina/bin/python apps/backoffice/src/components/ops/gen_forms.py

For every POST, PUT and PATCH it keeps the request fields (name, type, enum,
format, required, a short description). For every list GET it keeps the query
parameters and, where the response schema has one, the list of statuses.
"""
import json
import pathlib
import re

import yaml

HERE = pathlib.Path(__file__).resolve().parent
SPEC = HERE.parents[4] / "packages" / "api-client" / "openapi.yaml"
d = yaml.safe_load(SPEC.read_text())
comps = d["components"]["schemas"]


def res(s):
    seen = 0
    while isinstance(s, dict) and "$ref" in s and seen < 20:
        s = comps[s["$ref"].split("/")[-1]]
        seen += 1
    if isinstance(s, dict) and "allOf" in s and len(s["allOf"]) == 1:
        return res(s["allOf"][0])
    if isinstance(s, dict) and "oneOf" in s:
        opts = [res(x) for x in s["oneOf"]]
        enums = [e for o in opts for e in (o.get("enum") or []) if e not in ("", None)]
        if enums:
            return {"type": "string", "enum": enums}
        return opts[0] if opts else {}
    return s or {}


def short(desc):
    if not desc:
        return None
    desc = re.sub(r"\n?\* `[^`]*` - .*", "", desc).strip()
    return desc[:200] or None


def field(name, s, required):
    s = res(s)
    t = s.get("type")
    if isinstance(t, list):
        t = next((x for x in t if x != "null"), "string")
    f = {"n": name}
    if t and t != "string":
        f["t"] = t
    if s.get("enum"):
        f["e"] = [e for e in s["enum"] if e not in ("", None)]
    if s.get("format") in ("uuid", "date", "date-time", "email", "uri", "decimal", "binary"):
        f["f"] = s["format"]
    if t == "array":
        it = res(s.get("items", {}))
        f["i"] = it.get("type") or ("object" if it.get("properties") else "string")
    if s.get("properties") and set(s["properties"]) >= {"amount", "currency"}:
        f["t"] = "money"
    if required:
        f["r"] = 1
    desc = short(s.get("description"))
    if desc:
        f["d"] = desc
    return f


out = {}
for p, ops in d["paths"].items():
    if not p.startswith("/v1/"):
        continue
    for m, op in ops.items():
        if m in ("post", "put", "patch"):
            content = op.get("requestBody", {}).get("content", {})
            sch = content.get("application/json", {}).get("schema") or content.get("multipart/form-data", {}).get("schema")
            fields = []
            if sch:
                sch = res(sch)
                req = set(sch.get("required", []))
                for k, v in (sch.get("properties") or {}).items():
                    if res(v).get("readOnly"):
                        continue
                    fields.append(field(k, v, k in req))
            out[f"{m.upper()} {p}"] = fields
        elif m == "get":
            params = [x for x in op.get("parameters", []) if x.get("in") == "query" and x["name"] not in ("cursor", "limit")]
            statuses = None
            try:
                s = res(op["responses"]["200"]["content"]["application/json"]["schema"])
                item = None
                if "items" in (s.get("properties") or {}):
                    item = res(s["properties"]["items"].get("items", {}))
                elif s.get("type") == "array":
                    item = res(s.get("items", {}))
                if item and "status" in (item.get("properties") or {}):
                    statuses = res(item["properties"]["status"]).get("enum")
            except KeyError:
                pass
            if params or statuses:
                out[f"GET {p}"] = {"q": [x["name"] for x in params], **({"s": [x for x in statuses if x]} if statuses else {})}

(HERE / "forms.json").write_text(json.dumps(out, separators=(",", ":"), sort_keys=True))
print(f"{len(out)} entries")
