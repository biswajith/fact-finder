# Goal

Written 2026-11-20. This is where the project is heading. Change it only when the
goal itself changes; record progress in [REVIEW.md](REVIEW.md).

## The goal

Evaluate the fact extractor on any RFP without a person writing the reference list.

```
RFP PDF --> golden-dataset builder (goldset) --> reference fact list
RFP PDF --> fact extractor                   --> extracted facts
reference list + extracted facts --> DeepEval --> pass or fail per fact, with a reason
```

1. **goldset generates the reference data.** For an RFP it builds a checked list of
   the facts the extractor should find (`fact-extractor golden`).
2. **The fact extractor produces its facts** for the same RFP (`fact-extractor extract`).
3. **DeepEval evaluates the second against the first** (`deepeval test run evals/`),
   and judges whether each extracted fact is supported by its source and useful to a
   bid manager.

One command should run all three for a new RFP.

## Done means

- A new RFP gets a reference list and an evaluation report with no hand-written input.
- The goldset reference list is shown to be a fair yardstick: on the two RFPs that
  have hand-written lists, a person accepts its lines, and the extractor's recall
  against it is close to its recall against the hand-written list.
- The judged metrics agree with the hand labels in `poc/ablation/labels/` well
  enough to be trusted without a person re-checking them.
- The cost per RFP is measured and acceptable.

## Where it stands (2026-11-20)

| Piece | State |
| --- | --- |
| goldset copied into the repo, `evals` extra | Done, tests pass |
| `fact-extractor golden` (RFP to reference list) | Built, tested on a scripted model, never run live |
| DeepEval metric for "reference fact found" | Done, agrees with `fact-extractor score` |
| DeepEval judged metrics (same fact, supported, useful) | Built, never run live |
| One command for the whole chain | Not built |
| Goldset reference list checked against hand-written lists | Not done |

## What could make the result misleading

- **Same model on both sides.** goldset and the extractor use the same model and the
  same category definitions, so a shared misreading scores as correct.
- **The reference list is a sample the planner picks.** It may favour clear-cut
  units, which would make recall look better than it is.
- **Recall only.** goldset's "this unit is not a fact" cases are dropped today.
  Keeping them would give a precision check.
- **Contradictions (Q) are not covered.**
- **Cost is an estimate:** 1,300 to 1,600 model calls per RFP for all eight
  categories, from reading the code.

## Next steps, in order

1. Run `fact-extractor golden` live on one category of the Ulster RFP. Read the
   output and measure the cost.
2. Compare the goldset list with the hand-written list for that category: lines a
   person accepts, and the extractor's recall on each list.
3. If the sample is too easy, give goldset every unit, or a random sample of units,
   so the planner does not choose.
4. Run the judged DeepEval metrics and compare them with the hand labels.
5. Keep goldset's "not a fact" cases and score precision against them.
6. Add the single command that runs the whole chain.
7. Add contradiction (Q) cases.
