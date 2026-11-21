# Cross-reference check: measurement on the two test RFPs

Purpose: the TODO in `src/fact_extractor/xref.py` proposes replacing the code-only check with a
model-finds / code-verifies design, after first counting what the current check finds and misses and
comparing with what the CHECK call already finds. This is that count. No code was changed.

Method. Tagged text from `fact-extractor tag` for both PDFs; `xref.check()` and its regexes run on the
tagged document in code (no model calls); every referencing phrase found by a hand read of the tagged
text (see-section, Attachment/Appendix/Schedule/Article, "above/below", subsections, named forms and
templates); Durham facts from `runs/durham-rfp24-0031/run_2026_11_21_2857f5/facts.json`. There is no
stored Ulster run, so the CHECK column for Ulster is "not measured". Hand counts are approximate (one
phrase naming several targets, such as "Attachments C, D, E, and F", is counted once); the mismatch
lists are the careful part.

## Summary

| | Durham (Oracle ERP) | Ulster (Actuarial) |
|---|---|---|
| References found by hand | ~37 | ~75 (about 49 in-document, 13 to statutes or other documents, ~13 in forms and checklists xref cannot see) |
| Phrases xref's regex sees | 13 | 62 (49 in-document, 13 statutory/external) |
| Of those, actually compared with a heading | 0 | 40 |
| Real mismatches (by hand) | 6 | 3 |
| Caught by xref | 0 | 1 |
| Caught by CHECK | 2 | not measured (no run) |
| Caught by neither | 4 | at least 2 |

Durham: xref wrote no XREF fact in the run (the report has no `xref_conflicts`; no fact has source_call
XREF). Reproduced in code: `_headings()` returns an empty dict for Durham, because every heading is
"1.1. Purpose" style with no kind word, so all 13 sightings are dropped at the `kind not in
kinds_present` test. Ulster: xref's only fact is the Article 17 one.

## Durham: references

Unit ids refer to the tagged text. "Target" is the document heading or text the reference points at.

| Unit | Phrase | Intended target | xref |
|---|---|---|---|
| p5.22 | "RFP #24-0031 Appendix A - Model Services Contract" | external, not in the PDF | sees, skips |
| p5.15 | "any attached schedules" | external/vague | no |
| p4.11 | "the figure below" | image, no text target | no |
| p7.5 | "Table 1" | Table 1 caption on p7 | no |
| p7.6 | "Appendix B" (applications and disposition) | external, not in the PDF | sees, skips |
| p20.4 | "Refer to Appendix B" | same | sees, skips |
| p20.5 | "attached RFP #24-0031 Proponent Application Inventory list" | probably Appendix B (name differs) | no |
| p11.5 / p13.4 | Workforce Diversity Questionnaire "online form" link | 3.9 (p11.h1) | no |
| p11.10 | "Attachment A - EBOP fillable ..." | external attachment | sees, skips |
| p11.11 | "the form is included in attachment A" | external attachment | sees, skips |
| p12.26 | "Attachment A - EBOP Instruction and Fillable Form" | external attachment | sees, skips |
| p14.17 | "Workforce Diversity form: completed Attachment A" | conflicts with p11.10/p12.26 (A is EBOP) | sees, skips |
| p14.18 | "Equal Business Opportunity Program Procurement Forms: completed Attachment B" | conflicts with p12.26 | sees, skips |
| p12.24 | "RFP #24-0031 Proponent Response Template" | external Excel | no |
| p12.25 | "RFP #24-0031 Proponent Pricing Template" | external Excel | no |
| p14.12 | "Proponent Response Template ... as described in Section 4" | 4. Scope of Work (p17.9) | sees "Section 4", skips |
| p14.13 | "... as outlined in Section 6" | 6. Proponent profile (p21.10) | sees, skips |
| p14.14 | "Pricing Response Template ... Section 7" | 7. Budget & pricing | sees, skips |
| p16.t2r1 | "outlined in section 4.1 of this RFP" | 4.1 Solution Bill of Material (p17.h1) | sees, skips |
| p18.4 | "(section 4.1)" | 4.1 | sees, skips |
| p17.11 | "Refer to [blank] for a full list of Oracle Solution Components ... below" | target text is missing; no list follows | no |
| p17.3 | "per the schedule outlined below" | 2.6 Schedule of Events, which is above (p8) | no |
| p21.13 | "RFP #24-0031 City of Durham - Partner Response Template" | the "Proponent Response Template"? | no |
| p22.7 | "A pricing sheet template is provided" | Pricing template | no |
| p22.33 | "RFP #24-0031 Proponent Pricing Response Template" | pricing template | no |
| p22.32 | "refers specifically to this section" | 7.1 | no |
| p9.12 | "In this section (Trade Secrets and Confidentiality)" | 3.6 (p9.7-8) | no |
| p9.28 | "subsection (a) above" | (a) Designation, p9.18 | no |
| p10.2 | "subsection (c) below" | (c) Defense of City, p10.3 | no |
| p10.4 | "subsection (a)" / "(b) above" | p9.18, p9.27 | no |
| p10.13 | "This subsection (c)" | p10.3 | no |
| p13.21 | "this provision" (3.16 B) | p13.21 itself | no |
| p13.23 | "This subparagraph B" | p13.21 | no |
| p13.26 | "subsections (A) and (B)" | p13.20, p13.21 | no |
| p13.9 | "the format described in this RFP" | 3.17 Proposal Format | no |
| p15.2 | "as identified in the Scope of Work" | Section 4 | no |
| p6.2 | "exhibits and other attachments" | external | no |
| p13.17 | "an appendix to the proposal" | not a reference to the RFP | no |

