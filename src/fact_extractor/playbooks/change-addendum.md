---
name: change-addendum
description: An addendum from the buyer that changes an earlier buyer document: replaced, removed or added text, new dates, new terms.
reads: an addendum to an RFP
cutter: pdf
authority: buyer
role: change
codes: [B, C, G, X, D, S, E, R]
flags: [post-award, risk, unclear, precedence]
precedence: [X, G, D, S, E, C, R, B]
calls: [LABEL, STATE, CHECK, XREF, RELATE]
relations: [REPLACES, REMOVES, ADDS, CLARIFIES, CONFIRMS, DISAGREES, NONE]
relate_to: buyer documents
votes: 3
level: 1
visibility: external
sections: []
version: 1
---
A POINT IN AN ADDENDUM
An addendum changes a document that already exists. The bid manager reads it to learn what is now different.
- A change instruction, such as "Section X is replaced with" or "the following is deleted", states the point of the change. Label the instruction with the category of what it changes. The text that replaces or adds something is part of that point.
- Text restated without change is still a point. An addendum often repeats a whole section so that the reader has the current version; label the restated text as a unit of its own category.
- A section that has subsections is named by each of its headings. Read a unit under the heading it sits in, and the heading's number tells you which part of the earlier document it belongs to.
- A statement of which document wins when documents disagree is a point; flag it precedence.
- A line that only says the rest of the document is unchanged, a signature block, an acknowledgement form with blanks, and courtesy text state no point.
