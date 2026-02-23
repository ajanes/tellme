from collections import Counter
from pathlib import Path
import os
from threading import Lock
from uuid import UUID

from flask import Flask, abort, jsonify, redirect, render_template, request, session
import yaml

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "9430e003-162c-4f85-aac0-408211a62f01")

DEFAULT_POLL_FILE = Path(__file__).resolve().parent.parent / "polls.yml"
POLL_FILE = Path(os.getenv("POLL_FILE", str(DEFAULT_POLL_FILE)))
RESULTS_LOCK = Lock()
POLL_RESULTS: dict[str, dict] = {}
TOPIC_SELECTION_LOCK = Lock()
ACTIVE_TOPIC_POLL: dict[str, str] = {}
SUPPORTED_LOCALES = ("de", "it", "en")

MESSAGES = {
    "already_submitted": {
        "en": "You have already submitted this poll.",
        "de": "Du hast diese Umfrage bereits abgeschickt.",
        "it": "Hai gia inviato questo sondaggio.",
    },
    "unsupported_answer_type": {
        "en": "Unsupported answer type: {answer_type}",
        "de": "Nicht unterstuetzter Antworttyp: {answer_type}",
        "it": "Tipo di risposta non supportato: {answer_type}",
    },
    "missing_answer": {
        "en": "Please provide an answer before submitting.",
        "de": "Bitte gib eine Antwort ein, bevor du absendest.",
        "it": "Inserisci una risposta prima di inviare.",
    },
}

UI_TEXTS = {
    "submitted_answer": {
        "en": "Submitted answer:",
        "de": "Abgegebene Antwort:",
        "it": "Risposta inviata:",
    },
    "already_submitted_info": {
        "en": "You already submitted this poll.",
        "de": "Du hast diese Umfrage bereits abgeschickt.",
        "it": "Hai gia inviato questo sondaggio.",
    },
    "tap_one_option": {
        "en": "Tap one option",
        "de": "Waehle eine Option",
        "it": "Scegli un'opzione",
    },
    "choose_one_or_more_options": {
        "en": "Choose one or more options",
        "de": "Waehle eine oder mehrere Optionen",
        "it": "Scegli una o piu opzioni",
    },
    "your_answer": {
        "en": "Your answer",
        "de": "Deine Antwort",
        "it": "La tua risposta",
    },
    "enter_text": {
        "en": "Enter text",
        "de": "Text eingeben",
        "it": "Inserisci testo",
    },
    "submit": {
        "en": "Submit",
        "de": "Absenden",
        "it": "Invia",
    },
    "unsupported_answer_type": {
        "en": "Unsupported answer type:",
        "de": "Nicht unterstuetzter Antworttyp:",
        "it": "Tipo di risposta non supportato:",
    },
    "teacher_previous": {
        "en": "Previous",
        "de": "Zurueck",
        "it": "Precedente",
    },
    "teacher_next": {
        "en": "Next",
        "de": "Weiter",
        "it": "Successiva",
    },
    "teacher_prev_aria": {
        "en": "Previous poll",
        "de": "Vorherige Umfrage",
        "it": "Sondaggio precedente",
    },
    "teacher_next_aria": {
        "en": "Next poll",
        "de": "Naechste Umfrage",
        "it": "Sondaggio successivo",
    },
    "teacher_no_options": {
        "en": "No options configured.",
        "de": "Keine Optionen konfiguriert.",
        "it": "Nessuna opzione configurata.",
    },
    "teacher_no_text": {
        "en": "No text answers yet.",
        "de": "Noch keine Textantworten.",
        "it": "Ancora nessuna risposta testuale.",
    },
    "teacher_no_polls": {
        "en": "No polls found for this topic.",
        "de": "Keine Umfragen fuer dieses Thema gefunden.",
        "it": "Nessun sondaggio trovato per questo argomento.",
    },
    "teacher_response_one": {
        "en": "response",
        "de": "Antwort",
        "it": "risposta",
    },
    "teacher_response_other": {
        "en": "responses",
        "de": "Antworten",
        "it": "risposte",
    },
    "teacher_unsupported_poll_type": {
        "en": "Unsupported poll type.",
        "de": "Nicht unterstuetzter Umfragetyp.",
        "it": "Tipo di sondaggio non supportato.",
    },
    "teacher_failed_to_load": {
        "en": "Failed to load live results.",
        "de": "Live-Ergebnisse konnten nicht geladen werden.",
        "it": "Impossibile caricare i risultati live.",
    },
}

