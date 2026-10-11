"""Init request (empty buffer 00 0A, iNet Box -> CP Plus): "send me all status buffers".

Test vector: the request our emulated iNet Box uploaded to a CP Plus C3.00.00 and which made
it re-send 0C 0B, 14 33 and 18 3D (capture 2026-10-11, counter 0x16).
"""

import pytest

from inetbox import InetboxApp, InetboxLINProtocol, Lin
from inetbox.tools import calculate_checksum
from test_timer_buffer import DummySerial, h

# preamble, length 0, type 0A, counter 0x16, checksum 0x8A
INIT_REQUEST_16 = h("00 1e 00 00 22 ff ff ff 54 01 00 0a 16 8a")

HEATER_STATUS = h(
    "00 1e 00 00 22 ff ff ff 54 01 14 33 00 3c"
    "00 00 00 00 00 00 00 00 00 00 01 01 68 0b a6 0b 00 00 00 00 00 00 00 00"
)


def upload_request(lin):
    """CP Plus asks the iNet Box for an upload: BA, 0x0B bytes, as seen on the bus."""
    serial = DummySerial()
    for data in (h("03 10 0b ba 00 1f 00 1e"), h("03 21 00 00 22 ff ff ff")):
        serial.rx = bytes([0x00, 0x55, 0x3C]) + data + bytes([calculate_checksum(data)])
        lin.loop_serial(serial, True)


def queued_buffer(lin):
    """The answer queued in the transport layer, reassembled to the buffer."""
    frames = lin.transportlayer_response_buffer
    assert frames[0][:4] == h("03 10 29 fa"), frames[0]
    # the first frame carries the first two buffer bytes after "00 1F"
    return (frames[0][6:8] + b"".join(f[2:8] for f in frames[1:]))[: len(INIT_REQUEST_16)]


@pytest.fixture
def app():
    app = InetboxApp(False, "none")
    # InetboxApp keeps its state in class attributes, reset it for every test
    app.status = {"_command_counter": 0}
    app.updates_to_send = {}
    app.display_status = {}
    app.init_request_pending = False
    for command in InetboxApp.COMMANDS.values():
        command.can_send_updates = False
        command.updates_pending = False
    return app


@pytest.fixture
def lin(app):
    lin = Lin(InetboxLINProtocol(app, False), False)
    lin.transportlayer_response_buffer = []
    return lin


def test_nothing_pending_by_default(app):
    assert app._get_init_request_buffer() is None
    assert InetboxLINProtocol(app, False).answer_to_d8_message()[0] == 0xFE


def test_buffer_matches_the_one_accepted_by_the_cp_plus(app):
    app.status["_command_counter"] = 0x15
    app.request_init()

    assert app._get_init_request_buffer() == INIT_REQUEST_16
    assert not app.init_request_pending
    assert app._get_init_request_buffer() is None  # sent only once


def test_flag_ff_in_0x18_answer(app):
    app.request_init()

    assert InetboxLINProtocol(app, False).answer_to_d8_message()[0] == 0xFF


def test_upload_through_lin(app, lin):
    app.status["_command_counter"] = 0x15
    app.request_init()
    upload_request(lin)

    assert queued_buffer(lin) == INIT_REQUEST_16


def test_command_goes_first(app, lin):
    app.process_status_buffer_update(HEATER_STATUS)
    app.status["_command_counter"] = 0x15
    app.set_status("target_temp_room", "19")
    app.request_init()

    upload_request(lin)
    assert queued_buffer(lin)[10:12] == h("0c 32")  # heater command
    assert app.init_request_pending  # still waiting for the next upload

    lin.transportlayer_response_buffer = []
    upload_request(lin)
    assert queued_buffer(lin)[10:12] == h("00 0a")


def test_init_request_when_command_not_possible_yet(app, lin):
    """No status received yet: a command cannot be built, the init request can."""
    app.set_status("target_temp_room", "19")
    app.request_init()
    upload_request(lin)

    assert queued_buffer(lin)[10:12] == h("00 0a")
