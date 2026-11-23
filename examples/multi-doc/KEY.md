# Multi-document test set: answer key

Two made-up documents for the Ulster County RFP in the repo root
(`RFP-UC26-039 ACTUARIAL SERVICES FOR ULSTER COUNTY SELF INSURANCE PLAN.pdf`).
They test the transcript and deal-notes playbooks, the speaker map, RELATE, GROUP
across the bid and the priority ladder, as set out in `docs/multi-document-design.html`.

- `ulster-call-2026-08-12.gong.json`: a clarification call, in the shape of a Gong API export. This is the
  test input.
- `ulster-call-2026-08-12.txt`: the same call, readable, with timestamps. `to_gong.py` builds the JSON from it:
  `python3 to_gong.py ulster-call-2026-08-12.txt ulster-call-2026-08-12.gong.json`.
- `ulster-deal-notes.md`: the bid team's running notes, dated entries.

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

The RFP is real. The firm (Halvard Actuarial Partners), every person on the call and in
the notes, the incumbent (Northgate Actuarial) and everything they say are made up.
The RFP's named buyer, Brenden Boughton, is mentioned but never speaks.

Levels follow the ladder: 1 buyer document, 2 buyer on a call, 3 our side on a call,
4 deal notes. "Outcome" is what the design says should happen.

## Speaker map

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

## Planted points

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

## Speech-recognition slips

Gong's text is machine transcription, so the JSON has slips the readable file does not:

- "Comptroller" is transcribed "controller" twice (00:03:32 and 00:04:09). The payment-approval fact (#11) and the
  committee fact (#14) should still match the RFP's "Ulster County Comptroller" when the meaning is clear.
- "Brenden" is transcribed "Brendan" twice (00:01:53 and 00:05:34). The contact should still match the RFP's
  Principal Buyer.

## Gong topics

Gong labels some monologues with a `topic`: "Small Talk" on the first, "Pricing" on the payment and price
turns, "Next Steps" on the last. They are Gong's guesses, so they are hints at most: the scoring turn at
00:04:14 is tagged Pricing, and the in-person commitment at 00:05:16 shares a monologue with the fee turn, so
it carries Pricing too.

## Things that should produce nothing

- Greetings and sign-offs (00:00:04, 00:05:38-00:05:43).
- "Will do.", "Okay.", "Understood." turns.
- Dana's opening reminder that anything formal goes through Purchasing in writing (00:00:09) agrees with §3.5 ("shall not rely upon any oral statements"). It may group with that RFP fact, but it adds nothing new.

## Open design questions this set raises

- #4: how a retraction later in the same call is read. Today's design has no relation kind for "withdrawn by the same side in the same document".
- #22 and #23: two notes in one document disagree, and the later one says it corrects the earlier one. The ladder treats equal levels as "both kept"; the notes playbook may need to read an explicit correction as a replacement.
- #10: the RFP's checkbox state is not in the PDF text, so the call fills a gap rather than contradicting anything.
