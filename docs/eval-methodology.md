# Eval-gated prompt iteration: methodology and results

The agent's system prompt is the part of this project most likely to drift
under "looks better to me" tuning. A prompt change that visibly improves one
memo can quietly regress five others — and you'd never know, because nobody
reads twenty-five memos side by side in their head. This is a writeup of how
I built a scoreboard for that problem, and what the scoreboard said when I
ran six prompt changes through it.

## The problem with eyeballing prompts

The conventional way to tune an LLM prompt is: change a line, run one prompt,
read the output, decide if it "feels better." That works for tasks where the
output is short and the right answer is obvious — translate this sentence,
classify this email. It doesn't work for an agent that writes a multi-page
analytical document, because:

1. **One sample is not a distribution.** A change that produces a sharper
   memo on one listing can be neutral on ten others and actively bad on three.
   You only see this if you measure across a suite.
2. **Reasoning quality isn't visible in any single artifact.** Whether the
   agent is anchoring on its first impression, double-counting a factor it
   already applied via the comp set, or hedging instead of committing — these
   are statements about the agent's *process*, and a single output is at best
   weak evidence either way.
3. **Drift is silent.** A prompt change can lower the agent's calibration —
   making it overshoot toward Walk, say — and the memos will still read
   plausibly. You'd ship the regression.

The fix is a scoreboard: a fixed set of cases with structured assertions,
run before and after every prompt change. That's what `evals/` is.

## The setup

**25 cases across 14 Warsaw districts.** Studios to 4-room flats, pre-war
kamienice to 2025 new-builds, private sellers and developers, central to
outer. The case mix is deliberately wide — the suite has to surface
regressions for any kind of listing, not just the modal one.

**Deterministic tool I/O via snapshots.** The first time each case runs, the
exact JSON returned by every tool call is captured to
[`evals/snapshots/<case-id>.json`](../evals/snapshots/). On re-runs, the
agent's `Tool` calls return the snapshot instead of hitting Otodom, GUS,
OpenStreetMap, or pgvector. This is the load-bearing piece: it means the
only thing varying between two runs of the same case is the **LLM itself** —
the prompt, the model, the reasoning. The whole rest of the stack is held
constant.

**Structured grading.**
[`evals/parse_memo.py`](../evals/parse_memo.py) extracts a `ParsedMemo` from
the markdown — verdict, confidence, gross yield %, photo condition, photo
count, rent and sale comp counts, and the full §7 risks text. Each case in
[`evals/cases.json`](../evals/cases.json) asserts:

