from dataclasses import replace

import looma_fixture as fx
import pdf_fixtures as pf
import pytest

from looma_pipeline.extractors.captions import group_cues, parse_cues
from looma_pipeline.extractors.database import game_pieces, is_credits_slide, lesson_pieces, title_pieces
from looma_pipeline.extractors.html import read_html
from looma_pipeline.extractors.ocr import TesseractOcr
from looma_pipeline.extractors.pdf import PdfPage, extract_pages, remove_repeated_lines
from looma_pipeline.text.script import devanagari_share

needs_tesseract = pytest.mark.skipif(not TesseractOcr.available(), reason="tesseract not installed")


def _activity(item_id):
    return next(a for a in fx.looma_data()["activities"] if a["_id"] == item_id)


def test_title_pieces_carry_taxonomy_and_nepali_title():
    pieces = title_pieces(_activity(fx.A_PDF_TOOLS))
    assert pieces[0].text.startswith("Measuring tools (Lamguage")
    assert pieces[1].text == "नाप्ने साधनहरू" and pieces[1].expect_nepali


def test_lesson_slides_lose_base64_images_and_keep_both_languages():
    lesson = fx.looma_data()["lessons"][0]
    pieces = lesson_pieces("item", lesson)
    assert [p.order for p in pieces] == [0, 0, 2]  # slide 1 is only a reference to another activity
    assert "base64" not in pieces[0].text and "metres" in pieces[0].text
    assert pieces[1].expect_nepali and "मिटर" in pieces[1].text
    assert pieces[2].text == "Mass is measured in kilograms."


# Wordings of real Lesson Credits slides, from a read-only survey of all 8,047 inline slides (2026-11-02).
# People's names are replaced by placeholders.
CREDITS_SLIDES = [
    "Lesson Credits\nAcknowledgements of who drafted and translated this lesson.\n"
    "Enter the first name(s) only, and the date completed.\nMade by: Asha Date:12 11 17\n"
    "Translated by: first name(s). Date: YYMMDD",
    "Lesson credits\nMade by: Asha Date: 241218\nTranslated by: No one Date:YYMMDD",
    "पाठ क्रेडिट\nबनाइएको: आशा मिति: 210308\nअनुवादित: पहिलो नाम(हरू) मिति: YYMMDD",
    "LP क्रेडिट\nआशा, बिना, र चन्द्र 03/05/2024",
    "एलपी क्रेडिट\nआशा र बिना 6/14/19",
    "Made By: Asha and Bina",
    "Lesson made by Asha\nEdited by Bina",
    "Made by Asha and Bina 6-25-19",
    "आशा द्वारा बनाइएको",
    "पाठ आशा द्वारा बनाइएको",
    "बनाइएको: आशा",
    "Credits\nEdited by Asha",
    "Credit\nMade by Asha 6/19/2019",
    "Credits\nAsha and Bina\nJuly 8, 2024\nW",
    "श्रेय\nआशा र बिना\nजुलाई ८, २०२४\nW",
    "श्रेय\nछोड्नुहोस्\nआशा द्वारा सम्पादन\n12/21/24",
    "क्रेडिट\nआशा द्वारा बनाइएको ६/१९/२०१९",
    "क्रेडिट\nनाम मिति\nआशा र बिना 6/19/19",
    # Headings after a lesson code or title line, split over two lines, or with other by-line words
    "6M17.01 Perimeter Credits\nAsha and Bina 6/12/2019",
    "6M17.01 परिमिति क्रेडिट\nआशा र बिना 6/12/2019",
    "6EN Field Trip: Credits\nMade by: Asha and Bina Date: 20/06/23\nTranslated by: firstname(s) Date: YYMMDD",
    "6EN The World Cup: Lesson Credits\nMade by: Asha, Bina & Chandra Date: 20/06/23",
    "4SS01.01 पाठ क्रेडिट\nबनाउने: आशा मिति 2020/07/11",
    "5SS02.01-02\nCredits\nNames Date\nAsha and Bina 6/18/19",
    "L\nLesson Credits\ne\nMade by Asha 6-26-19\nEdited by Bina",
    "3S Animals and Seasons\nCredit\nMade by Asha 7/15/19",
    "Lesson\nCredits\nMade by: Asha Date: 20/06/28\nTranslated by:",
    "<----+----+----+---->\nLesson Credits\nThis last page acknowledges those who drafted and translated\neach lesson\nplan.",
    "Final Song and Dance all over the World!\n\nCredits\nAuthor Unknown\nEdits Asha\n12/31/2024",
    "Credits\nCreated by Asha",
    "श्रेय\nआशा द्वारा सिर्जना गरिएको",
    "By: Asha, Bina, and Chandra 7/20/20\nTranslated by: --- ----",
]

