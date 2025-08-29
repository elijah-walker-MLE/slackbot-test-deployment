import os, re, sqlite3, time
from pathlib import Path
from dotenv import load_dotenv
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler

# ---------- Setup ----------
load_dotenv()
app = App(token=os.environ["SLACK_BOT_TOKEN"])

DB_PATH = Path(__file__).with_name("acronyms.db")

def init_db():
    """Initialize the acronyms database and create tables if they don't exist."""
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS acronyms (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            term TEXT NOT NULL,          -- stored UPPERCASE for exact match
            expansion TEXT NOT NULL,     -- Spelled out
            created_at INTEGER NOT NULL 
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_term ON acronyms(term)")
    conn.commit()
    conn.close()

def add_acronym(term: str, expansion: str):
    """Add a new acronym and its expansion to the database."""
    term_clean = term.strip().upper()
    expansion_clean = expansion.strip()
    if not term_clean or not expansion_clean:
        return
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "INSERT INTO acronyms (term, expansion, created_at) VALUES (?, ?, ?)",
        (term_clean, expansion_clean, int(time.time()))
    )
    conn.commit()
    conn.close()

def get_acronyms(term: str):
    """Return a list of expansions for a given acronym term."""
    term_clean = term.strip().upper()
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute(
        "SELECT expansion FROM acronyms WHERE term = ? ORDER BY id ASC",
        (term_clean,)
    ).fetchall()
    conn.close()
    # rows is a list of tuples like [(expansion,), ...] -> flatten to [expansion, ...]
    return [row[0] for row in rows]

def format_defs(term: str, expansions):
    """Format a list of expansions for display in Slack."""
    term_clean = term.strip().upper()
    if not expansions:
        return f"Nothing for *{term_clean}* yet. Try `/wtf add` to submit one."
    lines = [f"*{term_clean}* has {len(expansions)} meaning(s):"]
    for idx, expansion in enumerate(expansions, 1):
        lines.append(f"{idx}. {expansion}")
    return "\n".join(lines)

# --- Delete and edit helpers ---
def get_acronym_ids_and_expansions(term: str):
    """Return a list of (id, expansion) tuples for a given acronym term."""
    term_clean = term.strip().upper()
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute(
        "SELECT id, expansion FROM acronyms WHERE term = ? ORDER BY id ASC",
        (term_clean,)
    ).fetchall()
    conn.close()
    return rows  # [(id, expansion), ...]

def delete_acronym_by_id(acronym_id: int):
    """Delete an acronym expansion by its unique ID."""
    conn = sqlite3.connect(DB_PATH)
    conn.execute("DELETE FROM acronyms WHERE id = ?", (acronym_id,))
    conn.commit()
    conn.close()

init_db()

# ---------- Slash command: /wtf ----------
@app.command("/wtf")

