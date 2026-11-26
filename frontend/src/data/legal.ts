// Shared shape of the legal documents (Terms, Privacy). Bump `version` and `effectiveDate` on every change.

export type LegalBlock =
  | { type: "paragraph"; text: string }
  | { type: "heading"; text: string }
  | { type: "list"; items: string[] };

export interface LegalSection {
  id: string;
  title: string;
  blocks: LegalBlock[];
}

export interface LegalDocument {
  title: string;
  lead: string;
  version: string;
  effectiveDate: string;
  sections: LegalSection[];
}

export const p = (text: string): LegalBlock => ({ type: "paragraph", text });
export const h = (text: string): LegalBlock => ({ type: "heading", text });
export const list = (...items: string[]): LegalBlock => ({ type: "list", items });