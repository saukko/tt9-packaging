#!/usr/bin/env python3
# Copyright (c) 2026 Jolla Mobile Ltd.
"""Build keypad layouts, and word lists for selected languages.

Every requested definition becomes <locale>.layout. A <locale>.sqlite word
list is written only for locales named with --dictionaries. The keyboard
uses a layout on its own. Prediction needs the sqlite file.

  python3 build-dictionaries.py --output out --from-list languages.list \\
      --dictionaries dictionaries.list
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


def parse_list_body(line):
    body = line[line.find("[") + 1 : line.rfind("]")]
    return [token.strip() for token in body.split(",") if token.strip()]


def parse_definition(path):
    locale = ""
    dictionary = ""
    keys = {}
    sounds = {}
    section = ""
    order = 0
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        if line.startswith("locale:"):
            locale = line.split(":", 1)[1].strip()
            section = ""
        elif line.startswith("dictionaryFile:"):
            dictionary = line.split(":", 1)[1].strip()
            section = ""
        elif line.startswith("layout:"):
            section = "layout"
            order = 0
        elif line.startswith("sounds:"):
            section = "sounds"
        elif line.endswith(":") and not line.startswith("-"):
            section = ""
        elif section == "layout" and line.startswith("- ["):
            comment = raw.split("#", 1)[1].strip() if "#" in raw else ""
            try:
                index = int(comment.split()[0])
            except (ValueError, IndexError):
                index = order
            order += 1
            chars = []
            for token in parse_list_body(line):
                chars.extend(expand_token(token))
            if 0 <= index <= 9 and chars:
                keys[str(index)] = "".join(chars)
        elif section == "sounds" and line.startswith("- ["):
            # [sound, digits]. The longer sound has to win later, so "Ng" is
            # not read as "N" plus a leftover.
            parts = parse_list_body(line)
            if len(parts) >= 2:
                sounds[parts[0]] = parts[1]
    return locale, dictionary, keys, sounds


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


def sound_sequence(transcription, sounds, ordered):
    position = 0
    digits = []
    while position < len(transcription):
        matched = None
        for sound in ordered:
            if transcription.startswith(sound, position):
                matched = sound
                break
        if matched is None:
            return None
        digits.append(sounds[matched])
        position += len(matched)
    return "".join(digits) if digits else None


def parse_frequency(text):
    try:
        frequency = int(text)
    except ValueError:
        return 0
    return frequency if frequency >= 0 else 0


def collect_words(csv_path, mapping, sounds):
    # Longest phonetic name first, so "Yu" is not consumed as "Y".
    ordered = sorted(sounds, key=len, reverse=True)
    best = {}
    skipped = 0
    with csv_path.open(encoding="utf-8") as handle:
        for line in handle:
            parts = line.rstrip("\n").split("\t")
            if not parts or not parts[0]:
                continue
            word = parts[0]
            if sounds:
                # word, phonetic, optional frequency. The letters of the word
                # itself are not on the digit keys.
                if len(parts) < 2 or not parts[1]:
                    skipped += 1
                    continue
                frequency = parse_frequency(parts[2]) if len(parts) > 2 else 0
                sequence = sound_sequence(parts[1], sounds, ordered)
            else:
                frequency = parse_frequency(parts[-1]) if len(parts) > 1 else 0
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


def build_layout(definition, output):
    locale, dictionary, keys, sounds = parse_definition(definition)
    if not locale or "2" not in keys:
        print("skip %s: no locale or letter keys" % definition.name, file=sys.stderr)
        return None
    write_layout(output / ("%s.layout" % locale), keys)
    return locale, dictionary, keys, sounds


def build_word_list(locale, dictionary, keys, sounds, output):
    if not dictionary:
        print("skip %s dictionary: no dictionary file" % locale, file=sys.stderr)
        return False
    csv_path = DICTIONARIES / dictionary
    if not csv_path.is_file():
        print("skip %s dictionary: missing %s" % (locale, csv_path), file=sys.stderr)
        return False
    words, skipped = collect_words(csv_path, load_mapping(keys), sounds)
    if not words:
        print("skip %s dictionary: no words mapped" % locale, file=sys.stderr)
        return False
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
    parser.add_argument("--only", action="append", default=[], help="layout locale to build; repeatable")
    parser.add_argument("--from-list", type=Path, help="layout locales to build, one per line")
    parser.add_argument("--dictionaries", type=Path, help="locales that also get a word list, one per line")
    parser.add_argument("--notices", type=Path, help="where to write per-language doc and license files")
    args = parser.parse_args()
    reset_dir(args.output)
    listed = read_locale_list(args.from_list) if args.from_list else []
    if args.from_list:
        missing = [locale for locale in REQUIRED_LOCALES if locale not in listed]
        if missing:
            raise SystemExit("language list must include %s" % ", ".join(missing))
    wanted = set(args.only) | set(listed)
    dictionaries = set(read_locale_list(args.dictionaries)) if args.dictionaries else set()
    if args.dictionaries:
        missing = [locale for locale in REQUIRED_LOCALES if locale not in dictionaries]
        if missing:
            raise SystemExit("dictionary list must include %s" % ", ".join(missing))
        outside = sorted(dictionaries - wanted) if wanted else []
        if outside:
            raise SystemExit("dictionary locales missing from the layout list: %s" % ", ".join(outside))
    if args.notices:
        reset_dir(args.notices)
    built = []
    built_dictionaries = []
    notice_lines = []
    for definition in sorted(DEFINITIONS.glob("*.yml")):
        locale, _dictionary, _keys, _sounds = parse_definition(definition)
        if wanted and locale not in wanted:
            continue
        prepared = build_layout(definition, args.output)
        if prepared is None:
            continue
        locale, dictionary, keys, sounds = prepared
        built.append(locale)
        if locale not in dictionaries:
            print("%s: layout" % locale)
            continue
        if not build_word_list(locale, dictionary, keys, sounds, args.output):
            continue
        built_dictionaries.append(locale)
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
        missing = [locale for locale in listed if locale not in built]
        if missing:
            raise SystemExit("layouts were not built: %s" % ", ".join(missing))
    if args.dictionaries:
        missing = [locale for locale in dictionaries if locale not in built_dictionaries]
        if missing:
            raise SystemExit("dictionaries were not built: %s" % ", ".join(missing))
    if args.notices:
        (args.notices / "files.list").write_text("\n".join(notice_lines) + "\n", encoding="utf-8")
    print("built %d layouts and %d dictionaries into %s" % (len(built), len(built_dictionaries), args.output))


if __name__ == "__main__":
    main()
