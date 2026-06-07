---
name: skill-creator
description: Create new skills, modify and improve existing skills, and package them for distribution. Use this skill when users want to create a skill from scratch, edit, or package an existing skill.
---

# Skill Creator

A skill for creating and packaging skills for the Togo agent platform.

## Togo Skill System

Togo has a two-tier skill system:

### Built-in Skills (内置技能)

- Location: `assets/skills/` in the Togo project directory
- Loaded at startup, marked `is_builtin=True`
- Only modifiable by developers (shipped with the product)
- Current built-in skills: `frontend-design`, `skill-creator`

### User Skills (外置技能)

- Location: `<STORAGE_ROOT>/skills/` directory
  - Development mode: `<repo>/dev_storage_root/skills/`
  - Production mode: `~/.togospace/skills/`
- Loaded at startup, marked `is_builtin=False`
- Created by users at runtime, no code deployment needed
- If a user skill has the same name as a built-in skill, the user skill takes priority

### How Skills Are Discovered

At startup, `skillService` scans both directories. Each subdirectory containing a `SKILL.md` with valid YAML frontmatter is registered. The `name` field in frontmatter must match the directory name. Skills are then available to agents through:

1. **Agent Authorization**: Each agent has an `allow_skills` list (e.g., `["frontend-design", "skill-creator"]`). Only listed skills can be loaded by that agent.
2. **Skill Loading**: Agents call the `load_skill` tool to load a skill's full content. The tool checks authorization and returns the SKILL.md content plus a file listing.
3. **Prompt Injection**: When building an agent's system prompt, authorized skills' names and descriptions are injected as a list, guiding the agent on when to use each skill.

### Adding a New User Skill

After creating a skill, you need to make it available to the system:

1. **Create the skill directory** in `<STORAGE_ROOT>/skills/<skill-name>/` with a valid `SKILL.md`
2. **Restart Togo** (or trigger a skill rescan) so the new skill appears in the registry
3. **Authorize the skill** for specific agents by updating their `allow_skills` property. This can be done via:
   - The web UI (Agent settings → Skills)
   - The API endpoint `POST /agents/<id>/modify_properties.json` with `{"allow_skills": ["skill-name"]}`
4. The agent will then see the skill in its available skills list and can `load_skill` it

### Updating an Existing Skill

For **user skills**, simply edit the files in `<STORAGE_ROOT>/skills/<skill-name>/` and restart.

For **built-in skills**, edit the files in `assets/skills/<skill-name>/` (requires code deployment). Be cautious — ensure the directory name and SKILL.md `name` field match.

---

## Creating a Skill

### Step 1: Capture Intent

Understand what the user wants the skill to do. Ask clarifying questions:

1. What should this skill enable an agent to do?
2. When should this skill trigger? (what user phrases/contexts)
3. What's the expected output format?

If the user has already demonstrated a workflow in conversation, extract the pattern from there.

### Step 2: Determine Skill Location

Decide where to create the skill:

- **User skill** (default): Create in `<STORAGE_ROOT>/skills/<skill-name>/`. This is the standard path for skills created at runtime.
- **Built-in skill** (developer only): Create in `assets/skills/<skill-name>/`. Only for skills that ship with the product.

Use the Togo workspace path as STORAGE_ROOT. In development mode this is typically `<repo>/dev_storage_root/`. You can find it by checking the `WORKSPACE_ROOT` config — the skills directory is a sibling of workspace: `<STORAGE_ROOT>/skills/`.

### Step 3: Write the SKILL.md

Each skill must have a `SKILL.md` with YAML frontmatter:

```yaml
---
name: my-skill-name
description: When to trigger, what it does. Include both what the skill does AND specific contexts for when to use it.
---
```

**Critical rules:**
- The `name` field must exactly match the directory name
- The `description` field is under 1024 characters (hard limit) and is the primary triggering mechanism
- Keep SKILL.md body under 500 lines; use reference files for longer content
- Write descriptions in the imperative: "Use this skill for..." not "this skill does..."

**Writing guidelines:**
- Explain *why* things are important, not just *what* to do
- Be "pushy" in descriptions to combat under-triggering — cover synonyms and related contexts
- Focus on user intent, not implementation details

### Step 4: Add bundled resources (optional)

If the skill benefits from helper scripts, reference docs, or templates:

- **scripts/** — Reusable code. Reference from SKILL.md with clear instructions on when/how to run it. Use `python -m scripts.<script_name>` from the skill directory.
- **references/** — Long-form documentation. Reference from SKILL.md with guidance on when to read each file.
- **assets/** — Templates, icons, fonts, or other binary resources.

### Step 5: Validate and fix

Run the validation script from the skill-creator directory:

```bash
python -m scripts.quick_validate <path-to-skill>
```

This checks:
- Valid YAML frontmatter with `name` and `description`
- `name` matches directory name
- SKILL.md is under 500 lines
- Referenced files exist

Fix any errors reported.

### Step 6: Register and authorize

After creating the skill in the correct directory:

1. Restart Togo or trigger a skill rescan so `skillService` picks up the new skill
2. Add the skill name to target agents' `allow_skills` list (via web UI or API)
3. Verify the skill appears when the agent calls `load_skill`

---

## Improving an Existing Skill

1. Read the current SKILL.md and understand what it does
2. Identify specific problems based on user feedback
3. Make targeted improvements while keeping the overall structure
4. Re-validate with `quick_validate.py`

### Key improvement principles

1. **Generalize, don't overfit.** The skill should work for many prompts, not just specific examples.
2. **Keep it lean.** Remove instructions that aren't pulling their weight.
3. **Explain the why.** Help the model understand reasoning, not just steps.
4. **Extract repeated patterns.** If helper logic appears across multiple interactions, extract it into a `scripts/` file.

---

## Packaging a Skill

When the skill is finished, package it for distribution:

```bash
python -m scripts.package_skill <path/to/skill-folder> [output-directory]
```

This creates a `.skill` file (ZIP format) containing all skill resources. The output `.skill` file path should be communicated to the user for installation.

**To install a packaged skill**, the user should:
1. Unzip the `.skill` file to `<STORAGE_ROOT>/skills/<skill-name>/`
2. Ensure the `name` in SKILL.md matches the directory name
3. Restart Togo and authorize the skill for target agents

---

## Quick Reference

| Concept | Path | Notes |
|---------|------|-------|
| Built-in skills | `assets/skills/<name>/` | Shipped with product, dev only |
| User skills | `<STORAGE_ROOT>/skills/<name>/` | Runtime, same-level priority overrides built-in |
| Skill entry point | `SKILL.md` | YAML frontmatter + Markdown |
| Agent authorization | `allow_skills` property | List of skill names the agent can load |
| Validation | `python -m scripts.quick_validate <path>` | Check SKILL.md format |
| Packaging | `python -m scripts.package_skill <path>` | Create distributable .skill file |