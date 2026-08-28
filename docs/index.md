# Potato annotation tasks

This is the reference material behind the `potato-tasks` Claude Code skill,
published so it can be read without installing anything.

[Potato](https://github.com/davidjurgens/potato) is a self-hosted annotation
tool: one YAML config plus a data file gets you a running study. These pages
cover the parts that config does not explain — what to ask annotators, how to
lay the interface out, which quality controls are worth their cost, and what
goes wrong once real people start clicking.

## Install the skill

```
/plugin marketplace add davidjurgens/potato-skill
/plugin install potato-tasks@potato
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
[repository](https://github.com/davidjurgens/potato-skill/tree/main/skills/potato-tasks/references).
