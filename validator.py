# validator.py
"""
Strict validator & parser for the DES / Q / A / ANS / EXP quiz format.

Public functions:
- validate_and_parse(text) -> (bool, parsed_or_error)
    If valid: (True, questions_list)
    If invalid: (False, error_message_string)

- extract_title_from_formatted(text) -> title_string or None

Parsed question format (each item in questions_list):
{
    "q": "Question text",
    "options": ["Option text A", "Option text B", ...],
    "ans": "A",   # single uppercase letter
    "exp": "optional explanation" or None
}
"""

import re
from typing import Tuple, List, Dict, Optional

# Regex patterns
RE_DES = re.compile(r'^\s*DES:\s*(?P<title>.+?)\s*$', re.IGNORECASE)
RE_DES_COMPLETED = re.compile(r'^\s*DES:\s*(?P<title>.+?)\s+COMPLETED\s*✅\s*$', re.IGNORECASE)
RE_Q = re.compile(r'^\s*Q:\s*(?P<q>.+?)\s*$', re.IGNORECASE)
# Option lines like:
# A: (A) text
# A: (A)text
# A: (A) text
# A: text
RE_OPTION = re.compile(r'^\s*(?P<label>[A-L])\s*[:\-)\.]\s*(?P<rest>.+)$', re.IGNORECASE)
# ANS: A
RE_ANS = re.compile(r'^\s*ANS:\s*(?P<ans>[A-L])\s*$', re.IGNORECASE)
RE_EXP = re.compile(r'^\s*EXP:\s*(?P<exp>.+?)\s*$', re.IGNORECASE)

def extract_title_from_formatted(text: str) -> Optional[str]:
    """
    Return the title found after the first DES: line.
    Prefer the DES ... COMPLETED line if present.
    """
    # Search for DES ... COMPLETED first (very end)
    for line in text.splitlines():
        m = RE_DES.match(line)
        if m:
            return m.group('title').strip()
    return None


def _normalize_option_text(raw: str) -> str:
    """
    Remove any leading '(A)', 'A)', 'A: (A)' style fragments from option text.
    Return cleaned text.
    """
    s = raw.strip()
    # remove leading parentheses like "(A) " or "(A)" if present
    s = re.sub(r'^\(\s*[A-L]\s*\)\s*', '', s, flags=re.IGNORECASE)
    # remove leading letter + dot/colon/paren like "A) " or "A: "
    s = re.sub(r'^[A-L]\s*[:\-\.\)]\s*', '', s, flags=re.IGNORECASE)
    return s.strip()


