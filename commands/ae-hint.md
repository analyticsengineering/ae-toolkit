---
name: ae-hint
description: Give the next progressive, non-solution hint for the active analytics-engineering exercise, using only local exercise files.
---

# Give an Exercise Hint

Apply the `learning-coach` agent and its progressive hint ladder. This runs locally: it reads the exercise and the learner's work in the repository and sends nothing anywhere.

## Workflow

1. Read `.ae/exercise.json` and parse exercise identity, Learn or Assessment mode, constraints, allowed assistance, hint state, and expected artifact. If it is missing or invalid, say so and offer general coaching on the concept the learner names instead.
2. In Assessment mode, give a hint only when the exercise's allowed assistance permits hints. Otherwise say hints are off for this attempt and stop.
3. Ask the learner to point at the relevant artifact and say what they tried and where they are stuck, unless they already have.
4. Work out the next level. Start from `hints_used` in `.ae/exercise.json` when present, then count hints already given in this conversation. Do not edit `.ae/exercise.json` to record it.
5. Give exactly one hint at that level:
   - Hint 1: a conceptual question or direction;
   - Hint 2: a targeted observation about their artifact;
   - Hint 3: the relevant construct or pattern, without writing it for them.
6. Never write the solution, replacement SQL or model, or the content of hidden tests, answer files, or rubric internals the exercise marks as hidden. A full solution is allowed only in Learn mode, after three hints, when the learner explicitly asks for it and the exercise does not forbid it.
7. End with the hint level given and one self-check the learner can run to know whether the hint landed.
