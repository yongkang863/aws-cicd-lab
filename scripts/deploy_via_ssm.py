"""Run on the GitHub runner: send deploy.sh to EC2 and check its result."""

import base64
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
import time


def aws_json(region, *arguments):
    """Use the runner's AWS CLI and its temporary OIDC credentials."""
    command = [
        "aws", "--region", region, "--no-cli-pager", "--output", "json",
        "--cli-connect-timeout", "10", "--cli-read-timeout", "20",
        "ssm", *arguments,
    ]
    try:
        result = subprocess.run(
            command, capture_output=True, text=True, check=False, timeout=120
        )
    except subprocess.TimeoutExpired as error:
        raise RuntimeError(
            "AWS CLI timed out. Inspect Systems Manager Run Command before retrying."
        ) from error
    if result.returncode:
        # A just-created command can take a few seconds to appear in this API.
        if arguments[0] == "get-command-invocation" and "InvocationDoesNotExist" in result.stderr:
            return None
        raise RuntimeError(result.stderr.strip() or "AWS CLI request failed.")
    return json.loads(result.stdout)


def make_parameters(script, image_uri):
    """Encode the script for transport; base64 is encoding, not encryption."""
    encoded = base64.b64encode(script.encode("utf-8")).decode("ascii")
    remote_command = (
        "set -eu\n"
        "LAB_SCRIPT=$(mktemp /tmp/cicd-lab-deploy.XXXXXX)\n"
        "trap 'rm -f \"$LAB_SCRIPT\"' EXIT\n"
        f"printf '%s' {shlex.quote(encoded)} | base64 --decode > \"$LAB_SCRIPT\"\n"
        f"bash \"$LAB_SCRIPT\" {shlex.quote(image_uri)}\n"
    )
    return {"commands": [remote_command], "executionTimeout": ["600"]}


def write_summary(message):
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        with open(summary_path, "a", encoding="utf-8") as summary:
            summary.write(message + "\n")


def wait_for_command(region, command_id, instance_id, timeout_seconds=900):
    deadline = time.monotonic() + timeout_seconds
    previous_status = None
    waiting_statuses = {"Pending", "InProgress", "Delayed", "Cancelling"}

    while time.monotonic() < deadline:
        result = aws_json(
            region, "get-command-invocation",
            "--command-id", command_id, "--instance-id", instance_id,
        )
        if result is not None:
            status = result["Status"]
            if status != previous_status:
                print(f"SSM status: {status}", flush=True)
                previous_status = status
            if status not in waiting_statuses:
                print("EC2 stdout:\n" + result.get("StandardOutputContent", ""), flush=True)
                print("EC2 stderr:\n" + result.get("StandardErrorContent", ""), flush=True)
                response_code = result.get("ResponseCode")
                write_summary(f"- SSM result: **{status}**; exit code: `{response_code}`")
                return 0 if status == "Success" and response_code == 0 else 1
        time.sleep(5)

    raise TimeoutError(
        f"Stopped waiting for SSM command {command_id}. It may still be running; "
        "inspect Systems Manager Run Command before retrying."
    )


def main():
    region = os.environ.get("AWS_REGION", "")
    instance_id = os.environ.get("EC2_INSTANCE_ID", "")
    image_uri = os.environ.get("LAB_IMAGE_URI", "")

    if region != "ap-southeast-1":
        raise ValueError("AWS_REGION must be ap-southeast-1 for this lab.")
    if not re.fullmatch(r"i-(?:[0-9a-f]{8}|[0-9a-f]{17})", instance_id):
        raise ValueError("EC2_INSTANCE_ID is missing or invalid. Check the repository variable.")
    image_pattern = (
        r"059488919510\.dkr\.ecr\.ap-southeast-1\.amazonaws\.com/"
        r"aws-cicd-lab:[0-9a-f]{40}-[0-9]+-[0-9]+"
    )
    if not re.fullmatch(image_pattern, image_uri):
        raise ValueError("LAB_IMAGE_URI is missing or is not an image tag from this pipeline.")

    # read_text normalizes Windows CRLF endings to Linux LF endings.
    script = Path(__file__).with_name("deploy.sh").read_text(encoding="utf-8-sig")
    response = aws_json(
        region, "send-command",
        "--instance-ids", instance_id,
        "--document-name", "AWS-RunShellScript",
        "--timeout-seconds", "60",
        "--comment", "Deploy aws-cicd-lab from GitHub Actions",
        "--parameters", json.dumps(make_parameters(script, image_uri)),
    )
    command_id = response["Command"]["CommandId"]
    print(f"SSM command ID: {command_id}", flush=True)
    write_summary(
        "## EC2 deployment\n"
        f"- Image: `{image_uri}`\n"
        f"- Instance: `{instance_id}`\n"
        f"- SSM command: `{command_id}`"
    )
    return wait_for_command(region, command_id, instance_id)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (RuntimeError, ValueError, OSError) as error:
        print(f"Deployment error: {error}", file=sys.stderr, flush=True)
        sys.exit(1)