def normalize_language(language: str | None) -> str:
    if isinstance(language, str):
        language = language.lower()
        if language in SUPPORTED_LOCALES:
            return language
    return "en"


def msg(message_key: str, locale: str = "en", **kwargs) -> str:
    template = MESSAGES.get(message_key, {}).get(locale) or MESSAGES.get(message_key, {}).get("en") or message_key
    return template.format(**kwargs)


def ui_texts(locale: str = "en") -> dict[str, str]:
    localized = {}
    for key, variants in UI_TEXTS.items():
        localized[key] = variants.get(locale) or variants.get("en") or key
    return localized


def load_polls() -> dict[tuple[str, str, str], dict]:
    with POLL_FILE.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}

    flattened_polls = []

    # Backward-compatible: allow a flat top-level "polls" list.
    for poll in data.get("polls", []):
        if "id" in poll:
            flattened_polls.append(
                {
                    **poll,
                    "subject": "general",
                    "topic": "general",
                    "language": "en",
                }
            )

    # Grouped format: subjects -> topics -> polls.
    for subject in data.get("subjects", []):
        subject_id = subject.get("id")
        subject_language = normalize_language(subject.get("language"))
        for topic in subject.get("topics", []):
            topic_id = topic.get("id")
            for poll in topic.get("polls", []):
                if "id" not in poll or not subject_id or not topic_id:
                    continue
                poll_with_context = {
                    **poll,
                    "subject": subject_id,
                    "topic": topic_id,
                    "language": subject_language,
                }
                flattened_polls.append(poll_with_context)

    polls_by_path = {}
    for poll in flattened_polls:
        key = (poll["subject"], poll["topic"], poll["id"])
        polls_by_path[key] = poll
    return polls_by_path


def get_run_id_or_404() -> str:
    raw_id = request.args.get("id", "")
    try:
        return str(UUID(raw_id))
    except (ValueError, TypeError):
        abort(404)


def build_submission_key(run_id: str, subject_id: str, topic_id: str, poll_id: str) -> str:
    return f"{run_id}|{subject_id}/{topic_id}/{poll_id}"


def build_topic_key(run_id: str, subject_id: str, topic_id: str) -> str:
    return f"{run_id}|{subject_id}/{topic_id}"


def get_topic_poll_ids(subject_id: str, topic_id: str) -> list[str]:
    polls_by_path = load_polls()
    poll_ids = []
    for current_subject, current_topic, poll_id in polls_by_path:
        if current_subject == subject_id and current_topic == topic_id:
            poll_ids.append(poll_id)
    return poll_ids


def get_active_topic_poll(run_id: str, subject_id: str, topic_id: str) -> str | None:
    topic_key = build_topic_key(run_id, subject_id, topic_id)
    with TOPIC_SELECTION_LOCK:
        return ACTIVE_TOPIC_POLL.get(topic_key)


def set_active_topic_poll(run_id: str, subject_id: str, topic_id: str, poll_id: str) -> bool:
    if poll_id not in get_topic_poll_ids(subject_id, topic_id):
        return False
    topic_key = build_topic_key(run_id, subject_id, topic_id)
    with TOPIC_SELECTION_LOCK:
        ACTIVE_TOPIC_POLL[topic_key] = poll_id
    return True


def ensure_active_topic_poll(run_id: str, subject_id: str, topic_id: str) -> str | None:
    poll_ids = get_topic_poll_ids(subject_id, topic_id)
    if not poll_ids:
        return None

    current = get_active_topic_poll(run_id, subject_id, topic_id)
    if current in poll_ids:
        return current

    first_poll_id = poll_ids[0]
    set_active_topic_poll(run_id, subject_id, topic_id, first_poll_id)
    return first_poll_id


