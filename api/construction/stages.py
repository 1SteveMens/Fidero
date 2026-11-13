"""What the contractor captures and what the inspector checks at each standard stage. Working defaults that a
country may replace in its configuration (`construction.stage_evidence`, `construction.stage_checklists`)
[TO VERIFY with the founder's quantity surveyor and inspector]."""

P = "photo"
V = "video"


def _e(key, label, media=P, required=True):
    return {"key": key, "label": label, "media": media, "required": required}


def _c(key, label):
    return {"key": key, "label": label}


EVIDENCE = {
    "mobilisation": [],
    "foundation": [_e("trench_depth_photo", "Trench depth against a tape"), _e("rebar_photo", "Rebar in place"),
                   _e("trench_walk_video", "Walk along the trenches", V)],
    "blocks": [_e("walls_photo", "Each wall to the agreed height"), _e("blocks_walk_video", "Walk around", V)],
    "lintel": [_e("lintel_photo", "Lintel beam and formwork"), _e("columns_photo", "Columns")],
    "roof": [_e("roof_frame_photo", "Roof frame"), _e("roof_sheets_photo", "Roof sheets fixed"),
             _e("roof_walk_video", "Walk around the roof line", V)],
    "finishing": [_e("rooms_photo", "Each room finished"), _e("services_photo", "Plumbing and wiring")],
    "handover": [_e("front_photo", "Front of the house"), _e("keys_photo", "Keys handed over"),
                 _e("handover_walk_video", "Walk through every room", V)],
    "retention": [_e("defects_fixed_photo", "Every listed defect fixed")],
}
DEFAULT_EVIDENCE = [_e("stage_photo", "The finished stage"), _e("stage_walk_video", "Walk around the stage", V)]

CHECKLISTS = {
    "foundation": [_c("trench_depth", "Trench depth as drawn"), _c("rebar_spacing", "Rebar spacing"),
                   _c("concrete_mix", "Concrete mix and cover")],
    "blocks": [_c("wall_height", "Walls at the agreed height"), _c("plumb", "Walls plumb and true"),
               _c("block_quality", "Block quality")],
    "lintel": [_c("lintel_level", "Lintel level"), _c("column_rebar", "Column rebar and cover")],
    "roof": [_c("roof_frame", "Roof frame fixed and treated"), _c("sheets", "Sheets fixed and sealed")],
    "finishing": [_c("plaster", "Plaster and screed"), _c("services", "Plumbing and wiring work"),
                  _c("doors_windows", "Doors and windows")],
    "handover": [_c("complete", "Work complete to the drawings"), _c("snag_list", "Snag list recorded")],
    "retention": [_c("defects_closed", "Every defect from earlier inspections is fixed"),
                  _c("no_new_defects", "No new defects in the defects period")],
}
DEFAULT_CHECKLIST = [_c("stage_complete", "The stage is complete as agreed"),
                     _c("quality", "The quality matches the agreed standard")]

FUNDS_CHECKLIST = [_c("work_seen", "The work or goods paid for are there"),
                   _c("receipts_match", "Receipts match what is on site")]


def evidence_for(country, key):
    from countries.selectors import config

    custom = config(country, "construction.stage_evidence", {}) or {}
    return list(custom.get(key, EVIDENCE.get(key, DEFAULT_EVIDENCE)))


def checklist_for(country, key, funds=False):
    from countries.selectors import config

    if funds:
        return list(FUNDS_CHECKLIST)
    custom = config(country, "construction.stage_checklists", {}) or {}
    return list(custom.get(key, CHECKLISTS.get(key, DEFAULT_CHECKLIST)))
