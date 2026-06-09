# BridgeEQA

Runs an agent against BridgeEQA
inspection questions. `run_agent.py` loads one QA row from `BridgeEQA_2025/test.db`,
builds the scene context (images + scene graph) for the referenced bridge, runs the
agent, and prints its answer vs. the ground truth.

## Requirements
- Python ≥ 3.12
- [uv](https://docs.astral.sh/uv/)

## Install
```bash
uv sync
```

## Environment variables
Copy `.env.example` to `.env` and fill in the values:
```bash
cp .env.example .env
```

- `OPENROUTER_API_KEY`: Model access (Gemini or other models via OpenRouter/LiteLLM)
- `SERVICE_NAME`: S3 service name (`s3`)
- `ENDPOINT_URL`: S3 / Cloudflare R2 endpoint
- `AWS_ACCESS_KEY_ID`: S3 / R2 access key
- `AWS_SECRET_ACCESS_KEY`: S3 / R2 secret key
- `REGION_NAME`: S3 region (`auto` for R2)
- `BUCKET_NAME`: Bucket for inspection images
- `OPENAI_AGENTS_DISABLE_TRACING`: Set `1` to disable agent tracing
- `LOGFIRE_TOKEN`: Logfire token for cloud logging

## Dataset
Download the `BridgeEQA_2025` dataset from
[hoskerelab/bridge-eqa](https://huggingface.co/datasets/hoskerelab/bridge-eqa)
into the repo root:
```bash
wget https://huggingface.co/datasets/hoskerelab/bridge-eqa/resolve/main/BridgeEQA_2025.zip
unzip BridgeEQA_2025.zip
```

Layout:
```
BridgeEQA_2025/
├── test.db                          # test QA pairs (SQLite)
├── train.db                         # train QA pairs (SQLite)
└── BridgeInspRpt-{LOCATION}-{ID}/   # one folder per bridge scene
    ├── images/                      # inspection images
    ├── scene_graph.json             # scene graph (nodes → images)
    ├── qa_pairs.json                # QA pairs + reference images / ratings
    └── BridgeInspRpt-{LOCATION}-{ID}.pdf
```

## Run
From the repo root (paths are relative to it):
```bash
uv run run_agent.py
```
This runs the agent on the first test question and prints the question, the agent's
answer and condition rating, and the ground-truth answer and rating.

## A note on prompts and reliability

Agent prompts were chosen to give tested VLM models the best chance of success. As models vary in instruction-following, structured-output, and function-calling behavior, you may
need to adjust the prompts to get optimal results. We have aimed
to set up prompts that are fair and model-agnostic, but some tuning per model is
expected.

Depending on a model's reliability, you may also need to run a query more than once.
Common failure cases include malformed structured outputs and malformed function
calls.

Metrics depend on the VLM (Vision-Language Model) used as the judge. Changing the judge shifts the values, so only compare results scored by the same judge model.