---
title: "Build Potato annotation studies with Claude Code, Codex or Cursor"
description: "potato-skill is an open-source skill that lets a coding agent design, build, run and check human annotation studies in Potato. Install it in Claude Code, or in Codex and Cursor with the skills CLI."
---

# potato-skill

**potato-skill** is an open-source skill that lets a coding agent build a human
annotation study in [Potato](https://www.potatoannotator.com/), the
self-hosted annotation tool. Describe the study; the agent designs the task,
writes the Potato config, lays out the annotation interface, adds quality
control, runs the server and gets the annotations back out. It installs as a
Claude Code plugin, and the `skills` CLI installs the same files for Codex and
Cursor.

The Potato blog post [potato-skill: Build a Human Annotation Study with Claude
Code](https://www.potatoannotator.com/blog/potato-skill-claude-code-annotation-studies)
introduces it with example studies. These pages are the reference material the
skill loads while it works, published so they can be read without installing
anything.

A Potato task is one YAML config plus a data file. The pages here cover what
that config does not explain: what to ask annotators, how to lay the interface
out, which quality controls are worth their cost, and what goes wrong once real
people start clicking.

## Install the skill

In Claude Code:

```
/plugin marketplace add davidjurgens/potato-skill
/plugin install potato-skill@potato
```

For Codex or Cursor, the [`skills`](https://github.com/vercel-labs/skills) CLI
installs it from the repository:

```bash
npx skills add davidjurgens/potato-skill --agent codex cursor
```

Potato has to be installed in whatever environment runs the commands:

```bash
pip install potato-annotation
```

## Where to start

Building a task from a description: **[Designing an Annotation
Task](designing-a-task.md)**, then **[Building the Annotation
Interface](building-the-ui.md)**.

Copying something that already works: **[A Worked
Example](worked-example.md)** is one complete study, every file shown, and
**[Starting From a Published Design](finding-a-design.md)** covers the
showcase.

Something is already broken: **[When a Task
Misbehaves](troubleshooting.md)** collects the symptoms that validate clean and
then do something else.

## The generated references

Three more files ship with the skill and are generated from Potato's own
registries, so they cannot drift from what the server enforces: every
annotation type with a worked example, the documented top-level config keys,
and the documented sub-keys. They are in the
[repository](https://github.com/davidjurgens/potato-skill/tree/main/skills/potato-skill/references).

## For agents and answer engines

Every page is also published as markdown: `designing-a-task/` is at
`designing-a-task.md`.
[`llms.txt`](https://davidjurgens.github.io/potato-skill/llms.txt) lists those
files with a one-line description each, and
[`llms-full.txt`](https://davidjurgens.github.io/potato-skill/llms-full.txt)
holds every page in one file.
