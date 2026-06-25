"""Load Impulse skill files and references into a structured knowledge base for the LLM agent.

Supports two modes:
- **Index mode**: parse YAML frontmatter to build a compact skill catalogue for the system prompt.
- **On-demand mode**: load the full SKILL.md + references when the agent calls the `load_skill` tool.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from server.config import SKILLS_ROOT

SKILL_NAMES = [
    "create-report",
    "configure-report",
    "select-vehicles",
    "define-channels",
    "define-aggregations",
    "validate-report-execution",
]

_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---", re.DOTALL)


@dataclass
class SkillIndex:
    name: str
    description: str


@dataclass
class SkillKnowledge:
    name: str
    skill_md: str
    references: dict[str, str] = field(default_factory=dict)


def _read_file(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return ""


def _parse_frontmatter(text: str) -> dict[str, str]:
    """Extract key-value pairs from YAML frontmatter (simple flat parser)."""
    match = _FRONTMATTER_RE.match(text)
    if not match:
        return {}
    result: dict[str, str] = {}
    for line in match.group(1).splitlines():
        if ":" in line and not line.startswith(" "):
            key, _, value = line.partition(":")
            result[key.strip()] = value.strip().strip('"').strip("'")
    return result


def _skills_root() -> Path:
    return Path(os.path.abspath(SKILLS_ROOT))


@lru_cache()
def load_skill_index() -> list[SkillIndex]:
    """Parse frontmatter from each SKILL.md to build a compact catalogue."""
    root = _skills_root()
    index: list[SkillIndex] = []
    for name in SKILL_NAMES:
        text = _read_file(root / name / "SKILL.md")
        fm = _parse_frontmatter(text)
        desc = fm.get("description", f"{name} skill (no description found)")
        index.append(SkillIndex(name=name, description=desc))
    return index


def load_skill_full(skill_name: str) -> str:
    """Load the full SKILL.md content + all reference files for a given skill."""
    if skill_name not in SKILL_NAMES:
        return f"Unknown skill '{skill_name}'. Available: {', '.join(SKILL_NAMES)}"

    root = _skills_root()
    base = root / skill_name
    skill_md = _read_file(base / "SKILL.md")
    if not skill_md:
        return f"Skill '{skill_name}' has no SKILL.md content."

    parts = [f"## Skill: {skill_name}\n\n{skill_md}"]

    refs_dir = base / "references"
    if refs_dir.is_dir():
        for ref_file in sorted(refs_dir.iterdir()):
            if ref_file.suffix == ".md":
                content = _read_file(ref_file)
                if content:
                    parts.append(f"### Reference: {skill_name}/{ref_file.name}\n\n{content}")

    return "\n\n".join(parts)


def build_system_prompt(
    wizard_step: str = "report_name",
    signals: list[dict] | None = None,
    available_channels: list[dict] | None = None,
    vehicle_candidates: list[dict] | None = None,
    vehicles: list[dict] | None = None,
    data_sources: dict | None = None,
) -> str:
    """Compose a compact system prompt with skill index and wizard-step context."""
    index = load_skill_index()

    skill_list = "\n".join(f"- **{s.name}**: {s.description}" for s in index)

    step_instructions = _STEP_INSTRUCTIONS.get(wizard_step, "")

    signal_context = ""
    if signals:
        lines = ["## Currently Defined Signals\n"]
        lines.append("Use these exact `var_name` values when referencing signals in virtual channel expressions.\n")
        for s in signals:
            kind = s.get("signal_type", "physical")
            name = s.get("var_name", "")
            alias = s.get("alias", "")
            ch_name = s.get("channel_name", "")
            expr = s.get("expression", "")
            if kind == "physical":
                label = ch_name or alias or name
                lines.append(f"- `{name}` (physical, channel: `{label}`)")
            else:
                lines.append(f"- `{name}` (virtual, expression: `{expr}`)")
        signal_context = "\n".join(lines) + "\n\n"

    channel_catalog_context = ""
    if available_channels:
        lines = ["## Available Channels in Silver Layer\n"]
        lines.append("These channels were discovered from the ingested data. Use this list to match "
                      "user requests to actual channel names. Channel names may be abbreviated or in "
                      "German — use the unit and value ranges as context clues.\n")
        lines.append("| Channel Name | Unit | Samples | Min | Max | Mean |")
        lines.append("|---|---|---|---|---|---|")
        for ch in available_channels:
            name = ch.get("channel_name", "")
            unit = ch.get("unit", "")
            count = ch.get("sample_count", 0)
            mn = ch.get("min_value")
            mx = ch.get("max_value")
            avg = ch.get("mean_value")
            mn_s = f"{mn:.2f}" if mn is not None else ""
            mx_s = f"{mx:.2f}" if mx is not None else ""
            avg_s = f"{avg:.2f}" if avg is not None else ""
            lines.append(f"| {name} | {unit} | {count} | {mn_s} | {mx_s} | {avg_s} |")
        channel_catalog_context = "\n".join(lines) + "\n\n"

    vehicle_context = ""
    if vehicle_candidates or vehicles or data_sources:
        lines = ["## Vehicle Context\n"]
        if data_sources:
            cm = data_sources.get("container_metrics", "")
            if cm:
                lines.append(f"**Container metrics table:** `{cm}` (use this for timeframe queries)\n")
            aliases = data_sources.get("aliases", "")
            if aliases:
                lines.append(
                    f"**Aliases table:** `{aliases}` is configured. Use the `search_aliases` tool "
                    f"(do NOT construct SQL manually) — it builds the right query for the active "
                    f"customer schema and returns rows you can pass straight to `suggest_signal_candidates`.\n"
                )
        if vehicle_candidates:
            lines.append("### Available Vehicle Candidates\n")
            lines.append("These vehicles were discovered from the data. Use `set_vehicle` to add them directly.\n")
            for vc in vehicle_candidates:
                vid = vc.get("vehicle_id", "")
                cnt = vc.get("datapoint_count", 0)
                lines.append(f"- `{vid}` ({cnt} datapoints)")
            lines.append("")
        if vehicles:
            lines.append("### Currently Configured Vehicles\n")
            for v in vehicles:
                vid = v.get("vehicle_id", "")
                col = v.get("col_name", "")
                start = v.get("start_ts", "")
                stop = v.get("stop_ts", "")
                stop_s = f", stop: {stop}" if stop else ""
                lines.append(f"- `{vid}` (col_name: `{col}`, start: {start}{stop_s})")
            lines.append("")
        vehicle_context = "\n".join(lines) + "\n"

    return (
        "You are an Impulse report builder assistant embedded in a Databricks App. "
        "You help users create Impulse reports through a guided step-by-step process.\n\n"
        "**Communication style:** Always share your thinking process with the user. Before calling "
        "tools, briefly explain what you are about to do and why (1-2 sentences). After receiving "
        "tool results, summarize what happened. Keep explanations precise and short — the user "
        "should always understand what step they are on and what comes next.\n\n"
        "## Guided Workflow\n\n"
        "The report creation follows 4 sequential steps. The user must complete each step before "
        "moving on. The current step is shown in the UI. **Only use tools relevant to the current step.**\n\n"
        "1. **Report Name** — Set the report name and description (`set_report_metadata`)\n"
        "2. **Vehicles** — Configure vehicles and data sources (`set_vehicle`, `set_data_sources`)\n"
        "3. **Channels** — Define physical and virtual signals (`add_physical_signal`, `add_virtual_signal`). Channels are filtered to those available for the selected vehicles.\n"
        "4. **Aggregations** — Define histograms (`add_histogram`)\n\n"
        f"### Current Step: {wizard_step.upper().replace('_', ' ')}\n\n"
        f"{step_instructions}\n\n"
        f"{signal_context}"
        f"{channel_catalog_context}"
        f"{vehicle_context}"
        "**Moving between steps:** When the user signals they want to move on — e.g. 'next step', "
        "'go ahead', 'proceed', 'continue', 'move on', 'next', or 'I'm done' — call the `advance_step` "
        "tool to advance the wizard for them (no need to tell them to click the button). If the current "
        "step isn't complete, `advance_step` returns what's missing — relay that to the user.\n\n"
        "**Important:** If the user asks to do something that belongs to a future step, politely explain "
        "they need to complete the current step first (offer to advance with `advance_step` once it's ready).\n\n"
        "You have access to Impulse skills that contain detailed procedures, code patterns, "
        "and data models. **Before performing any skill-specific task, call `load_skill` to load "
        "the relevant skill documentation.** This gives you the precise instructions you need.\n\n"
        "## Available Skills\n\n"
        f"{skill_list}\n\n"
        "Use `load_skill(skill_name)` to load the full documentation for a skill before acting on it.\n\n"
        "## Tool Usage Guidelines\n"
        "- After loading the relevant skill, follow its procedures exactly.\n"
        "- When matching user requests to channels, use the Available Channels table above. "
        "Match by name, unit, and value ranges — use your automotive domain knowledge to bridge "
        "natural language (e.g. 'engine speed') to channel names (e.g. 'nmot' with unit 'rpm').\n"
        "- After identifying matching channels, ALWAYS call `suggest_signal_candidates` — "
        "even for a single match. The user must confirm via the checkbox UI.\n"
        "- For derived signals (arithmetic, comparisons, filtering), use `add_virtual_signal`.\n"
        "- For histograms, determine the correct type (duration/distance) "
        "based on the define-aggregations skill, then use `add_histogram`.\n"
        "- Always suggest reasonable bin ranges based on the signal's physical meaning.\n"
        "- Use `preview_code` to show the user what will be generated before deploying.\n"
        "\n## Databricks SQL (DBSQL MCP Tools)\n"
        "Tools prefixed with `mcp_` connect to the Databricks managed DBSQL MCP server. "
        "Use these for:\n"
        "- Exploring data in Unity Catalog tables\n"
        "- Validating report results by querying gold-layer output tables\n"
        "- Any custom SQL query the user requests\n"
        "When presenting SQL results to the user, summarize them clearly as a table — "
        "never dump raw JSON.\n"
        "**If a SQL query fails**, NEVER show the raw error message to the user. Instead:\n"
        "1. Diagnose the issue silently (wrong column name? missing table? permission?)\n"
        "2. Try to fix and retry the query if the error suggests a simple fix (e.g. wrong column name)\n"
        "3. If you cannot fix it, tell the user in plain language what went wrong and suggest next steps\n"
    )


_STEP_INSTRUCTIONS: dict[str, str] = {
    "report_name": (
        "Ask the user for a **report name** (lowercase, underscores, no spaces) and an optional "
        "description. Use `set_report_metadata` to save it. When the user is done or says to "
        "move on, call `advance_step` to proceed to vehicle selection — do not just tell them to "
        "click 'Next Step'."
    ),
    "channels": (
        "Help the user define **physical and virtual signals**.\n\n"
        "### Proactive signal recommendations\n\n"
        "When the user describes a problem or analysis goal rather than specific signals "
        "(e.g. 'I want to analyze engine behavior at high speeds', 'Thermomanagement untersuchen'), "
        "you should:\n"
        "1. **Identify the domain** — Map the description to one or more automotive domains "
        "(engine, thermal, chassis, NVH, emissions, etc.).\n"
        "2. **Search broadly** — Scan the Available Channels table for ALL signals matching "
        "that domain, not just the most obvious one. Include related signals that provide context "
        "(e.g. for 'engine vibration' include RPM and torque alongside accelerometer signals).\n"
        "3. **Suggest a complete analysis plan** — After presenting channel candidates, briefly "
        "explain what aggregations you would recommend (e.g. 'For engine behavior analysis, I'd "
        "suggest duration histograms for engine speed and torque, plus a 2D heatmap of "
        "speed vs. torque').\n"
        "4. **Handle German input** — Many engineers describe problems in German. Channel names "
        "in OEM test data often use German abbreviations (e.g. `nmot` = Motordrehzahl = engine speed, "
        "`tKueMi` = Kuehlmitteltemperatur = coolant temp). Use the automotive domain reference to bridge "
        "both languages.\n\n"
        "Call `load_skill('define-channels')` to access the full automotive signal domain reference "
        "with channel name patterns, German abbreviations, and suggested aggregations per domain.\n\n"
        "### Adding physical signals\n\n"
        "The available channels from the ingested data are listed in the **Available Channels** "
        "table in your context. Use this list to match user requests to actual channel names.\n\n"
        "**Step A — Match.** When the user asks about signals (e.g. 'engine speed', 'temperature'), "
        "scan the Available Channels table and use your domain knowledge to identify matching channels. "
        "Channel names may be cryptic (e.g. `nmot` = engine speed, `pveh` = vehicle speed). "
        "Use the **unit** and **value ranges** as context clues:\n"
        "- `rpm` unit with max ~7000 → likely engine speed\n"
        "- `°C` unit with range -40 to 160 → likely a temperature signal\n"
        "- `km/h` unit → vehicle speed\n"
        "If the user's request is vague (e.g. 'show me what's available'), present ALL channels.\n"
        "If the Available Channels table is empty, use `mcp_execute_sql` to query the silver layer directly.\n\n"
        "**Step B — Add or present channels.** Choose the right approach based on user intent:\n\n"
        "**When the user explicitly asks to ADD channels** (e.g. 'add engine speed', "
        "'recommend and add channels', 'add all relevant signals'):\n"
        "- **Be selective, not exhaustive.** Only add channels that are directly relevant to the "
        "user's stated analysis goal. A focused set of 3-5 core channels is almost always better "
        "than dumping every remotely related signal. For example, if the user asks about 'cooling "
        "system under load', add coolant temp, oil temp, and engine load — but NOT vehicle speed "
        "or intake pressure unless the user's question specifically calls for them.\n"
        "- Call `add_physical_signal` directly for each selected channel. Set `var_name` to a clean "
        "Python name (lowercase, underscores), `alias` and `channel_name` to the exact channel "
        "name from the Available Channels table. **Act, don't narrate.**\n"
        "- After adding, briefly explain WHY each channel matters for the analysis goal. Then "
        "mention any channels you considered but left out, so the user can ask for them if needed.\n\n"
        "**When the user wants to BROWSE or EXPLORE** (e.g. 'what channels are available', "
        "'show me temperature signals'):\n"
        "- Call `suggest_signal_candidates` to present checkboxes in the right panel.\n"
        "- Say: 'I found N matching channels — select the ones you want and click **Add Selected**.'\n\n"
        "**When in doubt, prefer adding directly.** If the user says 'recommend channels' or "
        "'suggest and add', that means add them. Only use the checkbox flow when the user is "
        "clearly just exploring or browsing.\n\n"
        "### Adding virtual signals\n\n"
        "For derived signals (arithmetic, comparisons, filtering), use `add_virtual_signal`. "
        "**You MUST reference the exact `var_name` of already-defined signals** in the expression. "
        "Check the 'Currently Defined Signals' section above for the correct variable names.\n\n"
        "### Finishing\n\n"
        "Once all signals are defined and the user says to move on, call `advance_step` to proceed "
        "to aggregations — do not just tell them to click 'Next Step'."
    ),
    "aggregations": (
        "Help the user define **aggregations** on the signals from the previous step.\n\n"
        "Three aggregation types are available:\n"
        "- **1D Histogram** (`add_histogram`) — Duration, distance, count distributions. Best for "
        "understanding how much time/distance a signal spends in each range.\n"
        "- **2D Histogram** (`add_histogram_2d`) — Heatmap showing correlation between two signals. "
        "Best for operating point maps (e.g. engine speed vs. torque).\n"
        "- **Statistics** (`add_statistics`) — Summary statistics (min, max, mean, median, std, count) "
        "across one or more signals. Best for quick overviews.\n\n"
        "Suggest appropriate aggregation types and bin ranges based on the signal's physical meaning. "
        "Call `load_skill('define-aggregations')` for detailed guidance on each type.\n\n"
        "Once all aggregations are defined and the user says to move on, call `advance_step` to "
        "proceed to the final review — do not just tell them to click 'Next Step'."
    ),
    "vehicles": (
        "The **Vehicles** step lets users select vehicles and configure analysis timeframes.\n\n"
        "**How it works:** The right panel shows available vehicle candidates as checkboxes. "
        "Users can select via the UI, but **you can and should act directly** using `set_vehicle`.\n\n"
        "## Adding vehicles\n"
        "When the user asks to add a vehicle (e.g. 'add the Seat model'), "
        "**call `set_vehicle` directly** with the matching vehicle_id from the Vehicle Context section. "
        "Do NOT tell the user to click checkboxes.\n\n"
        "## Setting the analysis timeframe\n"
        "When the user asks to set or infer a timeframe:\n"
        "1. Look at the **Currently Configured Vehicles** in your context — if a vehicle is already "
        "added, you know its `col_name` and can update it with `set_vehicle`.\n"
        "2. To find the actual data range, query the container_metrics table:\n"
        "   ```\n"
        "   SELECT MIN(start_dt) AS first_data, MAX(stop_dt) AS last_data\n"
        "   FROM {container_metrics_table}\n"
        "   WHERE {vehicle_col} = '{vehicle_id}'\n"
        "   ```\n"
        "   Use the container_metrics table from the configured data sources and the col_name from "
        "the configured vehicle. If the query fails, try with column names from DESCRIBE TABLE.\n"
        "3. Then call `set_vehicle` with the appropriate `start_ts` and optionally `stop_ts` to "
        "update the vehicle's timeframe **directly** — do NOT just tell the user what to type.\n"
        "4. The UI shortcuts L1D/L7D/L30D/L90D correspond to last 1/7/30/90 days from today. "
        "'From Data' means use the full data range. You can compute these yourself and call `set_vehicle`.\n\n"
        "## Important notes\n"
        "- The `col_name` must match the vehicle ID column in the data. Check the Currently Configured "
        "Vehicles section — if a vehicle is already added, **reuse its `col_name`** when updating it.\n"
        "- If a SQL query fails, do NOT show raw errors. Explain briefly and suggest alternatives.\n"
        "- Once vehicles and timeframes are set and the user says to move on (e.g. 'next', "
        "'go ahead'), call `advance_step` yourself — do NOT just tell the user to click 'Next Step'.\n\n"
        "For more detail, call `load_skill('select-vehicles')`."
    ),
    "ready": (
        "All steps are complete. The user can now review the configuration, preview the generated "
        "code, and deploy the report using the 'Deploy & Run' button."
    ),
}
