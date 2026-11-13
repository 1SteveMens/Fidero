"""Hooks project lines register with BLD, so the shared project engine never imports them.

PRJ (projectfunds) registers the `funds` project type:

    from construction import registry
    registry.register_type("funds", create=create_fund_project, start_blockers=fn, dashboard=fn)

- create(person, data: dict) -> Project              POST /v1/projects with that type
- start_blockers(project) -> [reason]                 checks before money is accepted or the project starts
- dashboard(project, person) -> dict                  extra sections on GET /v1/projects/{id}/dashboard
"""
_types: dict = {}


def register_type(project_type, *, create=None, start_blockers=None, dashboard=None):
    _types[project_type] = {"create": create, "start_blockers": start_blockers, "dashboard": dashboard}


def hook(project_type, name):
    return (_types.get(project_type) or {}).get(name)
