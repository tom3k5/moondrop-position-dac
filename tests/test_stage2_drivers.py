import fcntl
import json
import os
import select
from pathlib import Path

import chu2_dsp
import dsp_control
import echo_a
import moondrop_position as dac
from dac_devices import DacRegistry
from dac_transport import HidInterface, HidrawTransport, scan_hidraw

FIXTURES = Path(__file__).resolve().parent / "fixtures"

POSITION_DESCRIPTOR = bytes.fromhex(
    "05 0c 09 01 a1 01 85 4b 75 08 95 3f 09 01 81 03 "
    "95 3f 09 02 91 02 85 54 75 08 95 3f 09 03 81 03 95 3f 09 04 91 02 c0"
)
CHU2_DESCRIPTOR = bytes.fromhex(
    "05 0c 09 01 a1 01 85 01 15 00 25 01 75 01 95 02 09 e9 09 ea 81 02 "
    "95 02 09 cd 09 cf 81 02 95 04 81 01 06 01 ff 85 4b 75 08 95 0a 09 01 "
    "81 03 95 0a 09 02 91 02 85 54 75 08 95 0a 09 03 81 03 95 0a 09 04 91 02 c0"
)
ECHO_A_DESCRIPTOR = POSITION_DESCRIPTOR


def _make_live_interface(tmp_path: Path, node: str, vid: int, pid: int, name: str, reports) -> HidInterface:
    instance = tmp_path / "usb" / node
    instance.mkdir(parents=True, exist_ok=True)
    sysfs_link = tmp_path / f"sysfs-{node}"
    if sysfs_link.exists() or sysfs_link.is_symlink():
        sysfs_link.unlink()
    sysfs_link.symlink_to(instance)
    dev_node = tmp_path / node
    dev_node.touch()
    return HidInterface(str(dev_node), sysfs_link, instance, name, vid, pid, reports)


def _patch_real_hidraw_transport(monkeypatch, handler) -> dict[str, object]:
    """Back the REAL HidrawTransport with a scripted handler via OS-level syscalls."""
    state: dict[str, object] = {"rx": [], "closed": [], "next_fd": 100}

    def fake_open(_path, _flags, _mode=0o666):
        fd = state["next_fd"]
        state["next_fd"] += 1
        return fd

    def fake_flock(_fd, _op):
        return None

    def fake_write(_fd, data: bytes) -> int:
        reply = handler(data)
        if reply is not None:
            state["rx"].append(reply)
        return len(data)

    def fake_select(rlist, _wlist, _xlist, _timeout=None):
        return (rlist, [], []) if state["rx"] else ([], [], [])

    def fake_read(_fd, size: int) -> bytes:
        if not state["rx"]:
            raise BlockingIOError()
        pkt = state["rx"].pop(0)
        return pkt[:size]

    def fake_close(fd: int) -> None:
        state["closed"].append(fd)

    monkeypatch.setattr(os, "open", fake_open)
    monkeypatch.setattr(fcntl, "flock", fake_flock)
    monkeypatch.setattr(os, "write", fake_write)
    monkeypatch.setattr(select, "select", fake_select)
    monkeypatch.setattr(os, "read", fake_read)
    monkeypatch.setattr(os, "close", fake_close)
    return state


def test_registry_detects_position_chu2_and_echo_a(tmp_path):
    sysfs = tmp_path / "sysfs"
    dev = tmp_path / "dev"
    sysfs.mkdir()
    dev.mkdir()

    def add(node: str, hid_id: str, name: str, descriptor: bytes):
        instance = tmp_path / "usb" / node
        device = instance / "device"
        device.mkdir(parents=True)
        (device / "uevent").write_text(f"HID_ID={hid_id}\nHID_NAME={name}\n")
        (device / "report_descriptor").write_bytes(descriptor)
        (sysfs / node).symlink_to(instance)
        (dev / node).touch()
        return str(dev / node)

    pos_node = add("hidraw0", "0003:000035D8:00000123", "MOONDROP:Gravity Position", POSITION_DESCRIPTOR)
    chu_node = add("hidraw1", "0003:000031B2:00000113", "Chu2 DSP", CHU2_DESCRIPTOR)
    echo_node = add("hidraw2", "0003:00003302:000012C5", "ECHO-A", ECHO_A_DESCRIPTOR)

    registry = DacRegistry(dac.DEVICE_REGISTRY.models, lambda: scan_hidraw(sysfs, dev))
    found = [(item.model.model_id, item.interface.node) for item in registry.detect()]
    assert found == [
        ("moondrop-position", pos_node),
        ("moondrop-chu2-dsp", chu_node),
        ("moondrop-echo-a", echo_node),
    ]


