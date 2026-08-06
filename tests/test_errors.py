from sonosify.errors import (
    AmbiguousSpeakerError,
    DiscoveryError,
    LocalAPIError,
    NetworkError,
    SonosifyError,
    SpeakerNotFoundError,
    SubscriptionError,
    UnsupportedFeatureError,
    UPnPError,
)


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


def test_sonosify_error_details_default_code() -> None:
    assert SonosifyError("boom").error_details() == {"code": "sonosify_error"}


def test_unsupported_feature_and_discovery_and_network_error_details() -> None:
    assert UnsupportedFeatureError("nope").error_details() == {
        "code": "unsupported_feature"
    }
    assert DiscoveryError("nope").error_details() == {"code": "discovery_error"}
    assert NetworkError("nope").error_details() == {"code": "network_error"}


def test_local_api_error_from_response_merges_header_and_body() -> None:
    error = LocalAPIError.from_response(
        {"success": False}, {"errorCode": "ERROR_COMMAND_FAILED"}
    )

    assert "ERROR_COMMAND_FAILED" in str(error)
    assert error.response == {
        "success": False,
        "errorCode": "ERROR_COMMAND_FAILED",
    }
    assert error.error_details() == {
        "code": "local_api_error",
        "sonos_code": "ERROR_COMMAND_FAILED",
    }


def test_local_api_error_from_response_without_error_code() -> None:
    error = LocalAPIError.from_response({"success": False}, {})

    assert str(error) == "local Sonos command failed"
    assert error.error_details() == {"code": "local_api_error"}


def test_local_api_error_response_property_returns_a_copy() -> None:
    error = LocalAPIError("boom", response={"key": "value"})

    response = error.response
    response["key"] = "mutated"

    assert error.response == {"key": "value"}


def test_speaker_not_found_error_details_with_and_without_query() -> None:
    with_query = SpeakerNotFoundError("no match", query="kitchen")
    assert with_query.query == "kitchen"
    assert with_query.error_details() == {
        "code": "speaker_not_found",
        "query": "kitchen",
    }

    without_query = SpeakerNotFoundError("no match")
    assert without_query.query is None
    assert without_query.error_details() == {"code": "speaker_not_found"}


def test_ambiguous_speaker_error_details() -> None:
    error = AmbiguousSpeakerError("office", ["Office", "Office 2"])

    assert error.error_details() == {
        "code": "ambiguous_speaker",
        "query": "office",
        "matches": ["Office", "Office 2"],
    }


def test_subscription_error_details() -> None:
    error = SubscriptionError("failed", services=["AVTransport", "RenderingControl"])

    assert error.services == ("AVTransport", "RenderingControl")
    assert error.error_details() == {
        "code": "subscription_error",
        "services": ["AVTransport", "RenderingControl"],
    }


def test_upnp_error_details() -> None:
    error = UPnPError("701", "Transition not available")

    assert error.error_details() == {
        "code": "upnp_error",
        "upnp_code": "701",
        "description": "Transition not available",
    }