- a **verdict band** (e.g. `["Walk", "Borderline"]` — what's acceptable
  given the listing's economics)
- a **gross yield band** (a min, given the listing's price and rent
  comparables)
- **tool-coverage minimums** (the §5 comp counts have to clear a floor —
  the agent didn't skip the comparables work)
- **risk substrings** the §7 section has to mention (e.g. for a ground-floor
  flat: the substring `ground`)

A run is graded pass / fail per case; the suite reports `N/25` plus the
diffs.

**Cost.** A full 25-case re-run costs about $8 and 30–50 minutes of
wall-clock with the Anthropic API. Cheap enough to run for every prompt
change, expensive enough that I don't burn through them carelessly.

## The six identified levers

Before running anything, I wrote out the levers I thought were worth
testing. Six items, ranked roughly by leverage vs. cost-to-test:

1. **Reasoning posture** — the prompt was procedural (fill the template).
   No explicit "argue the other side" step before §8. Anchoring risk.
2. **Framing & order** — `system.md` opened with formatting rules ("Output
   discipline"), framing the task as compliance rather than analysis.
3. **Memo structure** — verdict was at §8, last. A leading TL;DR would put
   it on screen one for skimmers.
4. **Calibration** — across the baseline 25 cases the agent issued **zero
   Buy verdicts**, ever, even on listings yielding 6.6% gross. Was the §8
   bar miscalibrated, or was the model just under-thinking?
5. **Reasoning effort** — `settings.agent.effort` was `medium`. The
   literal reasoning-depth dial; cheapest to test (one config line).
6. **Baked-in heuristics** — the prompt hard-coded priors (ground-floor
   discount %, czynsz thresholds, rent-tier table). The agent was applying
   these mechanically on top of comp-set medians that already contained the
   same information — a double-counting risk.

These map to the six experiments below, in the order I ran them.

## The experiments

### Exp 1 — high reasoning effort ([#62](https://github.com/khalidAlfozan/realestate-agent/pull/62))

**Hypothesis.** Settles the calibration question cheaply: if the agent is
just under-thinking, more thought-tokens should unlock Buy verdicts on the
high-yielding listings.

**Change.** `settings.agent.effort: "medium"` → `"high"`. One line.

**Result.** 7 verdicts shifted, **net more skeptical** (5 Borderline→Walk,
2 Walk→Borderline). Still **zero Buy**. A side-by-side read of the shifted
cases showed a modest but real reasoning lift — sharper §7 risks, less
hedging ("Walk" instead of "Borderline — lean Walk"), and concrete catches
medium-effort missed (`mokotow-4-room`: high effort flagged that the seller
claims metro access OSM data shows doesn't exist).

**Verdict: kept.** And the more important outcome: the zero-Buy result is a
**calibration** problem, not an under-thinking problem. The next experiment
has its target.

### Exp 2 — recalibrate the verdict criteria ([#63](https://github.com/khalidAlfozan/realestate-agent/pull/63))

**Hypothesis.** §8 framed the recommendation around "Walk at asking / would
Buy at a lower price" — its worked example was a Walk, and Buy appeared only
as a counterfactual. That's anchoring by example.

**Change.** §8 now gives Buy / Borderline / Walk each an **explicit bar**,
and **Buy is earnable at the asking price**: gross yield in or above the
typical 5–7% range, price fair or below the comp median, condition sound,
no disqualifying risk — a discount strengthens a Buy but is not required.

**Result.** Verdict mix `0 Buy / 9 B / 16 W` → `2 Buy / 13 B / 10 W`.
- `srodmiescie-kamienica` (6.21% yield, ~12% below comp median) became a
  clean Buy.
- `ochota-kamienica` (5.87%, fair price) became a marginal Buy.
- The guardrail held — all four 19–32%-premium cases stayed Walk.

**Verdict: kept.** First proof that the methodology surfaces a real fix
rather than just churn.

### Exp 3 — red-team the verdict before committing ([#64](https://github.com/khalidAlfozan/realestate-agent/pull/64))

**Hypothesis.** Whatever verdict was leaning while writing §1–§7 was tending
to get *confirmed* at §8 rather than stress-tested. Pure confirmation-bias
risk.

**Change.** A new step 5 in `# Workflow`, before the memo:

> Red-team the verdict before committing to it. With all the data in hand,
> state your preliminary verdict to yourself — Buy, Borderline, or Walk —
> then make the single strongest argument *against* it: the case a skeptical
> investor would press hardest. Weigh it honestly — change the verdict if
> the counter-case materially dents the thesis; keep it if the thesis
> survives.

A reasoning step, not a memo section. The 8-section template is untouched.

**Result.** `2 Buy / 13 B / 10 W` → `1 Buy / 11 B / 13 W`. The headline:
- **`bemowo-metro` Borderline → Walk** with confidence Medium → **High**.
  Exp 2 had produced an inconsistency here — the §8 label said "Borderline
  (leaning Walk)" while the body wrote "Walk at 979,000." The red-team
  caught it. This is exactly the kind of failure mode the change was
  designed for, surfaced on the first run.
- **`ochota-kamienica` Buy → Borderline.** The marginal Buy rested on a
  comp-set p75 rent; the red-team questioned it and took the median (yield
  4.96%, below the 5–7% range). An honest correction — the §8 explicitly
  states "would be a clear Buy at ~830k."

**Verdict: kept.** Lost the marginal Buy; gained a sharper Walk High and
visibly better §7 prioritisation across the suite.

### Exp 4 — framing & order (reverted, no PR)

**Hypothesis.** `system.md` opened with `# Output discipline` — formatting
rules. That frames the agent's task as **compliance**. Opening with an
analytical-standard preamble (what a sharp investment memo does) might
frame it as **analysis**.

**Change.** Reordered the prompt: opened with a short preamble on
analytical standards (skeptical reasoning, comp-set discipline, calibrated
verdicts), kept the rule sections but pushed them below.

**Result.** Verdict mix moved within band but a side-by-side read of five
cases showed **no qualitative improvement** — the §7 risk sections weren't
sharper, the §8 verdicts weren't better-stress-tested, the prose wasn't
tighter. The framing-as-analysis idea sounded plausible but didn't earn its
keep against the eval baseline.

**Verdict: reverted, no PR.** An honest null result. Worth documenting:
the methodology *only* has integrity if it rejects changes that don't pay
off, even when they came from your own backlog. If every experiment in a
"five wins out of six" series shipped, the bar wasn't real.

### Exp 5 — make the rent benchmark advisory ([#66](https://github.com/khalidAlfozan/realestate-agent/pull/66))

**Hypothesis.** `# Choosing the rent benchmark` listed prescriptive
triggers: "ground floor → p25 with 5–10% discount", "new-build → p75",
etc. Applied on top of comp-set medians, these **double-count** factors
the comps already price. A ground-floor flat in a comp set that also
contains ground-floor flats already has "ground-floorness" baked into the
median — subtracting another 5–10% pushes the rent estimate artificially
low.

**Change.** Made the section advisory: the comps already reflect the
distribution of floors / conditions / build years / amenities; default to
the median when typical of the comp set, lean p25/p75 only when the subject
is genuinely *unusual relative to the comp set* on a specific factor.

**Result.** The decisive evidence was in `wola-1959`'s §5, side by side:
- **Baseline:** took p25 (79 PLN/m²) **then applied an additional 8%
  ground-floor discount on top**, anchoring further to a 67 PLN/m² direct
  comp → 5,000 PLN rent → 4.65% yield → Walk. **This is literally the
  double-counting the hypothesis predicted.**
- **Exp 5:** kept p25 straight, with explicit case-specific reasoning that
  the comp-set p25 already reflects the ground-floor/older-build profile —
  no second discount → 5,767 PLN rent → 5.36% yield → Borderline.

**Verdict: kept.** The §5 reasoning is sharper across the suite — the agent
now identifies which comp-set members are direct matches and reasons about
the benchmark from there, rather than applying a mechanical adjustment.

### Exp 6 — leading TL;DR block ([#67](https://github.com/khalidAlfozan/realestate-agent/pull/67))

**Hypothesis.** A reader skimming the memo in Streamlit, or pasting it into
Slack, had to scroll past 7 sections before seeing the recommendation.
That's a product problem, not a reasoning problem.

**Change.** Inserted a `**TL;DR**` block between the metadata header and
`## 1. Property summary` — verdict + confidence, gross yield with range
context, single key driver, optional fair-value counter for Walks. §8 stays
intact; the TL;DR is for the skimmer, §8 is for the reader who studies.

**Result.** Verdict mix wobbled within bands (`0 / 13 / 12` → `0 / 12 / 13`)
— a net wash with no systemic shift, exactly what a UX change should show
against a reasoning-focused scoreboard. The TL;DR rendered well on
`srodmiescie-kamienica` and across the spot-checks; the parser remained
§8-scoped, so the new TL;DR verdict line didn't confuse anything.

**Verdict: kept.** Same reasoning, better surface.

## The aggregate result

| stage | verdict mix | suite |
|---|---|---|
| pre-pass baseline (medium effort) | 0 / 9 / 16 | 25 / 25 |
| Exp 1 (+ high effort) | 0 / 9 / 16¹ | 25 / 25 |
| Exp 2 (+ calibration) | 2 / 13 / 10 | 25 / 25 |
| Exp 3 (+ red-team) | 1 / 11 / 13 | 25 / 25 |
| Exp 4 (+ framing) | within-band wobble, no qualitative lift | reverted |
| Exp 5 (+ heuristic priors advisory) | 0 / 13 / 12 | 25 / 25 |
| Exp 6 (+ TL;DR) | 0 / 12 / 13 | 25 / 25 |

¹ verdict mix recorded equal in numbers but with 7 individual-case shifts
(Borderline ↔ Walk) and a measured reasoning lift.

The headline-metric movement is small: the suite started 0 Buy and ended 0
Buy. But the *quality* changes underneath are substantial:

- The agent now stress-tests its verdict before writing §8.
- Verdict criteria are explicit, and Buy is reachable in principle (Exp 2
  proved it on `srodmiescie`; later experiments lost it for *valid*
  reasons — Exp 3's red-team correctly downgraded the marginal Buy; Exp 5's
  rent-benchmark change correctly raised the bar on the surviving one).
- Rent benchmarks are no longer mechanically discounted on top of comps
  that already price the same factors.
- The reader sees the verdict on screen one.
- All at high reasoning effort, with confidence rising on the
  stress-tested cases (`bemowo` Medium → High, `wola` Medium → High).

## What the methodology taught me

**Eval bands catch regressions, side-by-side reads judge improvements.**
The suite's job is to flag "did this change break something I didn't intend
to change." For "did this change make the *thinking* better," there is no
substitute for reading a handful of memos side by side. Both halves are
necessary; either one alone is dangerous.

**Re-baseline after every accepted change.** Once Exp 2's calibration ships
and `srodmiescie` becomes a Buy, `cases.json` has to allow Buy for
`srodmiescie` — otherwise the next experiment fails on a "regression" that's
really nostalgia for the pre-Exp-2 verdict. The assertions follow what the
*current* prompt actually produces. The discipline isn't preserving old
outputs; it's catching unintentional drift from the current good output.

**The cheapest experiment goes first.** Exp 1 (high effort) was a one-line
config change. It didn't unlock Buys, but it answered the question "is the
zero-Buy problem an effort problem or a calibration problem" cheaply and
unambiguously, scoping Exp 2 properly. If Exp 1 *had* unlocked Buys, Exp 2
might never have run. The cost of running the cheap experiment first is
nearly zero; the value of the answer is high either way.

**Honest null results are the most credible signal.** If every experiment
in a series ships, either you're cherry-picking your backlog or your bar is
soft. Exp 4 didn't reach a PR — the framing-as-analysis hypothesis sounded
good in the backlog and *was* worth testing, but it didn't earn its keep.
Reverting it (without a PR, without ceremony) is what makes the other five
believable.

**Symptom and lever aren't always the same.** The Exp 5 writeup found a
case where `srodmiescie-kamienica` had reported `median=98` in one run and
`median=92` in another for the same snapshot data — a *reading* quirk in
how the agent narrates comp stats, not a reasoning change from the
experimental lever. Without a structured scoreboard, that would have looked
like a regression caused by Exp 5. With the scoreboard, it traced cleanly
back to a pre-existing agent quirk, separable from the lever under test.
You can't always fix what the suite surfaces, but you can avoid
mis-attributing it.