def ensure_result_entry(submission_key: str, poll: dict) -> dict:
    entry = POLL_RESULTS.get(submission_key)
    if entry is None:
        entry = {
            "answer_type": poll.get("answer_type"),
            "counts": {},
            "text_counts": {},
            "response_count": 0,
        }
        POLL_RESULTS[submission_key] = entry
    else:
        # Backward compatibility for older in-memory format.
        if "text_counts" not in entry:
            legacy_answers = entry.get("answers", [])
            text_counter: Counter[str] = Counter()
            for answer in legacy_answers:
                if answer:
                    text_counter[answer] += 1
            entry["text_counts"] = dict(text_counter)
            entry.pop("answers", None)

    if poll.get("answer_type") in {"single_choice", "multiple_choice"}:
        for answer in poll.get("answers", []):
            entry["counts"].setdefault(answer, 0)

    return entry


def record_submission(
    submission_key: str,
    poll: dict,
    submitted_answer: str | list[str],
    previous_answer: str | list[str] | None = None,
) -> None:
    with RESULTS_LOCK:
        entry = ensure_result_entry(submission_key, poll)
        answer_type = poll.get("answer_type")
        if answer_type == "single_choice":
            if not isinstance(submitted_answer, str):
                return
            if (
                isinstance(previous_answer, str)
                and previous_answer in entry["counts"]
                and entry["counts"][previous_answer] > 0
            ):
                entry["counts"][previous_answer] -= 1
            if submitted_answer in entry["counts"]:
                entry["counts"][submitted_answer] += 1
        elif answer_type == "multiple_choice":
            previous_choices = previous_answer if isinstance(previous_answer, list) else []
            current_choices = submitted_answer if isinstance(submitted_answer, list) else []
            previous_set = set(previous_choices)
            current_set = set(current_choices)

            if not previous_set and current_set:
                entry["response_count"] += 1
            elif previous_set and not current_set and entry["response_count"] > 0:
                entry["response_count"] -= 1

            for choice in previous_set:
                if choice in entry["counts"] and entry["counts"][choice] > 0:
                    entry["counts"][choice] -= 1
            for choice in current_set:
                if choice in entry["counts"]:
                    entry["counts"][choice] += 1
        elif answer_type == "text":
            if not isinstance(submitted_answer, str):
                return
            text_counts = entry["text_counts"]
            if (
                isinstance(previous_answer, str)
                and previous_answer in text_counts
                and text_counts[previous_answer] > 0
            ):
                text_counts[previous_answer] -= 1
                if text_counts[previous_answer] == 0:
                    text_counts.pop(previous_answer, None)
            text_counts[submitted_answer] = text_counts.get(submitted_answer, 0) + 1


def compute_term_frequencies(answer_counts: dict[str, int]) -> list[tuple[str, int]]:
    counter: Counter[str] = Counter()
    for answer, occurrences in answer_counts.items():
        normalized_answer = answer.strip()
        if occurrences <= 0 or not normalized_answer:
            continue
        counter[normalized_answer] += occurrences
    return counter.most_common(40)


def build_teacher_results(run_id: str) -> list[dict]:
    polls_by_path = load_polls()
    payload = []

    with RESULTS_LOCK:
        for (subject_id, topic_id, poll_id), poll in sorted(polls_by_path.items()):
            submission_key = build_submission_key(run_id, subject_id, topic_id, poll_id)
            entry = ensure_result_entry(submission_key, poll)
            answer_type = poll.get("answer_type")

            base_data = {
                "subject": subject_id,
                "topic": topic_id,
                "poll_id": poll_id,
                "question": poll.get("question", poll_id),
                "answer_type": answer_type,
                "path": f"/{subject_id}/{topic_id}/{poll_id}",
                "language": poll.get("language", "en"),
            }

            if answer_type in {"single_choice", "multiple_choice"}:
                counts = entry["counts"]
                total = sum(counts.values()) if answer_type == "single_choice" else entry.get("response_count", 0)
                options = []
                for answer in poll.get("answers", []):
                    count = counts.get(answer, 0)
                    percentage = round((count / total) * 100, 1) if total else 0.0
                    options.append(
                        {
                            "label": answer,
                            "count": count,
                            "percentage": percentage,
                        }
                    )
                payload.append(
                    {
                        **base_data,
                        "total_responses": total,
                        "options": options,
                    }
                )
            elif answer_type == "text":
                text_counts = dict(entry["text_counts"])
                terms = [
                    {"term": term, "count": count}
                    for term, count in compute_term_frequencies(text_counts)
                ]
                payload.append(
                    {
                        **base_data,
                        "total_responses": sum(text_counts.values()),
                        "terms": terms,
                    }
                )
            else:
                payload.append({**base_data, "total_responses": 0})

    return payload


