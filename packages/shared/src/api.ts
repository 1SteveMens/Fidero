import type {
  ApprovalResult,
  Case,
  Dashboard,
  DeletionPreview,
  Errand,
  Escrow,
  FamilyMember,
  Invoice,
  Report,
} from './types';

/**
 * Everything the client app reads or does. The sample implementation serves
 * in-memory data; the HTTP implementation will call the /v1 API in
 * docs/specs/02 section 7 with the same shapes.
 */
export interface FideroApi {
  getDashboard(): Promise<Dashboard>;
  listCases(): Promise<Case[]>;
  getCase(id: string): Promise<Case>;
  getReport(id: string): Promise<Report>;
  getEscrow(id: string): Promise<Escrow>;
  /** The client's approval (RUL-11). Two staff approve after it; the bank pays. */
  approveRelease(escrowId: string, code: string): Promise<ApprovalResult>;
  getInvoice(id: string): Promise<Invoice>;
  approveInvoice(invoiceId: string, code: string): Promise<ApprovalResult>;
  listFamily(): Promise<FamilyMember[]>;
  listErrands(): Promise<Errand[]>;
  previewAccountDeletion(): Promise<DeletionPreview>;
}
