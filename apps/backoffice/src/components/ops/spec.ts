/**
 * Ops screens are described, not hand-built: each back office section lists
 * its resources (a list endpoint, a detail endpoint, the columns, the actions
 * that move the workflow on and the related lists). Form fields come from the
 * API schema (forms.json, built by gen_forms.py) unless a spec overrides them.
 */
import type { ReactNode } from 'react';

// eslint-disable-next-line @typescript-eslint/no-explicit-any
export type Row = Record<string, any>;
export type Opt = { value: string; label: string };

export type FieldType = 'text' | 'textarea' | 'number' | 'date' | 'datetime' | 'select' | 'bool' | 'money' | 'json' | 'list' | 'file' | 'files' | 'textfile' | 'binary' | 'hidden';

export type FieldSpec = {
  name: string;
  label?: string;
  type?: FieldType;
  options?: Opt[] | ((row: Row, parent?: Row) => Opt[]);
  /** Load choices from the API, e.g. verified payees or contacts. */
  source?: { path: string | ((row: Row, parent?: Row) => string); query?: Record<string, unknown>; label: (r: Row) => string; value?: string };
  required?: boolean;
  hint?: string;
  default?: unknown | ((row: Row, parent?: Row) => unknown);
  /** For a file field: the evidence subject the upload belongs to. */
  upload?: { subject_type: string; role?: string; subjectId?: (row: Row, parent?: Row) => string };
  /** For a textfile field: also put the file's name in this field. */
  fileNameField?: string;
};

export type ActionSpec = {
  label: string;
  /** Path with {id} (the row, or the parent on a related list), {sub} (the related row) or {field}. */
  path: string;
  method?: 'POST' | 'PUT' | 'PATCH' | 'DELETE' | 'GET';
  /** Extra or replacement fields; others come from the schema. */
  fields?: FieldSpec[];
  only?: string[];
  omit?: string[];
  /** Body values set by the screen, not typed by staff. */
  fixed?: Record<string, unknown> | ((row: Row, parent?: Row) => Record<string, unknown>);
  tone?: 'primary' | 'dark' | 'ghost' | 'danger';
  /** Ask for the authenticator code first (approvals, releases, rights). */
  mfa?: boolean;
  /** Press and hold to confirm (money moves or an irreversible step). */
  hold?: boolean;
  /** Dialog on a black ground (money approvals). */
  ink?: boolean;
  /** One plain sentence on what happens. */
  confirm?: string | ((row: Row, parent?: Row) => string);
  when?: (row: Row, parent?: Row) => boolean;
  roles?: string[];
  done?: string;
  /** Download the response as a file instead of posting. */
  download?: string;
  /** Show the response (a new secret, a file hash) after the action. */
  showResult?: boolean;
  goto?: (result: Row, row: Row) => string | undefined;
};

export type ColKind = 'ref' | 'status' | 'money' | 'date' | 'when' | 'verdict' | 'bool' | 'text' | 'mono' | 'count' | 'name';
export type Col = { key: string; label: string; kind?: ColKind; render?: (row: Row) => ReactNode };

export type SubSpec = {
  label: string;
  /** Fetch from this path (with {id} of the parent), or read an array field of the parent. */
  path?: string;
  from?: string;
  query?: Record<string, unknown> | ((parent: Row) => Record<string, unknown>);
  columns?: Col[];
  /** Section-relative link for a row, e.g. 'invoices' opens /fees/invoices/{row.id}. */
  link?: string | ((r: Row) => string | undefined);
  actions?: ActionSpec[];
  create?: ActionSpec;
  note?: string;
  when?: (parent: Row) => boolean;
};

export type ResourceSpec = {
  key: string;
  label: string;
  list: string;
  listQuery?: Record<string, unknown> | ((me: { home_country: string | null; roles: string[] } | null) => Record<string, unknown>);
  /** Detail path with {id}; null for lists whose rows do not open. Default list + '/{id}'. */
  detail?: string | null;
  columns: Col[];
  /** Query parameters offered as filters. 'status' uses the statuses from the schema. */
  filters?: string[];
  title?: (r: Row) => string;
  intro?: string;
  screen?: string;
  create?: ActionSpec;
  actions?: ActionSpec[];
  /** Actions on each list row, for rows that do not open. */
  rowActions?: ActionSpec[];
  subs?: SubSpec[];
  hide?: string[];
  /** Evidence subject_type for uploads on this resource. */
  subject?: string;
  roles?: string[];
  /** Field (dotted) that names the detail; rows with the same value show once. */
  idKey?: string;
  /** Fields that open another screen: resource key in this section, or an absolute path prefix. */
  links?: Record<string, string>;
  /** Not a tab: reached only from links. */
  hidden?: boolean;
};

export type SectionSpec = {
  href: string;
  title: string;
  intro: string;
  screens?: string;
  resources: ResourceSpec[];
};
