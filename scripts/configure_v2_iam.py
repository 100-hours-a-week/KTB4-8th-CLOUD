"""Prepare/apply additive IAM changes for the verified Cloud/dev and app/develop subjects.

Default: read IAM and write reviewable JSON to infrastructure/v2-cd/. --apply rereads and
merges the same additions. No production subjects or existing role policies are removed.
"""
import argparse
import json
from pathlib import Path

from v2_common import AWS, Error, ROOT, check_account, load_config

SUBJECT = "token.actions.githubusercontent.com:sub"
ADDITIONS = {
    "keepgo-v2-github-deploy": "repo:100-hours-a-week@167328634/KTB4-8th-CLOUD@1344688950:environment:dev",
    "keepgo-be-ecr-push": "repo:100-hours-a-week@167328634/KTB4-8th-BE@1344686243:ref:refs/heads/develop",
    "keepgo-ai-ecr-push": "repo:100-hours-a-week@167328634/KTB4-8th-AI@1344686800:ref:refs/heads/develop",
}


def add_subject(document, subject):
    """Add a separate exact-subject statement, preserving all existing trust conditions."""
    condition = {"StringEquals": {"token.actions.githubusercontent.com:aud": "sts.amazonaws.com", SUBJECT: subject}}
    statement = {"Sid": "CloudV2Development" if ":environment:" in subject else "DevelopImagePublishing",
                 "Effect": "Allow", "Principal": {"Federated": "arn:aws:iam::602601433533:oidc-provider/token.actions.githubusercontent.com"},
                 "Action": "sts:AssumeRoleWithWebIdentity", "Condition": condition}
    existing = [item for item in document["Statement"] if item.get("Sid") == statement["Sid"]]
    if existing and existing != [statement]:
        raise Error("Existing IAM statement with the same Sid differs; inspect before applying")
    if not existing:
        document["Statement"].append(statement)
    return document


def support_policy():
    prefix = "arn:aws:ecs:ap-northeast-2:602601433533:"
    return {"Version": "2012-10-17", "Statement": [
        {"Sid": "ReadDeploymentAndImageState", "Effect": "Allow", "Action": [
            "ecs:ListTasks", "elasticloadbalancing:DescribeTargetHealth"], "Resource": "*"},
        {"Sid": "ReadV2Tasks", "Effect": "Allow", "Action": ["ecs:DescribeTasks"],
         "Resource": prefix + "task/keepgo-v2/*"},
        {"Sid": "PreserveTaskDefinitionTags", "Effect": "Allow", "Action": ["ecs:ListTagsForResource", "ecs:TagResource"],
         "Resource": [prefix + "task-definition/keepgo-v2-backend:*", prefix + "task-definition/keepgo-v2-ai-api:*"]},
        {"Sid": "VerifyPublishedImages", "Effect": "Allow", "Action": ["ecr:DescribeImages", "ecr:BatchGetImage"],
         "Resource": ["arn:aws:ecr:ap-northeast-2:602601433533:repository/keepgo-backend",
                      "arn:aws:ecr:ap-northeast-2:602601433533:repository/keepgo-ai"]},
        {"Sid": "PersistV2DeploymentState", "Effect": "Allow", "Action": ["ssm:GetParameter", "ssm:PutParameter"],
         "Resource": ["arn:aws:ssm:ap-northeast-2:602601433533:parameter/keepgo/v2-dev/deployments/backend",
                      "arn:aws:ssm:ap-northeast-2:602601433533:parameter/keepgo/v2-dev/deployments/ai"]},
    ]}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    config = load_config()
    aws = AWS(config["region"])
    check_account(aws, config)
    directory = ROOT / "infrastructure/v2-cd"
    directory.mkdir(parents=True, exist_ok=True)
    for role, subject in ADDITIONS.items():
        original = aws.call("iam", "get-role", role_name=role)["Role"]["AssumeRolePolicyDocument"]
        document = add_subject(original, subject)
        (directory / f"{role}-trust.json").write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
        if args.apply:
            aws.call("iam", "update-assume-role-policy", payload={"RoleName": role, "PolicyDocument": json.dumps(document)})
            actual = aws.call("iam", "get-role", role_name=role)["Role"]["AssumeRolePolicyDocument"]
            if actual != document:
                raise Error("IAM trust verification failed: " + role)
        print(("Applied and verified: " if args.apply else "Prepared: ") + role)
    document = support_policy()
    (directory / "cloud-v2-dev-cd-policy.json").write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    if args.apply:
        aws.call("iam", "put-role-policy", payload={"RoleName": "keepgo-v2-github-deploy",
                 "PolicyName": "cloud-v2-dev-cd", "PolicyDocument": json.dumps(document)})
        actual = aws.call("iam", "get-role-policy", role_name="keepgo-v2-github-deploy",
                          policy_name="cloud-v2-dev-cd")["PolicyDocument"]
        if actual != document:
            raise Error("IAM support policy verification failed")
    print("Existing production subjects and policies preserved")


if __name__ == "__main__":
    main()
