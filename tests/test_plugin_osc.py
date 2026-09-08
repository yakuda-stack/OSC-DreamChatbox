"""
tests/test_plugin_osc.py - the "chatbox" and "osc" manifest blocks, and
the endpoint behind api.osc.

What is worth pinning down here.

**The chatbox flag stops exactly two hooks.** get_text() and get_lines()
go quiet; get_values() keeps running. That line is the whole design
decision - a plugin can have nothing to do with the chatbox and still
offer {oscleash_name} to somebody else's line - and it is the kind of
thing a later refactor silently widens into "the plugin contributes
nothing".

**The osc block's defaults**, especially that user_editable is refused
in shared mode. Two settings rows for a port that belongs to the app
would be controls that move nothing, which is worse than no controls.

**The synthetic rows are ordinary settings.** They have to reach
config.json, api.get() and the schema like any other row, and they must
not let an author's own key collide with them.

**Failure is not an exception.** No python-osc, no zeroconf, a port
somebody else is holding: each of those has a defined outcome, because
each of them is a normal Tuesday on a machine with more than one OSC
tool installed.
"""

# Copyright (C) 2026 yakuda
# SPDX-License-Identifier: GPL-3.0-or-later

import json
import socket
import time
from pathlib import Path

from core.oscbridge import OscHub, encode
from core.oscin import OscParameterListener
from core.plugins import (
    OSC_PORT_KEY, OSC_QUERY_KEY, PLUGIN_API_VERSION, PluginManager, parse_osc)

FOLDER = Path("/tmp/does-not-have-to-exist")

PLUGIN_SRC = """
seen = []
def setup(api):
    if api.osc is not None:
        api.osc.subscribe(lambda a, args: seen.append((a, args)),
                          "/avatar/parameters/")
def get_text():
    return "line"
def get_lines():
    return ["extra"]
def get_values():
    return {"mood": "fine"}
"""


def make(**keys):
    data = {"id": "demo", "name": "Demo"}
    data.update(keys)
    return PluginManager._plugin_from_dict(data, FOLDER)


class FakeHost:
    """Just the three attributes the hub reads off the MainWindow."""

    def __init__(self, listener=None, target=None):
        self.osc_in = listener
        self.oscq = None
        self.cfg = ({"osc_ip": target[0], "osc_port": target[1]}
                    if target else {})


def manager(tmp_path, host=None, **manifest):
    folder = tmp_path / "demo"
    folder.mkdir()
    manifest.update({"id": "demo", "name": "Demo", "main": "main.py"})
    (folder / "plugin.json").write_text(json.dumps(manifest),
                                        encoding="utf-8")
    (folder / "main.py").write_text(PLUGIN_SRC, encoding="utf-8")
    mgr = PluginManager(log=lambda *a: None, host=host or FakeHost(),
                        plugins_dir=tmp_path)
    mgr.discover()
    return mgr


# ---------------------------------------------------------- the bump
def test_the_api_version_is_three():
    """api.osc is the first thing a plugin genuinely cannot work
    around, so "api": 3 in a manifest now means something."""
    assert PLUGIN_API_VERSION == 3


# ------------------------------------------------------- chatbox flag
def test_no_chatbox_block_means_on():
    plugin = make()
    assert plugin.chatbox == {"enabled": True, "user_editable": False}


def test_chatbox_can_be_switched_off_by_the_author():
    plugin = make(chatbox={"enabled": False})
    assert plugin.chatbox["enabled"] is False


def test_quoted_booleans_are_accepted():
    """Manifests are hand-written and "true" in quotes is the single
    most common thing an author gets wrong."""
    plugin = make(chatbox={"enabled": "false", "user_editable": "yes"})
    assert plugin.chatbox == {"enabled": False, "user_editable": True}


def test_a_silent_plugin_still_fills_its_placeholders(tmp_path):
    """The whole point of stage 2: OSCLeash has nothing to do with the
    chatbox and still offers {oscleash_name} to someone else's line."""
    mgr = manager(tmp_path, chatbox={"enabled": False})
    mgr.set_enabled("demo", True)
    snap = mgr.snapshot()["demo"]
    assert snap["text"] == ""
    assert snap["lines"] == []
    assert snap["values"] == {"mood": "fine"}


def test_a_normal_plugin_is_unaffected(tmp_path):
    mgr = manager(tmp_path)
    mgr.set_enabled("demo", True)
    snap = mgr.snapshot()["demo"]
    assert snap["text"] == "line"
    assert snap["lines"] == ["extra"]


def test_the_user_switch_overrides_the_manifest(tmp_path):
    mgr = manager(tmp_path,
                  chatbox={"enabled": False, "user_editable": True})
    mgr.set_enabled("demo", True)
    assert mgr.chat_enabled("demo") is False
    mgr.set_chat_enabled("demo", True)
    assert mgr.chat_enabled("demo") is True
    assert mgr.snapshot()["demo"]["text"] == "line"


def test_the_user_switch_survives_a_restart(tmp_path):
    mgr = manager(tmp_path,
                  chatbox={"enabled": True, "user_editable": True})
    mgr.set_chat_enabled("demo", False)
    again = PluginManager(log=lambda *a: None, host=FakeHost(),
                          plugins_dir=tmp_path)
    again.discover()
    assert again.chat_enabled("demo") is False


