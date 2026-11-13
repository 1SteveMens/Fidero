"""Template codes, their variables and the content policy per channel
(FR-NTF-002, FR-NTF-004, FR-APP-002).

Each variable has a class:
- safe: may appear on any channel;
- amount: may appear on any channel, but on SMS, WhatsApp and push an amount
  above `ntf_amount_threshold` is left out;
- code: a one-time confirmation code, allowed only in templates that exist to
  carry one (ADR-20);
- sensitive: report contents, account numbers, evidence links and third
  parties' personal data. Never on SMS, WhatsApp or push.

Default texts are used until an administrator saves a template version.
"""
PHONE_CHANNELS = ("sms", "whatsapp", "push")
CHANNELS = ("in_app", "email", "sms", "whatsapp", "push")

VARIABLES = {
    "first_name": "safe", "case_ref": "safe", "status_label": "safe", "task_title": "safe", "due_date": "safe",
    "link": "safe", "subject_label": "safe", "request_label": "safe", "summary": "safe", "recipient_name": "safe",
    "expires_in": "safe", "app_name": "safe", "service_label": "safe", "country_name": "safe",
    "amount": "amount",
    "otp_code": "code",
    "verdict": "sensitive", "findings": "sensitive", "report_summary": "sensitive", "account_number": "sensitive",
    "evidence_link": "sensitive", "payee_name": "sensitive", "assignee_name": "sensitive",
    "family_member_name": "sensitive", "client_name": "sensitive", "address": "sensitive", "body": "sensitive",
}

# Categories: money and safety always go in-app, whatever the preferences.
CATEGORIES = ("status", "task", "request", "approval", "reminder", "money", "safety", "account", "marketing")
MANDATORY_IN_APP = {"money", "safety"}

GENERIC_PHONE = "Tenmina: there is an update for you. Open the app to see it."
GENERIC_ACTION = "Tenmina: you have a request to review. Open the app to see it."

CATALOGUE = {
    "generic": {
        "category": "status", "variables": ["body", "link", "first_name"], "required": [],
        "defaults": {"subject": "An update from Tenmina", "body": "{{ body }}"},
        "phone": GENERIC_PHONE,
    },
    "case_status_changed": {
        "category": "status", "variables": ["first_name", "case_ref", "status_label", "link"],
        "required": ["case_ref", "status_label"],
        "defaults": {"subject": "Case {{ case_ref }}: {{ status_label }}",
                     "body": "Hello {{ first_name }}. Case {{ case_ref }} is now: {{ status_label }}."},
        "phone": "Tenmina: case {{ case_ref }} is now {{ status_label }}. Open the app for details.",
    },
    "task_assigned": {
        "category": "task", "variables": ["first_name", "task_title", "case_ref", "due_date", "link"],
        "required": ["task_title"],
        "defaults": {"subject": "New task: {{ task_title }}",
                     "body": "Hello {{ first_name }}. You have a new task on case {{ case_ref }}: {{ task_title }}. "
                             "It is due on {{ due_date }}."},
        "phone": "Tenmina: you have a new task, due {{ due_date }}. Open the app.",
    },
    "task_due_soon": {
        "category": "reminder", "variables": ["first_name", "task_title", "case_ref", "due_date", "link"],
        "required": ["task_title", "due_date"],
        "defaults": {"subject": "Due on {{ due_date }}: {{ task_title }}",
                     "body": "Hello {{ first_name }}. {{ task_title }} on case {{ case_ref }} is due on {{ due_date }}."},
        "phone": "Tenmina: a task is due on {{ due_date }}. Open the app.",
    },
    "task_overdue": {
        "category": "task", "variables": ["first_name", "task_title", "case_ref", "due_date", "assignee_name", "link"],
        "required": ["task_title", "due_date"],
        "defaults": {"subject": "Overdue: {{ task_title }}",
                     "body": "{{ task_title }} on case {{ case_ref }} was due on {{ due_date }} and is not done. "
                             "It is assigned to {{ assignee_name }}."},
        "phone": "Tenmina: a task is overdue. Open the back office.",
    },
    "approval_needed": {
        "category": "approval", "variables": ["first_name", "subject_label", "amount", "link"],
        "required": ["subject_label", "link"],
        "defaults": {"subject": "Your approval is needed: {{ subject_label }}",
                     "body": "Hello {{ first_name }}. {{ subject_label }} needs your approval ({{ amount }}). "
                             "Nothing is paid until you approve."},
        "phone": GENERIC_ACTION,
    },
    "request_received": {
        "category": "request", "variables": ["first_name", "request_label", "link"], "required": ["request_label"],
        "defaults": {"subject": "We need something from you", "body": "Hello {{ first_name }}. {{ request_label }}"},
        "phone": GENERIC_ACTION,
    },
    "money_update": {
        "category": "money", "variables": ["first_name", "subject_label", "amount", "payee_name", "link"],
        "required": ["subject_label"],
        "defaults": {"subject": "{{ subject_label }}",
                     "body": "Hello {{ first_name }}. {{ subject_label }}: {{ amount }} to {{ payee_name }}."},
        "phone": "Tenmina: {{ subject_label }} ({{ amount }}). Open the app for details.",
    },
    "report_released": {
        "category": "status", "variables": ["first_name", "case_ref", "verdict", "link"], "required": ["case_ref"],
        "defaults": {"subject": "Your report for {{ case_ref }} is ready",
                     "body": "Hello {{ first_name }}. The report for case {{ case_ref }} is ready. "
                             "Verdict: {{ verdict }}."},
        "phone": "Tenmina: your report for case {{ case_ref }} is ready. Open the app to read it.",
    },
    "family_confirmation_code": {
        "category": "safety", "variables": ["recipient_name", "otp_code", "summary", "link", "expires_in"],
        "required": ["otp_code"], "allows_code": True,
        "defaults": {"subject": "Please confirm: {{ summary }}",
                     "body": "Hello {{ recipient_name }}. Tenmina asks you to confirm: {{ summary }}. "
                             "Your code is {{ otp_code }}. Reply with the code or open {{ link }}. "
                             "It works for {{ expires_in }}. Never share it with the carer or agent."},
        "phone": "Tenmina: please confirm {{ summary }}. Code {{ otp_code }}. Or open {{ link }}. "
                 "Valid {{ expires_in }}. Do not share this code.",
    },
    "security_alert": {
        "category": "safety", "variables": ["summary", "link"], "required": ["summary"],
        "defaults": {"subject": "Security alert", "body": "Security alert: {{ summary }}."},
        "phone": "Tenmina: a security alert needs attention. Open the back office.",
    },
}


def entry(code: str) -> dict | None:
    return CATALOGUE.get(code)


def category_of(code: str, default="status") -> str:
    e = CATALOGUE.get(code)
    return e["category"] if e else default
