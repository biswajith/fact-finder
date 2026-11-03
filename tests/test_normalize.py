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