def test_a_stored_switch_is_ignored_without_the_opt_in(tmp_path):
    """Same rule as the block layout: the author decides whether the
    user gets a say, and an old answer waits rather than being lost."""
    mgr = manager(tmp_path, chatbox={"enabled": True})
    mgr.entry("demo")["chat"] = False
    assert mgr.chat_enabled("demo") is True


# ---------------------------------------------------------- osc block
def test_no_osc_block_means_no_endpoint():
    assert make().osc is None
    assert make(osc={"enabled": False}).osc is None


def test_defaults_are_shared_and_automatic():
    osc = parse_osc({"enabled": True})
    assert osc["mode"] == "shared"
    assert osc["port"] == 0
    assert osc["oscquery"] is True


def test_user_editable_is_refused_in_shared_mode():
    """There is one port and it belongs to the app. A spinbox for it
    would be a control that moves nothing."""
    osc = parse_osc({"enabled": True, "mode": "shared",
                     "user_editable": True})
    assert osc["user_editable"] is False


def test_user_editable_survives_in_own_mode():
    osc = parse_osc({"enabled": True, "mode": "own",
                     "user_editable": True})
    assert osc["user_editable"] is True


def test_an_unknown_mode_falls_back_to_shared():
    assert parse_osc({"enabled": True, "mode": "magic"})["mode"] == "shared"


def test_a_nonsense_port_falls_back_to_automatic():
    for port in ("nope", -1, 70000, None):
        assert parse_osc({"enabled": True, "port": port})["port"] == 0


# ------------------------------------------------- synthetic settings
def test_the_rows_appear_only_where_they_do_something():
    assert make(osc={"enabled": True}).schema == []
    assert make(osc={"enabled": True, "mode": "own"}).schema == []
    rows = make(osc={"enabled": True, "mode": "own",
                     "user_editable": True}).schema
    assert [i["key"] for i in rows] == ["osc"]
    assert [i["key"] for i in rows[0]["items"]] == [OSC_PORT_KEY,
                                                    OSC_QUERY_KEY]


def test_the_rows_carry_the_manifest_values_as_defaults():
    plugin = make(osc={"enabled": True, "mode": "own", "port": 9945,
                       "oscquery": False, "user_editable": True})
    items = {i["key"]: i["default"] for i in plugin.schema[0]["items"]}
    assert items[OSC_PORT_KEY] == 9945
    assert items[OSC_QUERY_KEY] is False


def test_an_author_key_cannot_collide_with_a_reserved_one():
    plugin = make(osc={"enabled": True, "mode": "own",
                       "user_editable": True},
                  settings=[{"key": OSC_PORT_KEY, "type": "text",
                             "default": "mine"}])
    assert [i["key"] for i in plugin.schema] == ["osc"]


def test_the_reserved_keys_are_free_without_an_endpoint():
    """Nothing to collide with, so an author may use the name."""
    plugin = make(settings=[{"key": OSC_PORT_KEY, "type": "text",
                             "default": "mine"}])
    assert [i["key"] for i in plugin.schema] == [OSC_PORT_KEY]


def test_the_rows_go_last():
    """The app's plumbing must not push the author's first row down."""
    plugin = make(osc={"enabled": True, "mode": "own",
                       "user_editable": True},
                  settings=[{"key": "a", "type": "bool", "default": True}])
    assert [i["key"] for i in plugin.schema] == ["a", "osc"]


# ------------------------------------------------------- the endpoint
def test_no_block_means_api_osc_is_none(tmp_path):
    mgr = manager(tmp_path)
    mgr.set_enabled("demo", True)
    assert mgr.plugins["demo"].api.osc is None


def test_a_shared_endpoint_reads_the_apps_stream(tmp_path):
    listener = OscParameterListener(log_fn=lambda *a: None)
    assert listener.start(port=0)
    try:
        mgr = manager(tmp_path, host=FakeHost(listener), api=3,
                      osc={"enabled": True})
        mgr.set_enabled("demo", True)
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.sendto(encode("/avatar/parameters/Demo", [0.5]),
                    ("127.0.0.1", listener.port))
        sock.sendto(encode("/somewhere/else", [1]),
                    ("127.0.0.1", listener.port))
        deadline = time.time() + 2
        seen = mgr.plugins["demo"].module.seen
        while not seen and time.time() < deadline:
            time.sleep(0.02)
        assert seen == [("/avatar/parameters/Demo", [0.5])]
        mgr.set_enabled("demo", False)
    finally:
        listener.stop()


def test_the_prefix_filter_is_not_optional(tmp_path):
    """A subscriber asking for avatar parameters must not be handed the
    rest of the stream - it would treat them as parameters."""
    listener = OscParameterListener(log_fn=lambda *a: None)
    assert listener.start(port=0)
    try:
        mgr = manager(tmp_path, host=FakeHost(listener), api=3,
                      osc={"enabled": True})
        mgr.set_enabled("demo", True)
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.sendto(encode("/somewhere/else", [1]),
                    ("127.0.0.1", listener.port))
        time.sleep(0.3)
        assert mgr.plugins["demo"].module.seen == []
        mgr.set_enabled("demo", False)
    finally:
        listener.stop()


