from __future__ import annotations

import re
from dataclasses import dataclass

_TOKEN = re.compile(r"[A-Za-z][A-Za-z0-9']*|\d+(?:\.\d+)?")
_NUMBER = re.compile(
    r"(?<![A-Za-z0-9_.])(\d+(?:\.\d+)?)\s*"
    r"(thousand|million|billion|trillion|tb|gb|mb|kb|ms|us|ns|x|×|k|m|b|t|%)?"
    r"(?![A-Za-z0-9_])",
    re.IGNORECASE,
)
_SCALES = {
    "k": "thousand",
    "thousand": "thousand",
    "m": "million",
    "million": "million",
    "b": "billion",
    "billion": "billion",
    "t": "trillion",
    "trillion": "trillion",
    "%": "percent",
    "tb": "tb",
    "gb": "gb",
    "mb": "mb",
    "kb": "kb",
    "ms": "ms",
    "us": "us",
    "ns": "ns",
    "x": "x",
    "×": "x",
}
# Standalone one/two are omitted because claims often use them as pronouns.
_WORD_UNITS = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
}
_WORD_TEENS = {
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
    "thirteen": 13,
    "fourteen": 14,
    "fifteen": 15,
    "sixteen": 16,
    "seventeen": 17,
    "eighteen": 18,
    "nineteen": 19,
}
_WORD_TENS = {
    "twenty": 20,
    "thirty": 30,
    "forty": 40,
    "fifty": 50,
    "sixty": 60,
    "seventy": 70,
    "eighty": 80,
    "ninety": 90,
}
_WORD_NUMBER = re.compile(
    r"(?<![A-Za-z0-9_])("
    r"zero|three|four|five|six|seven|eight|nine|"
    r"ten|eleven|twelve|thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|"
    r"(?:twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety)"
    r"(?:[-\s](?:one|two|three|four|five|six|seven|eight|nine))?"
    r")(?![A-Za-z])",
    re.IGNORECASE,
)


def _word_number_value(match: re.Match[str]) -> str:
    word = match.group(1).lower()
    if word == "zero":
        return "0"
    if word in _WORD_TEENS:
        return str(_WORD_TEENS[word])
    if word in _WORD_UNITS:
        return str(_WORD_UNITS[word])
    parts = re.split(r"[-\s]", word, maxsplit=1)
    if len(parts) == 2:
        return str(_WORD_TENS[parts[0]] + _WORD_UNITS[parts[1]])
    return str(_WORD_TENS[word])
_STOPWORDS = frozenset(
    ["a", "about", "after", "again", "against", "all", "am", "an", "and", "any", "are", "as", "at", "be", "because", "been", "before", "being", "below", "between", "both", "but", "by", "can", "could", "did", "do", "does", "doing", "down", "during", "each", "few", "for", "from", "further", "had", "has", "have", "having", "he", "her", "here", "hers", "herself", "him", "himself", "his", "how", "i", "if", "in", "into", "is", "it", "its", "itself", "just", "me", "more", "most", "my", "myself", "no", "nor", "not", "now", "of", "off", "on", "once", "only", "or", "other", "our", "ours", "ourselves", "out", "over", "own", "same", "she", "should", "so", "some", "such", "than", "that", "the", "their", "theirs", "them", "themselves", "then", "there", "these", "they", "this", "those", "through", "to", "too", "under", "until", "up", "very", "was", "we", "were", "what", "when", "where", "which", "while", "who", "whom", "why", "will", "with", "would", "you", "your", "yours", "yourself", "yourselves", "via", "per", "e", "g", "eg", "ie", "etc"]
)
MAX_KEYWORDS = 12


@dataclass(frozen=True)
class NumberMention:
    value: float
    scale: str
    raw: str

    @property
    def key(self) -> tuple[float, str]:
        return (round(self.value, 6), self.scale)


def tokens(text: str) -> list[str]:
    return [token.lower() for token in _TOKEN.findall(text)]


def extract_keywords(text: str, limit: int = MAX_KEYWORDS) -> tuple[str, ...]:
    keywords: list[str] = []
    for token in tokens(text):
        token = token.removesuffix("'s")
        if len(token) < 3 and not token.isdigit():
            continue
        if token in _STOPWORDS:
            continue
        if token not in keywords:
            keywords.append(token)
        if len(keywords) >= limit:
            break
    return tuple(keywords)


def extract_numbers(text: str) -> tuple[NumberMention, ...]:
    mentions: list[NumberMention] = []
    normalized = _WORD_NUMBER.sub(_word_number_value, text)
    for match in _NUMBER.finditer(normalized):
        raw_number, raw_scale = match.group(1), (match.group(2) or "").lower()
        try:
            value = float(raw_number)
        except ValueError:
            continue
        scale = _SCALES.get(raw_scale, "none")
        mention = NumberMention(value=value, scale=scale, raw=match.group(0).strip())
        if mention not in mentions:
            mentions.append(mention)
    return tuple(mentions)


def keyword_coverage(keywords: tuple[str, ...] | list[str], text: str) -> float:
    if not keywords:
        return 0.0
    haystack = text.lower()
    present = sum(1 for keyword in keywords if keyword in haystack)
    return present / len(keywords)


def number_status(
    claim_numbers: tuple[NumberMention, ...] | list[NumberMention],
    evidence_text: str,
) -> str:
    if not claim_numbers:
        return "none"
    evidence_numbers = extract_numbers(evidence_text)
    if not evidence_numbers:
        return "missing"
    evidence_keys = {mention.key for mention in evidence_numbers}
    if any(mention.key in evidence_keys for mention in claim_numbers):
        return "match"
    claim_scales = {mention.scale for mention in claim_numbers if mention.scale != "none"}
    evidence_scales = {mention.scale for mention in evidence_numbers if mention.scale != "none"}
    if claim_scales & evidence_scales:
        return "conflict"
    return "missing"
