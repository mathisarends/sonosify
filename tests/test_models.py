from sonosify.models import Group, Speaker


def test_group_coordinator_returns_matching_member() -> None:
    coordinator = Speaker(ip="1", room_name="Kitchen", uid="k", is_coordinator=True)
    member = Speaker(ip="2", room_name="Office", uid="o")
    group = Group(id="g", coordinator_uid="k", members=(coordinator, member))

    assert group.coordinator == coordinator


def test_group_coordinator_returns_none_when_absent() -> None:
    member = Speaker(ip="2", room_name="Office", uid="o")
    group = Group(id="g", coordinator_uid="k", members=(member,))

    assert group.coordinator is None
