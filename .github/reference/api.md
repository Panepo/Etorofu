# API Reference — GX10 Qwen3.5 Research Hub

Base URL: `http://localhost:8000`

---

## POST `/research`

Submit a new research topic. The task is queued and processed asynchronously by the CrewAI agent pipeline.

### Request Body

| Field   | Type   | Required | Description             |
|---------|--------|----------|-------------------------|
| `topic` | string | Yes      | The research topic/query to investigate |

```json
{
  "topic": "Quantum computing breakthroughs in 2025"
}
```

### Response `200 OK`

```json
{
  "task_id": "a3f1c2b4-...",
  "message": "任務已加入排隊隊列"
}
```

| Field     | Type   | Description                       |
|-----------|--------|-----------------------------------|
| `task_id` | string | UUID identifying the queued task  |
| `message` | string | Confirmation message              |

### Errors

| Status | Detail                  | Cause               |
|--------|-------------------------|---------------------|
| `400`  | 請提供研究主題           | `topic` is empty    |

---

## GET `/status/{task_id}`

Poll the current status and result of a research task.

### Path Parameters

| Parameter | Type   | Description              |
|-----------|--------|--------------------------|
| `task_id` | string | UUID returned by `/research` |

### Response `200 OK`

```json
{
  "task_id": "a3f1c2b4-...",
  "status": "completed",
  "topic": "Quantum computing breakthroughs in 2025",
  "elapsed_seconds": 142.3,
  "result": "## Research Report\n...",
  "tags": "quantum, computing, physics",
  "error": null
}
```

| Field              | Type         | Description                                            |
|--------------------|--------------|--------------------------------------------------------|
| `task_id`          | string       | Task UUID                                              |
| `status`           | string       | Current status (see [Task Lifecycle](#task-lifecycle)) |
| `topic`            | string       | Original research topic                                |
| `elapsed_seconds`  | float        | Seconds elapsed since creation (0 if finished)        |
| `result`           | string\|null | Final markdown report (populated when `completed`)     |
| `tags`             | string\|null | Comma-separated tags (populated when `completed`)      |
| `error`            | string\|null | Error message (populated when `failed`)                |

### Errors

| Status | Detail           | Cause                           |
|--------|------------------|---------------------------------|
| `404`  | 找不到該任務      | `task_id` does not exist        |

---

## Task Lifecycle

Tasks transition through the following statuses:

```
queued → searching → writing → tagging → completed
                                        ↘ failed
```

| Status      | Description                                          |
|-------------|------------------------------------------------------|
| `queued`    | Task is waiting in the async queue                   |
| `searching` | Research agent is running DuckDuckGo web searches    |
| `writing`   | Writing agent (`qwen3.5:35b`) is drafting the report |
| `tagging`   | Tags are being generated for the report              |
| `completed` | Report and tags are ready; persisted to SQLite       |
| `failed`    | An unrecoverable error occurred during processing    |
