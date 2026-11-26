# API Reference — GX10 Qwen3.5 Research Hub

Base URL: `http://localhost:8050`

## Authentication

Sign in at `/login` or send `POST /auth/login` with JSON `email` and `password`.
The server validates the Shiratsuyu JWT and sets an HttpOnly session cookie.
`POST /auth/logout` clears the cookie. All other pages and endpoints require
that cookie or an `Authorization: Bearer <shiratsuyu_jwt>` header. Expired or
invalid sessions return 401; authentication service failures fail closed.

---

## Scheduled topics

`GET /scheduled-topics` lists schedules. `POST /scheduled-topics` creates one;
`PUT /scheduled-topics/{id}` replaces it; and `DELETE /scheduled-topics/{id}`
removes it. Create and replace accept:

```json
{
  "topic": "AI research",
  "start_date": "2026-11-26",
  "schedule_time": "23:00",
  "interval_days": 2
}
```

The interval is 1–365 calendar days. Dates and times use the server's local
time. Responses include the schedule's `id` and `next_run` (local ISO datetime).
Invalid inputs return 422 and unknown IDs return 404. The first run is the
next occurrence after saving; overdue schedules are queued once on restart.

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

---

## GET `/reports`

List summaries of all persisted reports (no full content).

### Response `200 OK`

```json
[
  {
    "id": "a3f1c2b4-...",
    "topic": "Quantum computing breakthroughs in 2025",
    "tags": "quantum, computing, physics",
    "created_at": 1742950000.0
  }
]
```

| Field        | Type         | Description                        |
|--------------|--------------|------------------------------------|
| `id`         | string       | Report UUID                        |
| `topic`      | string       | Original research topic            |
| `tags`       | string\|null | Comma-separated tags               |
| `created_at` | float        | Unix timestamp of creation         |

---

## GET `/reports/{report_id}`

Retrieve a single report with full content.

### Path Parameters

| Parameter   | Type   | Description         |
|-------------|--------|---------------------|
| `report_id` | string | UUID of the report  |

### Response `200 OK`

```json
{
  "id": "a3f1c2b4-...",
  "topic": "Quantum computing breakthroughs in 2025",
  "content": "## Research Report\n...",
  "tags": "quantum, computing, physics",
  "created_at": 1742950000.0
}
```

| Field        | Type         | Description                        |
|--------------|--------------|------------------------------------|
| `id`         | string       | Report UUID                        |
| `topic`      | string       | Original research topic            |
| `content`    | string       | Full markdown report body          |
| `tags`       | string\|null | Comma-separated tags               |
| `created_at` | float        | Unix timestamp of creation         |

### Errors

| Status | Detail        | Cause                          |
|--------|---------------|--------------------------------|
| `404`  | 找不到該報告   | `report_id` does not exist     |

---

## PATCH `/reports/{report_id}`

Update the content, tags, or both for an existing report. At least one field must be provided.

### Path Parameters

| Parameter   | Type   | Description         |
|-------------|--------|---------------------|
| `report_id` | string | UUID of the report  |

### Request Body

| Field     | Type         | Required | Description                   |
|-----------|--------------|----------|-------------------------------|
| `content` | string\|null | No*      | New markdown body for report  |
| `tags`    | string\|null | No*      | New comma-separated tag string |

\* At least one of `content` or `tags` must be provided.

```json
{
  "content": "## Updated Report\n...",
  "tags": "quantum, physics, new-tag"
}
```

### Response `200 OK`

```json
{
  "message": "報告已更新"
}
```

### Errors

| Status | Detail        | Cause                                      |
|--------|---------------|--------------------------------------------|
| `400`  | 請提供 content 或 tags | Neither field was provided          |
| `404`  | 找不到該報告   | `report_id` does not exist                 |
