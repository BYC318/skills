---
name: git-commit-spec
description: Generate, rewrite, review, and validate git commit messages that conform to Conventional Commits 1.0.0. Use when Codex needs to draft a commit message from staged changes or diffs, normalize an existing message, choose a type/scope/description, mark breaking changes, add issue footers, or enforce Conventional Commits style for git commits, squash merges, and PR merge messages.
---

# Git Commit Spec

## Overview

Write git commit messages that follow Conventional Commits 1.0.0 and stay faithful to the actual code changes. Prefer one accurate message over several weak alternatives.

## Output Language

Write all human-readable content in Simplified Chinese by default:

- Keep Conventional Commits structure tokens and code identifiers in their required form, including types such as `feat` and `fix`, scopes, `BREAKING CHANGE`, `Refs`, and `Closes`.
- Write the summary description, body, footer content, and any necessary explanation in Simplified Chinese.
- Treat English source code, identifiers, repository content, skill instructions, and examples as evidence, not as a request to answer in English.
- Use another language only when the user explicitly requests it.

## Workflow

1. Inspect the staged diff, requested changes, or user summary before writing the message.
2. Identify the dominant intent of the change. If the work mixes unrelated intents, recommend splitting the commit instead of forcing one misleading title.
3. Choose the smallest accurate type:
   - `feat` for a new feature.
   - `fix` for a bug fix.
   - Other types are allowed by the spec. Use project conventions such as `docs`, `refactor`, `test`, `build`, `ci`, `chore`, `perf`, or `revert` only when they fit the actual change.
4. Add a scope only when it clarifies the affected area, such as `api`, `parser`, or `auth`. Omit the scope when it is uncertain or artificial.
5. Write the summary line as `<type>[optional scope][optional !]: <description>`.
6. Keep the description short, specific, and action-oriented. Describe the change itself, not the debugging process or the ticket workflow.
7. Use lowercase types by default for consistency. Avoid decorative prefixes, issue IDs in the summary, or trailing filler like `update stuff`.

## Breaking Changes

- Mark a breaking change with `!` immediately before the colon, for example `feat(api)!: remove v1 session endpoint`.
- Add a `BREAKING CHANGE: ...` footer when the compatibility impact needs explanation.
- If `!` is used without a breaking-change footer, make sure the summary itself clearly states the breaking change.

## Body And Footers

- Add a body only when extra context helps the reader understand why the change exists or how it behaves.
- Separate the body from the summary with exactly one blank line.
- Add one or more footers only when the user or repo context provides real metadata, such as issue references.
- Use footer tokens such as `Refs: #123` or `Closes #456` only when those references are known. Never invent issue IDs, ticket keys, or breaking-change details.

## Output Rules

- Unless the user asks for alternatives or explanation, return only the raw commit message.
- When the user asks to review or fix an existing commit message, explain the exact rule violation and then provide the corrected message.
- When the diff does not justify the requested type, say so and choose the type that matches the code.
- When the user asks for project-specific type vocabularies or footer formats, follow the repo convention if it does not contradict the specification.

## Quick Checks

- Summary starts with a type.
- Scope, if present, is wrapped in parentheses.
- Summary contains a colon and single space before the description.
- Description appears immediately after the prefix.
- Body starts one blank line after the summary.
- Footers start one blank line after the body or summary.
- `BREAKING CHANGE` stays uppercase when used as a footer token.

## Examples

```text
feat(parser): 支持数组字面量
```

```text
fix(auth): 刷新过期的会话令牌
```

```text
refactor(cache): 简化缓存失效流程

删除重复的淘汰分支，并集中处理缓存键匹配。
```

```text
feat(api)!: 移除旧版会话接口

BREAKING CHANGE: 客户端必须从 `/v1/session` 迁移到 `/v2/session`。
```

## Reference

Read `references/conventional-commits.md` when exact structure, footer grammar, or common type guidance is needed.
