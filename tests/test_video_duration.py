from videos.duration import extract_video_duration


def test_duration_parsing_and_cleanup():
    cleaned, frames = extract_video_duration("девушка медленно ложится, 6 секунд")
    assert cleaned == "девушка медленно ложится"
    assert frames == 145


def test_duration_parsing_english():
    cleaned, frames = extract_video_duration("she slowly sits down, 5 seconds")
    assert cleaned == "she slowly sits down"
    assert frames == 121


def test_default_duration():
    cleaned, frames = extract_video_duration("девушка медленно ложится")
    assert cleaned == "девушка медленно ложится"
    assert frames == 97


def test_short_russian_unit():
    cleaned, frames = extract_video_duration("девушка садится, 3 с")
    assert cleaned == "девушка садится"
    assert frames == 73
