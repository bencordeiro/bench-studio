# Terminal suite review

The three questioned answer keys were reproduced locally with SQLite, GNU sed and Git. None needs a different expected value. Terminal suite 2.1.0 retains all twelve questions and their weights.

| Question | Expected answer | Reason |
| --- | --- | --- |
| WAL reader snapshot across a writer commit | `10,10,30` | R's first read establishes its snapshot. W commits successfully in WAL mode, but R retains the old snapshot until its own COMMIT. The next read sees both rows. |
| sed range over mixed script blocks | `13` | Selected input lines are 6–11, 13–16 and 19–21: six plus four plus three. The ending regexp is first tested on the line after an opening match. A closing tag inside a JavaScript string still ends a range. The final one-line script starts a range that continues through EOF. |
| Reachability after reset and a divergent commit | `3,3,1` | HEAD reaches D, B, A; saved reaches C, B, A. `HEAD..saved` includes only C. Reflog entries do not add commits to these traversals. |

These behaviors agree with the [SQLite isolation documentation](https://www.sqlite.org/isolation.html), [GNU sed address rules](https://www.gnu.org/software/sed/manual/html_node/Addresses.html), and [Git rev-list documentation](https://git-scm.com/docs/git-rev-list).

A real formatting mismatch was found: the old exact graders rejected `ANSWER: 10, 10, 30` and `ANSWER: 3, 3, 1`, despite the prompts permitting comma-separated answers without forbidding spaces. Their graders now accept spaces after either comma, including mixtures, while still rejecting wrong values, missing values and extra values. Expected answers are unchanged.

The Git prompt now explicitly specifies distinct commit messages and no other commits. The SQLite prompt explicitly specifies a committed initial row, private caches and autocommit outside the stated transactions. The sed prompt explicitly names GNU sed 4.9 and LF line endings; its irrelevant editorial JavaScript line was simplified without changing the line count or matching behavior.

On restart, bundled seeding upgrades the live suite to 2.1.0 while preserving its ID. A targeted startup repair also corrects completed saved WAL/Git answers rejected for comma spacing and refreshes their cached run summaries, including leaderboard and Index scores. Original prompt snapshots, responses and reasoning remain intact; the grade details record the correction and previous grade. Wrong answers, failed or token-exhausted generations, manual overrides and locally altered answer keys are left alone. No re-benchmarking is needed. Regression checks execute the underlying tools and test accepted and rejected answer formats. No model endpoint requests were used.
