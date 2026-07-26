from services.translation.policy.rule_profiles import build_rule_profile_context


def test_engineering_drawing_profile_is_loaded_without_fallback() -> None:
    context = build_rule_profile_context("engineering_drawing")

    assert context.profile_name == "engineering_drawing"
    assert "DEPOH LORI" in context.profile_text
    assert "company names" in context.profile_text
    assert "Never change a number or unit" in context.profile_text


def test_engineering_drawing_profile_normalizes_hyphenated_name() -> None:
    context = build_rule_profile_context("engineering-drawing")

    assert context.profile_name == "engineering_drawing"
