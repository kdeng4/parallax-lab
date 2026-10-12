# Repository safeguards

Changes go through a pull request, pass `engine`, `web` and `containers`, and
merge with squash or rebase. CODEOWNERS records `kdeng4` as the responsible
owner. CI checks accounting, persistence, authorization, browser flows and builds;
it does not replace a review of the resulting behaviour.

## Default-branch rule

`.github/default-branch-ruleset.json` targets whichever branch is the repository
default. It requires a pull request and current-base status checks supplied by
the verified GitHub Actions integration, resolves review conversations, preserves
linear history, and blocks deletion and force pushes. No bypass actor is granted.

The required approving-review count is zero because this is a sole-maintainer
repository: GitHub does not let an author approve their own pull request. This
still requires a pull request and all checks. Raise the approval count after an
independent maintainer is added; CODEOWNERS alone does not enforce an approval.

## Application status

The rule is **prepared but not applied**. On October 12, 2026, the default branch
was `main`, `protected` was false, and the repository had no rulesets. The GitHub
connector returned `Resource not accessible by integration` for branch-protection
administration, and browser credential protection blocked the settings page.
Committing this JSON does not activate a GitHub rule.

An administrator can import it in GitHub repository Settings, under Rulesets:
choose **New ruleset → Import a ruleset**, select the JSON, review it, and create
the active rule. Alternatively, from a repository checkout with an authenticated
GitHub CLI account that has repository Administration write permission:

```bash
gh api --method POST repos/kdeng4/parallax-lab/rulesets \
  --input .github/default-branch-ruleset.json
```

Verify it afterwards with:

```bash
gh api repos/kdeng4/parallax-lab/rules/branches/main
```

Official references: [import rulesets](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/managing-rulesets-for-a-repository#importing-a-ruleset)
and [ruleset API](https://docs.github.com/en/rest/repos/rules#create-a-repository-ruleset).
