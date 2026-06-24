import sys

from sonosify import SonosController


if len(sys.argv) < 3:
    raise SystemExit("usage: python examples/spotify_enqueue.py ROOM SPOTIFY_URI_OR_URL")

room = sys.argv[1]
spotify_value = sys.argv[2]

sonos = SonosController()
with sonos.client(room) as client:
    position = client.open_spotify(spotify_value)

print(f"enqueued at queue position: {position}")
