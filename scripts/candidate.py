#!/usr/bin/env python3
"""신뢰된 기준 브랜치에서 실행하며 후보 PR은 JSON 데이터로만 읽는다."""
import base64
import copy
import json
import os
import sys
from release import ROOT, GROUPS, github, load, resolve_images, validate_manifest, verify_source

MANIFEST = "deployment/production-manifest.json"


def get_file(repo, ref, token):
    value = github(f"repos/{repo}/contents/{MANIFEST}?ref={ref}", token)
    return json.loads(base64.b64decode(value["content"])), value["sha"]


def diff_groups(before, after):
    return [g for g in GROUPS if before["sources"][g] != after["sources"][g] or
            any(before["images"][s] != after["images"][s] for s in GROUPS[g])]


def require_review(repo, pr, token):
    reviews = github(f"repos/{repo}/pulls/{pr['number']}/reviews?per_page=100", token)
    latest = {}
    for review in reviews:
        if review["state"] in ("APPROVED", "CHANGES_REQUESTED", "DISMISSED"):
            latest[review["user"]["login"]] = review
    for login, review in latest.items():
        if login == pr["user"]["login"] or review["state"] != "APPROVED" or review["commit_id"] != pr["head"]["sha"]:
            continue
        permission = github(f"repos/{repo}/collaborators/{login}/permission", token)["permission"]
        if permission in ("admin", "maintain", "write"):
            return
    raise ValueError("Current-head approval by a different maintainer required; rerun this gate after review")


def gate(event, repo, token, source_token, policy):
    number = event["pull_request"]["number"]
    pr = github(f"repos/{repo}/pulls/{number}", token)
    head = pr["head"]["sha"]
    is_bot = pr["user"]["login"] == os.environ["CD_BOT_LOGIN"]
    if pr["base"]["ref"] != "main":
        raise ValueError("Only main PRs are accepted")
    # pull_request_target에서도 검사 결과를 검증한 PR의 정확한 커밋에 기록한다.
    def status(state, description):
        github(f"repos/{repo}/statuses/{head}", token, "POST", {
            "state": state, "context": "release-policy", "description": description})
    status("pending", "Checking trusted release policy")
    try:
        files = github(f"repos/{repo}/pulls/{number}/files?per_page=100", token)
        if pr["changed_files"] != len(files):
            raise ValueError("PR too large for automatic policy evaluation")
        manifest_only = [f["filename"] for f in files] == [MANIFEST] and files[0]["status"] == "modified"
        if not manifest_only:
            if is_bot:
                raise ValueError("Release bot may only change the manifest")
            require_review(repo, pr, token)
            status("success", "Platform PR: current-head maintainer approval verified")
            return
        if pr["head"]["repo"]["full_name"] != repo:
            raise ValueError("Manifest PR must originate in the Cloud repository")
        before, _ = get_file(repo, pr["base"]["sha"], token)
        after, _ = get_file(repo, head, token)
        validate_manifest(after)
        groups = diff_groups(before, after)
        if is_bot and len(groups) != 1:
            raise ValueError("Automatic candidate must change exactly one deployment unit")
        for group in groups:
            verify_source(group, after["sources"][group], policy, source_token, latest=is_bot)
        resolve_images(after, policy, os.environ["AWS_ACCOUNT_ID"])
        # 검사 결과를 기록하고 자동 병합을 켜기 직전에 PR 커밋을 다시 확인한다.
        if github(f"repos/{repo}/pulls/{number}", token)["head"]["sha"] != head:
            raise ValueError("PR head changed while validating")
        if not is_bot:
            require_review(repo, pr, token)
        status("success", "Source CI, deployment unit and ECR images verified")
        if is_bot:
            result = github("graphql", token, "POST", {
                "query": "mutation($id:ID!){enablePullRequestAutoMerge(input:{pullRequestId:$id,mergeMethod:SQUASH}){pullRequest{id}}}",
                "variables": {"id": pr["node_id"]}})
            if result.get("errors"):
                raise RuntimeError("GitHub refused auto-merge; check repository rules / plan")
    except Exception:
        status("failure", "Release policy rejected; inspect workflow log")
        raise


