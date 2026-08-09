"""Shape checks for the workspace files that register the triage MCP server
and its procedure with a monō foundry client: `.mcp.json`, a `SKILL.md`
under the workspace skills directory, and `MONOFOUNDRY.md`.

None of the three exists yet, so every test reaches its target through a
helper that asserts the target's presence before touching it, rather than
importing or opening it at module scope. A missing file then surfaces as a
per-test `AssertionError` instead of a collection error, the same technique
this suite already uses for a package pinned before it exists.

These are static-file checks, not a running process: no test here spawns a
monō foundry client or a server subprocess. Each test parses a file with a
real parser (`json`, a YAML loader) rather than matching phrases in text, so
a hand-wrapped or YAML-folded value can't defeat an assertion the way a
single-line regex over wrapped prose would.
"""

import json
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Locating the repo and the not-yet-created workspace artifacts, read lazily
# ---------------------------------------------------------------------------


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _import_yaml() -> Any:
    # PyYAML is only a *transitive* dependency here (pulled in by pre-commit
    # and uvicorn[standard]), not declared directly in [project.dependencies]
    # -- imported lazily so a future dependency shuffle that drops it surfaces
    # as a failure on the tests that actually parse frontmatter, not as a
    # collection error for this whole module.
    import yaml

    return yaml


def _mcp_json_path() -> Path:
    return _repo_root() / ".mcp.json"


def _load_mcp_config() -> dict[str, Any]:
    path = _mcp_json_path()
    assert path.is_file(), f"no .mcp.json at {path}"
    return json.loads(path.read_text(encoding="utf-8"))


def _skills_dir() -> Path:
    return _repo_root() / ".monofoundry" / "skills"


def _the_skill_md_path() -> Path:
    skills_dir = _skills_dir()
    assert skills_dir.is_dir(), f"no .monofoundry/skills/ directory at {skills_dir}"
    matches = sorted(skills_dir.glob("*/SKILL.md"))
    assert matches, f"no <name>/SKILL.md found under {skills_dir}"
    assert len(matches) == 1, f"more than one SKILL.md discovered under {skills_dir}: {matches}"
    return matches[0]


def _split_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    """(frontmatter, body) for a SKILL.md-shaped file.

    Frontmatter is delimited by a `---` line at the very start of the file
    and a second, standalone `---` line that closes it. Parsed with a real
    YAML loader rather than string matching, so a folded (`>`) or literal
    (`|`) block-scalar `description` -- exactly the shape the contract's own
    example uses -- still parses correctly regardless of how it is wrapped.
    """
    yaml = _import_yaml()
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].strip() != "---":
        return {}, text
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            raw_yaml = "".join(lines[1:i])
            body = "".join(lines[i + 1 :])
            frontmatter = yaml.safe_load(raw_yaml) or {}
            assert isinstance(frontmatter, dict), (
                f"frontmatter did not parse as a mapping: {frontmatter!r}"
            )
            return frontmatter, body
    return {}, text


def _monofoundry_md_path() -> Path:
    return _repo_root() / "MONOFOUNDRY.md"


# ---------------------------------------------------------------------------
# .mcp.json: registers the read-only triage server without flipping transport
# ---------------------------------------------------------------------------


def _forbidden_transport_key_hits(node: Any, path: str = "$") -> list[str]:
    """Every location, anywhere in a parsed `.mcp.json` document, carrying a
    `url` or `serverUrl` key, or a `type` key whose value is `sse` -- matched
    case-insensitively and at any depth, since any of these (regardless of
    where it sits or what it is named to look like) triggers the unsupported
    SSE transport, either by auto-detection (`url`/`serverUrl`) or explicit
    request (`type: "sse"`)."""
    hits: list[str] = []
    if isinstance(node, dict):
        for key, value in node.items():
            if str(key).lower() in {"url", "serverurl"}:
                hits.append(f"{path}.{key}")
            elif str(key).lower() == "type" and isinstance(value, str) and value.lower() == "sse":
                hits.append(f"{path}.{key}")
            hits += _forbidden_transport_key_hits(value, f"{path}.{key}")
    elif isinstance(node, list):
        for index, item in enumerate(node):
            hits += _forbidden_transport_key_hits(item, f"{path}[{index}]")
    return hits


