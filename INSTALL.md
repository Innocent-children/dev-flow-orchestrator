# Install Dev Flow Orchestrator

This guide covers a first installation, replacement under the same plugin
identity, scope configuration, optional MCP setup, verification, and removal.

Dev Flow Orchestrator is installed as the single plugin identity
`dev-flow-orchestrator`. Its current package version is declared in
`.codex-plugin/plugin.json`.

## 1. Requirements

The supported host for this release is macOS.

Required software:

- Git;
- Python 3.9 or newer;
- Codex with the `codex plugin` command.

Check the local tools:

```sh
sw_vers
git --version
python3 --version
codex plugin --help
```

The runtime uses only the Python standard library. There is no runtime package
installation step such as `pip install`, `uv sync`, `npm install`, or
`pnpm install`.

## 2. Choose the local marketplace root

The examples below use the user's home directory as the marketplace root:

```text
<MARKETPLACE_ROOT>/
├── .agents/plugins/marketplace.json
└── plugins/dev-flow-orchestrator/
```

The repository includes matching templates:

- `templates/personal-marketplace.example.json`: complete `personal`
  marketplace file;
- `templates/marketplace-entry.json`: one entry to merge into an existing
  marketplace.

The template source path is `./plugins/dev-flow-orchestrator`, resolved from
`<MARKETPLACE_ROOT>`.

## 3. Place the reviewed source

Place the exact reviewed candidate at:

```text
<MARKETPLACE_ROOT>/plugins/dev-flow-orchestrator
```

For a fresh checkout from GitHub:

```sh
mkdir -p "$HOME/plugins"
git clone https://github.com/Innocent-children/dev-flow-orchestrator.git \
  "$HOME/plugins/dev-flow-orchestrator"
```

SSH alternative:

```sh
mkdir -p "$HOME/plugins"
git clone git@github.com:Innocent-children/dev-flow-orchestrator.git \
  "$HOME/plugins/dev-flow-orchestrator"
```

If a reviewed local candidate was supplied instead, copy that candidate to the
same path without combining it with stale files from another copy. Preserve
the candidate unchanged through acceptance.

Confirm the plugin identity and host requirements:

```sh
python3 -m json.tool \
  "$HOME/plugins/dev-flow-orchestrator/.codex-plugin/plugin.json"
```

The manifest name must be `dev-flow-orchestrator`, and its version must have
major version `4`.

## 4. Create or update the personal marketplace

Create this directory if it does not exist:

```sh
mkdir -p "$HOME/.agents/plugins"
```

If this is a new personal marketplace, copy the bundled example:

```sh
cp \
  "$HOME/plugins/dev-flow-orchestrator/templates/personal-marketplace.example.json" \
  "$HOME/.agents/plugins/marketplace.json"
```

If `~/.agents/plugins/marketplace.json` already contains other plugins, do not
overwrite it. Merge the object from
`templates/marketplace-entry.json` into its `plugins` array instead. The
resulting entry is:

```json
{
  "name": "dev-flow-orchestrator",
  "source": {
    "source": "local",
    "path": "./plugins/dev-flow-orchestrator"
  },
  "policy": {
    "installation": "AVAILABLE",
    "authentication": "ON_INSTALL"
  },
  "category": "Productivity"
}
```

Keep exactly one marketplace entry for the plugin name.

Validate the JSON before registration:

```sh
python3 -m json.tool "$HOME/.agents/plugins/marketplace.json"
```

## 5. Register the marketplace

Register the marketplace root, not the nested JSON file:

```sh
codex plugin marketplace add "$HOME"
```

Confirm that Codex sees it:

```sh
codex plugin marketplace list
codex plugin list
```

Before installation, the expected row is similar to:

```text
dev-flow-orchestrator@personal  not installed
```

If a marketplace named `personal` is already registered at the same root, it
does not need to be added again.

## 6. Install the plugin

Install the one marketplace entry:

```sh
codex plugin add dev-flow-orchestrator@personal
```

Confirm the result:

```sh
codex plugin list
```

The expected state is one row for this identity:

```text
dev-flow-orchestrator@personal  installed, enabled
```

Do not install another copy from a different marketplace at the same time.

Codex loads newly installed plugin capabilities in a new session. Close the
current Codex session and start a new one before testing Skills, Hook, or MCP.

## 7. Replace an installed copy

Use the same plugin identity and marketplace entry.

1. Obtain the reviewed replacement candidate.
2. Replace the source at
   `<MARKETPLACE_ROOT>/plugins/dev-flow-orchestrator` without overlaying stale
   files.
3. Remove the installed snapshot:

   ```sh
   codex plugin remove dev-flow-orchestrator@personal
   ```

4. Install the same identity again:

   ```sh
   codex plugin add dev-flow-orchestrator@personal
   ```

5. Start a new Codex session.
6. Run `codex plugin list` and confirm exactly one enabled instance.

Do not change the marketplace entry to a second plugin name.

## 8. Configure activation scope

The plugin is active in every directory by default. Scope state is stored in
the plugin data directory.

Use the installed launcher:

```sh
"$HOME/plugins/dev-flow-orchestrator/scripts/dev_flow_python_launcher" \
  "$HOME/plugins/dev-flow-orchestrator/scripts/dev_flow.py" scope
```

Exclude a directory recursively:

```sh
"$HOME/plugins/dev-flow-orchestrator/scripts/dev_flow_python_launcher" \
  "$HOME/plugins/dev-flow-orchestrator/scripts/dev_flow.py" \
  scope --mode all --add-exclude /path/to/excluded-directory
```

Activate only inside selected directories:

```sh
"$HOME/plugins/dev-flow-orchestrator/scripts/dev_flow_python_launcher" \
  "$HOME/plugins/dev-flow-orchestrator/scripts/dev_flow.py" \
  scope --mode allowlist \
  --add /path/to/project-a \
  --add /path/to/project-b
```

Check one path:

```sh
"$HOME/plugins/dev-flow-orchestrator/scripts/dev_flow_python_launcher" \
  "$HOME/plugins/dev-flow-orchestrator/scripts/dev_flow.py" \
  scope --check /path/to/project
```

Remove a configured exclusion:

```sh
"$HOME/plugins/dev-flow-orchestrator/scripts/dev_flow_python_launcher" \
  "$HOME/plugins/dev-flow-orchestrator/scripts/dev_flow.py" \
  scope --remove-exclude /path/to/excluded-directory
```

Reset scope and protected-path configuration:

```sh
"$HOME/plugins/dev-flow-orchestrator/scripts/dev_flow_python_launcher" \
  "$HOME/plugins/dev-flow-orchestrator/scripts/dev_flow.py" scope --clear
```

The deepest matching include or exclude directory wins. An equal match is
excluded.

## 9. Choose the data directory

Task state and scope configuration stay outside target repositories. The
runtime resolves the state directory in this order:

1. command-line `--data-dir`;
2. `DEV_FLOW_DATA_DIR`;
3. Codex-provided `PLUGIN_DATA`;
4. `~/Library/Application Support/dev-flow-orchestrator`.

For direct CLI use, the default is normally sufficient. To choose an explicit
location:

```sh
"$HOME/plugins/dev-flow-orchestrator/scripts/dev_flow_python_launcher" \
  "$HOME/plugins/dev-flow-orchestrator/scripts/dev_flow.py" \
  --data-dir "/path/to/dev-flow-data" list
```

Use the same value for every command that operates on the same task. Do not
place the data directory inside a target repository.

## 10. Verify Hook pickup

The plugin manifest discovers `hooks/hooks.json`. The Hook runs through the
packaged macOS launcher and handles:

- session start, resume, clear, and compact context restoration;
- prompt-time task context;
- bounded subagent assignment and result checks;
- guardrails before Bash and file-editing tools.

After installation:

1. start a new Codex session inside an in-scope project;
2. ask Codex to use `$follow-dev-flow`;
3. confirm that the session receives the installed controller locator or task
   checkpoint;
