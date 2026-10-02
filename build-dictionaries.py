#!/usr/bin/env python3
# Copyright (c) 2026 Jolla Mobile Ltd.
"""Build keypad dictionaries from the tt9 submodule.

Each language definition becomes <locale>.layout and <locale>.sqlite. The
keyboard reads those pairs from /usr/share/tt9 and offers only the ones that
are installed. Alphabetic layouts only: a word is kept when every character
belongs to one key.

  python3 build-dictionaries.py --output out
  python3 build-dictionaries.py --only en --output /tmp/tt9-en
"""

import argparse
import re
import shutil
import sqlite3
import sys
from pathlib import Path


HERE = Path(__file__).resolve().parent
DEFINITIONS = HERE / "tt9" / "app" / "languages" / "definitions"
DICTIONARIES = HERE / "tt9" / "app" / "languages" / "dictionaries"
READMES = HERE / "tt9" / "docs" / "dictionaries"

# A package build must produce these even when the list grows.
REQUIRED_LOCALES = ("en", "fi-FI")

# Word-list readmes are not named after the locale. None means upstream
# shipped the dictionary without a notice.
README_ALIASES = {
    "be-narmawka": "benarmawka",
    "da": None,
    "gr": None,
    "ja-romaji": "ja",
    "ph": "fil",
    "pt-BR": "pt",
    "pt-PT": "pt",
    "srl": "sr",
    "tamazight": "zgh",
    "tamazight-latin": "zgh",
    "zh-bopomofo": "bopomofo",
    "zh-simplified-pinyin": "pinyin",
    "zh-traditional-pinyin": "pinyin",
}

# The same groups Traditional T9 substitutes for the placeholders in a layout.
SPECIAL = list("@_#%[]{}§|^<>\\/=*+")
PUNCTUATION = {
    "PUNCTUATION": list(',.-()&~`;:\'"!?' ),
    "PUNCTUATION_AR": list("،.-()&~`'\"\u061b:!؟"),
    "PUNCTUATION_BP": list("，、。1—～゠（）.「」『』•《》〈〉'“”；：！？"),
    "PUNCTUATION_ZH": list("，、。—～゠（）.「」『』•《》〈〉'“”；：！？"),
    "PUNCTUATION_FA": list("،.-\u200c()&~`'\"\u061b:!؟"),
    "PUNCTUATION_FR": list(',.-«»()&`~;:\'"!?' ),
    "PUNCTUATION_DE": list(',.-„“()&~`\'";:!?' ),
    "PUNCTUATION_GR": list(',.-«»()&~`\'"·:!;'),
    "PUNCTUATION_IE": list(',.-()&⁊~`;:\'"!?' ),
    "PUNCTUATION_IN": list(",.-()\u200d\u200c।॰॥&~`;:'\"!?"),
    "PUNCTUATION_KR": list(",.~1()&-`;:'\"!?"),
}


def expand_token(token):
    if token == "SPECIAL":
        # Space and newline stay first, as on the printed 0 key.
        return [" ", "\n"] + SPECIAL
    if token in PUNCTUATION:
        return PUNCTUATION[token]
    return list(token)


def parse_definition(path):
    locale = ""
    dictionary = ""
    keys = {}
    order = 0
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].strip()
        if line.startswith("locale:"):
            locale = line.split(":", 1)[1].strip()
        elif line.startswith("dictionaryFile:"):
            dictionary = line.split(":", 1)[1].strip()
        elif line.startswith("- ["):
            comment = raw.split("#", 1)[1].strip() if "#" in raw else ""
            try:
                index = int(comment.split()[0])
            except (ValueError, IndexError):
                index = order
            order += 1
            body = line[line.find("[") + 1 : line.rfind("]")]
            chars = []
            for token in body.split(","):
                token = token.strip()
                if token:
                    chars.extend(expand_token(token))
            if 0 <= index <= 9 and chars:
                keys[str(index)] = "".join(chars)
    return locale, dictionary, keys


def load_mapping(keys):
    mapping = {}
    for digit, chars in keys.items():
        for char in chars:
            mapping[char.lower()] = digit
    return mapping


def digit_sequence(word, mapping):
    sequence = []
    for char in word.lower():
        digit = mapping.get(char)
        if digit is None:
            return None
        sequence.append(digit)
    return "".join(sequence) if sequence else None


def collect_words(csv_path, mapping):
    best = {}
    skipped = 0
    with csv_path.open(encoding="utf-8") as handle:
        for line in handle:
            parts = line.rstrip("\n").split("\t")
            if not parts or not parts[0]:
                continue
            word = parts[0]
            frequency = 0
            if len(parts) > 1:
                try:
                    frequency = int(parts[-1])
                except ValueError:
                    frequency = 0
            if frequency < 0:
                frequency = 0
            sequence = digit_sequence(word, mapping)
            if sequence is None:
                skipped += 1
                continue
            key = (sequence, word)
            previous = best.get(key)
            if previous is None or frequency > previous:
                best[key] = frequency
    return best, skipped


def escape_layout(chars):
    # One line per key. Newline and backslash are written escaped and undone
    # by T9Dictionary when it reads the file.
    return chars.replace("\\", "\\\\").replace("\n", "\\n")