def build_teacher_topic_results(run_id: str, subject_id: str, topic_id: str) -> list[dict]:
    polls_by_path = load_polls()
    payload = []

    with RESULTS_LOCK:
        for (current_subject, current_topic, poll_id), poll in polls_by_path.items():
            if current_subject != subject_id or current_topic != topic_id:
                continue

            submission_key = build_submission_key(run_id, subject_id, topic_id, poll_id)
            entry = ensure_result_entry(submission_key, poll)
            answer_type = poll.get("answer_type")

            base_data = {
                "subject": subject_id,
                "topic": topic_id,
                "poll_id": poll_id,
                "question": poll.get("question", poll_id),
                "answer_type": answer_type,
                "path": f"/{subject_id}/{topic_id}/{poll_id}",
                "language": poll.get("language", "en"),
            }

            if answer_type in {"single_choice", "multiple_choice"}:
                counts = entry["counts"]
                total = sum(counts.values()) if answer_type == "single_choice" else entry.get("response_count", 0)
                options = []
                for answer in poll.get("answers", []):
                    count = counts.get(answer, 0)
                    percentage = round((count / total) * 100, 1) if total else 0.0
                    options.append(
                        {
                            "label": answer,
                            "count": count,
                            "percentage": percentage,
                        }
                    )
                payload.append(
                    {
                        **base_data,
                        "total_responses": total,
                        "options": options,
                    }
                )
            elif answer_type == "text":
                text_counts = dict(entry["text_counts"])
                terms = [
                    {"term": term, "count": count}
                    for term, count in compute_term_frequencies(text_counts)
                ]
                payload.append(
                    {
                        **base_data,
                        "total_responses": sum(text_counts.values()),
                        "terms": terms,
                    }
                )
            else:
                payload.append({**base_data, "total_responses": 0})

    return payload


@app.get("/")
def index():
    abort(404)


@app.get("/teacher")
def teacher_dashboard():
    abort(404)


@app.get("/teacher/<subject_id>/<topic_id>")
@app.get("/techer/<subject_id>/<topic_id>")
def teacher_topic_dashboard(subject_id: str, topic_id: str):
    run_id = get_run_id_or_404()
    if not build_teacher_topic_results(run_id, subject_id, topic_id):
        abort(404)
    language = "en"
    polls_by_path = load_polls()
    for (current_subject, _, _), poll in polls_by_path.items():
        if current_subject == subject_id:
            language = normalize_language(poll.get("language"))
            break
    ensure_active_topic_poll(run_id, subject_id, topic_id)
    return render_template(
        "teacher_topic.html",
        subject_id=subject_id,
        topic_id=topic_id,
        run_id=run_id,
        ui=ui_texts(language),
    )


@app.get("/api/teacher/results")
def teacher_results_api():
    run_id = get_run_id_or_404()
    return jsonify({"polls": build_teacher_results(run_id)})


@app.get("/api/teacher/<subject_id>/<topic_id>/results")
@app.get("/api/techer/<subject_id>/<topic_id>/results")
def teacher_topic_results_api(subject_id: str, topic_id: str):
    run_id = get_run_id_or_404()
    polls = build_teacher_topic_results(run_id, subject_id, topic_id)
    if not polls:
        abort(404)
    active_poll_id = ensure_active_topic_poll(run_id, subject_id, topic_id)
    return jsonify({"polls": polls, "active_poll_id": active_poll_id})


