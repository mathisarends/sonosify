from sonosify.soap import build_envelope, parse_response, parse_upnp_error


def test_build_envelope_sorts_and_escapes_args() -> None:
    envelope = build_envelope("urn:test", "DoThing", {"B": "x&y", "A": "1"})

    assert envelope.index("<A>1</A>") < envelope.index("<B>x&amp;y</B>")
    assert 'SOAPACTION' not in envelope


def test_parse_response_reads_direct_children() -> None:
    raw = """
    <s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/">
      <s:Body>
        <u:GetVolumeResponse xmlns:u="urn:test">
          <CurrentVolume>23</CurrentVolume>
        </u:GetVolumeResponse>
      </s:Body>
    </s:Envelope>
    """

    assert parse_response(raw) == {"CurrentVolume": "23"}


def test_parse_upnp_error() -> None:
    raw = """
    <s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/">
      <s:Body><s:Fault><detail><UPnPError xmlns="urn:schemas-upnp-org:control-1-0">
        <errorCode>701</errorCode><errorDescription>Transition not available</errorDescription>
      </UPnPError></detail></s:Fault></s:Body>
    </s:Envelope>
    """

    error = parse_upnp_error(raw)

    assert error is not None
    assert error.code == "701"
    assert "Transition not available" in str(error)
