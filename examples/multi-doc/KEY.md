# Multi-document test set: answer key

Made-up calls and deal notes for the two RFPs in the repo root. They test the transcript and deal-notes
playbooks, the speaker map, RELATE, GROUP across the bid and the priority ladder, as set out in
`docs/multi-document-design.html`.

| RFP | Call (test input) | Readable call | Deal notes |
|---|---|---|---|
| Ulster County, `RFP-UC26-039 ACTUARIAL SERVICES FOR ULSTER COUNTY SELF INSURANCE PLAN.pdf` | `ulster-call-2026-08-12.gong.json` | `ulster-call-2026-08-12.txt` | `ulster-deal-notes.md` |
| City of Durham, `RFP24 0031 for Oracle ERP Implementation Partner - Addendum 1.pdf` | `durham-call-2024-07-24.gong.json` | `durham-call-2024-07-24.txt` | `durham-deal-notes.md` |

`to_gong.py` builds each JSON from its readable call; the parties, speech-recognition slips and call details
for each call are in its `CALLS` table:

```
python3 to_gong.py ulster-call-2026-08-12.txt ulster-call-2026-08-12.gong.json
python3 to_gong.py durham-call-2024-07-24.txt durham-call-2024-07-24.gong.json
```

Each RFP is real. The firms, every person on the calls and in the notes, the competitors, the reference
cities and everything they say are made up. The real contacts the RFPs name are mentioned at most, never
quoted.

## The Gong shape

Gong has no single transcript file with names in it. An export is two API responses, and the JSON holds both:

- `extensive`: the response of `POST /v2/calls/extensive` with parties requested. `metaData` describes the call
  (title, `started`, `duration` in seconds, `system`, `scope`). `parties` lists the people: `name`,
  `emailAddress`, `title`, `userId` (only for people with a Gong account, which means our side), `speakerId`,
  `affiliation` (`Internal`, `External` or `Unknown`) and `methods` (`Invitee`, `Attendee`).
- `transcript`: the response of `POST /v2/calls/transcript`. Each call has a list of monologues: a `speakerId`,
  an optional `topic`, and `sentences`, each with `start` and `end` in milliseconds from the start of the call.
  One monologue holds one speaker's uninterrupted run, so two turns in a row by the same person are one monologue.

Names come only from joining `speakerId` to `parties`. Times in this key are `start` rounded down to
seconds, written hh:mm:ss.

Gong's in-app "Download transcript" gives a text file, but its help pages do not describe that file's layout,
so it is not imitated here.

