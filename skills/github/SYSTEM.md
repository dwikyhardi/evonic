# GitHub CLI (`gh`) Usage

## Mandatory: Token Setup (DO THIS FIRST)

You **cannot** use any `gh` command without a valid GitHub token. Before doing anything else, you **must** ensure the token is available. Follow this exact sequence:

### Step 1: Check if token is already stored

Call `recall()` to search long-term memory:

```
recall(query="GitHub personal access token")
```

If `recall()` returns a token — skip to **Step 3** (authenticate).

### Step 2: Ask the user (MANDATORY when no token)

If no token is found in memory, **stop immediately** and ask the user:

> I need a GitHub personal access token to use `gh`. Please provide one with `repo` and `workflow` scopes. You can create one at https://github.com/settings/tokens. I'll store it in my memory so you only need to do this once.

When the user provides the token, **immediately save it**:

```
remember(content="User's GitHub personal access token for API operations: <the-token>", category="user_info")
```

Then proceed to Step 3.

### Step 3: Authenticate

With the token in hand, choose one method:

**Per-command (recommended — token never lingers in env):**

```bash
GITHUB_TOKEN="<token>" gh pr list --repo {owner}/{repo}
```

**Session-wide (convenient for multiple commands):**

```bash
export GITHUB_TOKEN="<token>"
```

**Persistent login (survives the session):**

```bash
echo "<token>" | gh auth login --with-token
```

Verify it works:

```bash
gh auth status
```

### Token Security Rules

- **Never echo or log the token** in visible output. Always pipe it or use env vars.
- **Never commit the token** to any file.
- The token needs `repo` scope (for private repos) and `workflow` scope (for Actions).

---

## Default Repository

The repo slug `{owner}/{repo}` is used throughout this document. Substitute the actual repo you're working with. If you're inside a cloned repo directory, omit `--repo` — `gh` auto-detects from the git remote.

```bash
cd /path/to/repo && gh pr list    # auto-detects from git remote
```

---

## Pull Requests

### List

```bash
gh pr list --repo {owner}/{repo}
gh pr list --repo {owner}/{repo} --state all
gh pr list --repo {owner}/{repo} --label bug
gh pr list --repo {owner}/{repo} --search "fix:" --limit 50 --json number,title,state,author,createdAt
```

### View

```bash
gh pr view 42 --repo {owner}/{repo}                              # summary
gh pr view 42 --repo {owner}/{repo} --json number,title,body,state,author,mergeable,reviews
gh pr view 42 --repo {owner}/{repo} --json files,additions,deletions
```

### Diff

```bash
gh pr diff 42 --repo {owner}/{repo}
gh pr diff 42 --repo {owner}/{repo} --color=always
```

### Changed file list (programmatic)

```bash
gh pr view 42 --repo {owner}/{repo} --json files --jq '.files[].path'
```

### Checkout locally

```bash
gh pr checkout 42 --repo {owner}/{repo}
```

### Comment

```bash
gh pr comment 42 --repo {owner}/{repo} --body "Your comment here"
```

For multi-line comments, use a heredoc:

```bash
gh pr comment 42 --repo {owner}/{repo} --body "$(cat <<'EOF'
Line one.
Line two.
EOF
)"
```

**Always follow the PR commenting convention** (see bottom of this document).

### Close (without merging)

```bash
gh pr close 42 --repo {owner}/{repo}
gh pr close 42 --repo {owner}/{repo} --comment "Closing because..."
```

### Reopen

```bash
gh pr reopen 42 --repo {owner}/{repo}
```

### Merge

```bash
gh pr merge 42 --repo {owner}/{repo} --merge --delete-branch       # merge commit
gh pr merge 42 --repo {owner}/{repo} --squash --delete-branch      # squash
gh pr merge 42 --repo {owner}/{repo} --rebase --delete-branch      # rebase
gh pr merge 42 --repo {owner}/{repo} --auto --merge                # auto-merge when checks pass
```

Flags: `--merge` / `--squash` / `--rebase`, `--delete-branch`, `--auto`, `--admin`.

**Never merge a PR without explicit user approval.**

### Review

```bash
gh pr review 42 --repo {owner}/{repo} --approve --body "LGTM"
gh pr review 42 --repo {owner}/{repo} --request-changes --body "Needs work on..."
gh pr review 42 --repo {owner}/{repo} --comment --body "Just a note..."
```

### Edit a comment

```bash
# Find comment ID first
gh api repos/{owner}/{repo}/issues/42/comments --jq '.[] | {id, body}'

# Edit by ID
gh api -X PATCH repos/{owner}/{repo}/issues/comments/<comment-id> -f body="Updated text"
```

### Create

```bash
gh pr create --repo {owner}/{repo} \
  --title "feat: add widget frobnicator" \
  --body "## Summary\nAdds frobnicator for widgets.\n\nFixes #123" \
  --base main \
  --head feature/frobnicator
```

