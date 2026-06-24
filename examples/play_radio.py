import sys

from sonosify import SonosController


if len(sys.argv) < 3:
    raise SystemExit("usage: python examples/play_radio.py ROOM STREAM_URL [TITLE]")

room = sys.argv[1]
stream_url = sys.argv[2]
title = sys.argv[3] if len(sys.argv) > 3 else stream_url

sonos = SonosController()
with sonos.client(room) as client:
    client.play_uri(stream_url, radio=True, title=title)
