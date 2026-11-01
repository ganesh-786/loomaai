"""A small, realistic slice of Looma's data for tests, including the real data quirks the pipeline must handle:
a grade stored as text and as a decimal, a BOM-prefixed key, a string ch_id, a CEHRD-only file, an excluded quiz,
an out-of-scope grade-7 item, a base64 image inside a lesson, and a Nepali-only title."""

from __future__ import annotations

import copy

CH_5S01, CH_6S01, CH_6S0102, CH_6SS02, CH_7S01 = "5S01", "6S01", "6S01.02", "6SS02", "7S01"

A_CH_6S0102 = "a00000000000000000000001"
A_VID_UNITS = "a00000000000000000000002"
A_LESSON = "a00000000000000000000003"
A_GAME = "a00000000000000000000004"
A_PDF_TOOLS = "a00000000000000000000005"
A_HTML_CEHRD = "a00000000000000000000006"
A_IMG_FAMILY = "a00000000000000000000007"
A_QUIZ = "a00000000000000000000008"
A_VID_NEWTON = "a00000000000000000000009"
A_CH_7S01 = "a00000000000000000000010"
A_VID_PHOTO = "a00000000000000000000011"
A_CH_5S01 = "a00000000000000000000012"
A_IMG_NEPALI = "a00000000000000000000013"
LESSON_DOC = "b00000000000000000000001"
GAME_DOC = "c00000000000000000000001"

_DATA = {
    "chapters": [
        {"_id": CH_5S01, "dn": "Living things", "ndn": "सजीव", "pn": 3, "len": 10, "npn": 3, "nlen": 10},
        {"_id": CH_6S01, "dn": "Scientific Learning", "ndn": "वैज्ञानिक सिकाइ", "pn": 3, "len": 0, "npn": 7, "nlen": 0},
        {"_id": CH_6S0102, "dn": "Measurement and unit", "ndn": "नाप र एकाइ", "pn": 8, "len": 2, "npn": 12, "nlen": 2},
        {"_id": CH_6SS02, "dn": "Our community", "ndn": "हाम्रो समुदाय", "pn": 20, "len": 5, "npn": 22, "nlen": 5},
        {"_id": CH_7S01, "dn": "Force", "ndn": "बल", "pn": 1, "len": 9, "npn": 1, "nlen": 9},
    ],
    "textbooks": [
        {"_id": "t6s", "prefix": "6S", "dn": "Grade 6 Science", "fp": "textbooks/Class6/Science/",
         "fn": "Science_6_0036.pdf", "nfn": "Science_6_Nepali_9589.pdf"},
        {"_id": "t5s", "prefix": "5S", "dn": "Grade 5 Science", "fp": "textbooks/Class5/Science/",
         "fn": "Science_5_0035.pdf", "nfn": ""},
        {"_id": "t6ss", "prefix": "6SS", "dn": "Grade 6 Social Studies", "fp": "textbooks/Class6/SocialStudies/",
         "fn": "", "nfn": "Social_6_Nepali.pdf"},
    ],
    "activities": [
        {"_id": A_CH_6S0102, "ft": "chapter", "ID": CH_6S0102, "dn": "Measurement and unit", "ndn": "नाप र एकाइ",
         "key1": "Science", "key2": "Other Science"},
        {"_id": A_VID_UNITS, "ft": "video", "dn": "Converting units of measurement", "fn": "units.mp4",
         "fp": "../content/videos/", "captions": "../content/captions/units.srt", "ch_id": [CH_6S0102],
         "cl_lo": "6", "cl_hi": 7.0, "key1": "Science", "key2": "Physics", "src": "khan", "lang": "en"},
        {"_id": A_LESSON, "ft": "lesson", "dn": "6S Measuring length", "mongoID": LESSON_DOC, "ch_id": CH_6S0102},
        {"_id": A_GAME, "ft": "game", "dn": "Units game", "mongoID": GAME_DOC, "ch_id": [CH_6S0102]},
        {"_id": A_PDF_TOOLS, "ft": "pdf", "dn": "Measuring tools", "ndn": "नाप्ने साधनहरू", "fn": "tools.pdf",
         "\ufeffch_id": [CH_6SS02], "nch_id": [CH_6S0102], "key1": "Lamguage ", "lang": "english"},
        {"_id": A_HTML_CEHRD, "ft": "html", "dn": "Community helpers", "fp": "../content/CEHRD/html/",
         "fn": "community.html", "ch_id": [CH_6SS02], "src": "CEHRD", "key1": "Social Studies"},
        {"_id": A_IMG_FAMILY, "ft": "image", "dn": "Family tree", "fn": "family.jpg", "ch_id": [CH_6SS02],
         "key1": "Social Studies", "key2": "Community", "lang": "both"},
        {"_id": A_QUIZ, "ft": "quiz", "dn": "Units quiz", "ch_id": [CH_6S0102]},
        {"_id": A_VID_NEWTON, "ft": "video", "dn": "Newton's laws", "fn": "newton.mp4", "ch_id": [CH_7S01],
         "key1": "Science"},
        {"_id": A_CH_7S01, "ft": "chapter", "ID": CH_7S01, "dn": "Force", "ndn": "बल"},
        {"_id": A_VID_PHOTO, "ft": "video", "dn": "Photosynthesis", "fn": "photo.mp4", "ch_id": [CH_5S01],
         "cl_lo": 5, "cl_hi": 6, "key1": "Science", "key2": "Biology", "src": "khan"},
        {"_id": A_CH_5S01, "ft": "chapter", "ID": CH_5S01, "dn": "Living things", "ndn": "सजीव", "key1": "Science"},
        {"_id": A_IMG_NEPALI, "ft": "image", "ndn": "हाम्रो गाउँ", "fn": "village.jpg", "ch_id": [CH_6SS02],
         "key1": "Social Studies", "lang": "np"},
    ],
    "lessons": [
        {"_id": LESSON_DOC, "dn": "6S Measuring length", "data": [
            {"ft": "inline",
             "html": "<p>Length is measured in metres. A ruler measures short lengths.</p>"
                     "<img src=\"data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAA=\">",
             "nepali": "<p>लम्बाइ मिटरमा नापिन्छ। छोटो लम्बाइ रुलरले नापिन्छ।</p>"},
            {"collection": "activities", "id": A_VID_UNITS},
            {"ft": "inline", "html": "<div>Mass is measured in kilograms.</div>", "nepali": ""},
        ]},
    ],
    "games": [
        {"_id": GAME_DOC, "title": "Units game", "ft": "game", "prompts": ["metre", "litre"],
         "responses": ["unit of length", "unit of volume"], "cl_lo": 6, "cl_hi": 6, "subject": ["science"]},
    ],
    "dictionary": [
        {"_id": "d1", "en": "measurement", "np": "नाप"},
        {"_id": "d2", "en": "unit", "np": "एकाइ"},
        {"_id": "d3", "en": "photosynthesis", "np": "प्रकाश संश्लेषण"},
        {"_id": "d4", "en": "", "np": "खाली"},
    ],
}


def looma_data() -> dict[str, list[dict]]:
    """A fresh deep copy, so a test can change it without affecting others."""
    return copy.deepcopy(_DATA)