(A further 3.x subsection set and the numbered lists in 3.17 and 4.2 contain no other targetable references.)

## Durham: real mismatches

| # | Mismatch | Units | xref | CHECK |
|---|---|---|---|---|
| D1 | EBOP is Attachment A in the submission list (3.15) and 3.10, but Attachment B in the proposal format checklist (3.17) | p11.10, p12.26, p14.18 | no (no Attachment headings, so skipped) | yes (f: "EBOP is Attachment A ... but Attachment B ...", p12.26 + p14.18) |
| D2 | Workforce Diversity form is "Attachment A" in 3.17, but 3.9 and 3.15 item 6 say it is an online questionnaire link, and Attachment A is the EBOP form elsewhere | p14.17 vs p11.5, p11.10, p13.4 | no | no (its D1 fact cites p14.18, not p14.17) |
| D3 | "Refer to [nothing] for a full list of Oracle Solution Components ... below": the reference text is blank and no list follows | p17.11 | no | no |
| D4 | "per the schedule outlined below": the schedule is in 2.6, above, and "Presentation Dates: TBD" (p17.4) disagrees with the Table 4 estimates ("60 days") | p17.3, p17.4, p8.t3r4 | no | no |
| D5 | Template names drift: "Proponent Response Template" (p12.24, p14.12, p14.13) vs "Partner Response Template" (p21.13); "Proponent Pricing Template" (p12.25) vs "Pricing Response Template" (p14.14, p22.33). Low severity. | as listed | no | no |
| D6 | The Workforce Diversity Questionnaire is required before contract execution (3.9) yet also listed as a required proposal submission (3.15) | p11.7, p13.4 | no (no reference phrase) | yes (f: p11.7 + p13.4) |

Not counted: Appendix A and B, and Attachments A and B, are named but are not in the PDF. That is not a
mismatch inside the document, though a bid manager would want it listed as "files to obtain". The
table of contents lists 3.11, 3.12 and 3.16, which the tagger turned into plain paragraphs; that is a
tagging artefact, not an RFP error.

Durham CHECK output: 2 contradiction facts in total (both source_call CHECK), both real, both on
reference-like conflicts (D1, D6). The CHECK call found nothing for D2 to D5.

## Ulster: references

