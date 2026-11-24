---
name: qa-addendum
description: A question-and-answer addendum from the buyer: bidders' questions with the buyer's answers.
reads: a question-and-answer addendum to an RFP
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
A POINT IN QUESTIONS AND ANSWERS
Each entry is a bidder's question followed by the buyer's answer. The buyer's answer is what binds the buyer.
- The answer states the point. Label the answer with the category of what it settles. The question is its context: when the question is needed to understand the answer, label the question as a continuation of the answer's point only if it comes right before it, otherwise leave it without a point.
- An answer of "no change", "noted", "see the RFP", or "refer to section X" with nothing added states no point.
- An answer that changes a term, date, quantity or requirement of an earlier document states a point of the change. An answer that only repeats what the earlier document says is still a point, as a confirmation.
- A section with subsections is named by each of its headings; the heading or question number says which part of the earlier document the entry is about.
- A statement of which document wins when documents disagree is a point; flag it precedence.
- Names of the bidders who asked, entry numbers alone, and courtesy text state no point.
