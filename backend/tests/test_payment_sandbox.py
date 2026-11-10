import subprocess
from pathlib import Path

import pytest

from backend.payment_sandbox import PaymentSandboxControlAdapter


def adapter(tmp_path: Path, runner, active_config_reader):
    (tmp_path / "payment_api").mkdir()
    (tmp_path / "compose.yaml").write_text("services: {}\n", encoding="utf-8")
    sample = Path(__file__).parents[2] / "payment_api" / "sandbox.env.example"
    (tmp_path / "payment_api" / "sandbox.env.example").write_text(sample.read_text(encoding="utf-8"), encoding="utf-8")
    return PaymentSandboxControlAdapter(
        root=tmp_path,
        runner=runner,
        active_config_reader=active_config_reader,
        audit_path=tmp_path / "audit.jsonl",
        compose_provider="podman-compose-test-provider",
    )


def reject_compose(*arguments, **options):
    raise AssertionError(f"Unexpected Compose call: {arguments} {options}")


def test_pool_change_uses_only_fixed_compose_target_and_verifies_live_state(tmp_path):
    commands = []

    def run(command, **kwargs):
        commands.append(command)
        assert kwargs["timeout"] == 180
        assert command[:2] == ["podman", "compose"]
        assert kwargs["env"]["PODMAN_COMPOSE_PROVIDER"] == "podman-compose-test-provider"
        return subprocess.CompletedProcess(command, 0, "", "")

    control = adapter(
        tmp_path,
        run,
        lambda _: {
            "service": "payment-api",
            "release": "3.8.1",
            "pool_size": 20,
            "max_overflow": 0,
            "pool_timeout": 2,
            "hold_seconds": 0.3,
        },
    )

    result = control.set_pool_size(20, actor_id="operator-1")

    assert result["status"] == "SUCCEEDED"
    assert result["active_config"]["pool_size"] == 20
    assert all(command[command.index("--project-name") + 1] == "behave-payment-sandbox" for command in commands)
    assert all(command[-1] == "payment-api" for command in commands)
    assert all("--force-recreate" in command for command in commands)
    audit = (tmp_path / "audit.jsonl").read_text(encoding="utf-8")
    assert '"status": "PENDING"' in audit
    assert '"status": "SUCCEEDED"' in audit


@pytest.mark.parametrize("release", ["production", "latest", "3.8.2"])
def test_unapproved_release_is_rejected_without_running_compose(tmp_path, release):
    control = adapter(tmp_path, reject_compose, lambda _: {})

    with pytest.raises(ValueError, match="Only the previous release"):
        control.set_release(release)


def test_unapproved_pool_size_is_rejected_without_running_compose(tmp_path):
    control = adapter(tmp_path, reject_compose, lambda _: {})

    with pytest.raises(ValueError, match="Only the calibrated"):
        control.set_pool_size(10)


def test_live_configuration_mismatch_is_not_reported_as_success(tmp_path):
    def command(arguments, **options):
        assert options["check"] is True
        assert arguments[:2] == ["podman", "compose"]
        return subprocess.CompletedProcess(arguments, 0, "", "")

    control = adapter(
        tmp_path,
        command,
        lambda _: {"service": "payment-api", "release": "3.8.1", "pool_size": 5},
    )

    result = control.set_pool_size(20)

    assert result["status"] == "MANUAL_INTERVENTION_REQUIRED"
    assert "does not match" in result["error"]


def test_prepare_sandbox_builds_both_releases_and_verifies_initial_state(tmp_path):
    commands = []

    def run(command, **kwargs):
        commands.append(command)
        assert kwargs["check"] is True
        assert command[:2] == ["podman", "compose"]
        assert kwargs["env"]["PODMAN_COMPOSE_PROVIDER"] == "podman-compose-test-provider"
        assert command[:2] == ["podman", "compose"]
        return subprocess.CompletedProcess(command, 0, "", "")

    control = adapter(
        tmp_path,
        run,
        lambda values: {
            "service": "payment-api",
            "release": values["PAYMENT_API_VERSION"],
            "pool_size": int(values["PAYMENT_DB_POOL_SIZE"]),
            "max_overflow": 0,
            "pool_timeout": 2,
            "hold_seconds": 0.3,
        },
    )

    result = control.prepare_sandbox(actor_id="stage1a-test")

    assert result["status"] == "SUCCEEDED"
    assert control._matches(result["active_config"], "3.8.1", 5)
    build = next(command for command in commands if "build" in command)
    assert build[-2:] == ["payment-api", "payment-api-previous"]
    assert all(command[command.index("--project-name") + 1] == "behave-payment-sandbox" for command in commands)


def test_previous_release_always_uses_pool_size_twenty(tmp_path):
    def run(command, **options):
        assert options["check"] is True
        return subprocess.CompletedProcess(command, 0, "", "")

    control = adapter(
        tmp_path,
        run,
        lambda values: {
            "service": "payment-api",
            "release": values["PAYMENT_API_VERSION"],
            "pool_size": int(values["PAYMENT_DB_POOL_SIZE"]),
            "max_overflow": 0,
            "pool_timeout": 2,
            "hold_seconds": 0.3,
        },
    )

    result = control.set_release("previous")

    assert result["status"] == "SUCCEEDED"
    assert result["active_config"]["pool_size"] == 20
    with pytest.raises(ValueError, match="previous Payment API release must use pool size 20"):
        control.set_pool_size(5)
    with pytest.raises(ValueError, match="previous Payment API release must use pool size 20"):
        control.apply_configuration("previous", 5)