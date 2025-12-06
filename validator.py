# validator.py
import re
from typing import Tuple, List, Dict, Optional

RE_DES = re.compile(r'^\s*DES:\s*(?P<title>.+?)\s*$', re.IGNORECASE)
RE_DES_COMPLETED = re.compile(r'^\s*DES:\s*(?P<title>.+?)\s+COMPLETED\s*✅\s*$', re.IGNORECASE)
RE_Q = re.compile(r'^\s*Q:\s*(?P<q>.+?)\s*$', re.IGNORECASE)
RE_OPTION = re.compile(r'^\s*(?P<label>[A-L])\s*[:\-\.\)]\s*(?P<rest>.+)$', re.IGNORECASE)
RE_ANS = re.compile(r'^\s*ANS:\s*(?P<ans>[A-L])\s*$', re.IGNORECASE)
RE_EXP = re.compile(r'^\s*EXP:\s*(?P<exp>.+?)\s*$', re.IGNORECASE)
RE_TARGET = re.compile(r'^\s*TARGET:\s*(?P<target>.+?)\s*$', re.IGNORECASE)

def _normalize_option_text(raw: str) -> str:
    s = raw.strip()
    s = re.sub(r'^\(\s*[A-L]\s*\)\s*', '', s, flags=re.IGNORECASE)
    s = re.sub(r'^[A-L]\s*[:\-\.\)]\s*', '', s, flags=re.IGNORECASE)
    return s.strip()

def extract_title_and_target(text: str) -> Tuple[Optional[str], Optional[str]]:
    title = None
    target = None
    for line in text.splitlines():
        if not title:
            m = RE_DES.match(line)
            if m:
                title = m.group('title').strip()
        m2 = RE_TARGET.match(line)
        if m2:
            target = m2.group('target').strip()
    return title, target

def validate_and_parse(text: str) -> Tuple[bool, object]:
    lines = [ln.rstrip() for ln in text.splitlines()]
    if not lines:
        return False, "Empty message."

    title = None
    start_idx = 0
    for i, ln in enumerate(lines):
        m = RE_DES.match(ln)
        if m:
            title = m.group('title').strip()
            start_idx = i + 1
            break
    if not title:
        return False, "Missing DES: <title> header at the top."

    # detect target if present
    target = None
    for ln in lines:
        m = RE_TARGET.match(ln)
        if m:
            target = m.group('target').strip()
            break

    cursor = start_idx
    total = len(lines)
    questions: List[Dict] = []
    current_q = None

    def _finalize_current():
        nonlocal current_q
        if not current_q:
            return None
        qtext = current_q.get("q","").strip()
        opts = current_q.get("options", {})
        ans = current_q.get("ans")
        exp = current_q.get("exp")
        if not qtext:
            return "A question has empty text."
        if len(opts) < 2:
            return f"Question '{qtext[:30]}...' must have at least two options."
        if not ans:
            return f"Missing ANS for question: '{qtext[:40]}...'"
        if ans.upper() not in opts:
            return f"ANS '{ans}' not present in options for question: '{qtext[:40]}...'"
        ordered = [opts[k] for k in sorted(opts.keys())]
        parsed = {
            "q": qtext,
            "options": ordered,
            "ans": ans.upper(),
            "exp": exp.strip() if exp else None
        }
        questions.append(parsed)
        current_q = None
        return None

    while cursor < total:
        ln = lines[cursor].strip()
        cursor += 1
        if ln == "":
            continue

        m_q = RE_Q.match(ln)
        if m_q:
            if current_q:
                err = _finalize_current()
                if err:
                    return False, err
            current_q = {"q": m_q.group("q").strip(), "options": {}, "ans": None, "exp": None}
            continue

        m_opt = RE_OPTION.match(ln)
        if m_opt and current_q is not None:
            label = m_opt.group("label").upper()
            rest = m_opt.group("rest").strip()
            clean = _normalize_option_text(rest)
            if not clean:
                return False, f"Option {label} has empty text in question: '{current_q.get('q','')[:40]}...'"
            if label in current_q["options"]:
                return False, f"Duplicate option label '{label}' in question: '{current_q.get('q','')[:40]}...'"
            current_q["options"][label] = clean
            continue

        m_ans = RE_ANS.match(ln)
        if m_ans and current_q is not None:
            current_q["ans"] = m_ans.group("ans").upper()
            continue

        m_exp = RE_EXP.match(ln)
        if m_exp and current_q is not None:
            current_q["exp"] = m_exp.group("exp").strip()
            continue

        if RE_DES_COMPLETED.match(ln):
            if current_q:
                err = _finalize_current()
                if err:
                    return False, err
            break

        if ln.startswith("Eg(") or ln.lower().startswith("the respondent") or ln.lower().startswith("total points") or ln.lower().startswith("name"):
            continue

        if current_q:
            return False, f"Unrecognized line inside question '{current_q.get('q','')[:30]}': {ln}"
        else:
            return False, f"Unexpected line outside questions: {ln}"

    if current_q:
        err = _finalize_current()
        if err:
            return False, err

    if not questions:
        return False, "No questions parsed. Ensure you have at least one 'Q:' block."

    for i,q in enumerate(questions, start=1):
        opts_len = len(q["options"])
        max_label = chr(ord("A") + opts_len -1)
        if not ("A" <= q["ans"] <= max_label):
            return False, f"Question {i}: ANS '{q['ans']}' invalid for {opts_len} options."

    result = {
        "title": title,
        "target": target,
        "questions": questions
    }
    return True, result
