// Privacy Policy. DRAFT written from the facts in the Terms — replace with the official text after legal review.
// TODO(legal): add the data controller's identity and a contact email for privacy requests.

import { h, list, p, type LegalDocument } from "./legal";

export const PRIVACY: LegalDocument = {
  title: "Privacy Policy",
  lead: "How SynopStudio collects, uses and protects your personal data, and the rights you have over it.",
  version: "1.0",
  effectiveDate: "2026-11-01",
  sections: [
    {
      id: "data-we-collect",
      title: "Data We Collect",
      blocks: [
        list(
          "Account data: your name, email address and password (stored only in hashed form).",
          "Content you provide: uploaded videos or YouTube links, supporting files, project titles and descriptions. This content may include the image and voice of the people recorded.",
          "Generated data: transcripts, speaker attribution, summaries, clips and the editorial decisions you approve.",
          "Sharing data: the email addresses of the people you invite to view a clip.",
          "Billing data: your plan and payment records. Card details are handled by the payment provider, not stored by us.",
          "Technical data: logs, device and browser information needed to keep the service secure and available.",
        ),
      ],
    },
    {
      id: "how-we-use-data",
      title: "How We Use Your Data",
      blocks: [
        list(
          "To provide the service you signed up for: processing your videos with AI to produce transcripts, clips and summaries (performance of a contract).",
          "To keep the platform secure and to record license confirmations and editorial decisions (legal obligation and legitimate interest).",
          "To bill your subscription and keep the required accounting records (legal obligation).",
          "To notify you about changes to the service, the terms or this policy (legal obligation and legitimate interest).",
        ),
        p("We do not sell your personal data."),
      ],
    },
    {
      id: "sharing",
      title: "Who We Share Data With",
      blocks: [
        p(
          "We use service providers to host files, process media with AI, send emails and handle payments. They act on our instructions and are bound by data protection agreements.",
        ),
        p(
          "When you import a video by link, the external platform (e.g., YouTube) processes the request under its own terms and privacy policy.",
        ),
        p("People you invite to view a clip can see only that clip, its title and the name of the person who shared it."),
      ],
    },
    {
      id: "retention",
      title: "How Long We Keep Data",
      blocks: [
        p("We keep your data while your account is active."),
        p(
          "Deleting a project, or closing your account, permanently deletes the uploaded videos, supporting files, transcripts and generated and exported clips from our servers.",
        ),
        p(
          "Billing records and audit records related to license confirmations and editorial decisions are kept for 12 months for legal compliance, and then deleted.",
        ),
      ],
    },
    {
      id: "your-rights",
      title: "Your Rights",
      blocks: [
        p("Under the General Data Protection Regulation (GDPR) you have the right to:"),
        list(
          "Access your personal data and get a copy of it;",
          "Correct inaccurate data;",
          "Have your data deleted;",
          "Restrict or object to certain processing;",
          "Receive your data in a portable format;",
          "Withdraw consent at any time, where processing is based on consent.",
        ),
        p(
          "You can also lodge a complaint with the Portuguese data protection authority (CNPD) or the authority of your country of residence.",
        ),
        h("Minors"),
        p(
          "Users between 13 and 18 years old may only use the service with the authorization of a parent or legal guardian.",
        ),
      ],
    },
    {
      id: "security",
      title: "Security",
      blocks: [
        p(
          "We apply technical and organisational measures appropriate to the risk, such as encrypted connections and restricted access to personal data.",
        ),
      ],
    },
    {
      id: "changes",
      title: "Changes to This Policy",
      blocks: [
        p(
          "Changes that alter the purposes or categories of data processed are communicated to you before they take effect. Each version is numbered and dated, and previous versions remain available for reference.",
        ),
      ],
    },
  ],
};