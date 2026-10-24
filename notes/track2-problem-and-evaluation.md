# Track 2: AI data-center power and computing co-scheduling

## Problem as stated

Track 2 asks for a method to schedule computing and electricity use in an AI data center as grid prices, computing demand, and power supply change over time, while making operation cheaper and greener without compromising service. The statement explains that renewable/green supply can be inexpensive but variable, grid prices vary, and workloads have different urgency. Therefore, low-cost/low-carbon periods may not coincide with peak demand.

The problem setters are named as Huawei Technologies Co., Ltd. and Xiamen Hithium Energy Storage Technology Co., Ltd. No dataset or standard answer is supplied. The team is expected to choose and justify workload types, which work can wait, applicable constraints, how to trade off cost versus greenness, and other relevant factors.

## Questions the submission must answer

The statement prioritizes justified results over a particular numerical answer. It asks the team to:

- Define what counts as “good” and how it is measured.
- Compare against a simple unscheduled approach and quantify where/how much the method improves.
- Explain why results are close to optimal rather than merely functional.
- Examine behavior under changing conditions and identify failure cases.
- Defend assumptions and explain how conclusions would change if assumptions were wrong.

The form of result presentation is left open. The statement also says internship or research opportunities may be offered to outstanding teams, but are not guaranteed and depend on solution quality and thoughtfulness.

## Useful interpretation

This is an operations-research modeling and evidence task, not only a coding challenge. A credible submission needs a defined workload and service model, explicit objective/metrics, a feasible baseline, a solver or other method with an honest optimality claim, and stress cases that expose where assumptions matter. This interpretation connects the Track 2 questions to the detailed pasted MVP specification; the exact model choices remain team decisions rather than facts imposed by the Track 2 PDF.

## Source boundaries

The Track 2 statement does not prescribe a solver, programming language, dataset, baseline algorithm, carbon accounting method, or battery model. Those details appear in the separate pasted text as a recommended/proposed project plan and should not be attributed to the Track 2 statement itself. No numerical performance result is supplied by either PDF.

## Works Cited

### Original sources

- [Track 2 Problem Statement(1).pdf](../sources/originals/Track%202%20Problem%20Statement%281%29.pdf) — supplied Track 2 problem statement copy.

### Source provenance

- [Track 2 statement provenance](../sources/provenance/track2-problem-statement.md)