Sources: Gong API reference for
[/v2/calls/transcript](https://help.gong.io/apidocs/retrieve-transcripts-of-calls-by-date-or-callids-v2callstranscript-2)
and [/v2/calls/extensive](https://help.gong.io/apidocs/retrieve-detailed-call-data-by-various-filters-v2callsextensive-2);
[Gong community answer on mapping speaker IDs to names](https://visioneers.gong.io/support-tip-of-the-week-55/can-the-gong-api-return-speaker-names-email-instead-of-speaker-ids-in-transcripts-1304);
[Work with the call transcript](https://help.gong.io/docs/view-a-call-transcript). The `affiliation` and `methods`
values come from a summary of the extensive page, not a verbatim read.

Levels follow the ladder: 1 buyer document, 2 buyer on a call, 3 our side on a call,
4 deal notes. "Outcome" is what the design says should happen.

# Ulster County set

Our firm is Halvard Actuarial Partners; the incumbent is Northgate Actuarial. The RFP's named buyer,
Brenden Boughton, is mentioned but never speaks.

### Speaker map

| Party | Gong affiliation | Side | Trap |
|---|---|---|---|
| Dana Whitcomb | External | buyer | |
| Marcus Fell | External | buyer | Plan administrator: a county employee, so buyer, not a third party. |
| Priya Raman | Internal | ours | |
| Tom Okafor | Internal | ours | |
| phone +1 845-555-0142, no name or email | Unknown | buyer | Says "this is Jen from Purchasing" in her first sentence. The speaker map must use that, not the affiliation. |
| Sam Lee | Internal | ours | Invited, never joined: no `speakerId`, says nothing. Must not appear as a speaker. |

`External` means "not our company", not "the buyer". On a call with a partner or a consultant, External
would include people who are not the buyer, so the speaker map still needs the user's confirmation.

### Planted points

| # | Point | Where | RFP says | Outcome |
|---|---|---|---|---|
| 1 | First valuation is year end 2026, three valuations inside a 2027-2029 contract | call 00:00:22-00:01:00 (Priya asks, Dana and Marcus answer); notes 08-12 | §1.0 years ending 2026-2028; §9.0 term 2027-01-01 to 2029-12-31 | The RFP already disagrees with itself: a Q fact. The buyer's call statement (2) relates to that Q, it does not settle it. Conflict with the options; the user picks "ask in writing" (notes 08-14 show the question). |
| 2 | Final report by March 31; draft early March, mid-February better | call 00:01:13-00:01:27; notes 08-12 | Draft, discussion, final report (§2.0); no dates | New information (2), no conflict. Call and notes are the same point: one group, the call is the highest member. |
| 3 | Final report "by end of Feb" | notes 08-07 | no date | Note (4) vs the buyer on the call (2): warning, the note is possibly wrong. Not the same point as #2: different date. |
| 4 | Electronic copy may be emailed | call 00:01:39 (Dana), withdrawn 00:01:53-00:02:01 (Jen, then Dana) | §3.2 CD or thumb drive | Within the call the buyer withdraws it. Expected: no live conflict, or one shown as withdrawn. If the statement is taken alone it is a level-2 conflict with §3.2, which is the failure to catch. |
| 5 | "Dana said we can email the electronic copy" | notes 08-12 | §3.2 | The note misses the withdrawal. Note (4) vs RFP (1): warning. Should link to #4 on the call. |
| 6 | Electronic copy on a thumb drive | notes 08-07 | §3.2 | Agrees with the RFP: same group. |
| 7 | About 380 open claims at end of July 2026 | call 00:02:16; notes 08-12 | §1.0 365 open as of 2026-05-31 | Different date, so not the same point: related, not a conflict and not grouped as "same". |
| 8 | A village leaves the plan at year end 2026; withdrawal calculation in year 1 | call 00:02:34-00:02:47; notes 08-12 | §2.0 3 villages; withdrawal calculation in scope | New information (2). Links to the withdrawal-calculation requirement. |
| 9 | New TPA starts January 1; data comes from two TPAs | call 00:02:55-00:03:09; notes 08-03 (rumour), 08-12 (confirmed) | §2.0 administration uses a third-party administrator | New information (2). The 08-03 note is a rumour the call confirms. |
| 10 | Professional liability box is checked: $1M per occurrence, $2M aggregate | call 00:03:19; notes 08-03 ("looks unchecked"), 08-12 | Schedule C IX "If this box is checked": $1M / $2M | Call (2) fills a gap the RFP leaves unclear. The 08-03 note (4) is out of date against the call: warning. |
| 11 | Our side proposes net 30 | call 00:03:27 (Priya) | §17.0 60 days after receipt, Department Head and Comptroller approval | Our side (3) vs RFP (1): warning. Dana (2) corrects it on the call at 00:03:32, which agrees with the RFP. |
| 12 | Paid once a year on the final report "in practice" | call 00:03:45; notes 08-12 | §17.0 invoice monthly | Buyer on a call (2) vs RFP (1). Dana says not to rely on it; still a conflict to show, user likely keeps "the RFP stands". |
| 13 | Interviews likely the week of September 21; two or three firms | call 00:04:00; notes 08-12 | §10.0 interviews may be held, no date | New information (2), hedged ("probably"). |
| 14 | Committee: Risk Management, plan administrator, Comptroller's office, Finance | call 00:04:09; notes 08-12 | §5.0 a committee of county representatives | New information (2). |
| 15 | Price is 30 points; prices were close last round | call 00:04:19; notes 07-31, 08-12 | §5.0 30 points | The points agree: same group as the RFP's criterion. "Prices were close" is new background (2). |
| 16 | Contingencies bullet means a low / expected / high range | call 00:04:36-00:04:47; notes 08-12 | §2.0 "Anticipated and unanticipated contingencies" | Clarifies an RFP requirement (2). Related, not a conflict. |
| 17 | Optional hourly work about 10-15 hours a year | call 00:04:53; notes 08-12 | §2.0 optional services, hourly | New information (2). |
| 18 | Albany office gets 1 local point | call 00:05:07; notes 07-31 | §5.0 1 point within New York State | Agrees with the RFP: same group. |
| 19 | Someone in person for the draft review; we committed to it | call 00:05:07-00:05:16; notes 08-12 | §2.0 office availability question | Buyer wish (2) plus our commitment (3). |
| 20 | One fixed annual fee, hourly rates quoted separately | call 00:05:19 (Tom), accepted by Dana 00:05:27 | §4.0 fee schedule; §2.0 hourly rates | Our side (3), acknowledged by the buyer (2). No conflict. |
| 21 | Questions due August 18 | call 00:05:29-00:05:34; notes 08-12, 08-14 | §3.5 at least 10 calendar days before 2026-08-28 | Agrees: 2026-08-18 is the derived date. Same group. |
| 22 | Proposal due August 31, 4pm | notes 07-31 | §3.2 2026-08-28 4:00 PM | Note (4) vs RFP (1): warning. The notes correct themselves on 08-14. |
| 23 | Due date is Friday August 28, 4pm | notes 08-14 | §3.2 | Agrees: same group. Within the notes it corrects #22. |
| 24 | Fee proposal in a separate envelope marked COST PROPOSAL, same package | notes 08-07 | §4.0 Section IV | Agrees: same group. |
| 25 | Licensed in NY since 2019, which meets the 4-year minimum | notes 07-31 | Vendor qualification 1: licensed in NY at least 4 years | Our claim (4) about a gate. Not a buyer fact; related to the gate. |
| 26 | Incumbent Northgate, about $41k a year, unconfirmed | notes 07-31 | none | Internal intelligence. Visibility test: must never appear in an export meant for outside the team. |
| 27 | Pricing target $36-38k a year | notes 08-03 | none | Internal: visibility test as #26. |
| 28 | Decision to bid; owners, red team Aug 21, ship Aug 26 (moved to Aug 25 on 08-14) | notes 08-03, 08-07, 08-14 | none | Internal plan facts. The ship date changes within the notes. |

### Speech-recognition slips

Gong's text is machine transcription, so the JSON has slips the readable file does not:

- "Comptroller" is transcribed "controller" twice (00:03:32 and 00:04:09). The payment-approval fact (#11) and the
  committee fact (#14) should still match the RFP's "Ulster County Comptroller" when the meaning is clear.
- "Brenden" is transcribed "Brendan" twice (00:01:53 and 00:05:34). The contact should still match the RFP's
  Principal Buyer.

### Gong topics

Gong labels some monologues with a `topic`: "Small Talk" on the first, "Pricing" on the payment and price
turns, "Next Steps" on the last. They are Gong's guesses, so they are hints at most: the scoring turn at
00:04:14 is tagged Pricing, and the in-person commitment at 00:05:16 shares a monologue with the fee turn, so
it carries Pricing too.

### Things that should produce nothing

- Greetings and sign-offs (00:00:04, 00:05:38-00:05:43).
- "Will do.", "Okay.", "Understood." turns.
- Dana's opening reminder that anything formal goes through Purchasing in writing (00:00:09) agrees with §3.5 ("shall not rely upon any oral statements"). It may group with that RFP fact, but it adds nothing new.

### Open design questions this set raises

- #4: how a retraction later in the same call is read. Today's design has no relation kind for "withdrawn by the same side in the same document".
- #22 and #23: two notes in one document disagree, and the later one says it corrects the earlier one. The ladder treats equal levels as "both kept"; the notes playbook may need to read an explicit correction as a replacement.
- #10: the RFP's checkbox state is not in the PDF text, so the call fills a gap rather than contradicting anything.

# City of Durham set

The RFP is the reissued Oracle ERP implementation-partner RFP (dated 2024-05-10, due 2024-06-10). Our firm is
Corvane Consulting. The call is a short-list briefing after submission, arranged by Info-Tech Research Group,
the City's selection advisor, which section 1.2 names as the post-submission contact. The RFP's named
contacts are not on the call.

This set adds traps the Ulster one lacks: the buyer's side includes an outside advisor, the RFP bans direct
contact with City staff, and our own claim on a call fails a mandatory gate that the notes know about.

### Speaker map

| Party | Gong affiliation | Side | Trap |
|---|---|---|---|
| Marco Delgado (infotech.example) | External | buyer | Works for Info-Tech, not the City: a different email domain from the City's people, yet he speaks for the buyer and his statements outrank ours. |
| Renee Caldwell | External | buyer | |
| Kevin Osei | External | buyer | |
| phone +1 919-555-0187, no name or email | Unknown | buyer | Says "this is Lauren from Budget and Management Services" in her first sentence. |
| Nadia Brooks | Internal | ours | |
| Sam Whitfield | Internal | ours | |
| Eli Navarro | Internal | ours | Invited, never joined: no `speakerId`. Must not appear as a speaker. He is the one who broke the contact rule in the notes. |

### Planted points

| # | Point | Where | RFP says | Outcome |
|---|---|---|---|---|
| 1 | The call is the sanctioned channel; keep going through Info-Tech | call 00:00:03 | §1.2 no direct contact with City personnel, through the City contact; Info-Tech is the post-submission contact | Agrees with the RFP: groups with the §1.2 fact. |
| 2 | Presentations the week of September 16, 3 hours, in person at City Hall, agenda about two weeks ahead | call 00:00:21-00:00:35; notes 07-24 | §2.6 an estimated 60 days after short-list notice; Selection: "Presentation Dates: TBD" | New information (2) that fills a TBD. Not a conflict. Call and notes are one group. |
| 3 | Presentations are recorded | call 00:04:08; notes 07-24 | Selection: the presentation will be recorded | Agrees: same group. |
| 4 | Refined pricing due one week before the presentation slot, same template | call 00:00:42; notes 07-24 | §3.17 item 7 short-listed firms may refine pricing during the demonstration period | New date (2), related to the RFP fact. |
| 5 | Our side asks for 90-day price validity | call 00:00:49 (Sam); notes 05-21 ("standard price validity is 90 days") | §7.1 prices valid 180 days from the due date | Our side (3) and the note (4) vs RFP (1): warnings. Marco (2) restates 180 at 00:00:55, which agrees with the RFP; notes 07-24 record the fix. |
| 6 | City prefers phased: finance and procurement, then HR and payroll, then utility billing; payroll live on a January 1, target January 2026 | call 00:01:09; notes 07-24 | §4.2.1 the proponent proposes the approach (phased or big bang) | New information (2): a buyer preference, related to the requirement. No conflict. |
| 7 | About 95,000 utility customer accounts, monthly billing | call 00:01:26; notes 07-24 | §2.5 gives users, not accounts | New B fact (2). |
| 8 | Meter to Cash has about 60 full users, not 40 | call 00:01:40 (Kevin); notes 07-24 | §2.5 Table 2: Meter to Cash 40 users, 50 limited | Buyer on a call (2) vs RFP (1): conflict. Marco (2) says at 00:01:51 to price to the table and state 60 as an assumption, and Kevin agrees. Expected: conflict shown with the call's own resolution; the user picks "the RFP stands". |
| 9 | Seven years of financial history migrated from Munis; open items and balances for the rest | call 00:02:08; notes 07-24 | §4.2.1 item 8 data migration approach; §2.4 Munis is the current system | New information (2). |
| 10 | Kronos is retired; Oracle Time and Labor replaces it | call 00:02:14; notes 07-24 | §2.4 Kronos is a current workforce system; §4.1 item 9 Time and Labor is in scope | Agrees and adds a cutover (2). |
| 11 | Which attachment is EBOP | call 00:02:20-00:02:33; notes 06-07, 07-24 | §3.15 item 4: Attachment A is the EBOP form; §3.17 items 9-10: Attachment A is the diversity form, Attachment B is EBOP | The RFP disagrees with itself: a Q fact. Marco (2) says §3.15 is right and the notes say it will be written up. Relates to the Q; it settles it only once written. |
| 12 | Termination for convenience at 30 days; we want 90 | call 00:02:45-00:03:03; notes 05-21, 07-24 | §8.1 the City may terminate on 30 days' written notice; §3.16 B the City may negotiate any term | Our side (3) vs RFP (1): warning, and a risk fact. Renee (2) says it won't move; Marco (2) says raise it as an exception. |
| 13 | Three years plus two one-year options; the City expects to use both | call 00:03:06; notes 07-24 | §8.1 3 years with two one-year renewal options | The term agrees (same group). "Expects to use both" is new (2). |
| 14 | Cyber liability at $5 million, "probably", not final | call 00:03:18 (phone, Lauren); notes 07-24 | §3.8 lists general, auto, umbrella and workers' compensation cover; no cyber | A requirement the RFP does not have, hedged, from a speaker who gives her name only in speech. Expected: shown as call-only and not binding; Marco (2) says price to §3.8. |
| 15 | The livable wage figure is out of date | call 00:03:34-00:03:47; notes 07-24 | §3.13 B $17.60 an hour through 2023-06-30, to be reset | The buyer (2) confirms the RFP fact is stale without giving a new figure: the RFP fact should carry unclear. |
| 16 | Reference contacts will be called in August | call 00:03:51; notes 07-24 | §6.3 contacts requested from short-listed firms | Agrees and adds a date (2). |
| 17 | "We've done Oracle for two North Carolina municipalities in the 100k-500k range" | call 00:03:57 (Nadia) | §3.21 mandatory: at least two municipalities of 100k-500k within 5 years | Our claim (3) that we meet a gate. |
| 18 | Only one reference is in the 100k-500k band; the other is 82k | notes 05-21, 07-24, 07-26 | §3.21 | The notes (4) disagree with our own call statement (3) about a mandatory gate. Ladder: 3 vs 4, both kept and flagged for review. This is the most important point in the set: a bid manager must see it. |
| 19 | A team member emailed the City's HR director directly on May 16 | notes 05-16, 07-26 | §1.2 contacting City personnel directly may disqualify the proponent | Our own fact (4) that touches a disqualification rule. Should link to the §1.2 X fact and be flagged as a risk. |
| 20 | Proposals due June 10, 5pm ET | notes 05-13 | §2.6, §3.15 June 10, 2024, 2 pm ET | Note (4) vs RFP (1): warning. The notes correct themselves on 07-26. |
| 21 | Questions close May 24, 2pm ET | notes 05-13 | §2.6, §3.14 2024-05-24 2:00 pm ET | Agrees: same group. |
| 22 | Package: proposal, response template, pricing template, EBOP Attachment A, UBE statement of intent, online diversity questionnaire | notes 06-07 | §3.15 items 1-6 | Agrees: groups with the §3.15 checklist facts. |
| 23 | 2,903 employees | notes 05-13 | §2.5 Table 3 total 2,903 | Agrees: same group. |
| 24 | 22 line items in the bill of materials | notes 05-13 | §4.1 items 1-22 | Agrees. |
| 25 | Competitor Brightline pricing about $9M, unconfirmed | notes 05-13 | none | Internal intelligence: visibility test. |
| 26 | Price target $7.5-8.2M over about 30 months | notes 05-21 | none | Internal: visibility test. |
| 27 | Decision to bid; owners; actions | notes 05-21, 07-26 | none | Internal plan facts. |

### Speech-recognition slips

- "Kronos" is transcribed "Chronos" (00:02:14). Point #10 should still match the RFP's Kronos.
- "EBOP" is transcribed "e-bop" (00:02:33). Point #11 should still match the EBOP form.
- "Info-Tech" is transcribed "InfoTech" (00:00:03).

### Gong topics

"Small Talk" on the first monologue, "Pricing" on several, "Next Steps" on the last. As in the Ulster call
they are rough: the termination and insurance turns carry "Pricing" because they mention days or price.

### Things that should produce nothing

- Greetings, thanks and sign-offs (00:00:14, 00:04:14, 00:04:16).
- "Understood.", "Great, thank you.", "Will do." turns.

### Open design questions this set raises

- #1, #8, #14: the advisor is a third party that speaks for the buyer. The speaker map needs a "buyer's
  advisor" side, or the user must map Info-Tech to the buyer.
- #11: a buyer statement on a call that names which of two RFP passages is right. Is that a resolution of the
  Q fact or only a relation, until the written notes arrive?
- #17 and #18: our call statement and our notes disagree about a gate. The ladder says "both kept"; a gate
  failure may deserve a louder flag than an ordinary disagreement.
- #19: a note about our own conduct that may trigger a disqualification rule. No category covers "risk we
  created", and the design has no link from our facts to an X fact.