# Lesson content that says "made by" or starts with a heading; it must stay searchable. The first four are real
# slides; the rest are edge cases the rule must not catch.
CONTENT_SLIDES = [
    "Final Song and Dance all over the World!\n\nWatch the next\njoyful\nvideo made by a man named Matt who\n"
    "travelled all over the world dancing with people.",
    "Farming Tools continued\nTo cut grass and tame animals, farmers need to use a:\nsickle\nrope\n"
    "--a length of strong cord made by twisting together\nsmaller strands of something--grass, plastic, or more.",
    "Class 4: Music, Musical Instruments video\nIn the next video, you will hear the sounds made by\n16 musical\n"
    "instruments:",
    "समीक्षा\nभिडियोमा बिरुवाको कुन भाग थियो?\nयो\nफूल\nथियो!",
    "Credit\nCredit is money that a bank lends and that must be paid back with interest.",
    "Made by hand: paper crafts of Nepal",
    "मानव द्वारा बनाइएको वातावरण",
    "Extra Credit\nTrue or False:\ncan you figure this out?\nIf the edges of a cube double in length, the volume increases\n"
    "by a factor of 8.",
    "शब्दावली\n\nघरमा बनाइएको:\nघरमा बनाइएका चीजहरू\n\nतयार गरिएको:\nघर बाहिर बनाइएका चीजहरू",
    "Buying on credit\nShops sell goods on credit. In 2020 many families bought rice this way.",
    "By: Laxmi Prasad Devkota\nA short poem about the moon and the hills.",
]


@pytest.mark.parametrize("text", CREDITS_SLIDES)
def test_credits_slides_are_recognised(text):
    assert is_credits_slide(text)


@pytest.mark.parametrize("text", CONTENT_SLIDES)
def test_lesson_content_is_not_mistaken_for_credits(text):
    assert not is_credits_slide(text)


def test_long_slides_are_never_credits():
    assert not is_credits_slide("Credits\nMade by Asha\n" + "word " * 60)


def test_lesson_credits_slides_are_not_indexed_in_either_language():
    lesson = {"data": [
        {"ft": "inline", "html": "<p>Mass is measured in kilograms.</p>", "nepali": "<p>पिण्ड किलोग्राममा नापिन्छ।</p>"},
        {"ft": "inline", "html": "<div>&nbsp;Lesson Credits&nbsp;</div><div>Made by: Asha Date: 210308</div>",
         "nepali": "<div>&nbsp;पाठ क्रेडिट&nbsp;</div><div>बनाइएको: आशा मिति: 210308</div>"},
    ]}
    pieces = lesson_pieces("item", lesson)
    assert [(p.order, p.text) for p in pieces] == [(0, "Mass is measured in kilograms."), (0, "पिण्ड किलोग्राममा नापिन्छ।")]


def test_game_prompts_are_paired_with_responses():
    [piece] = game_pieces("item", fx.looma_data()["games"][0])
    assert piece.text == "metre — unit of length\nlitre — unit of volume"


def test_multiple_choice_games_keep_question_and_correct_answer_only():
    game = {"presentation_type": "multiple choice", "prompts": [
        {"question": "Through what do insects breathe?", "correctAns": "Spiracles", "wrongAns": ["Gills", "Lungs"]},
        {"question": "Unanswered?"}, 7]}
    [piece] = game_pieces("item", game)
    assert piece.text == "Through what do insects breathe? — Spiracles\nUnanswered?"
    assert "Gills" not in piece.text


def test_srt_and_vtt_timestamps_including_hours():
    srt = "1\n00:00:01,000 --> 00:00:04,000\nHello <i>class</i>\n\n2\n01:02:03,500 --> 01:02:05,000\nLater\n"
    cues = parse_cues(srt)
    assert [(c.start, c.text) for c in cues] == [(1.0, "Hello class"), (3723.5, "Later")]
    vtt = ("WEBVTT\n\nNOTE made by a tool\n\n00:05.250 --> 00:07.000 align:start\n<c>Plants</c> need light\n"
           "Plants need light\n\n00:08.000 --> 00:09.000\nand water\n")
    assert [(c.start, c.text) for c in parse_cues(vtt)] == [(5.25, "Plants need light"), (8.0, "and water")]


def test_cues_are_grouped_into_blocks_with_the_first_start_time():
    cues = parse_cues("".join(f"00:00:{s:02d},000 --> 00:00:{s:02d},500\nword{s} " * 1 + "\n\n" for s in range(10)))
    blocks = group_cues(cues, max_chars=20)
    assert blocks[0].start == 0.0 and len(blocks) > 1
    assert " ".join(b.text for b in blocks).split() == [f"word{s}" for s in range(10)]