def write_layout(path, keys):
    lines = ["# Generated from Traditional T9. digit=characters.", ""]
    for digit in "0123456789":
        if digit in keys:
            lines.append("%s=%s" % (digit, escape_layout(keys[digit])))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_database(path, words):
    if path.exists():
        path.unlink()
    connection = sqlite3.connect(str(path))
    try:
        connection.execute("PRAGMA journal_mode = OFF")
        connection.execute("PRAGMA synchronous = OFF")
        connection.execute(
            "CREATE TABLE words ("
            "sequence TEXT NOT NULL, "
            "word TEXT NOT NULL, "
            "frequency INTEGER NOT NULL)"
        )
        connection.executemany(
            "INSERT INTO words(sequence, word, frequency) VALUES (?, ?, ?)",
            ((sequence, word, frequency) for (sequence, word), frequency in words.items()),
        )
        connection.execute("CREATE INDEX idx_words_sequence ON words(sequence)")
        connection.commit()
        connection.execute("VACUUM")
    finally:
        connection.close()


def dictionary_key(dictionary_name):
    stem = Path(dictionary_name).stem
    if stem.endswith("-utf8"):
        stem = stem[: -len("-utf8")]
    return stem


def find_readme(dictionary_name):
    key = dictionary_key(dictionary_name)
    if key in README_ALIASES:
        key = README_ALIASES[key]
        if key is None:
            return None
    else:
        key = key.lower()
    if not READMES.is_dir():
        return None
    for path in READMES.iterdir():
        if not path.is_file():
            continue
        base = path.name
        cut = base.lower().find("wordlistreadme.txt")
        if cut <= 0:
            continue
        if base[:cut].lower() == key:
            return path
    return None


_LICENSE_HEADING = re.compile(
    r"^(COPYRIGHT\b|GNU GENERAL PUBLIC LICENSE|Apache License|MIT License|"
    r"Permission is hereby granted|THE SOFTWARE IS PROVIDED)",
    re.M,
)
_LICENSE_HINT = re.compile(
    r"licen[cs]e|copyright|public domain|creative commons|"
    r"\bGPL\b|\bLGPL\b|\bMIT\b|\bMPL\b|\bBSD\b|\bApache\b",
    re.I,
)


def extract_license(text):
    # A readme that carries the license itself: keep that text, not the word-list essay.
    heading = _LICENSE_HEADING.search(text)
    if heading and heading.start() > 0:
        return text[heading.start():].strip() + "\n"
    paragraphs = re.split(r"\n\s*\n", text.strip())
    chosen = [paragraph for paragraph in paragraphs if _LICENSE_HINT.search(paragraph)]
    if chosen:
        return "\n\n".join(chosen).strip() + "\n"
    return text.strip() + "\n"


def write_notice(notices, locale, dictionary):
    readme = find_readme(dictionary)
    if readme is None:
        print("notice %s: no word-list readme for %s" % (locale, dictionary), file=sys.stderr)
        return None
    text = readme.read_text(encoding="utf-8", errors="replace")
    doc = notices / ("%s.txt" % locale)
    license_path = notices / ("%s.license" % locale)
    doc.write_text(text if text.endswith("\n") else text + "\n", encoding="utf-8")
    license_path.write_text(extract_license(text), encoding="utf-8")
    return doc.name, license_path.name


def build_one(definition, output):
    locale, dictionary, keys = parse_definition(definition)
    if not locale or not dictionary or "2" not in keys:
        print("skip %s: no locale, dictionary, or letter keys" % definition.name, file=sys.stderr)
        return False
    csv_path = DICTIONARIES / dictionary
    if not csv_path.is_file():
        print("skip %s: missing %s" % (locale, csv_path), file=sys.stderr)
        return False
    mapping = load_mapping(keys)
    words, skipped = collect_words(csv_path, mapping)
    if not words:
        print("skip %s: no words mapped" % locale, file=sys.stderr)
        return False
    write_layout(output / ("%s.layout" % locale), keys)
    write_database(output / ("%s.sqlite" % locale), words)
    print("%s: %d words, %d skipped" % (locale, len(words), skipped))
    return True


def reset_dir(path):
    # A previous run may have written languages that are no longer requested.
    # %install copies this directory as-is, so those leftovers would ship.
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True)


def read_locale_list(path):
    locales = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].strip()
        if line:
            locales.append(line)
    return locales


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--only", action="append", default=[], help="locale to build; repeatable")
    parser.add_argument("--from-list", type=Path, help="locales to build, one per line")
    parser.add_argument("--notices", type=Path, help="where to write per-language doc and license files")
    args = parser.parse_args()
    reset_dir(args.output)
    listed = read_locale_list(args.from_list) if args.from_list else []
    if args.from_list:
        missing = [locale for locale in REQUIRED_LOCALES if locale not in listed]
        if missing:
            raise SystemExit("language list must include %s" % ", ".join(missing))
    wanted = set(args.only) | set(listed)
    if args.notices:
        reset_dir(args.notices)
    built = []
    notice_lines = []
    for definition in sorted(DEFINITIONS.glob("*.yml")):
        locale, dictionary, _keys = parse_definition(definition)
        if wanted and locale not in wanted:
            continue
        if not build_one(definition, args.output):
            continue
        built.append(locale)
        if args.notices and dictionary:
            written = write_notice(args.notices, locale, dictionary)
            if written:
                # %% so the percent signs survive the format operation.
                # Both the full notice and the license text are %%license, so other
                # packages can read them from the license directory.
                notice_lines.append("%%license %s" % (args.notices / written[0]))
                notice_lines.append("%%license %s" % (args.notices / written[1]))
    if not built:
        raise SystemExit("no languages built")
    if args.from_list:
        missing = [locale for locale in REQUIRED_LOCALES if locale not in built]
        if missing:
            raise SystemExit("required languages were not built: %s" % ", ".join(missing))
    if args.notices:
        (args.notices / "files.list").write_text("\n".join(notice_lines) + "\n", encoding="utf-8")
    print("built %d languages into %s" % (len(built), args.output))


if __name__ == "__main__":
    main()
