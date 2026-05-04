# agent_router examples

Every workflow task should provide:

- a prompt file with the task text
- a config file that selects a model alias, enabled tools with per-tool limits, and usage limits

Model backend details live in `llm_select/models.yaml`.

Run from `Bybot_V4`:

```bash
python -m agent_router \
  --prompt agent_router/examples/research.prompt.md \
  --config agent_router/examples/openai_compatible.yaml \
  --llm-config llm_select/models.yaml \
  --var topic="pydantic-ai OpenAI-compatible API"
```
