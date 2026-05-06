from models.nebula.video_attributes import VideoNebulaAttributes


def test_video_attributes_values():
    assert VideoNebulaAttributes.IS_NEBULA_ORIGINAL.value == "is_nebula_original"
    assert VideoNebulaAttributes.IS_NEBULA_PLUS.value == "is_nebula_plus"
    assert VideoNebulaAttributes.IS_NEBULA_FIRST.value == "is_nebula_first"
    assert VideoNebulaAttributes.FREE_SAMPLE_ELIGIBLE.value == "free_sample_eligible"


def test_video_attributes_str_subclass_allows_string_compare():
    assert VideoNebulaAttributes.IS_NEBULA_PLUS == "is_nebula_plus"
    assert "is_nebula_plus" == VideoNebulaAttributes.IS_NEBULA_PLUS


def test_video_attributes_constructed_from_value():
    assert VideoNebulaAttributes("is_nebula_first") is VideoNebulaAttributes.IS_NEBULA_FIRST


def test_video_attributes_membership():
    assert {a for a in VideoNebulaAttributes} == {
        VideoNebulaAttributes.IS_NEBULA_ORIGINAL,
        VideoNebulaAttributes.IS_NEBULA_PLUS,
        VideoNebulaAttributes.IS_NEBULA_FIRST,
        VideoNebulaAttributes.FREE_SAMPLE_ELIGIBLE,
    }
