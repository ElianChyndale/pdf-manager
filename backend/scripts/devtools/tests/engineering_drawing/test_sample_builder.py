from services.engineering_drawing.sample_builder import _offline_translation


def test_offline_sample_glossary_preserves_numeric_annotation() -> None:
    assert _offline_translation("GARISAN ANJAKAN BANGUNAN 40'") == "建筑退界线 40'"
    assert _offline_translation("CADANGAN LALUAN SEHALA (6100MM LEBAR)") == "建议单向通道 6100MM"


def test_offline_sample_glossary_handles_fixed_vector_regression() -> None:
    assert _offline_translation("DEPOH LORI") == "卡车车库"
