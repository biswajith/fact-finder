---
name: call-transcript
description: Recording or notes of a live call between buyer and bidder; speaker turns, timestamps, conversational wording.
reads: a call transcript
cutter: transcript             # sentences inside speaker turns
authority: speaker
role: context
codes: [B, D, C, R, E, S, PRIORITY, DECIDER, BUDGET, QUESTION]
flags: [post-award, risk, unclear, tentative]
precedence: [BUDGET, D, C, S, R, E, DECIDER, PRIORITY, QUESTION, B]
calls: [LABEL, STATE, RELATE]
relations: [CONFIRMS, CLARIFIES, DISAGREES, ADDS, NONE]
relate_to: buyer documents
votes: 3
level: by speaker              # buyer units 2, our units 3
visibility: internal           # default for citations from this document
sections: [buyer-priorities, open-questions]
version: 1
---
A POINT IN A CONVERSATION
- A question states no point by itself. When the answer only agrees or disagrees, label the question with the point and the answer as its continuation. When the answer states the point, label the answer.
- A hedged statement is still a point; flag it tentative.
- "That date" or "the other system": label the unit with the point it refers to.
- Small talk, greetings, and arranging the call itself (who joins, when to meet again, whether the line works) state no point.
- Speech recognition makes slips. Read a unit for what was meant, but never correct a number, a date, or a name: state it as it was written.
- Who said it does not change the label. Label a unit by what it says, whichever side spoke.