def handle_acronym(ack, respond, command, client):
    # Always ack first in all handlers
    ack()

    text = (command.get("text") or "").strip()

    if not text:
        respond("Usage: `/wtf ATO` or `/wtf add`", response_type="ephemeral")
        return

    # /wtf add [term] -> open modal, optionally prepopulate term
    if text.lower().startswith("add"):
        parts = text.split(None, 2)
        prefill_term = parts[1].upper() if len(parts) > 1 else ""

        client.views_open(
            trigger_id=command["trigger_id"],
            view={
                "type": "modal",
                "callback_id": "add_acronym",
                "title": {"type": "plain_text", "text": "Add Acronym"},
                "submit": {"type": "plain_text", "text": "Save"},
                "close": {"type": "plain_text", "text": "Cancel"},
                "private_metadata": command.get("channel_id", ""),
                "blocks": [
                    {
                        "type": "input",
                        "block_id": "term",
                        "label": {"type": "plain_text", "text": "Acronym (e.g., ATO)"},
                        "element": {
                            "type": "plain_text_input",
                            "action_id": "t",
                            **({"initial_value": prefill_term} if prefill_term else {})
                        }
                    },
                    {
                        "type": "input",
                        "block_id": "exp",
                        "label": {"type": "plain_text", "text": "Expansion (meaning)"},
                        "element": {"type": "plain_text_input", "action_id": "e", "multiline": True}
                    }
                ]
            }
        )
        return

    # /wtf delete <TERM>
    if text.lower().startswith("delete"):
        parts = text.split(None, 2)
        if len(parts) < 2:
            respond("Usage: `/wtf delete [acronym]`", response_type="ephemeral")
            return

        term = parts[1]
        rows = get_acronym_ids_and_expansions(term)
        if not rows:
            respond(f"No definitions found for *{term.upper()}*.", response_type="ephemeral")
            return

        # Show interactive message with buttons for each definition
        blocks = [
            {"type": "section", "text": {"type": "mrkdwn", "text": f"*{term.upper()}* has {len(rows)} meaning(s). Which one do you want to delete?"}}
        ]
        for idx, (acronym_id, expansion) in enumerate(rows, 1):
            blocks.append({
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"{idx}. {expansion}"},
                "accessory": {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Delete"},
                    "style": "danger",
                    "action_id": "delete_acronym_select",
                    "value": f"{acronym_id}|{term}"
                }
            })
        blocks.append({
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Cancel"},
                    "style": "primary",
                    "action_id": "delete_acronym_cancel",
                    "value": term
                }
            ]
        })
        respond(blocks=blocks, response_type="ephemeral")
        return

    # /wtf edit <TERM>
    if text.lower().startswith("edit"):
        parts = text.split(None, 2)
        if len(parts) < 2:
            respond("Usage: `/wtf edit [acronym]`", response_type="ephemeral")
            return

        term = parts[1]
        rows = get_acronym_ids_and_expansions(term)
        if not rows:
            respond(f"No definitions found for *{term.upper()}*.", response_type="ephemeral")
            return

        blocks = [
            {"type": "section", "text": {"type": "mrkdwn", "text": f"*{term.upper()}* has {len(rows)} meaning(s). Which one do you want to edit?"}}
        ]
        for idx, (acronym_id, expansion) in enumerate(rows, 1):
            blocks.append({
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"{idx}. {expansion}"},
                "accessory": {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Edit"},
                    "style": "primary",
                    "action_id": "edit_acronym_select",
                    "value": f"{acronym_id}|{term}"
                }
            })
        blocks.append({
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Cancel"},
                    "style": "primary",
                    "action_id": "edit_acronym_cancel",
                    "value": term
                }
            ]
        })
        respond(blocks=blocks, response_type="ephemeral")
        return

    # /wtf <TERM> -> look up in DB
    expansions = get_acronyms(text)
    respond(
        format_defs(text, expansions),
        response_type="ephemeral" if not expansions else "in_channel"
    )
# ---------- Edit interactions ----------
@app.action("edit_acronym_select")
def handle_edit_select(ack, body, respond, action, client):
    # Always ack first
    ack()
    user = body["user"]["id"]
    value = action["value"]  # format: id|term
    aid, term = value.split("|", 1)
    # Fetch the definition text for editing
    conn = sqlite3.connect(DB_PATH)
    row = conn.execute("SELECT expansion FROM acronyms WHERE id = ?", (aid,)).fetchone()
    conn.close()
    exp = row[0] if row else ""
    client.views_open(
        trigger_id=body["trigger_id"],
        view={
            "type": "modal",
            "callback_id": "edit_acronym_modal",
            "title": {"type": "plain_text", "text": "Edit Definition"},
            "submit": {"type": "plain_text", "text": "Save"},
            "close": {"type": "plain_text", "text": "Cancel"},
            "private_metadata": f"{aid}|{term}",
            "blocks": [
                {
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": f"*{term.upper()}*"}
                },
                {
                    "type": "input",
                    "block_id": "exp_edit",
                    "label": {"type": "plain_text", "text": "Edit Expansion (meaning)"},
                    "element": {"type": "plain_text_input", "action_id": "e_edit", "multiline": True, "initial_value": exp}
                }
            ]
        }
    )

@app.action("edit_acronym_cancel")
def handle_edit_cancel(ack, respond, action):
    # Always ack first
    ack()
    respond(text="Edit cancelled.", response_type="ephemeral", replace_original=True)

