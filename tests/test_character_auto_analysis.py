from characters.analysis import normalize_analysis


def test_normalize_character_analysis_maps_ui_parameters_and_excludes_scene_traits():
    raw = {
        "parameters": {
            "weight_profile": "curvy",
            "bust_size": 3,
            "age_category": "young adult",
            "hairstyle": "long wavy hair",
            "hair_color": "dark brown hair",
        },
        "identity": {
            "face": {"shape": "round", "forehead": "high"},
            "eyes": {"shape": "almond", "iris_color": "light hazel"},
            "distinctive_features": ["small beauty mark near the left cheek"],
        },
        "scene_attributes": {
            "pose": "hand resting on cheek",
            "accessories": "thin bracelet",
        },
    }
    result = normalize_analysis(raw)
    assert result["weight_profile"] == "Пышная"
    assert result["bust_size"] == 3
    assert result["age_category"] == "Молодая"
    assert result["hairstyle"] == "Длинные волнистые"
    assert result["hair_color"] == "Тёмно-каштановые"
    assert "description" not in result
    assert "identity" not in result
    assert "scene_attributes" not in result
    assert set(result) == {"weight_profile", "bust_size", "age_category", "hairstyle", "hair_color", "confidence"}


def test_body_and_bust_are_left_empty_when_not_visible():
    raw = {"parameters": {"weight_profile": None, "bust_size": None, "age_category": "mature"}}
    result = normalize_analysis(raw)
    assert result["weight_profile"] is None
    assert result["bust_size"] is None
    assert result["age_category"] == "Милф"
