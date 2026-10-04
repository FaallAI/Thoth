"""The seroval-subset decoder over synthetic pages shaped like X's stream; no network."""

from __future__ import annotations

from thoth_control_plane.acquisition.adapters.seroval import decode_scripts


def _page(*scripts: str) -> str:
    return "".join(f'<script nonce="n">{script}</script>' for script in scripts)


def _next(value: str, key: str = "k1", slot: int = 0) -> str:
    return f'($R=>$R[{slot}].next({value}))($R["{key}"]);document.currentScript.remove()'


def test_literals_decode() -> None:
    value = (
        '$R[1]={a:"x\\"y\\\\z",n:-12,f:1.5e2,g:2E3,t:!0,u:!1,v:void 0,w:null,'
        'l:[1,"\\x41\\u00e9"],o:{},e:[],"quoted key":1,7:"seven"}'
    )
    assert decode_scripts(_page(_next(value))) == [
        {
            "a": 'x"y\\z',
            "n": -12,
            "f": 150.0,
            "g": 2000.0,
            "t": True,
            "u": False,
            "v": None,
            "w": None,
            "l": [1, "Aé"],
            "o": {},
            "e": [],
            "quoted key": 1,
            "7": "seven",
        }
    ]


def test_a_surrogate_pair_escape_joins() -> None:
    assert decode_scripts(_page(_next('{s:"\\ud83d\\ude00"}'))) == [{"s": "😀"}]


def test_references_resolve_within_and_across_scripts() -> None:
    first = _next('$R[1]={user:$R[2]={name:"a"},again:$R[2]}')
    second = _next("$R[3]={later:$R[2]}")
    one, two = decode_scripts(_page(first, second))
    assert one["user"] == {"name": "a"}
    assert one["again"] is one["user"]
    assert two["later"] is one["user"]


def test_a_cycle_resolves_to_the_same_object() -> None:
    (value,) = decode_scripts(_page(_next("$R[1]={me:$R[1],list:[$R[1]]}")))
    assert value["me"] is value
    assert value["list"][0] is value


def test_tables_are_per_stream_key() -> None:
    first = _next('$R[1]={v:"a"}', key="a")
    second = _next('$R[1]={v:"b"}', key="b")
    third = _next("{ref:$R[1]}", key="a")
    assert decode_scripts(_page(first, second, third))[2] == {"ref": {"v": "a"}}


def test_an_unknown_reference_is_none() -> None:
    assert decode_scripts(_page(_next("{ref:$R[9]}"))) == [{"ref": None}]


def test_an_unsupported_wrapper_spares_the_others() -> None:
    router = '$_TSR.router=($R=>$R[0]={go:function(){return 1}})($R["k1"])'
    page = _page(router, _next('{ok:"yes"}'), "requestAnimationFrame(function(){})")
    assert decode_scripts(page) == [{"ok": "yes"}]


def test_return_and_throw_wrappers_carry_no_data() -> None:
    page = _page(
        '($R=>$R[0].return(void 0))($R["k1"])',
        '($R=>$R[0].throw({e:1}))($R["k1"])',
    )
    assert decode_scripts(page) == []


def test_an_assignment_wrapper_decodes() -> None:
    assert decode_scripts(_page('($R=>$R[0]={v:1})($R["k1"])')) == [{"v": 1}]


def test_scripts_without_the_table_are_ignored() -> None:
    assert decode_scripts(_page('var x = {a:"b"};', '{"json": true}')) == []


def test_malformed_input_never_raises() -> None:
    for html in (
        _page("($R=>$R[0].next({a:"),
        _page('($R=>$R[0].next({a:"unterminated}))($R["k1"])'),
        _page('($R=>$R[0].next({a:"\\x4"}))($R["k1"])'),
        _page('($R=>$R[0].next({a:"\\ud83d"}))($R["k1"])'),
        _page('($R=>$R[0].next([,1]))($R["k1"])'),
        _page("($R=>$R[0].next({a:1})"),
        _page("($R=>" + "[" * 5_000 + "]" * 5_000 + ')($R["k1"])'),
        "<script>($R=>",
        _page(_next("[" + ",".join(f"$R[{n}]=[$R[{n + 1}]]" for n in range(3_000)) + "]")),
        "",
    ):
        assert decode_scripts(html) == []
