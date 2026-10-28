from .models import RepeatMode as _RepeatMode


def _repeat_from_play_mode(mode: str) -> _RepeatMode:
    if mode.endswith("REPEAT_ONE"):
        return _RepeatMode.ONE
    if mode in {"REPEAT_ALL", "SHUFFLE"}:
        return _RepeatMode.ALL
    return _RepeatMode.OFF


def _play_mode(shuffle: bool, repeat: _RepeatMode) -> str:
    if shuffle:
        return {
            _RepeatMode.OFF: "SHUFFLE_NOREPEAT",
            _RepeatMode.ONE: "SHUFFLE_REPEAT_ONE",
            _RepeatMode.ALL: "SHUFFLE",
        }[repeat]
    return {
        _RepeatMode.OFF: "NORMAL",
        _RepeatMode.ONE: "REPEAT_ONE",
        _RepeatMode.ALL: "REPEAT_ALL",
    }[repeat]