### Edit title or body

```bash
gh pr edit 42 --repo {owner}/{repo} --title "New title"
gh pr edit 42 --repo {owner}/{repo} --body "New body"
```

---

## Issues

### List

```bash
gh issue list --repo {owner}/{repo}
gh issue list --repo {owner}/{repo} --state all
gh issue list --repo {owner}/{repo} --label bug
gh issue list --repo {owner}/{repo} --assignee @me
gh issue list --repo {owner}/{repo} --search "crash" --limit 50 --json number,title,state,labels
```

### View

```bash
gh issue view 99 --repo {owner}/{repo}
gh issue view 99 --repo {owner}/{repo} --json number,title,body,state,comments
```

### Create

```bash
gh issue create --repo {owner}/{repo} \
  --title "Bug: frobnicator leaks memory" \
  --body "## Steps\n1. Run frobnicator\n2. Watch memory\n\n## Expected\nStable\n\n## Actual\nOOM after 10 min" \
  --label "bug,needs-triage"
```

### Comment

```bash
gh issue comment 99 --repo {owner}/{repo} --body "Working on this."
```

### Close

```bash
gh issue close 99 --repo {owner}/{repo}
gh issue close 99 --repo {owner}/{repo} --reason completed
gh issue close 99 --repo {owner}/{repo} --reason "not planned"
gh issue close 99 --repo {owner}/{repo} --comment "Fixed in commit abc1234"
```

**When closing an issue that you fixed, always include the commit hash in the comment.**

### Reopen

```bash
gh issue reopen 99 --repo {owner}/{repo}
```

### Edit

```bash
gh issue edit 99 --repo {owner}/{repo} --title "New title"
gh issue edit 99 --repo {owner}/{repo} --body "Updated body"
gh issue edit 99 --repo {owner}/{repo} --add-label "bug" --remove-label "wontfix"
```

---

## Repo Operations

### Clone

```bash
gh repo clone {owner}/{repo}
gh repo clone {owner}/{repo} /path/to/dest
```

### View info

```bash
gh repo view {owner}/{repo}
gh repo view {owner}/{repo} --json name,description,defaultBranch,isPrivate,updatedAt
```

---

## GitHub API (`gh api`) — Escape Hatch

When `gh` subcommands don't cover what you need:

```bash
# Raw JSON for any endpoint
gh api repos/{owner}/{repo}/pulls/42

# Edit a comment
gh api -X PATCH repos/{owner}/{repo}/issues/comments/123456 -f body="Updated"

# List PR reviews
gh api repos/{owner}/{repo}/pulls/42/reviews

# Check rate limit
gh api rate_limit --jq '.rate'
gh api rate_limit --jq '.resources.core'
```

---

## Working Inside a Cloned Repo

When inside a cloned repo, omit `--repo`:

```bash
git remote -v                    # verify remote origin
gh pr list                       # auto-detects repo
gh issue view 99
gh pr diff 42
```

---

## PR Commenting Convention (MANDATORY)

Every PR comment posted via `gh pr comment` or `gh pr review` **must** follow this template:

```
Thank you for the PR! [review content]

Best,
{agent_name}
--
{user_name}'s agent.
```

### Rules

1. **Never mention the PR author's name** — not even in greeting.
2. **Sign as yourself** — use your agent name, never the user's name.
3. **Always add the footer** `-- {user_name}'s agent.` after the signature.

### Correct example

```
Thank you for the PR! The locking is correct and error handling is
solid. One suggestion: extract that 200-line validation block into
a helper — it'll make the control flow much clearer.

Best,
{agent_name}
--
{user_name}'s agent.
```

### Wrong examples

```
// WRONG — mentions author name
Hi Robin, great PR!

// WRONG — signs as the user
Best,
{user_name}.
```

---

## Error Recovery

### "gh not authenticated"

```bash
gh auth status
echo "$GITHUB_TOKEN" | gh auth login --with-token
```

If `GITHUB_TOKEN` is empty, go back to **Step 1** — retrieve from memory or ask the user.

### "Could not resolve to a Pull Request with the number of X"

The PR/issue number doesn't exist or the token lacks access. Double-check the number and repo name.

### "Resource not accessible by integration"

Token scope issue. Ensure the token has `repo` scope.

### Rate limiting

```bash
gh api rate_limit --jq '.resources.core'
```

If near the limit, wait or inform the user.

---

## Summary Checklist

1. ✅ Token retrieved from memory — or user asked and token saved
2. ✅ `gh auth status` confirms authentication
3. ✅ `--repo {owner}/{repo}` on every command (or inside cloned repo)
4. ✅ PR comments follow the convention — no author name, signed as agent, agent footer present
5. ✅ Close issues with commit hash when fixed
6. ✅ Never merge PRs without user approval