def test_mcp_json_uses_the_workspace_servers_format():
    config = _load_mcp_config()
    assert "servers" in config, f".mcp.json has no top-level 'servers' key: {sorted(config)}"
    assert isinstance(config["servers"], dict), (
        f"'servers' must map server names to config objects, got {config['servers']!r}"
    )
    # 'mcpServers' is the legacy Antigravity-only shape; a file at this
    # specific path is parsed as 'servers' regardless of what it contains, so
    # a stray 'mcpServers' key here would be silently ignored, not honoured
    assert "mcpServers" not in config, (
        "'.mcp.json' carries a 'mcpServers' key, the legacy format for a different "
        "config location -- it will be silently ignored here, not parsed"
    )


def test_a_server_entry_launches_the_real_mcp_server_entrypoint():
    config = _load_mcp_config()
    servers = config.get("servers", {})
    assert servers, ".mcp.json declares no servers at all"

    def _launches_mcp_server(entry: dict[str, Any]) -> bool:
        # the real, already-built entrypoint is `python -m mcp_server`: no
        # subcommand, no flags. Look for that adjacent pair wherever it falls
        # in the effective argv, since a launcher may be wrapped (e.g. `uv
        # run python -m mcp_server`) rather than invoking python directly.
        argv = [str(entry.get("command", "")), *(str(a) for a in entry.get("args", []))]
        return any(argv[i] == "-m" and argv[i + 1] == "mcp_server" for i in range(len(argv) - 1))

    matches = {name: entry for name, entry in servers.items() if _launches_mcp_server(entry)}
    assert matches, f"no server entry launches `-m mcp_server`; servers were: {servers!r}"


def test_no_server_entry_triggers_sse_via_url_serverurl_or_explicit_type():
    config = _load_mcp_config()
    hits = _forbidden_transport_key_hits(config)
    assert not hits, (
        "a 'url'/'serverUrl' key or an explicit type:'sse' is present -- any of these "
        f"triggers the unsupported SSE transport and disables the server: {hits}"
    )


def test_the_transport_key_checker_actually_catches_a_url_key():
    # A checker exercised only by conforming input is structurally blind to
    # its own failure mode: prove the same walk flags a planted 'url' key
    # before trusting that it found none in the real file.
    config = _load_mcp_config()
    dirty = json.loads(json.dumps(config))  # a deep copy, via round-trip
    servers = dirty.get("servers", {})
    assert servers, ".mcp.json declares no servers at all"
    first_server_name = next(iter(servers))
    servers[first_server_name]["url"] = "https://example.invalid/sse"
    hits = _forbidden_transport_key_hits(dirty)
    assert hits, "planting a 'url' key on a real server entry went undetected by the checker"


def test_the_transport_key_checker_actually_catches_an_explicit_sse_type():
    # Same blindness risk, the other trigger: prove the walk flags a planted
    # type:'sse' with no url/serverUrl anywhere near it, since that
    # combination is exactly what the enumerate-two-of-three-triggers defect
    # this test guards against would otherwise miss.
    config = _load_mcp_config()
    dirty = json.loads(json.dumps(config))  # a deep copy, via round-trip
    servers = dirty.get("servers", {})
    assert servers, ".mcp.json declares no servers at all"
    first_server_name = next(iter(servers))
    servers[first_server_name]["type"] = "sse"
    hits = _forbidden_transport_key_hits(dirty)
    assert hits, "planting an explicit type:'sse' went undetected by the checker"