def test_an_own_endpoint_binds_the_port_it_was_given(tmp_path):
    mgr = manager(tmp_path, api=3,
                  osc={"enabled": True, "mode": "own", "port": 0,
                       "oscquery": False})
    mgr.set_enabled("demo", True)
    endpoint = mgr.plugins["demo"].api.osc
    assert endpoint.mode == "own"
    assert endpoint.port > 0          # 0 means "pick one", not "none"
    assert endpoint.available
    mgr.set_enabled("demo", False)


def test_a_taken_port_falls_back_instead_of_failing(tmp_path):
    """Another OSC tool on that port is a normal situation. Everything
    that finds the plugin through OSCQuery keeps working."""
    busy = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    busy.bind(("0.0.0.0", 0))
    taken = busy.getsockname()[1]
    try:
        mgr = manager(tmp_path, api=3,
                      osc={"enabled": True, "mode": "own", "port": taken,
                           "oscquery": False})
        mgr.set_enabled("demo", True)
        endpoint = mgr.plugins["demo"].api.osc
        assert endpoint.port not in (0, taken)
        assert endpoint.available
        mgr.set_enabled("demo", False)
    finally:
        busy.close()


def test_send_reaches_an_explicit_target(tmp_path):
    rx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    rx.bind(("127.0.0.1", 0))
    rx.settimeout(2)
    try:
        mgr = manager(tmp_path, api=3, osc={"enabled": True})
        mgr.set_enabled("demo", True)
        endpoint = mgr.plugins["demo"].api.osc
        assert endpoint.send("/avatar/parameters/Out", 1.0,
                             to=("127.0.0.1", rx.getsockname()[1]))
        from pythonosc.osc_packet import OscPacket
        data, _ = rx.recvfrom(4096)
        message = OscPacket(data).messages[0].message
        assert message.address == "/avatar/parameters/Out"
        assert list(message.params) == [1.0]
        mgr.set_enabled("demo", False)
    finally:
        rx.close()


def test_send_without_a_target_says_no(tmp_path):
    """Rather than shouting at 9000 on the off-chance. A plugin can tell
    the user "no VRChat found"; it cannot notice a silent nowhere."""
    mgr = manager(tmp_path, api=3, osc={"enabled": True})
    mgr.set_enabled("demo", True)
    endpoint = mgr.plugins["demo"].api.osc
    assert endpoint.target is None
    assert endpoint.send("/avatar/parameters/Out", 1.0) is False
    mgr.set_enabled("demo", False)


def test_the_target_comes_from_the_apps_settings(tmp_path):
    mgr = manager(tmp_path, host=FakeHost(target=("127.0.0.1", 9002)),
                  api=3, osc={"enabled": True})
    mgr.set_enabled("demo", True)
    assert mgr.plugins["demo"].api.osc.target == ("127.0.0.1", 9002)
    mgr.set_enabled("demo", False)


def test_the_endpoint_is_gone_after_unloading(tmp_path):
    mgr = manager(tmp_path, api=3,
                  osc={"enabled": True, "mode": "own", "oscquery": False})
    mgr.set_enabled("demo", True)
    port = mgr.plugins["demo"].api.osc.port
    mgr.set_enabled("demo", False)
    assert mgr.plugins["demo"].endpoint is None
    # the socket really went away, so the port can be taken again
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        probe.bind(("0.0.0.0", port))
    finally:
        probe.close()


def test_a_callback_that_raises_is_dropped_not_fatal():
    """One bad plugin must not take the OSC link down for the others."""
    hub = OscHub(host=FakeHost(), log=lambda *a: None)
    endpoint = hub.open("demo", {"enabled": True, "mode": "shared"})
    good = []

    def bad(address, args):
        raise ValueError("boom")

    endpoint.subscribe(bad)
    endpoint.subscribe(lambda a, args: good.append(a))
    endpoint._dispatch("/x", [1])
    endpoint._dispatch("/x", [2])
    assert good == ["/x", "/x"]
    hub.close("demo")


def test_rebinding_lands_on_the_port_the_user_typed(tmp_path):
    """The regression this file exists for: close() used to return
    while the receive thread still held the socket, so the reopen
    immediately after it found its own old port taken and fell back to
    a random one - the number the user just entered being the one port
    it would not use."""
    mgr = manager(tmp_path, api=3,
                  osc={"enabled": True, "mode": "own", "port": 0,
                       "oscquery": False, "user_editable": True})
    mgr.set_enabled("demo", True)
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    probe.bind(("0.0.0.0", 0))
    wanted = probe.getsockname()[1]
    probe.close()

    mgr.set_option("demo", OSC_PORT_KEY, wanted)
    assert mgr.plugins["demo"].api.osc.port == wanted
    # and again, onto the very port it is already sitting on
    mgr.set_option("demo", OSC_PORT_KEY, wanted)
    assert mgr.plugins["demo"].api.osc.port == wanted
    mgr.set_enabled("demo", False)
