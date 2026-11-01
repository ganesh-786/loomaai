"""Source files stay readable: no invisible characters (zero-width spaces, BOMs, no-break spaces).

Invisible characters inside string literals look identical to normal ones in review; write them as escapes instead.
"""

from pathlib import Path

INVISIBLE = {0xFEFF, 0x200B, 0x200C, 0x200D, 0x2060, 0x00A0, 0x202F, 0x205F, 0x3000, *range(0x2000, 0x200B),
             0x0900}  # U+0900 is a combining sign; in code it only appears as a regex range start, write \u0900
ROOT = Path(__file__).resolve().parents[1]


def test_no_invisible_characters_in_python_sources():
    offenders = []
    for path in sorted(ROOT.rglob("*.py")):
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            hidden = sorted({f"U+{ord(c):04X}" for c in line if ord(c) in INVISIBLE})
            if hidden:
                offenders.append(f"{path.relative_to(ROOT)}:{number} {hidden}")
    assert offenders == [], "write these as \\u escapes: " + "; ".join(offenders)