def test_cwd_resolves_to_the_workspace_root_when_present():
    config = _load_mcp_config()
    servers = config.get("servers", {})
    assert servers, ".mcp.json declares no servers at all"
    root = _repo_root()
    for name, entry in servers.items():
        cwd = entry.get("cwd")
        if cwd is None:
            # the documented default already resolves here: cwd defaults to
            # the config file's own directory, and .mcp.json sits at the
            # workspace root -- exactly where `python -m mcp_server` must run
            continue
        resolved = (root / cwd).resolve()
        assert resolved == root, (
            f"server {name!r} declares cwd={cwd!r}, which resolves to {resolved}, "
            f"not the workspace root {root}"
        )


# ---------------------------------------------------------------------------
# SKILL.md: first in workspace scan order, frontmatter shaped per contract
# ---------------------------------------------------------------------------


def test_exactly_one_skill_md_is_discoverable_at_the_workspace_skills_path():
    path = _the_skill_md_path()
    # the preferred `<dir>/SKILL.md` convention, not the `<name>.md` fallback
    assert path.name == "SKILL.md"
    # `.monofoundry/skills/` is first among the six workspace skill
    # directories scanned, ahead of `.claude/skills/` and the rest
    assert path.parent.parent == _skills_dir(), (
        f"{path} is not directly under {_skills_dir()}/<name>/"
    )


def test_skill_frontmatter_declares_name_and_description():
    path = _the_skill_md_path()
    frontmatter, _body = _split_frontmatter(path.read_text(encoding="utf-8"))
    name = frontmatter.get("name")
    assert isinstance(name, str) and name, (
        f"frontmatter has no non-empty string 'name': {frontmatter!r}"
    )
    description = frontmatter.get("description")
    assert isinstance(description, str) and description, (
        f"frontmatter has no non-empty string 'description': {frontmatter!r}"
    )


def test_description_first_line_stays_inside_the_terse_budget():
    path = _the_skill_md_path()
    frontmatter, _body = _split_frontmatter(path.read_text(encoding="utf-8"))
    description = frontmatter.get("description") or ""
    # only the first line of `description` is what ships in the standing
    # per-turn workspace context sent on every turn -- a folded or literal
    # block scalar can run much longer in the file than what actually costs
    # tokens on every turn, so the budget applies to the first line alone
    first_line = description.splitlines()[0] if description else ""
    assert len(first_line) <= 100, (
        f"description's first line is {len(first_line)} chars, over the terse budget: "
        f"{first_line!r}"
    )


def test_tools_field_is_present_and_is_a_list_of_strings():
    path = _the_skill_md_path()
    frontmatter, _body = _split_frontmatter(path.read_text(encoding="utf-8"))
    assert "tools" in frontmatter, f"frontmatter has no 'tools' field: {frontmatter!r}"
    tools = frontmatter["tools"]
    assert isinstance(tools, list), f"'tools' is present but not a list: {tools!r}"
    assert tools, "'tools' is present but empty"
    assert all(isinstance(t, str) for t in tools), f"'tools' has a non-string element: {tools!r}"
    # invariant: this field is informational only. It documents which tools
    # the skill's procedure expects to use; it does not gate, allowlist, or
    # otherwise restrict which tools the agent may actually call at runtime.


def test_trigger_is_manual_when_present_and_manual_is_the_documented_default():
    path = _the_skill_md_path()
    frontmatter, _body = _split_frontmatter(path.read_text(encoding="utf-8"))
    trigger = frontmatter.get("trigger", "manual")
    assert trigger == "manual", (
        f"trigger is {trigger!r}; 'manual' is the only documented trigger value, and it is "
        "also the default when the field is absent -- either way this skill is invoked "
        "explicitly, never fired automatically"
    )


# ---------------------------------------------------------------------------
# MONOFOUNDRY.md: workspace-level project instructions
# ---------------------------------------------------------------------------


def test_monofoundry_md_exists_at_the_workspace_root():
    path = _monofoundry_md_path()
    assert path.is_file(), f"no MONOFOUNDRY.md at {path}"


def test_monofoundry_md_is_not_an_empty_stub():
    path = _monofoundry_md_path()
    assert path.is_file(), f"no MONOFOUNDRY.md at {path}"
    content = path.read_text(encoding="utf-8").strip()
    assert content, "MONOFOUNDRY.md exists but is empty"