def test_chu2_dsp_via_real_hidraw_transport_write_slot_and_reconnect(tmp_path, monkeypatch):
    capture = json.loads((FIXTURES / "ktmicro_chu2_dsp.json").read_text())
    expected_rx = {
        tuple(ex["send"]["data"]): bytes([0x4B, *ex["responses"][0]["data"]])
        for ex in capture["exchanges"]
        if ex["send"]["data"][4] == chu2_dsp.CMD_READ
    }

    state_regs: dict[int, list[int]] = {}
    committed: list[bool] = []

    def handler(frame: bytes) -> bytes | None:
        assert frame[0] == 0x4B
        payload = list(frame[1:])
        reg, cmd = payload[0], payload[4]
        if cmd == chu2_dsp.CMD_READ:
            if reg in state_regs:
                return bytes([0x4B, reg, 0, 0, 0, cmd, 0, *state_regs[reg]])
            return expected_rx[tuple(payload)]
        if cmd == chu2_dsp.CMD_WRITE:
            state_regs[reg] = payload[6:10]
            return bytes([0x4B, reg, 0, 0, 0, cmd, 0, 3, 0, 0, 0])
        if cmd == chu2_dsp.CMD_COMMIT:
            committed.append(True)
            return bytes([0x4B, reg, 0, 0, 0, cmd, 0, 3, 0, 0, 0])
        return None

    iface = _make_live_interface(tmp_path, "hidraw1", 0x31B2, 0x0113, "Chu2 DSP", chu2_dsp.CHU2_MODEL.reports)
    reattached = _make_live_interface(tmp_path, "hidraw2", 0x31B2, 0x0113, "Chu2 DSP", chu2_dsp.CHU2_MODEL.reports)
    io_state = _patch_real_hidraw_transport(monkeypatch, handler)
    dev = chu2_dsp.Chu2Dsp(HidrawTransport(iface))

    assert dev.slot() == 3
    assert dev.preamp() == 0.0
    bands = dev.read_eq()
    assert bands == [
        {"band": 1, "freq": 25, "gain": 0.0, "q": 0.3, "type": "PK"},
        {"band": 2, "freq": 200, "gain": -3.0, "q": 2.0, "type": "LSQ"},
        {"band": 3, "freq": 1400, "gain": 0.0, "q": 7.0, "type": "PK"},
        {"band": 4, "freq": 3500, "gain": 0.0, "q": 1.0, "type": "PK"},
        {"band": 5, "freq": 9000, "gain": 0.0, "q": 1.5, "type": "PK"},
    ]

    state = dsp_control.read_state(dev)
    assert state.model_name == "MOONDROP CHU II DSP"
    assert state.experimental is True
    assert state.band_count == 5
    assert state.custom_slot == 3

    # Writing through dac.write_profile with default Position slot (7) must normalize to CHU II slot (3)
    # and close the old transport because commit 0x53 restarts USB.
    new_bands = [
        {"band": 1, "type": "LSQ", "freq": 80, "gain": 2.5, "q": 0.71},
        {"band": 2, "type": "PK", "freq": 250, "gain": -1.5, "q": 1.4},
        {"band": 3, "type": "PK", "freq": 1500, "gain": 1.2, "q": 2.5},
        {"band": 4, "type": "PK", "freq": 4200, "gain": -2.0, "q": 3.0},
        {"band": 5, "type": "HSQ", "freq": 10000, "gain": 1.5, "q": 0.7},
    ]
    dac.write_profile(dev, new_bands, preamp=None, slot=dac.CUSTOM_SLOT, persist=True)
    assert committed == [True]
    assert dev.transport._fd is None
    assert len(io_state["closed"]) == 1

    # Reconnect path in GUI apply_profile re-opens the re-enumerated device and verifies persistence.
    monkeypatch.setattr(
        dac.DEVICE_REGISTRY,
        "detect",
        lambda: [dac.DacRegistry((chu2_dsp.CHU2_MODEL,), lambda: [reattached]).detect()[0]],
    )
    monkeypatch.setattr(dsp_control.time, "sleep", lambda _s: None)

    profile = dsp_control.Profile("CHU2 Test", dac.CUSTOM_SLOT, new_bands, 0.0)
    updated = dsp_control.apply_profile(lambda target: chu2_dsp.Chu2Dsp(HidrawTransport(target)), reattached, profile)
    assert updated.slot == 3
    assert updated.bands[0] == {"band": 1, "freq": 80, "gain": 2.5, "q": 0.71, "type": "LSQ"}
    assert updated.bands[4] == {"band": 5, "freq": 10000, "gain": 1.5, "q": 0.7, "type": "HSQ"}


