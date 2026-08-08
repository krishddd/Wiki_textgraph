"""``textgraph doctor`` — the read-only environment health check."""

import json

import pytest
from textgraph.cli import main
from textgraph.doctor import (
    FAIL,
    OK,
    WARN,
    Check,
    check_names,
    format_text,
    run_checks,
)


def test_run_checks_covers_every_registered_name() -> None:
    checks = run_checks()
    assert [c.name for c in checks] == check_names()
    # Core invariants that must hold on any machine that can run the test suite.
    by_name = {c.name: c for c in checks}
    assert by_name["python-version"].status == OK  # we're on >=3.11 by definition
    assert by_name["core-import"].status == OK
    assert by_name["determinism"].status == OK  # byte-identical build, proven here


def test_determinism_check_is_the_marquee_guarantee() -> None:
    (check,) = run_checks(["determinism"])
    assert check.name == "determinism"
    assert check.status == OK
    assert "byte-identical" in check.detail


def test_run_checks_subset_preserves_registry_order() -> None:
    got = run_checks(["determinism", "python-version"])
    # Requested order is honored (not registry order) so --check is predictable.
    assert [c.name for c in got] == ["determinism", "python-version"]


def test_unknown_check_raises_keyerror() -> None:
    with pytest.raises(KeyError):
        run_checks(["does-not-exist"])


def test_check_ok_property_only_false_on_fail() -> None:
    assert Check("x", OK, "").ok is True
    assert Check("x", WARN, "").ok is True
    assert Check("x", FAIL, "").ok is False


def test_details_are_ascii_for_cp1252_consoles() -> None:
    # Windows console is cp1252 — printed detail strings must encode cleanly.
    for c in run_checks():
        c.detail.encode("ascii")  # raises UnicodeEncodeError if a non-ASCII char slipped in


def test_format_text_summarizes_status_counts() -> None:
    checks = [Check("a", OK, "fine"), Check("b", WARN, "optional missing")]
    text = format_text(checks)
    assert "[ok]" in text and "[warn]" in text
    assert "core is healthy" in text  # warnings only -> core healthy
    fail_text = format_text([Check("c", FAIL, "broken")])
    assert "NOT healthy" in fail_text


def test_doctor_cli_default_is_healthy(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["doctor"]) == 0  # no FAIL checks on a working install
    out = capsys.readouterr().out
    assert "textgraph doctor" in out
    assert "determinism" in out


def test_doctor_cli_json_is_machine_readable(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["doctor", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert {c["name"] for c in payload} == set(check_names())
    assert all({"name", "status", "detail"} == c.keys() for c in payload)


def test_doctor_cli_single_check(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["doctor", "--check", "determinism"]) == 0
    out = capsys.readouterr().out
    assert "determinism" in out
    assert "python-version" not in out


def test_doctor_cli_unknown_check_errors(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["doctor", "--check", "nope"]) == 2
    err = capsys.readouterr().err
    assert "unknown check" in err
    assert "determinism" in err  # lists the valid names
