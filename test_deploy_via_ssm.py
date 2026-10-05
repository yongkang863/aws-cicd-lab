"""Deployment checks use fake AWS responses and never contact AWS."""

import base64
import json
import shlex
import subprocess
from unittest.mock import Mock

import pytest

from scripts import deploy_via_ssm as deploy


@pytest.fixture(autouse=True)
def isolated_environment(monkeypatch):
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    monkeypatch.setenv("AWS_REGION", "ap-southeast-1")
    monkeypatch.setenv("EC2_INSTANCE_ID", "i-0123456789abcdef0")
    monkeypatch.setenv(
        "LAB_IMAGE_URI",
        "059488919510.dkr.ecr.ap-southeast-1.amazonaws.com/aws-cicd-lab:"
        + "a" * 40 + "-123-1",
    )
    monkeypatch.setattr(deploy.time, "sleep", lambda seconds: None)


def test_script_transport_preserves_content_and_quotes_image():
    script = '#!/bin/bash\nprintf "%s\\n" "$HOME"\n'
    image_uri = "registry/repository:tag; echo unexpected"
    parameters = deploy.make_parameters(script, image_uri)
    lines = parameters["commands"][0].splitlines()
    encoded = shlex.split(lines[3])[2]

    assert base64.b64decode(encoded).decode("utf-8") == script
    assert shlex.split(lines[4]) == ["bash", "$LAB_SCRIPT", image_uri]
    assert parameters["executionTimeout"] == ["600"]


def test_invocation_not_yet_visible_is_retried(monkeypatch):
    result = subprocess.CompletedProcess([], 255, "", "InvocationDoesNotExist")
    monkeypatch.setattr(deploy.subprocess, "run", Mock(return_value=result))
    assert deploy.aws_json("ap-southeast-1", "get-command-invocation") is None


def test_access_denied_is_not_treated_as_pending(monkeypatch):
    result = subprocess.CompletedProcess([], 255, "", "AccessDeniedException")
    monkeypatch.setattr(deploy.subprocess, "run", Mock(return_value=result))
    with pytest.raises(RuntimeError, match="AccessDeniedException"):
        deploy.aws_json("ap-southeast-1", "get-command-invocation")


def test_cli_timeout_requires_inspection_before_retry(monkeypatch):
    monkeypatch.setattr(
        deploy.subprocess, "run",
        Mock(side_effect=subprocess.TimeoutExpired("aws", 120)),
    )
    with pytest.raises(RuntimeError, match="Inspect Systems Manager"):
        deploy.aws_json("ap-southeast-1", "send-command")


def test_waits_for_success_and_prints_ec2_output(monkeypatch, capsys):
    responses = [None, {"Status": "InProgress"}, {
        "Status": "Success", "ResponseCode": 0,
        "StandardOutputContent": "Deployment succeeded",
    }]
    fake_aws = Mock(side_effect=responses)
    monkeypatch.setattr(deploy, "aws_json", fake_aws)

    assert deploy.wait_for_command("ap-southeast-1", "command-id", "instance-id") == 0
    assert fake_aws.call_count == 3
    assert "Deployment succeeded" in capsys.readouterr().out


@pytest.mark.parametrize("status,code", [
    ("Failed", 1), ("TimedOut", -1), ("Cancelled", -1), ("Success", 1),
])
def test_failed_or_incomplete_execution_fails_the_job(monkeypatch, status, code):
    monkeypatch.setattr(deploy, "aws_json", Mock(return_value={
        "Status": status, "ResponseCode": code,
        "StandardErrorContent": "Previous container restored and healthy.",
    }))
    assert deploy.wait_for_command("ap-southeast-1", "command-id", "instance-id") == 1


def test_polling_timeout_does_not_claim_success(monkeypatch):
    monkeypatch.setattr(deploy, "aws_json", Mock(return_value={"Status": "InProgress"}))
    monkeypatch.setattr(deploy.time, "monotonic", Mock(side_effect=[0, 0, 901]))
    with pytest.raises(TimeoutError, match="may still be running"):
        deploy.wait_for_command("ap-southeast-1", "command-id", "instance-id")


@pytest.mark.parametrize("variable,value", [
    ("AWS_REGION", "us-east-1"), ("EC2_INSTANCE_ID", ""), ("LAB_IMAGE_URI", ""),
])
def test_invalid_configuration_never_sends_a_command(monkeypatch, variable, value):
    monkeypatch.setenv(variable, value)
    fake_aws = Mock()
    monkeypatch.setattr(deploy, "aws_json", fake_aws)
    with pytest.raises(ValueError):
        deploy.main()
    fake_aws.assert_not_called()


def test_sends_once_and_waits_for_that_command(monkeypatch):
    fake_aws = Mock(return_value={"Command": {"CommandId": "command-123"}})
    monkeypatch.setattr(deploy, "aws_json", fake_aws)
    fake_wait = Mock(return_value=0)
    monkeypatch.setattr(deploy, "wait_for_command", fake_wait)

    assert deploy.main() == 0
    fake_aws.assert_called_once()
    arguments = fake_aws.call_args.args
    assert arguments[1] == "send-command"
    parameters = json.loads(arguments[arguments.index("--parameters") + 1])
    assert "base64 --decode" in parameters["commands"][0]
    fake_wait.assert_called_once_with("ap-southeast-1", "command-123", "i-0123456789abcdef0")
