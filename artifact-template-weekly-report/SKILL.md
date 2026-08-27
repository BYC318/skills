---
name: artifact-template-weekly-report
description: "Create an email using the weekly-report template and its retained reference file. Use when the user selects this template, names weekly-report, or explicitly invokes $artifact-template-weekly-report. 将本周工作、问题复盘和下周计划整理为适合企业微信邮件发送的简体中文研发周报。"
---

# weekly-report

Create an email from this template. Keep the reference file unchanged.

## Workflow

1. Read `artifact-template.json` and resolve its paths relative to this skill directory.
2. Read the retained plain-text email and use it as the structural and voice reference.
3. Draft a new plain-text email that preserves the reference's subject, body, calls to action, and signature conventions.
4. Treat the user's prompt and available sources as the content input. Do not invent facts or send the email merely because this skill was invoked.
5. Review the draft for fidelity, completeness, and ready-to-copy plain-text formatting, then return it.

## Fidelity

Preserve the reference email's voice, information hierarchy, pacing, subject, body, calls to action, and signature conventions.

User instructions control requested content and explicit deviations. The retained reference controls layout and formatting where the user has not requested a change.
