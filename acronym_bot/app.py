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
    t = term.strip().upper()
    e = expansion.strip()
    if not t or not e:
        return
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "INSERT INTO acronyms (term, expansion, created_at) VALUES (?, ?, ?)",
        (t, e, int(time.time()))
    )
    conn.commit()
    conn.close()

def get_acronyms(term: str):
    t = term.strip().upper()
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute(
        "SELECT expansion FROM acronyms WHERE term = ? ORDER BY id ASC",
        (t,)
    ).fetchall()
    conn.close()
    # rows is a list of tuples like [(expansion,), ...] -> flatten to [expansion, ...]
    return [r[0] for r in rows]

def format_defs(term: str, expansions):
    t = term.strip().upper()
    if not expansions:
        return f"Nothing for *{t}* yet. Try `/acronym add` to submit one."
    lines = [f"*{t}* has {len(expansions)} meaning(s):"]
    for i, exp in enumerate(expansions, 1):
        lines.append(f"{i}. {exp}")
    return "\n".join(lines)

# --- Delete helpers ---
def get_acronym_ids_and_expansions(term: str):
    t = term.strip().upper()
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute(
        "SELECT id, expansion FROM acronyms WHERE term = ? ORDER BY id ASC",
        (t,)
    ).fetchall()
    conn.close()
    return rows  # [(id, expansion), ...]

def delete_acronym_by_id(acronym_id: int):
    conn = sqlite3.connect(DB_PATH)
    conn.execute("DELETE FROM acronyms WHERE id = ?", (acronym_id,))
    conn.commit()
    conn.close()

init_db()

# ---------- Slash command: /acronym ----------
@app.command("/acronym")
def handle_acronym(ack, respond, command, client):
    ack()
    text = (command.get("text") or "").strip()

    if not text:
        respond("Usage: `/acronym ATO` or `/acronym add`", response_type="ephemeral")
        return

    # /acronym add [term] -> open modal, optionally prepopulate term
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


    # /acronym delete <TERM>
    if text.lower().startswith("delete"):
        parts = text.split(None, 2)
        if len(parts) < 2:
            respond("Usage: `/acronym delete [acronym]`", response_type="ephemeral")
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
        for idx, (aid, exp) in enumerate(rows, 1):
            blocks.append({
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"{idx}. {exp}"},
                "accessory": {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Delete"},
                    "style": "danger",
                    "action_id": "delete_acronym_select",
                    "value": f"{aid}|{term}"
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

    # /acronym <TERM> -> look up in DB
    expansions = get_acronyms(text)
    respond(
        format_defs(text, expansions),
        response_type="ephemeral" if not expansions else "in_channel"
    )
# ---------- Modal submission ----------
# ---------- Delete interactions ----------
@app.action("delete_acronym_select")
def handle_delete_select(ack, body, respond, action):
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
    ack()
    user = body["user"]["id"]
    value = action["value"]  # format: id|term
    aid, term = value.split("|", 1)
    delete_acronym_by_id(int(aid))
    respond(text=f"Deleted one definition for *{term.upper()}*.", response_type="ephemeral", replace_original=True)

@app.action("delete_acronym_cancel")
def handle_delete_cancel(ack, respond, action):
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
    term = re.sub(r"<@[^>]+>", "", body["event"]["text"]).strip()
    if not term:
        say("Give me an acronym, e.g., `ATO`")
        return
    expansions = get_acronyms(term)
    say(format_defs(term, expansions))

# ---------- Run ----------
if __name__ == "__main__":
    SocketModeHandler(app, os.environ["SLACK_APP_TOKEN"]).start()