def create(event, repo, token, source_token, policy):
    if event["sender"]["login"] != os.environ["CD_BOT_LOGIN"]:
        raise ValueError("repository_dispatch sender is not the allowed GitHub App")
    payload = event["client_payload"]
    if set(payload) != {"group", "sha", "run_id"} or payload["group"] not in GROUPS:
        raise ValueError("Expected group, sha and run_id")
    group = payload["group"]
    base = github(f"repos/{repo}/git/ref/heads/main", token)["object"]["sha"]
    manifest, blob = get_file(repo, base, token)
    candidate = copy.deepcopy(manifest)
    candidate["sources"][group] = {"sha": payload["sha"], "run_id": payload["run_id"]}
    for service in GROUPS[group]:
        candidate["images"][service] = payload["sha"]
    validate_manifest(candidate)  # 최초 연결 전에 유효한 전체 배포 목록이 필요하다.
    verify_source(group, candidate["sources"][group], policy, source_token)
    resolve_images(candidate, policy, os.environ["AWS_ACCOUNT_ID"])
    if candidate == manifest:
        print("Candidate already desired")
        return
    branch = f"release/{group}-{payload['sha']}-{payload['run_id']}"
    open_prs = github(f"repos/{repo}/pulls?state=open&base=main&per_page=100", token)
    for pr in open_prs:
        if pr["head"]["ref"] == branch:
            print("Candidate PR already exists")
            return
    for pr in open_prs:
        if pr["user"]["login"] == os.environ["CD_BOT_LOGIN"] and pr["head"]["ref"].startswith(f"release/{group}-"):
            github(f"repos/{repo}/pulls/{pr['number']}", token, "PATCH", {"state": "closed"})
    github(f"repos/{repo}/git/refs", token, "POST", {"ref": "refs/heads/" + branch, "sha": base})
    github(f"repos/{repo}/contents/{MANIFEST}", token, "PUT", {
        "branch": branch, "sha": blob, "message": f"release: {group} {payload['sha']}",
        "content": base64.b64encode((json.dumps(candidate, indent=2) + "\n").encode()).decode()})
    pr = github(f"repos/{repo}/pulls", token, "POST", {
        "title": f"release: {group} {payload['sha'][:12]}", "head": branch, "base": "main",
        "body": f"Automated candidate from {policy[group]['repository']} CI run {payload['run_id']}.\n\nOnly this deployment unit is updated. Source CI and ECR are checked again before auto-merge."})
    print(pr["html_url"])


def refresh(repo, token):
    for pr in github(f"repos/{repo}/pulls?state=open&base=main&per_page=100", token):
        if pr["user"]["login"] != os.environ["CD_BOT_LOGIN"] or not pr["head"]["ref"].startswith("release/"):
            continue
        detail = github(f"repos/{repo}/pulls/{pr['number']}", token)
        if detail["mergeable_state"] == "behind":
            github(f"repos/{repo}/pulls/{pr['number']}/update-branch", token, "PUT",
                   {"expected_head_sha": pr["head"]["sha"]})


def poll(repo, token, source_token, policy):
    # GitHub 동시 실행 제어로 대기 중 알림이 생략될 수 있어 성공한 CI를 주기적으로 확인한다.
    # 후보는 원본 저장소 main의 최신 커밋만 선택한다.
    for group, p in policy.items():
        if "CONFIGURE" in json.dumps(p):
            raise ValueError("Complete source policy before enabling automatic intake")
        sha = github(f"repos/{p['repository']}/commits/main", source_token)["sha"]
        runs = github(f"repos/{p['repository']}/actions/runs?branch=main&event=push&status=success&head_sha={sha}&per_page=100", source_token)["workflow_runs"]
        matching = [r for r in runs if r["path"] == p["workflow"] and r["head_sha"] == sha]
        if matching:
            ci = max(matching, key=lambda r: r["id"])
            try:
                create({"sender": {"login": os.environ["CD_BOT_LOGIN"]},
                        "client_payload": {"group": group, "sha": sha, "run_id": ci["id"]}},
                       repo, token, source_token, policy)
            except ValueError as error:
                print(f"Candidate {group} rejected: {error}")


if __name__ == "__main__":
    event = load(os.environ["GITHUB_EVENT_PATH"])
    args = (os.environ["GITHUB_REPOSITORY"], os.environ["GH_TOKEN"])
    if sys.argv[1] == "refresh":
        refresh(*args)
        poll(*args, os.environ["SOURCE_READ_TOKEN"], load(ROOT / "deployment/source-policy.json"))
    else:
        action = create if sys.argv[1] == "create" else gate
        action(event, *args, os.environ["SOURCE_READ_TOKEN"], load(ROOT / "deployment/source-policy.json"))
