---
name: fill-in-template
description: A form or spreadsheet from the buyer that the bidder fills in and returns, such as a price sheet or a response matrix.
reads: a fill-in form from the buyer
authority: buyer
role: base
codes: [S, R, C, D, E, B]
flags: [post-award, risk, unclear]
precedence: [D, S, E, C, R, B]
calls: [LABEL, STATE]
votes: 3
level: 1
visibility: external
sections: []
version: 1
---
A POINT ON A FORM
A form is made to be filled in, so most of it is blanks. The bid manager needs to know what must be filled in and what the buyer has already said.
- A row or field the bidder must fill in is a point. It is S when it is a thing to submit (a form, a signature, a certificate, a price sheet) and R when it is a requirement the bidder must answer or confirm.
- A value the buyer has already filled in is a fact of its own category: a date is D, a contract term is C, a score or weight is E, a buyer detail is B.
- An instruction written on the form is a point, whatever it is about.
- An empty label, a column header alone, a row number, and a blank line state no point.
- Read a cell with its row and its column heading: the heading says what the cell means.