# ---------- Modal submission for edit ----------
@app.view("edit_acronym_modal")
def handle_edit_view(ack, body, view, client, logger):
    # Always ack first
    ack()
    user_id = body["user"]["id"]
    values = view["state"]["values"]
    meta = view.get("private_metadata", "")
    aid, term = meta.split("|", 1)
    new_exp = values["exp_edit"]["e_edit"]["value"].strip()
    if new_exp:
        conn = sqlite3.connect(DB_PATH)
        conn.execute("UPDATE acronyms SET expansion = ? WHERE id = ?", (new_exp, aid))
        conn.commit()
        conn.close()

    channel_id = view.get("private_metadata", "")
    if channel_id:
        try:
            client.chat_postEphemeral(
                channel=channel_id,
                user=user_id,
                text=f"Updated: *{term.upper()}* → {new_exp}"
            )
        except Exception as e:
            logger.exception(e)


    try:
        client.chat_postEphemeral(
            channel=body["user"]["id"],
            user=user_id,
            text=f"Updated definition for *{term.upper()}*."
        )
    except Exception as e:
        logger.exception(e)

# ---------- Delete interactions ----------
@app.action("delete_acronym_select")
def handle_delete_select(ack, body, respond, action):
    # Always ack first
    ack()
    user = body["user"]["id"]
    value = action["value"]  # format: id|term
    aid, term = value.split("|", 1)
    # Fetch the definition text for confirmation
    conn = sqlite3.connect(DB_PATH)
    row = conn.execute("SELECT expansion FROM acronyms WHERE id = ?", (aid,)).fetchone()
    conn.close()
    exp = row[0] if row else "(definition not found)"
    blocks = [
        {"type": "section", "text": {"type": "mrkdwn", "text": f"Are you sure you want to delete this definition for *{term.upper()}*?\n> {exp}"}},
        {"type": "actions", "elements": [
            {
                "type": "button",
                "text": {"type": "plain_text", "text": "Yes, Delete"},
                "style": "danger",
                "action_id": "delete_acronym_confirm",
                "value": f"{aid}|{term}"
            },
            {
                "type": "button",
                "text": {"type": "plain_text", "text": "Cancel"},
                "style": "primary",
                "action_id": "delete_acronym_cancel",
                "value": term
            }
        ]}
    ]
    respond(blocks=blocks, response_type="ephemeral", replace_original=True)

@app.action("delete_acronym_confirm")
def handle_delete_confirm(ack, body, respond, action):
    # Always ack first
    ack()
    user = body["user"]["id"]
    value = action["value"]  # format: id|term
    aid, term = value.split("|", 1)
    delete_acronym_by_id(int(aid))
    respond(text=f"Deleted one definition for *{term.upper()}*.", response_type="ephemeral", replace_original=True)

@app.action("delete_acronym_cancel")
def handle_delete_cancel(ack, respond, action):
    # Always ack first
    ack()
    respond(text="Delete cancelled.", response_type="ephemeral", replace_original=True)

# ---------- Modal submission ----------
@app.view("add_acronym")
def handle_add_view(ack, body, view, client, logger):
    # Always ack first
    ack()

    user_id = body["user"]["id"]
    values = view["state"]["values"]
    term = values["term"]["t"]["value"].strip()
    expansion = values["exp"]["e"]["value"].strip()

    if term and expansion:
        add_acronym(term, expansion)

    channel_id = view.get("private_metadata", "")
    if channel_id:
        try:
            client.chat_postEphemeral(
                channel=channel_id,
                user=user_id,
                text=f"Saved: *{term.upper()}* → {expansion}"
            )
        except Exception as e:
            logger.exception(e)

# ---------- @ mention ----------
@app.event("app_mention")
def on_mention(body, say):
    """Respond to @ mentions with acronym definitions."""
    term = re.sub(r"<@[^>]+>", "", body["event"]["text"]).strip()
    if not term:
        say("Give me an acronym, e.g., `ATO`")
        return
    expansions = get_acronyms(term)
    say(format_defs(term, expansions))

# ---------- Run ----------
if __name__ == "__main__":
    SocketModeHandler(app, os.environ["SLACK_APP_TOKEN"]).start()
