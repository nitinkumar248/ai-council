import os
import time
import datetime

import streamlit as st
from google import genai
from google.genai import types

st.set_page_config(page_title="AI Decision Council", page_icon="🏛️", layout="centered")


# ---------- config ----------
def secret(name, default=""):
    try:
        return st.secrets[name]
    except Exception:
        return os.getenv(name, default)


API_KEY = secret("GEMINI_API_KEY")
MODEL = secret("GEMINI_MODEL", "gemini-3.8-flash")  # change if Google retires it
APP_PASSWORD = secret("APP_PASSWORD")

# ---------- council design ----------
MEMBER_FORMAT = """Respond in exactly this format, under 300 words total:
**Recommendation:** (one sentence)
**Top 3 reasons:**
**Top 3 risks:**
**What would change my mind:**
**Confidence:** (0-100)"""

CRITIQUE_FORMAT = """Respond in exactly this format, under 250 words total:
**Strongest point from the others:**
**Where the others are wrong or missing something:**
**Do I change my recommendation?** (yes/no, and why)
**Final recommendation:** (one sentence)
**Final confidence:** (0-100)"""

ROLES = {
    "gemini": (
        "The Analyst",
        "Focus on facts, numbers, base rates, costs, and feasibility. Be concrete and skeptical of hype.",
    ),
    "gpt": (
        "The Challenger",
        "Assume the obvious option is wrong. Hunt for failure modes, hidden costs, and what could go badly.",
    ),
    "claude": (
        "The Strategist",
        "Focus on long-term and second-order effects, reversibility, the people involved, and values.",
    ),
}
LABELS = {"gemini": "A", "gpt": "B", "claude": "C"}  # anonymous labels for the Chair

CHAIR_SYSTEM = (
    "You are the impartial Chair of a decision council. You receive anonymous opinions from "
    "Member A, B and C. Weigh them equally on the strength of their reasoning, not their order "
    "or confidence. Do not invent facts. Be direct and practical."
)

CHAIR_FORMAT = """Write the council's report in exactly this format:
## Verdict
(one clear recommendation, 1-2 sentences)
## Where they agree
## Where they disagree
{round2_section}## Blind spots nobody covered
## 7-day action plan
(3-5 concrete steps)
## Kill criteria
(signals that mean: stop or change course)
## Council confidence
(0-100 and one line why)"""

ROUND2_SECTION = "## How positions changed in Round 2\n"


def build_packet(role_key, question, context):
    title, lens = ROLES[role_key]
    return (
        f"You are {title} on a 3-member decision council. {lens}\n\n"
        f"DECISION:\n{question}\n\n"
        f"CONTEXT:\n{context or '(none given)'}\n\n"
        f"{MEMBER_FORMAT}"
    )


def build_round2_packet(role_key, question, context, round1):
    title, lens = ROLES[role_key]
    own = round1[role_key]
    others = [round1[k] for k in ("gemini", "gpt", "claude") if k != role_key and round1[k]]
    others_text = "\n\n".join(f"--- Other member {i + 1} ---\n{o}" for i, o in enumerate(others))
    return (
        f"You are {title} on a 3-member decision council. {lens}\n"
        f"This is Round 2: cross-examination. Read the other members' opinions, "
        f"attack their weakest points, and revise your own view if they earned it.\n\n"
        f"DECISION:\n{question}\n\n"
        f"CONTEXT:\n{context or '(none given)'}\n\n"
        f"YOUR ROUND 1 OPINION:\n{own}\n\n"
        f"THE OTHERS' ROUND 1 OPINIONS:\n{others_text}\n\n"
        f"{CRITIQUE_FORMAT}"
    )


def ask_gemini(prompt, system=None):
    client = genai.Client(api_key=API_KEY)
    cfg = types.GenerateContentConfig(system_instruction=system, temperature=0.7)
    last = None
    for attempt in range(3):
        try:
            r = client.models.generate_content(model=MODEL, contents=prompt, config=cfg)
            return r.text or "(empty response)"
        except Exception as e:  # rate limits etc.
            last = e
            time.sleep(3 * (attempt + 1))
    raise last


# ---------- password gate (protects your free quota) ----------
if APP_PASSWORD and not st.session_state.get("ok"):
    pw = st.text_input("Password", type="password")
    if pw and pw == APP_PASSWORD:
        st.session_state["ok"] = True
        st.rerun()
    st.stop()

if not API_KEY:
    st.error("Missing GEMINI_API_KEY. Add it in Streamlit Secrets (or as an environment variable).")
    st.stop()

# ---------- state ----------
for k in ("gemini", "gpt", "claude", "gemini2", "gpt2", "claude2", "report"):
    st.session_state.setdefault(k, "")

st.title("🏛️ AI Decision Council")
st.caption("Gemini runs automatically. GPT and Claude run in their free chat apps: copy, paste, bring back.")