def validate_and_parse(text: str) -> Tuple[bool, object]:
    """
    Validate the formatted quiz text and parse into structured questions.

    Returns:
      (True, questions_list) on success
      (False, "error message") on failure
    """
    lines = [ln.rstrip() for ln in text.splitlines()]
    if not lines:
        return False, "Empty message."

    # Find DES title (first DES:)
    title = None
    for i, ln in enumerate(lines):
        m = RE_DES.match(ln)
        if m:
            title = m.group('title').strip()
            start_idx = i + 1
            break
    if not title:
        return False, "Missing DES: <title> header at the top."

    # Check for COMPLETED line at the end (optional but recommended)
    # We'll allow missing COMPLETED but warn. If present, ensure it matches title.
    has_completed = False
    for ln in reversed(lines):
        m2 = RE_DES_COMPLETED.match(ln)
        if m2:
            comp_title = m2.group('title').strip()
            if comp_title != title:
                return False, "DES COMPLETED title does not match initial DES title."
            has_completed = True
            break

    # Parse body lines after first DES
    cursor = start_idx
    total_lines = len(lines)
    questions: List[Dict] = []
    current_q: Optional[Dict] = None
    expecting = "Q_or_END"  # states: Q_or_END, OPTIONS, ANS_or_EXP

    # Helper to finalize current question
    def _finalize_current():
        nonlocal current_q
        if not current_q:
            return None
        # check q text
        qtext = current_q.get("q", "").strip()
        opts = current_q.get("options", {})
        ans = current_q.get("ans")
        exp = current_q.get("exp")
        if not qtext:
            return "A question has empty text."
        if len(opts) < 2:
            return f"Question '{qtext[:30]}...' must have at least two options."
        if not ans:
            return f"Missing ANS for question: '{qtext[:40]}...'"
        # Ans must be one of option labels
        if ans.upper() not in opts:
            return f"ANS '{ans}' not present in options for question: '{qtext[:40]}...'"
        # Build ordered options list based on labels sorted A..L
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

    while cursor < total_lines:
        ln = lines[cursor].strip()
        cursor += 1
        if ln == "":
            # blank lines are allowed between blocks
            continue

        # If line starts a new question
        m_q = RE_Q.match(ln)
        if m_q:
            # finalize previous question if any
            if current_q:
                err = _finalize_current()
                if err:
                    return False, err
            current_q = {"q": m_q.group("q").strip(), "options": {}, "ans": None, "exp": None}
            expecting = "OPTIONS"
            continue

        # Option line?
        m_opt = RE_OPTION.match(ln)
        if m_opt and current_q is not None:
            label = m_opt.group("label").upper()
            rest = m_opt.group("rest").strip()
            # rest might itself start with "(A) " etc; normalize
            clean = _normalize_option_text(rest)
            if not clean:
                return False, f"Option {label} has empty text in question: '{current_q.get('q','')[:40]}...'"
            # ensure no duplicate labels
            if label in current_q["options"]:
                return False, f"Duplicate option label '{label}' in question: '{current_q.get('q','')[:40]}...'"
            current_q["options"][label] = clean
            continue

        # ANS line?
        m_ans = RE_ANS.match(ln)
        if m_ans and current_q is not None:
            ans_letter = m_ans.group("ans").upper()
            current_q["ans"] = ans_letter
            expecting = "Q_or_END"  # after ans, next expected is next Q or end
            continue

        # EXP line?
        m_exp = RE_EXP.match(ln)
        if m_exp and current_q is not None:
            current_q["exp"] = m_exp.group("exp").strip()
            # EXP may appear before or after ANS; keep expecting Q_or_END
            expecting = "Q_or_END"
            continue

        # Unknown line: could be final DES COMPLETED or footer Eg(...)
        # If it's DES: ... COMPLETED, we can break
        if RE_DES_COMPLETED.match(ln):
            # finalize last question and break
            if current_q:
                err = _finalize_current()
                if err:
                    return False, err
            has_completed = True
            break

        # If line looks like an "Eg(" footer or email or score, wrap as Eg(...) — we do not require parsing it here
        if ln.startswith("Eg(") or ln.lower().startswith("the respondent") or ln.lower().startswith("total points"):
            # ignore meta lines
            continue

        # If reached here and we have a current question but line doesn't match any pattern,
        # it is probably malformed.
        if current_q:
            return False, f"Unrecognized line inside question '{current_q.get('q','')[:30]}': {ln}"
        else:
            # not inside a question and unrecognized line
            # allow some footer lines but otherwise error
            return False, f"Unexpected line outside questions: {ln}"

    # End of lines — finalize last question if any
    if current_q:
        err = _finalize_current()
        if err:
            return False, err

    if not questions:
        return False, "No questions parsed. Ensure you have at least one 'Q:' block."

    # Verify ANS letters map to available option counts: e.g., if only A-D present, ANS should be A-D
    for qi, q in enumerate(questions, start=1):
        opts_len = len(q["options"])
        max_label = chr(ord("A") + opts_len - 1)
        if not ( "A" <= q["ans"] <= max_label ):
            return False, f"Question {qi}: ANS '{q['ans']}' invalid for {opts_len} options."

    # If completed not present, it's okay — but suggest adding it (not an error)
    # Return parsed questions
    return True, questions
