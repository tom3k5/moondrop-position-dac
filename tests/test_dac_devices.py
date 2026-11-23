from dataclasses import replace

import pytest

import moondrop_position as position
from dac_devices import AmbiguousDac, DacRegistry
from dac_transport import HidDeviceChanged, HidError, HidrawTransport, HidReport, parse_reports, scan_hidraw

POSITION_DESCRIPTOR = bytes.fromhex(
    "05 0c 09 01 a1 01 85 4b 75 08 95 3f 09 01 81 03 "
    "95 3f 09 02 91 02 85 54 75 08 95 3f 09 03 81 03 95 3f 09 04 91 02 c0"
)


@pytest.fixture
def linux_hidraw(tmp_path):
    sysfs = tmp_path / "sysfs"
    dev = tmp_path / "dev"
    sysfs.mkdir()
    dev.mkdir()

    def add(node, generation, descriptor, *, hid_id="0003:000035D8:00000123"):
        instance = tmp_path / generation / node
        device = instance / "device"
        device.mkdir(parents=True)
        (device / "uevent").write_text(f"HID_ID={hid_id}\nHID_NAME=Test DAC\n")
        (device / "report_descriptor").write_bytes(descriptor)
        (sysfs / node).unlink(missing_ok=True)
        (sysfs / node).symlink_to(instance)
        (dev / node).touch()
        return str(dev / node)

    return add, lambda: scan_hidraw(sysfs, dev)


def test_descriptor_read_is_structural_and_checks_both_directions():
    reports = parse_reports(POSITION_DESCRIPTOR)
    assert reports == frozenset(HidReport(report, kind, 63) for report in (0x4B, 0x54) for kind in ("input", "output"))
    assert parse_reports(bytes.fromhex("27 85 4b 00 00")) == frozenset()
    assert parse_reports(bytes.fromhex("85 4b 75")) == frozenset()


def test_registry_does_not_confuse_hid_interface_or_model(linux_hidraw):
    add, scan = linux_hidraw
    position_node = add("hidraw1", "position", POSITION_DESCRIPTOR)
    add("hidraw2", "consumer", bytes.fromhex("85 03 75 01 95 08 81 02"))
    add("hidraw3", "same-report", POSITION_DESCRIPTOR.replace(b"\x95\x3f", b"\x95\x0a"))
    other_node = add("hidraw4", "other-model", POSITION_DESCRIPTOR, hid_id="0003:00001234:00000001")
    other_model = replace(position.POSITION_MODEL, model_id="test-dac", usb_id=(0x1234, 1))
    registry = DacRegistry((position.POSITION_MODEL, other_model), scan)
    assert [(item.model.model_id, item.interface.node) for item in registry.detect()] == [
        ("moondrop-position", position_node),
        ("test-dac", other_node),
    ]
    assert registry.select(other_node).model is other_model


def test_selection_distinguishes_two_units_and_reused_hidraw_node(linux_hidraw):
    add, scan = linux_hidraw
    first = add("hidraw1", "first-unit", POSITION_DESCRIPTOR)
    second = add("hidraw2", "second-unit", POSITION_DESCRIPTOR)
    registry = DacRegistry((position.POSITION_MODEL,), scan)
    with pytest.raises(AmbiguousDac):
        registry.select()
    selected = registry.select(second)
    assert registry.select(selected.interface) == selected
    assert registry.select(first).interface != selected.interface

    add("hidraw2", "reattached", POSITION_DESCRIPTOR)
    with pytest.raises(HidDeviceChanged):
        registry.select(selected.interface)
    with pytest.raises(HidDeviceChanged):
        registry.open(selected, 20)
    assert registry.select(second).interface != selected.interface


def test_session_lock_lasts_until_close(linux_hidraw):
    add, scan = linux_hidraw
    node = add("hidraw1", "position", POSITION_DESCRIPTOR)
    registry = DacRegistry((position.POSITION_MODEL,), scan)
    selected = registry.select(node)
    with registry.open(selected, 20), pytest.raises(HidError, match="zajęty"):
        HidrawTransport(selected.interface)
    with registry.open(selected, 20) as reopened:
        assert reopened.interface == selected.interface