@app.post("/api/teacher/<subject_id>/<topic_id>/active")
@app.post("/api/techer/<subject_id>/<topic_id>/active")
def teacher_topic_active_api(subject_id: str, topic_id: str):
    run_id = get_run_id_or_404()
    if not get_topic_poll_ids(subject_id, topic_id):
        abort(404)

    payload = request.get_json(silent=True) or {}
    poll_id = payload.get("poll_id")
    if not isinstance(poll_id, str) or not poll_id:
        return jsonify({"error": "poll_id is required"}), 400

    if not set_active_topic_poll(run_id, subject_id, topic_id, poll_id):
        return jsonify({"error": "invalid poll_id for this topic"}), 400

    return jsonify({"ok": True, "active_poll_id": poll_id})


def render_student_poll(run_id: str, subject_id: str, topic_id: str, poll_id: str):
    polls_by_path = load_polls()
    poll = polls_by_path.get((subject_id, topic_id, poll_id))
    if not poll:
        abort(404)

    submission_key = build_submission_key(run_id, subject_id, topic_id, poll_id)
    submitted_answers = dict(session.get("submitted_answers", {}))
    previous_answer = submitted_answers.get(submission_key)
    submitted_answer = previous_answer
    error = None
    language = normalize_language(poll.get("language"))
    already_submitted = previous_answer is not None

    if request.method == "POST":
        answer_type = poll.get("answer_type")
        if answer_type == "text":
            submitted_answer = (request.form.get("answer_text") or "").strip()
        elif answer_type == "single_choice":
            submitted_answer = (request.form.get("answer_choice") or "").strip()
            valid_answers = set(poll.get("answers", []))
            if submitted_answer and submitted_answer not in valid_answers:
                submitted_answer = None
        elif answer_type == "multiple_choice":
            valid_answers = set(poll.get("answers", []))
            selected_answers = []
            for answer in request.form.getlist("answer_choices"):
                if answer in valid_answers and answer not in selected_answers:
                    selected_answers.append(answer)
            submitted_answer = selected_answers
        else:
            error = msg("unsupported_answer_type", locale=language, answer_type=answer_type)

        if not submitted_answer and not error:
            error = msg("missing_answer", locale=language)

        if submitted_answer and not error:
            record_submission(
                submission_key=submission_key,
                poll=poll,
                submitted_answer=submitted_answer,
                previous_answer=previous_answer,
            )
            submitted_answers[submission_key] = submitted_answer
            session["submitted_answers"] = submitted_answers
            already_submitted = True

    if isinstance(submitted_answer, list):
        selected_answers = submitted_answer
        submitted_answer_display = ", ".join(submitted_answer)
        text_value = ""
    elif isinstance(submitted_answer, str):
        selected_answers = [submitted_answer]
        submitted_answer_display = submitted_answer
        text_value = submitted_answer
    else:
        selected_answers = []
        submitted_answer_display = None
        text_value = ""

    return render_template(
        "poll.html",
        poll=poll,
        submitted_answer=submitted_answer,
        submitted_answer_display=submitted_answer_display,
        selected_answers=selected_answers,
        text_value=text_value,
        error=error,
        already_submitted=already_submitted,
        ui=ui_texts(language),
        subject_id=subject_id,
        topic_id=topic_id,
        poll_id=poll_id,
        run_id=run_id,
    )


@app.route("/<subject_id>/<topic_id>", methods=["GET", "POST"])
def topic_entry(subject_id: str, topic_id: str):
    run_id = get_run_id_or_404()
    active_poll_id = ensure_active_topic_poll(run_id, subject_id, topic_id)
    if not active_poll_id:
        abort(404)
    return render_student_poll(run_id, subject_id, topic_id, active_poll_id)


@app.route("/<subject_id>/<topic_id>/<poll_id>", methods=["GET", "POST"])
def poll_page(subject_id: str, topic_id: str, poll_id: str):
    # Keep old poll-specific URLs as compatibility redirects.
    run_id = get_run_id_or_404()
    return redirect(f"/{subject_id}/{topic_id}?id={run_id}")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5001, debug=True)
