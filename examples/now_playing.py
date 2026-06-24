import sys

from sonosify import SonosController


room = sys.argv[1] if len(sys.argv) > 1 else None

sonos = SonosController()
with sonos.client(room) as client:
    state = client.now_playing()

print(state.state)
if state.track:
    print(state.track.title)
    print(state.track.creator)
    print(state.track.album)