def test_html_keeps_title_and_body_without_navigation(tmp_path):
    page = tmp_path / "page.html"
    page.write_text("<html><head><title>Plants</title><script>x()</script></head>"
                    "<body><nav>Home</nav><h1>Plants</h1><p>Leaves make food.</p></body></html>")
    title, text = read_html(page)
    assert title == "Plants"
    assert "Leaves make food." in text and "Home" not in text and "x()" not in text


def test_pdf_pages_keep_numbers_and_lose_running_headers(tmp_path):
    topics = ["length", "mass", "time", "volume"]
    pages = [["Grade 6 Science", f"We study {topic} and measure-", f"ment of {topic} here.", str(n)]
             for n, topic in enumerate(topics, start=1)]
    path = pf.text_pdf(tmp_path / "book.pdf", pages)
    every_page = extract_pages(path)
    assert all("Grade 6 Science" not in p.text for p in every_page)  # running header removed
    assert all(not p.text.splitlines()[-1].strip().isdigit() for p in every_page)  # page numbers removed
    assert "measurement of mass here." in every_page[1].text  # hyphen break joined
    in_range = extract_pages(path, first_page=2, page_count=2)
    assert [p.number for p in in_range] == [2, 3]
    assert all(p.method == "text" for p in in_range)


# Bottom lines of Grade 10 Science pages 77-114 as read from the book's OCR text layer (checked 2026-11-26). The
# page-number badge and print marks come out as fragments glued to the footer, so no two copies are identical.
FOOTERS_SEEN_IN_10S = ["Science and Technology, Grade 10 cm", "cm Science and Technology, Grade 10",
                       "coe Science and Technology, Grade 10", "Science and Technology, Grade 10 &",
                       "oo Science and Technology, Grade 10", "Science and Technology, Grade 10 105",
                       "102 Science and Technology, Grade 10", "Science and Technology, Grade 10 —",
                       "“100 Science and Technology, Grade 10", "Science and Technology, Grade 10"]
TOPICS = ["chromosomes", "genes", "alleles", "traits", "zygotes", "gametes", "hybrids", "variation", "mutation",
          "dominance"]


def _book(footers: list[str]) -> list[PdfPage]:
    """One page per footer: three body lines that differ in their words, then the footer."""
    return [PdfPage(77 + i, f"Chapter text about {topic} starts here.\nStudents observe {topic} in the lab.\n"
                            f"Questions about {topic} follow.\n{footer}", "text")
            for i, (topic, footer) in enumerate(zip(TOPICS, footers))]


def test_ocr_fragments_glued_to_a_running_footer_do_not_hide_it():
    cleaned = remove_repeated_lines(_book(FOOTERS_SEEN_IN_10S))
    assert [p.text.count("Technology") for p in cleaned] == [0] * 10
    assert all(len(p.text.splitlines()) == 3 for p in cleaned)  # the three body lines stay


def test_an_ocr_misspelled_running_footer_at_the_page_edge_is_removed():
    # page 108 of the book reads "104 Sciénco:and Technology, Grade10"
    footers = ["Science and Technology, Grade 10"] * 9 + ["104 Sciénco:and Technology, Grade10"]
    cleaned = remove_repeated_lines(_book(footers))
    assert cleaned[-1].text.splitlines() == ["Chapter text about dominance starts here.",
                                             "Students observe dominance in the lab.",
                                             "Questions about dominance follow."]


def test_nepali_running_footer_with_ocr_fragments_is_removed():
    lines = ["कोषको केन्द्रकमा क्रोमोजोम हुन्छन्।", "जीनले आमाबुबाको गुण सन्तानमा सार्छ।",
             "मेन्डलले केराउको बिरुवामा प्रयोग गरे।", "डीएनए दोहोरो कुण्डली आकारको हुन्छ।",
             "लिङ्ग निर्धारण क्रोमोजोमले गर्छ।"]
    footers = ["विज्ञान तथा प्रविधि, कक्षा १० cm", "co विज्ञान तथा प्रविधि, कक्षा १०",
               "विज्ञान तथा प्रविधि, कक्षा १० ८७", "८८ विज्ञान तथा प्रविधि, कक्षा १०",
               "विज्ञान तथा प्रविधि, कक्षा १० &"]
    pages = [PdfPage(n + 1, f"{lines[n]}\n{lines[(n + 1) % 5]}\n{footers[n]}", "text") for n in range(5)]
    cleaned = remove_repeated_lines(pages)
    assert all("विज्ञान" not in p.text for p in cleaned)
    assert cleaned[0].text.splitlines() == [lines[0], lines[1]]