| Unit(s) | Phrase | Target | xref |
|---|---|---|---|
| p4.7 | "Attachment A", "Attachment B", "Attachments C, D, E, and F" | 26.0 ATTACHMENTS list (p15.8-13); titles agree | sees A and B only; "kind has no heading" so skipped; C-F plural not matched |
| p15.8-13 | "ATTACHMENT A ... F" list entries | the attachments themselves (external files) | sees all 6, skips (no heading) |
| p6.9 | "Receipt Confirmation Form which follows the cover page" | p2 RECEIPT CONFIRMATION FORM | no (but see U3) |
| p7.11 | "Section 4.0 SUBMITTAL CONTENT AND FORMAT" | heading "4.0 SUBMITTAL CONTENT AND FORMAT" (p8.h1) | sees "Section 4.0"; heading has no "Section" word so not found, silently skipped |
| p7.13 | "General Specifications specified in this RFP" | no such section | no (see U2) |
| p9.11 | "Section "3.2 RETURN DATE"" | 3.2 (p6.h3), correct | no (quote mark defeats the regex) |
| p9.15 | "Return Sheets as indicated at the end of this RFP" | p35-45 forms | no |
| p11.4 | "the attached sample ... AGREEMENT FOR PROFESSIONAL SERVICES" | p16 onward | no |
| p11.7 | "separate Business Associate Agreement" | external | no |
| p12.3 | "Schedule C "Insurance Requirements"" | SCHEDULE C (p31.h3), title consistent | yes, compared |
| p13.1 | "Disclosure of Ownership Interest Certification Form ... at the end" | p39.h1, present | no |
| p14.1 | "Affidavit of Non-Collusion, included with this RFP" | p41.h2, present | no |
| p36.4 | checklist of 11 forms | forms at p37-45; all present | no |
| p16.9, p16.11, p24.6 | "Schedule A" | SCHEDULE A | yes, compared |
| p17.2, p25.10, p30.11 | "Schedule B" | SCHEDULE B | yes, compared |
| p20.5, p23.11, p23.15 | "Schedule C" | SCHEDULE C | yes, compared |
| p27.1 | "Schedules A, B, and C" | A, B, C | no (plural) |
| p19.11, p20.8, p21.7, p21.11-13, p21.16, p22.11(ext.), p23.15, p24.6, p25.2, p25.14, p26.5 (x4), p28.17, p30.7, p30.9 | in-contract "Article N" references | ARTICLE N headings | yes, compared (title in parentheses also compared) |
| p27.2 | 12 articles listed with titles | ARTICLE 7, 8, 13, 15, 16, 17, 18, 19, 25, 26, 28, 31 | yes; 11 match, Article 17 differs |
| p13.9, p20.2, p22.11 | "Article 6 of the Public Officers Law", "Article 2 of Chapter 12 ...", "Article 15 of the ... Executive Law" | statutes | yes, correctly skipped as external |
| p11.6, p20.20, p12.7, p14.6, p22.14-15, p23.5, p31.21, p32.7 | "Section 164.504(e)", "2(K)", "220-A", "230", "239", "57", "220(8)" | statutes | sees, skips (unreported by accident: "section" is not in `_CHECK_MISSING`) |

Totals by xref's own accounting on Ulster: 62 sightings = 40 compared with a heading, 3 skipped as
external, 8 skipped because the document has no Attachment headings, 11 where no heading is found (10
are statute numbers, 1 is the real in-document "Section 4.0").

## Ulster: real mismatches

| # | Mismatch | Units | xref | CHECK |
|---|---|---|---|---|
| U1 | Survival clause cites "Article 17 (Intellectual Property)" but Article 17 is "INTENTIONALLY LEFT BLANK" | p27.2, p21.h2 | yes (the one fact it writes) | not measured |
| U2 | "General Specifications specified in this RFP" does not exist; the nearest heading is 3.4 General Guidelines | p7.13 | no | not measured |
| U3 | Section 3.1 is titled RETURN CONFIRMATION FORM; the form it describes (p2) and its own text call it the RECEIPT CONFIRMATION FORM. Low severity. | p6.h2, p6.9, p2.h1 | no | not measured |

Close calls not counted: Attachment F "as of 7.1.2026" (p15.13) against "through June 30, 2026" (p4.7) is a
one-day difference in how a date is written, not a different document. Contradictions that are not
references, seen in passing and worth a CHECK-side look: the three-year term "ending December 31,
2026, 2027, and 2028" (p4.3) against the contract period January 1, 2027 to December 31, 2029 (p11.2);
insurance evidence "within ten (10) days" (p12.4) against "ten (10) business days" (p44).

## Conclusion

On these two documents the code-only check found one real mismatch out of nine (U1 only; zero on
Durham, where no heading is shaped like "Section N"), and the CHECK call found the two Durham mismatches
that were visible as "the same form, two different descriptions" (D1, D6) but none of the five that need a
reference resolved to a target (D2 to D5). The two checks barely overlap: their union on Durham still
misses 4 of 6, so the model-based finder is worth building, because a model that lists every reference and
its target is the only way to get D2 to D5 and U2 to U3 in front of the code verifier. It must handle
numbered headings with no kind word ("4.1", "4.0"), plural and quoted forms ("Attachments C, D, E",
"Section "3.2 RETURN DATE""), named forms and templates, "above/below" direction, subsection letters, and references with a
blank target; the verifier must also treat attachments and appendices that are not in the PDF as
"external, obtain separately" rather than as errors, and must compare names for the same attachment across
every place it is mentioned (D1, D2, D5), not just against a heading. Caveat: this is six real Durham
and three real Ulster mismatches, a small sample, and Ulster has no CHECK run, so the overlap with CHECK on
Ulster is unmeasured.
