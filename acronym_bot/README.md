# Wilcore Acronym Slackbot
This slackbot provides users with a way to look up and add acronyms that are commonly used in government contracting.

## Usage
- /acronym [acronym]
- /acronym add [acronym] # Optionally prepopulate the add modal with the acronym
- /acronym delete [acronym]

## Local Development
To start local development, from your project root:
- Run `./setup.sh`
- Run `source .venv/bin/activate`
- Duplicate `.env.example` and rename to `.env`
- Retrieve environment variables and fill out fields in `.env`
- Run `python app.py`
- From within Slack, use the bot!

### Possible errors
- If you get an "not executable file" error, run `chmod +x setup.sh` first.
- If using Fish, run `source .venv/bin/activate.fish` instead of `source .venv/bin/activate`.