# ---------- step 1 ----------
st.subheader("1. The decision")
question = st.text_area("What are you deciding?", height=90, key="question",
                        placeholder="Should I take the first client for my outreach agency at a low price?")
context = st.text_area("Context (budget, deadline, constraints, options)", height=120, key="context")

# ---------- step 2 ----------
st.subheader("2. Round 1: independent opinions")
if st.button("Run Gemini", type="primary", disabled=not question.strip()):
    with st.spinner("Gemini is thinking..."):
        try:
            st.session_state["gemini"] = ask_gemini(build_packet("gemini", question, context))
        except Exception as e:
            st.error(f"Gemini failed: {e}")
if st.session_state["gemini"]:
    st.markdown(st.session_state["gemini"])

if question.strip():
    for key, link, name in (
        ("gpt", "https://chatgpt.com", "ChatGPT"),
        ("claude", "https://claude.ai", "Claude"),
    ):
        with st.expander(f"{name}: copy prompt, paste answer", expanded=False):
            st.markdown(f"Copy this into [{name}]({link}) (use a new chat):")
            st.code(build_packet(key, question, context), language=None)
            st.text_area(f"Paste {name}'s answer here", height=200, key=key)
else:
    st.info("Enter a decision above to generate the prompts.")

round1 = {k: st.session_state[k].strip() for k in ("gemini", "gpt", "claude")}
n1 = sum(1 for v in round1.values() if v)
st.caption(f"Round 1: {n1}/3 opinions in.")

# ---------- step 3 (optional) ----------
st.subheader("3. Round 2 (optional): cross-examination")
if n1 < 2:
    st.info("Needs at least 2 Round 1 opinions.")
else:
    st.caption("Each member sees the others' opinions, attacks the weak spots, and may change their mind.")
    if round1["gemini"]:
        if st.button("Run Gemini's critique"):
            with st.spinner("Gemini is cross-examining..."):
                try:
                    st.session_state["gemini2"] = ask_gemini(
                        build_round2_packet("gemini", question, context, round1)
                    )
                except Exception as e:
                    st.error(f"Gemini failed: {e}")
        if st.session_state["gemini2"]:
            st.markdown(st.session_state["gemini2"])
    for key, link, name in (
        ("gpt", "https://chatgpt.com", "ChatGPT"),
        ("claude", "https://claude.ai", "Claude"),
    ):
        if not round1[key]:
            continue  # member sat out Round 1, so they sit out Round 2
        with st.expander(f"{name}: Round 2 prompt and answer", expanded=False):
            st.markdown(f"Copy this into the **same chat** in [{name}]({link}) (or a new one):")
            st.code(build_round2_packet(key, question, context, round1), language=None)
            st.text_area(f"Paste {name}'s Round 2 answer here", height=200, key=f"{key}2")

# ---------- step 4 ----------
st.subheader("4. Chair's verdict")
filled = [k for k in ("gemini", "gpt", "claude") if round1[k]]
has_r2 = any(st.session_state[f"{k}2"].strip() for k in ("gemini", "gpt", "claude"))
st.caption(f"{len(filled)}/3 opinions in" + (", Round 2 included." if has_r2 else ". Round 2 is optional."))

if st.button("Convene the Chair", disabled=len(filled) < 2):
    r1_text = "\n\n".join(f"=== Member {LABELS[k]} (Round 1) ===\n{round1[k]}" for k in filled)
    r2_parts = [
        f"=== Member {LABELS[k]} (Round 2) ===\n{st.session_state[f'{k}2'].strip()}"
        for k in filled
        if st.session_state[f"{k}2"].strip()
    ]
    r2_text = ("\n\n" + "\n\n".join(r2_parts)) if r2_parts else ""
    fmt = CHAIR_FORMAT.format(round2_section=ROUND2_SECTION if r2_parts else "")
    prompt = (
        f"DECISION:\n{question}\n\nCONTEXT:\n{context or '(none)'}\n\n"
        f"OPINIONS:\n{r1_text}{r2_text}\n\n{fmt}"
    )
    with st.spinner("The Chair is deliberating..."):
        try:
            st.session_state["report"] = ask_gemini(prompt, system=CHAIR_SYSTEM)
        except Exception as e:
            st.error(f"Chair failed: {e}")

if st.session_state["report"]:
    st.markdown(st.session_state["report"])
    s = st.session_state
    transcript = (
        f"# Council session {datetime.date.today()}\n\n## Decision\n{question}\n\n"
        f"## Context\n{context}\n\n"
        f"## Round 1\n### Gemini\n{s['gemini']}\n\n### GPT\n{s['gpt']}\n\n### Claude\n{s['claude']}\n\n"
        f"## Round 2\n### Gemini\n{s['gemini2']}\n\n### GPT\n{s['gpt2']}\n\n### Claude\n{s['claude2']}\n\n"
        f"---\n{s['report']}\n"
    )
    st.download_button("Download transcript (.md)", transcript, file_name="council-session.md")
