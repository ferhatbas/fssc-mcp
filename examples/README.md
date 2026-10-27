# Examples

Small, copy-paste starting points. Start the server first (see the root [README](../README.md#installation)).

| Example | What it shows |
| --- | --- |
| [`sample-spec.md`](sample-spec.md) | A short product brief to paste into the spec vault; a good first run |
| [`mcp-config.example.json`](mcp-config.example.json) | The `fssc-visual-observer` entry for Claude Desktop, Claude Code or Antigravity |
| [`check_server.py`](check_server.py) | Stdlib-only script that asks a running server for its projects |

## First run in four steps

1. `python -m server.main --mode web`, then open <http://127.0.0.1:8099>.
2. In the top bar choose *Add New* and pick an empty folder.
3. Open the spec vault and paste [`sample-spec.md`](sample-spec.md).
4. In your AI client, with the project folder open, type: `Run the pipeline for the <project-id> project`.

No API key is involved at any point: your connected client produces every step with your own subscription.

```bash
python examples/check_server.py          # lists the projects the server knows about
```
