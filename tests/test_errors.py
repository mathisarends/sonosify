from sonosify.errors import AmbiguousSpeakerError, UPnPError


def test_ambiguous_speaker_error_exposes_query_and_matches() -> None:
    error = AmbiguousSpeakerError("office", ["Office", "Office 2"])

    assert error.query == "office"
    assert error.matches == ("Office", "Office 2")
    assert "office" in str(error)
    assert "Office, Office 2" in str(error)


def test_upnp_error_formats_message_with_and_without_description() -> None:
    with_description = UPnPError("701", "Transition not available")
    assert with_description.code == "701"
    assert with_description.description == "Transition not available"
    assert str(with_description) == "upnp error 701: Transition not available"

    without_description = UPnPError("500")
    assert without_description.description == ""
    assert str(without_description) == "upnp error 500"
