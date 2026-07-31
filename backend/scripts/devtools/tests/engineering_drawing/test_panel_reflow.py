from services.engineering_drawing.panel_reflow import company_panel_font_bounds


def test_company_panel_font_grows_with_available_whitespace() -> None:
    small = company_panel_font_bounds([0, 0, 120, 45], text="公司地址与联系方式" * 4)
    large = company_panel_font_bounds([0, 0, 260, 150], text="公司地址与联系方式" * 4)
    assert large["max_size"] > small["max_size"]
    assert large["min_size"] >= 6.4
    assert large["batch_scale"] > 1.0
