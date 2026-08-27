# Conventional Commits 1.0.0 Reference

Source: https://www.conventionalcommits.org/en/v1.0.0

## Core Structure

Use this shape:

```text
<type>[optional scope][optional !]: <description>

[optional body]

[optional footer(s)]
```

The specification requires:

- A type at the start of the summary.
- An optional scope in parentheses.
- An optional `!` before the colon to mark a breaking change.
- A required colon and space before the description.
- A blank line before the body.
- A blank line before the footer block.

## Required Semantics

- `feat` means a new feature.
- `fix` means a bug fix.
- Other types are allowed, but they are project conventions rather than hard requirements of the specification.
- Breaking changes can be marked with `!` in the summary or with a `BREAKING CHANGE:` footer.
- `BREAKING CHANGE` must stay uppercase when used as a footer token.
- `BREAKING-CHANGE` is treated as equivalent to `BREAKING CHANGE` in footers.

## Footer Notes

- A footer is metadata, not prose continuation.
- Footer tokens normally replace spaces with hyphens, such as `Reviewed-by` or `Refs`.
- A footer can also use the issue style separator ` #`, such as `Refs #123`.
- Footer values may continue across lines until the next valid footer token appears.

## Common But Optional Types

These are common ecosystem conventions, not mandatory parts of Conventional Commits:

- `docs`
- `refactor`
- `test`
- `build`
- `ci`
- `chore`
- `perf`
- `revert`

Prefer the repository's established vocabulary when it exists.

## Practical Guidance

- Omit the scope when it does not add real signal.
- Split unrelated changes into separate commits when possible.
- Keep the summary concrete and specific.
- Add a body only when a reader would benefit from extra reasoning or rollout details.
- Add issue references only when they are known from the prompt, diff, or repository context.

## Examples

```text
docs(readme): clarify local setup
```

```text
perf(search): reduce query allocations
```

```text
revert: restore previous cache key format

Refs: 676104e
```
