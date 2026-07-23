import sonosify


def test_all_exports_are_importable_attributes() -> None:
    for name in sonosify.__all__:
        assert hasattr(sonosify, name), f"{name!r} listed in __all__ but not defined"


def test_no_duplicate_exports() -> None:
    assert len(sonosify.__all__) == len(set(sonosify.__all__))
