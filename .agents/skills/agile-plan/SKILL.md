---
name: agile-plan
description: Generate an AI-Assisted Agile Development Plan as a Markdown file from a project goal, context and constraints. Use only when the user explicitly asks for an agile plan, sprint plan or development plan for a software project (for example "/agile-plan Goal: ..."). Do not use for writing application code, fixing bugs, or one-off task breakdowns.
argument-hint: <Goal> | Context: ... | Constraints: ... | Other details: ...
allowed-tools: Read, Glob, Grep, Write
disable-model-invocation: true
---

You are a Senior Software Engineer and Agile coach. Produce an **AI-Assisted Agile Development Plan** for the project described below.

## Input

$ARGUMENTS

(Input may include Goal, Context, Constraints and other details such as platform, language, framework, tools, deliverable and sprint length.)

## Rules

1. **Goal required.** If the input has no clear goal, ask for it (and at most 3 short clarifying questions) and stop. Otherwise do not ask questions; proceed.
2. **Use the repo if one exists.** Briefly scan the workspace (README, package files, folder structure, CLAUDE.md) so the plan fits the existing stack. If it is empty, plan from scratch.
3. **Never invent facts.** If a header field (language, framework, packaging, etc.) was not given, choose a sensible default and mark it "(proposed)". If it truly cannot be inferred, write "To be confirmed".
4. **Fixed format.** Use EXACTLY the template below: same title, same header fields, same five phases, same Final Deliverable section, same order, every run. Do not add, remove, rename or reorder sections. Keep wording of the fixed text (Daily Workflow, Phase 5) as written, only substituting the AI tool name.
5. **Backlog rules.** IDs are sequential `US-001`, `US-002`, ... Priority is High, Medium or Low. Use 8 to 15 items. Every backlog item must be covered by a Sprint goal in Phase 3.
6. **Sprint rules.** Default sprint duration is 5 Working Days. Use 3 to 6 sprints. The last sprint is always testing plus packaging/release (or deployment) of the Final Deliverable.
7. **Last-sprint tasks.** In Phase 4, write 8 to 10 numbered tasks for the final sprint, tailored to the Final Deliverable: testing, build/package, installer or deployment config, clean-environment verification, security checks, and final approval.
8. **Plan only.** Do not write application code or change project files other than the plan itself.
9. **Save the file** to `docs/plans/<kebab-case-project-name>-agile-plan.md` (create folders if needed). Then reply with the path, a 3-line summary, and any "(proposed)" or "To be confirmed" items only.

## Template (copy this structure exactly)

```markdown
# AI-Assisted Agile Development Plan

**Project:** <Project Name>
**Application Type:** <e.g. Windows Desktop / Web App / Mobile App / API / CLI>
**Language:** <language and version>
**GUI / Framework:** <UI toolkit or framework>
**Development:** <IDE and AI tool, e.g. VS Code + Claude Code>
**Packaging / Deployment:** <build and packaging tools>
**Final Deliverable:** <e.g. setup.exe / Docker image / deployed URL / app store build>
**Sprint Duration:** <N Working Days>

---

## Phase 1 — Project Planning

**Objective:** <one or two sentences describing what will be built and for whom>

**Requirements:**
- <requirement>
- <requirement>

---

## Phase 2 — Product Backlog

| ID | Feature | Priority |
|----|---------|----------|
| US-001 | <feature> | High |
| US-002 | <feature> | High |

---

## Phase 3 — Sprint Planning

| Sprint | Duration | Goal |
|--------|----------|------|
| Sprint 1 | <N Days> | <goal> |
| Sprint 2 | <N Days> | <goal> |

---

## Phase 4 — AI Development & Testing

**Daily Workflow:**
1. Review approved Sprint tasks.
2. Assign tasks to <AI tool>.
3. AI proposes an implementation plan.
4. Product Owner approves the plan.
5. AI develops the feature.
6. AI runs automated tests.
7. IT Engineer verifies functionality.
8. Update the Sprint Backlog.
9. Commit reviewed changes using Git.

**Sprint <N> — <Testing and Packaging/Release> Tasks:**
1. <task>
2. <task>

---

## Phase 5 — Sprint Review & Retrospective

- Demonstrate completed features.
- Review testing results.
- Approve completed work.
- Identify problems and improvements.
- Update the Product Backlog.
- Plan the next Sprint.
- Repeat Phases 3–5 until the application meets its release requirements.

---

## Final Deliverable

**<deliverable name>** — <Project Name>

**Requirements:**
- <requirement>
- <requirement>

**Final Release Status:** Subject to successful <installation / deployment>, security and acceptance testing.
```
