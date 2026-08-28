#!/usr/bin/env python3
"""
Package the skill for the routes that are not the plugin marketplace.

    python scripts/package_skill.py                 # build dist/potato-tasks/ + .zip
    python scripts/package_skill.py --install-personal
    python scripts/package_skill.py --out /tmp/build

A Claude Code skill is a directory: `SKILL.md` plus whatever it references. The
same directory is what the Agent SDK loads and what the Claude API accepts as an
uploaded skill, so one build serves all three.

For Claude Code itself, `/plugin install potato-tasks@potato` is simpler than any
of this. Use the build when there is no marketplace in the picture -- the SDK and
the API both take a directory or a zip.
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from skillpack import REFERENCES, SCRIPTS, SKILL_MD, SKILL_NAME, reference_path, script_path


def build(out_dir: str) -> str:
    """Assemble the skill directory. Returns its path."""
    skill_dir = os.path.join(out_dir, SKILL_NAME)
    if os.path.isdir(skill_dir):
        shutil.rmtree(skill_dir)
    os.makedirs(os.path.join(skill_dir, "references"), exist_ok=True)
    os.makedirs(os.path.join(skill_dir, "scripts"), exist_ok=True)

    shutil.copyfile(SKILL_MD, os.path.join(skill_dir, "SKILL.md"))
    for name in REFERENCES:
        shutil.copyfile(reference_path(name),
                        os.path.join(skill_dir, "references", name))
    for name in SCRIPTS:
        dest = os.path.join(skill_dir, "scripts", name)
        shutil.copyfile(script_path(name), dest)
        # copyfile drops the mode, and a helper the skill tells an agent to run
        # should be runnable.
        os.chmod(dest, 0o755)
    return skill_dir


def zip_skill(skill_dir: str) -> str:
    """Zip the directory with the skill name as the top-level entry."""
    archive = skill_dir.rstrip(os.sep) + ".zip"
    parent = os.path.dirname(skill_dir)
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, _dirs, files in os.walk(skill_dir):
            for name in sorted(files):
                full = os.path.join(root, name)
                zf.write(full, os.path.relpath(full, parent))
    return archive


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--out", default="dist",
                        help="Where to build (default: dist/)")
    parser.add_argument("--no-zip", action="store_true")
    parser.add_argument("--install-personal", action="store_true",
                        help="Also copy into ~/.claude/skills/, making the skill "
                             "available in every project on this machine")
    args = parser.parse_args(argv)

    out_dir = os.path.abspath(args.out)
    os.makedirs(out_dir, exist_ok=True)
    skill_dir = build(out_dir)

    files = sum(len(f) for _r, _d, f in os.walk(skill_dir))
    print(f"Built {skill_dir} ({files} files)")

    archive = None
    if not args.no_zip:
        archive = zip_skill(skill_dir)
        size = os.path.getsize(archive) / 1024
        print(f"Built {archive} ({size:.0f} KB)")

    if args.install_personal:
        personal = os.path.expanduser(os.path.join("~", ".claude", "skills", SKILL_NAME))
        if os.path.isdir(personal):
            shutil.rmtree(personal)
        shutil.copytree(skill_dir, personal)
        print(f"Installed {personal}")

    print(f"""
Three ways to use what was just built:

  Claude Code, every project on this machine
      cp -r {skill_dir} ~/.claude/skills/
      (or re-run this with --install-personal)

  Claude Agent SDK
      Point the SDK's skill directory setting at {os.path.dirname(skill_dir)}
      and it loads {SKILL_NAME} the same way Claude Code does.

  Claude API
      Upload {archive or "the zip"} as a skill, then reference it from the
      Messages API. The endpoint is in beta and the exact shape moves, so check
      Anthropic's Agent Skills documentation for the current call.

Inside Claude Code, the marketplace is less work than any of these:

      /plugin marketplace add davidjurgens/potato-skill
      /plugin install potato-tasks@potato
""")
    return 0


if __name__ == "__main__":
    sys.exit(main())