def test_echo_a_via_real_hidraw_transport_and_consistent_sample_rate(tmp_path, monkeypatch):
    assert echo_a.COEFF_FS == echo_a.EchoA.sample_rate_hz == 93750.0

    lines = (FIXTURES / "echo-a-read-195126.log").read_text().splitlines()
    pairs: list[tuple[bytes, bytes]] = []
    pending_tx: bytes | None = None
    for line in lines:
        stripped = line.split("#", 1)[0].strip()
        if not stripped:
            continue
        if stripped.startswith("TX "):
            pending_tx = bytes.fromhex(stripped[3:])
        elif stripped.startswith("RX ") and pending_tx is not None:
            pairs.append((pending_tx, bytes.fromhex(stripped[3:])))
            pending_tx = None

    canned = {tx[:6]: rx for tx, rx in pairs}
    bands_mem: dict[int, bytes] = {}
    global_gain_mem = [0]
    commit_cmds: list[int] = []

    def handler(frame: bytes) -> bytes | None:
        assert frame[0] == 0x4B
        op, cmd = frame[1], frame[2]
        if op == echo_a.OP_READ:
            if cmd == echo_a.CMD_PEQ_VALUES and frame[5] in bands_mem:
                return bands_mem[frame[5]]
            if cmd == echo_a.CMD_GLOBAL_GAIN and bands_mem:
                reply = bytearray(64)
                reply[0] = 0x4B
                reply[1] = echo_a.OP_READ
                reply[2] = echo_a.CMD_GLOBAL_GAIN
                reply[3] = 0x02
                reply[5] = global_gain_mem[0] & 0xFF
                return bytes(reply)
            return canned.get(frame[:6])
        if op == echo_a.OP_WRITE:
            if cmd == echo_a.CMD_PEQ_VALUES:
                idx = frame[5]
                reply = bytearray(frame)
                reply[1] = echo_a.OP_READ
                bands_mem[idx] = bytes(reply)
            elif cmd == echo_a.CMD_GLOBAL_GAIN:
                global_gain_mem[0] = frame[5]
            elif cmd in (echo_a.CMD_RESET_STEP, echo_a.CMD_COMMIT_PREP, echo_a.CMD_TEMP_WRITE, echo_a.CMD_FLASH_EQ):
                commit_cmds.append(cmd)
        return None

    iface = _make_live_interface(tmp_path, "hidraw2", 0x3302, 0x12C5, "ECHO-A", echo_a.ECHO_A_MODEL.reports)
    _patch_real_hidraw_transport(monkeypatch, handler)
    dev = echo_a.EchoA(HidrawTransport(iface))

    assert dev.version() == "0.1"
    assert dev.preamp() == 0.0
    bands = dev.read_eq()
    assert len(bands) == 8
    assert [b["band"] for b in bands] == [1, 2, 3, 4, 5, 6, 7, 8]
    assert [b["freq"] for b in bands] == [31, 62, 125, 250, 500, 1000, 2000, 4000]
    assert all(b["type"] == "PK" and b["gain"] == 0.0 for b in bands)

    state = dsp_control.read_state(dev)
    assert state.model_name == "MOONDROP ECHO-A"
    assert state.experimental is True
    assert state.band_count == 8
    assert state.sample_rate_hz == 93750.0

    # GUI response_points must use the device's 93750 Hz sample rate.
    readback_profile = dsp_control.profile_from_readback(state)
    assert readback_profile is not None
    assert readback_profile.sample_rate_hz == 93750.0
    points = dsp_control.response_points(readback_profile, [100.0, 1000.0, 10000.0])
    assert len(points) == 3

    target_bands = [
        {
            "band": i + 1,
            "type": "LSQ" if i == 0 else ("HSQ" if i == 7 else "PK"),
            "freq": 100 * (i + 1),
            "gain": -2.0 + i * 0.5,
            "q": 1.0,
        }
        for i in range(8)
    ]
    # Passing Position's default slot=7 through dac.write_profile normalizes to ECHO-A's custom_slot (0).
    applied_preamp = dac.write_profile(dev, target_bands, preamp=-4.0, slot=dac.CUSTOM_SLOT, persist=True)
    assert applied_preamp == -4.0
    assert commit_cmds == [
        echo_a.CMD_RESET_STEP,
        echo_a.CMD_COMMIT_PREP,
        echo_a.CMD_TEMP_WRITE,
        echo_a.CMD_FLASH_EQ,
    ]
    assert dev.read_band(0)["band"] == 1
    assert dev.read_band(0)["type"] == "LSQ"
    assert dev.read_band(7)["band"] == 8
    assert dev.read_band(7)["type"] == "HSQ"
    assert dev.preamp() == -4.0


def test_rootless_diagnostic_report_works_without_open_permission(tmp_path):
    iface = _make_live_interface(tmp_path, "hidraw9", 0x31B2, 0x0113, "Chu2 DSP", chu2_dsp.CHU2_MODEL.reports)

    def raise_perm():
        raise dac.HidError("Brak dostępu do DAC-a. Sprawdź regułę udev na hoście.")

    report = dsp_control.build_diagnostic_report(scan=lambda: [iface], open_device=raise_perm)
    assert report["app_version"] == dsp_control.APP_VERSION
    assert report["open_error"] == "Brak dostępu do DAC-a. Sprawdź regułę udev na hoście."
    assert len(report["hidraw_interfaces"]) == 1
    entry = report["hidraw_interfaces"][0]
    assert entry["vid_pid"] == "31b2:0113"
    assert entry["matched_model"] == "moondrop-chu2-dsp"