def test_pdf_with_noisy_running_footers_loses_them(tmp_path):
    footers = FOOTERS_SEEN_IN_10S[:6]  # the ASCII ones: the test PDF font has no curly quote or long dash
    path = pf.text_pdf(tmp_path / "book.pdf", [[f"Chapter text about {topic} starts here.",
                                                f"Students observe {topic} in the lab.", footer]
                                               for topic, footer in zip(TOPICS, footers)])
    pages = extract_pages(path)
    assert all("Technology" not in p.text and "Students observe" in p.text for p in pages)


def test_a_running_footer_followed_by_figure_labels_is_still_removed():
    pages = _book(["Science and Technology, Grade 10"] * 10)
    pages[3] = replace(pages[3], text=pages[3].text + '\n° 10 " 2\nXY XX')  # labels after the footer, as on page 87
    assert "Technology" not in remove_repeated_lines(pages)[3].text


def test_body_lines_that_mention_the_footer_words_are_kept():
    pages = _book(["Science and Technology, Grade 10 cm"] * 10)
    pages[0] = replace(pages[0], text="Science and technology help farmers grow more food.\n" + pages[0].text)
    assert remove_repeated_lines(pages)[0].text.startswith("Science and technology help farmers grow more food.")


def test_an_edge_heading_on_few_pages_is_kept():
    pages = _book(["Science and Technology, Grade 10"] * 10)
    for i in (2, 7):
        pages[i] = replace(pages[i], text="Exercise\n" + pages[i].text)
    cleaned = remove_repeated_lines(pages)
    assert cleaned[2].text.startswith("Exercise\n") and cleaned[7].text.startswith("Exercise\n")


def test_running_lines_without_long_words_still_match_exactly():
    pages = [replace(p, text=f"p. {p.number}\n{p.text}") for p in _book(["Science and Technology, Grade 10"] * 10)]
    assert all(not p.text.startswith("p.") for p in remove_repeated_lines(pages))


@needs_tesseract
def test_scanned_english_page_goes_through_ocr(tmp_path):
    path = pf.scanned_pdf(tmp_path / "scan.pdf", "<p>Photosynthesis makes food in green leaves.</p>")
    [page] = extract_pages(path, ocr=TesseractOcr("eng"))
    assert page.method == "ocr"
    assert "photosynthesis" in page.text.lower()


@needs_tesseract
def test_scanned_nepali_page_goes_through_ocr(tmp_path):
    path = pf.scanned_pdf(tmp_path / "scan-np.pdf", "<p>नेपाल सुन्दर देश हो। हिमाल अग्लो छ।</p>",
                          css=pf.DEVANAGARI_CSS, archive_dir=pf.DEVANAGARI_FONT_DIR)
    [page] = extract_pages(path, ocr=TesseractOcr("nep"), min_letters=5)
    assert page.method == "ocr"
    assert devanagari_share(page.text) > 0.9
    assert "नेपाल" in page.text


def test_without_ocr_a_scanned_page_is_reported_empty(tmp_path):
    path = pf.scanned_pdf(tmp_path / "scan.pdf", "<p>No text layer here.</p>")
    [page] = extract_pages(path, ocr=None)
    assert page.method == "empty" and page.text == ""


class _RecordingOcr:
    """Stands in for Tesseract: returns fixed text and records which 1-based pages it was asked to read."""

    def __init__(self):
        self.pages = []

    def page_text(self, page):
        self.pages.append(page.number + 1)
        return "Text that OCR read from the page image."


def test_pages_with_a_transcript_are_not_sent_to_ocr(tmp_path):
    # Lines this short (< 40 letters) make every page look scanned, so each one would go to OCR.
    path = pf.text_pdf(tmp_path / "short.pdf", [["Page one."], ["Page two."], ["Page three."]])
    ocr = _RecordingOcr()
    pages = extract_pages(path, ocr=ocr, skip_ocr=frozenset({2}))
    assert ocr.pages == [1, 3]
    assert (pages[1].method, pages[1].text) == ("text", "Page two.")
    assert pages[0].method == "ocr"


def test_running_footers_are_found_when_many_pages_have_no_text():
    # Transcribed scanned pages come back empty (no OCR). The footer share must count only pages with text,
    # otherwise 4 footers out of 10 pages fall below the 60% rule and stay in the text.
    pages = _book(["Science and Technology, Grade 10"] * 4) + [PdfPage(90 + i, "", "empty") for i in range(6)]
    cleaned = remove_repeated_lines(pages)
    assert all("Technology" not in p.text for p in cleaned[:4])
    assert all(len(p.text.splitlines()) == 3 for p in cleaned[:4])
