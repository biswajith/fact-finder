from fact_extractor.normalize import missing_values, values


def test_dates_and_times_normalised():
    src = "All proposals must be received no later than 5:00 PM Eastern on March 3, 2027."
    assert missing_values("Proposals due 5 PM ET 2027-03-03", [src]) == set()
    assert missing_values("Proposals due 2027-03-04", [src]) == {"date:2027-03-04"}
    assert "time:17:00" in values("17:00")
    assert values("3rd of March 2027") == {"date:2027-03-03"}


def test_money_and_scale():
    assert missing_values("Budget $1,200,000", ["budget is $1.2 million"]) == set()
    assert missing_values("Budget 1200000 USD", ["budget is $1,200,000"]) == set()
    assert missing_values("Budget $1.5 million", ["budget is $1,200,000"]) == {"1500000"}


def test_number_words_and_sections():
    assert missing_values("3 copies", ["three (3) copies"]) == set()
    assert missing_values("Submit 3 copies", ["Submit three copies"]) == set()
    assert missing_values("See Section 4.2", ["4.2 Submission Deadline"]) == set()
    assert missing_values("24/7 support", ["Item: Support hours | Requirement: 24/7"]) == set()
    assert missing_values("99.9% uptime", ["Uptime: 99.90%"]) == set()


def test_glued_pdf_text():
    # Strings as extracted from the City of Durham Oracle ERP RFP (RFP24 0031).
    cell = "IssuanceofRFP: LastdateforSubmittingQuestions/Time | May10 2024\n,: May24 2024 at2pmET , ,"
    assert missing_values("Questions due May 24, 2024 at 2:00 pm ET", [cell]) == set()
    assert missing_values("Questions due 2024-05-24", [cell]) == set()
    prose = "requests for clarification that require addenda, if received by the City afterMay 24, 2024 @ 2:00 pm ET."
    assert missing_values("Questions due 2024-05-24 2:00 pm ET", [prose]) == set()
    row = "IssuanceofRFP: NotificationtoShort -listedProponents | May10 2024\n,: Anestimated30daysafterthepreviousstep"
    assert missing_values("Shortlist notification an estimated 30 days after the previous step", [row]) == set()
    due = "ReceiveProposals/RFPCloseDate/Time | May10 2024\n,: June10 2024 at2pmET , ,"
    assert missing_values("Submit the proposal by 2024-06-10 2:00 pm ET", [due]) == set()


def test_glued_text_still_catches_wrong_values():
    cell = "LastdateforSubmittingQuestions/Time | May10 2024\n,: May24 2024 at2pmET"
    assert missing_values("Questions due 2024-05-25", [cell]) == {"date:2024-05-25"}
    assert missing_values("Questions due 2024-05-24 at 3 pm", [cell]) == {"time:15:00"}
    assert missing_values("an estimated 45 days", ["Anestimated30daysafterthepreviousstep"]) == {"45"}
    # Ulster County RFP: schedule cell and a form blank
    ulster = "Tuesday August 18 2026 , ,: WeekofSeptember7 2026 , | SelectionCommitteeevaluates Proposals"
    assert missing_values("Selection committee evaluates proposals: week of September 7 2026", [ulster]) == set()
    assert missing_values("MacBride Statement 2", ["___2."]) == set()
    # digit-then-letter is not split, so scale suffixes keep their meaning
    assert missing_values("Budget $10,000", ["budget of $10k"]) == set()