4. confirm that an out-of-scope project is reported as out of scope when such
   a rule is configured.

Do not treat repository-local Hook tests as a substitute for this host check.

## 11. Enable and verify MCP

The bundled `dev-flow-macos` MCP profile is optional, `required: false`, and
disabled by default. Enable it in the installed plugin's Codex settings when
you want typed MCP tools.

Start another new session after changing the setting. MCP initialization and
tool discovery should expose exactly:

- `task-next`;
- `node-description`;
- `evidence-read`;
- `action-preview`;
- `action-apply`;
- `worker-result`.

If MCP remains disabled, `follow-dev-flow` continues to work through the exact
CLI locator injected by the Hook.

For package-local diagnosis only, the stdio server can be launched with:

```sh
"$HOME/plugins/dev-flow-orchestrator/scripts/dev_flow_python_launcher" \
  "$HOME/plugins/dev-flow-orchestrator/scripts/dev_flow_mcp.py"
```

This process waits for JSON-RPC input on standard input; it is not an
interactive shell command.

## 12. Run the real-project smoke

In a real, disposable or otherwise appropriate Git project:

1. configure the project as in scope;
2. start a new Codex session;
3. ask `$follow-dev-flow` to create a small V4 task;
4. confirm the task pins either `lite@4` or `full@4`;
5. preview and complete one representative action;
6. confirm the resulting projection and receipt describe the next legal
   action.

The task must be newly created with the installed candidate. Do not edit task
state files directly.

## 13. Acceptance checklist

Installation is accepted only after the user confirms all three items:

- exactly one enabled `dev-flow-orchestrator` plugin instance;
- real Codex Hook pickup and MCP initialization/tool discovery;
- one representative end-to-end action in a newly created real-project V4
  task.

These checks are intentionally user-owned because they depend on the real
Codex host, plugin cache, permissions, and project.

## Troubleshooting

### `codex plugin list` does not show the plugin

- Run `python3 -m json.tool` on the marketplace file.
- Confirm the marketplace was registered from `<MARKETPLACE_ROOT>`, not from
  `.agents/plugins`.
- Confirm the source path resolves to
  `<MARKETPLACE_ROOT>/plugins/dev-flow-orchestrator`.
- Run `codex plugin marketplace list`.

### The row says `not installed`

Run:

```sh
codex plugin add dev-flow-orchestrator@personal
```

### More than one instance is installed

Use `codex plugin list` to identify every marketplace selector. Remove the
extra selector with:

```sh
codex plugin remove dev-flow-orchestrator@<marketplace>
```

Keep the one reviewed installation.

### A project is unexpectedly inactive

Inspect scope and the exact path:

```sh
"$HOME/plugins/dev-flow-orchestrator/scripts/dev_flow_python_launcher" \
  "$HOME/plugins/dev-flow-orchestrator/scripts/dev_flow.py" scope
"$HOME/plugins/dev-flow-orchestrator/scripts/dev_flow_python_launcher" \
  "$HOME/plugins/dev-flow-orchestrator/scripts/dev_flow.py" \
  scope --check /path/to/project
```

Also confirm that direct CLI commands and Codex are using the same data
directory.

### Hook or MCP changes are not visible

- Confirm the plugin is `installed, enabled`.
- Start a new Codex session.
- Confirm `.codex-plugin/plugin.json`, `hooks/hooks.json`, and `.mcp.json` exist
  in the installed source.
- Remember that `dev-flow-macos` MCP is disabled by default.
- Confirm `python3 --version` is at least 3.9.

### The launcher reports no supported Python

Install or expose Python 3.9 or newer on `PATH`, then run:

```sh
"$HOME/plugins/dev-flow-orchestrator/scripts/dev_flow_python_launcher" \
  "$HOME/plugins/dev-flow-orchestrator/scripts/dev_flow.py" --help
```

## Remove the plugin

Remove the installed snapshot:

```sh
codex plugin remove dev-flow-orchestrator@personal
```

Removing the plugin does not authorize deletion of its source directory or
data directory. Preserve or remove those separately according to your own
retention requirements.
