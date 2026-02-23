# Poll Server

Simple Flask-based classroom poll server with:

- topic-based student URL
- teacher-controlled active question
- live teacher results (bars + text cloud)
- session-scoped runs via `?id=<uuid>`
- editable poll config via root `polls.yml`

## Requirements

- Python 3.11+ (or Docker)

## Configure Polls

Edit `polls.yml` in the project root.

Example structure:

```yml
subjects:
  - id: operating_systems
    language: it
    topics:
      - id: introduction
        polls:
          - id: operatingsystem
            question: "Che tipo di computer usi?"
            answer_type: single_choice
            answers: [Mac, Linux, Windows]
```

Supported `answer_type` values:

- `single_choice`
- `multiple_choice`
- `text`

Supported subject languages:

- `en`
- `de`
- `it`

## Run Locally

```bash
cd server
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python app.py
```

Server runs on `http://localhost:5001`.

## Run With Docker

```bash
docker compose up --build
```

`polls.yml` is mounted from the host (`./polls.yml:/app/polls.yml`), so you can edit it after deployment.

## URLs

Use one run/session UUID for a class, for example:
`59d7fe1b-84ad-4577-aa89-617af082ba4b`

Student topic URL:

```text
http://localhost:5001/<subject>/<topic>?id=<uuid>
```

Teacher topic URL:

```text
http://localhost:5001/teacher/<subject>/<topic>?id=<uuid>
```

Examples:

- `http://localhost:5001/operating_systems/introduction?id=59d7fe1b-84ad-4577-aa89-617af082ba4b`
- `http://localhost:5001/teacher/operating_systems/introduction?id=59d7fe1b-84ad-4577-aa89-617af082ba4b`

Without `id`, topic URLs return `404`.
