# Brain — Cross-Session Memory

Memory backend is Brain MCP (7 native tools in tool list). No bash. No memstack-db.py.

## Project scope
Always pass `project: "thesis"` when calling Brain MCP tools for this repo.

## Triggers

| Trigger | Action |
|---|---|
| "recall" / "remember" / past session reference | `recall(query="...", project="thesis", topk=8)` |
| Root cause confirmed, gotcha found, pattern established | `save_insight(content="...", type="gotcha|pattern|architecture|decision", project="thesis", tags="...")` |
| User corrects your approach | `save_insight(..., type="feedback", project="thesis")` |
| Before risky ops (deploy, VPS, prod) | `recall_principle(topic="...", project="thesis")` |
| Verifying a recalled insight still holds | `verify_insight(id=<id>, status="verified|stale")` |
| 3+ insights on same theme | `distill(insight_ids=[...], content="...")` |
| Weekly health check | `recall_stats(project="thesis")` |

## Key project facts (always available via recall)
- Ernis GPU server: `I6365661@ernis.dacs.maastrichtuniversity.nl` (VPN required, RTX 6000 Ada 48GB)
- Inference: llama.cpp with Qwen3-VL-30B-A3B Q4_K_XL via SSH tunnel `ssh -N -L 8001:localhost:8001 I6365661@ernis...`
- VPS prod: 89.167.11.147, deploy via docker-compose.prod.yml + watchtower auto-pull
- Benchmark target: 20 captures × 4 backends (claude-haiku, claude-sonnet, gemini-3-flash-preview, qwen3-vl)
