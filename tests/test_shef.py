from hydropulse.adapters.shef import parse


def test_sequence_parsing_and_missing_value():
    text = ".E CIDI4 20240628 Z /DC202406281446/DH15/DIH06/HGIFF 10.1/11.2/M/13.0"
    values, errors = parse(text)
    assert not errors and len(values) == 4 and values[2].value is None
    assert values[1].valid_at.hour == 21


def test_unknown_construct_is_reported():
    values, errors = parse(".B UNKNOWN")
    assert not values and len(errors) == 1
