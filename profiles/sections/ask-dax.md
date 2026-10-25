## Ask Dax, don't guess

When you meet something your task doesn't settle, stop and ask Dax, the way you would stop and
ask a person at the keyboard. Stop when the task contradicts the code or the spec, when it needs
a decision it doesn't make, or when finishing would mean changing files outside its scope. Don't
stop for what reading the repository, its openspec/ or this file settles.

1. Open your pull request as a draft: `gh pr create --draft`. Never mark it ready for review.
2. To ask: commit and push what you have, and add a section `Question for Dax:` to the draft's
   description. Give one question, what you found that raised it, and the options you see, with
   the one you would pick. Write the draft's URL on the first line of your report, then
   `Question for Dax:` and the question. Then stop. Don't guess, and don't widen the task.
3. If the dispatcher's notes say `Continue draft PR #N`, start by merging its branch into yours
   (`git fetch origin <its branch>`, then `git merge --no-edit FETCH_HEAD`), and begin your new
   draft's description with `Supersedes #N`.
