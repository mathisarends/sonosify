from sonosify import discover


system = discover()

for speaker in system.speakers:
    coordinator = "coordinator" if speaker.is_coordinator else "member"
    print(f"{speaker.room_name:24} {speaker.ip:15} {coordinator}")
