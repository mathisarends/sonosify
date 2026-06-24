import sys

from sonosify import SonosController


room = sys.argv[1] if len(sys.argv) > 1 else None

sonos = SonosController()
with sonos.client(room) as client:
    print(f"watching {client.ip}; press Ctrl+C to stop")
    with client.watch() as watcher:
        for event in watcher:
            if event.service == "av_transport":
                print("transport", event.transport_state, event.track.title if event.track else "")
            elif event.service == "rendering_control":
                print("rendering", "volume=", event.volume, "muted=", event.muted)
            else:
                print(event.service, event.values)
