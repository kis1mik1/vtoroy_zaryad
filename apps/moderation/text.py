import re

LATIN_LOOKALIKES = str.maketrans(
    {
        "a": "а",
        "b": "в",
        "c": "с",
        "e": "е",
        "h": "н",
        "k": "к",
        "m": "м",
        "o": "о",
        "p": "р",
        "t": "т",
        "x": "х",
        "y": "у",
        "u": "и",
    }
)
CYRILLIC = re.compile(r"[а-я]")
WORD = re.compile(r"[a-zа-я0-9]+")
SPACED_LETTERS = re.compile(r"(?<![а-я])(?:[а-я][ .\-_*]){3,}[а-я](?![а-я])")
SPACES = re.compile(r"\s+")


def _fix_mixed_script(match: re.Match) -> str:
    word = match.group(0)
    if CYRILLIC.search(word) and re.search(r"[a-z]", word):
        return word.translate(LATIN_LOOKALIKES)
    return word


def normalize(text: str) -> str:
    text = text.lower().replace("ё", "е")
    text = WORD.sub(_fix_mixed_script, text)
    text = SPACED_LETTERS.sub(lambda m: re.sub(r"[ .\-_*]", "", m.group(0)), text)
    return SPACES.sub(" ", text).strip()


def ad_text(title: str, description: str) -> str:
    return normalize(f"{title}\n{description}")
