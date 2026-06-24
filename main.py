from sonosify import discover


def main() -> None:
    system = discover()
    for speaker in system.speakers:
        print(f"{speaker.room_name}\t{speaker.ip}")


if __name__ == "__main__":
    main()
