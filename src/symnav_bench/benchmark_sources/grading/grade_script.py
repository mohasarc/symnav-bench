import json
import os
import re
import subprocess
import sys
from collections import namedtuple

CONTAINER_EXIT_MARKER = "Container exited"
ANSI_CODES = re.compile("\x1b\\[[0-9;]*m")


class TestOutcomes(namedtuple("TestOutcomes", ["passed", "failed", "skipped"])):
    __test__ = False

    @classmethod
    def of(cls, passed=(), failed=(), skipped=()):
        return cls(frozenset(passed), frozenset(failed), frozenset(skipped))


def parse_test_log(parser, log_text):
    if parser not in PARSERS:
        raise ValueError("unknown log parser %r" % parser)
    return PARSERS[parser](log_text)


def report_json(text, start_pattern, end_pattern=None):
    match = re.search(start_pattern, text)
    if match is None:
        return None
    start = match.start()
    if end_pattern is not None:
        end_match = re.search(end_pattern, text[start:])
        if end_match is None:
            return None
        raw = text[start : start + end_match.end()]
    else:
        marker = text.find(CONTAINER_EXIT_MARKER, start)
        end = marker if marker != -1 else len(text)
        section = text[start:end]
        brace = section.rfind("}")
        if brace == -1:
            return None
        raw = section[: brace + 1]
    try:
        return json.loads(raw)
    except ValueError:
        return None


def jest_status_buckets(document, title_key):
    passed, failed, skipped = [], [], []
    for suite in document.get("testResults") or []:
        file_name = str(suite.get("name") or "").strip()
        for assertion in suite.get("assertionResults") or []:
            title = str(assertion.get(title_key) or "").strip()
            if not title:
                continue
            name = file_name + "->" + title
            status = assertion.get("status")
            if status == "passed":
                passed.append(name)
            elif status == "failed":
                failed.append(name)
            else:
                skipped.append(name)
    return TestOutcomes.of(passed, failed, skipped)


def parse_jest(text):
    document = report_json(text, r'{\s*"numFailedTestSuites"')
    if document is None:
        return TestOutcomes.of()
    return jest_status_buckets(document, "fullName")


def parse_jest_tailwind(text):
    document = report_json(
        text, r'{\s*"numFailedTestSuites"', r'"wasInterrupted":(true|false)}'
    )
    if document is None:
        return TestOutcomes.of()
    return jest_status_buckets(document, "title")


def parse_mocha(text):
    document = report_json(text, r'{\s*"stats"')
    if document is None:
        return TestOutcomes.of()
    passed = [str(test.get("fullTitle")) for test in document.get("passes") or []]
    failed = [str(test.get("fullTitle")) for test in document.get("failures") or []]
    return TestOutcomes.of(passed, failed)


def parse_mocha_filename(text):
    document = report_json(text, r'{\s*"stats"')
    if document is None:
        return TestOutcomes.of()
    passed, failed = [], []
    for test in document.get("tests") or []:
        name = str(test.get("file") or "") + "->" + str(test.get("fullTitle") or "")
        status = test.get("status")
        if status == "passed":
            passed.append(name)
        elif status == "failed":
            failed.append(name)
    return TestOutcomes.of(passed, failed)


def parse_bazel_angular(text):
    passed, failed = [], []
    for line in text.splitlines():
        clean = ANSI_CODES.sub("", line).strip()
        if "PASSED" in clean:
            bucket, verdict = passed, "PASSED"
        elif "FAILED" in clean:
            bucket, verdict = failed, "FAILED"
        else:
            continue
        name = clean.split(verdict)[0].strip()
        if name.startswith("//"):
            bucket.append(name[1:])
    return TestOutcomes.of(passed, failed)


def parse_jest_darkreader(text):
    passed, failed = set(), set()
    current_suite = None
    pass_suite = re.compile(r"^PASS (\S+)(\s*\(.+\))?$")
    fail_suite = re.compile(r"^FAIL (\S+)(\s*\(.+\))?$")
    pass_test = re.compile(r"^✓ (.+?)(\s+\(.+\))?$")
    fail_test = re.compile(r"^✕ (.+?)(\s+\(.+\))?$")
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        pass_suite_match = pass_suite.match(line)
        if pass_suite_match:
            current_suite = pass_suite_match.group(1)
            passed.add(current_suite)
        fail_suite_match = fail_suite.match(line)
        if fail_suite_match:
            current_suite = fail_suite_match.group(1)
            failed.add(current_suite)
        pass_test_match = pass_test.match(line)
        if pass_test_match:
            if current_suite is None:
                raise ValueError("Test passed without suite: %s" % line)
            passed.add("%s:%s" % (current_suite, pass_test_match.group(1)))
        fail_test_match = fail_test.match(line)
        if fail_test_match:
            if current_suite is None:
                raise ValueError("Test failed without suite: %s" % line)
            failed.add("%s:%s" % (current_suite, fail_test_match.group(1)))
    return TestOutcomes.of(passed, failed)


def parse_vitest_vuejs(text):
    passed, failed = set(), set()
    pass_test = re.compile(r"^✓ (.+?)(?:\s*\d*\.?\d+\s*(?:ms|s|m))?$")
    fail_test = re.compile(r"^× (.+?)(?:\s*\d*\.?\d+\s*(?:ms|s|m))?$")
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        pass_match = pass_test.match(line)
        if pass_match:
            passed.add(pass_match.group(1))
        fail_match = fail_test.match(line)
        if fail_match:
            failed.add(fail_match.group(1))
    return TestOutcomes.of(passed, failed)


MUI_REPORT_KEYS = ("stats", "tests", "pending", "failures", "passes")


def mui_test_name(entry):
    return "%s:%s" % (
        str(entry.get("file") or ""),
        str(entry.get("fullTitle") or ""),
    )


def iterate_json_objects(text):
    decoder = json.JSONDecoder()
    pos = 0
    while True:
        start = text.find("{", pos)
        if start == -1:
            return
        try:
            document, length = decoder.raw_decode(text[start:])
        except ValueError:
            pos = start + 1
            continue
        pos = start + length
        yield document


def parse_mocha_mui(text):
    if "Building new" in text:
        text = text[text.find("Building new") :]
    text = re.sub(r"error Command failed with exit code \d+\.", "", text)
    text = text.replace("\r\n", "").replace("\n", "")
    passed, failed, skipped = set(), set(), set()
    for document in iterate_json_objects(text):
        if not all(key in document for key in MUI_REPORT_KEYS):
            continue
        for entry in document.get("passes") or []:
            passed.add(mui_test_name(entry))
        for entry in document.get("failures") or []:
            failed.add(mui_test_name(entry))
        for entry in document.get("pending") or []:
            skipped.add(mui_test_name(entry))
    passed -= failed
    skipped -= failed
    passed -= skipped
    return TestOutcomes.of(passed, failed, skipped)


PARSERS = {
    "jest": parse_jest,
    "jest-tailwind": parse_jest_tailwind,
    "jest-darkreader": parse_jest_darkreader,
    "mocha": parse_mocha,
    "mocha-filename": parse_mocha_filename,
    "mocha-mui": parse_mocha_mui,
    "bazel-angular": parse_bazel_angular,
    "vitest-vuejs": parse_vitest_vuejs,
}


def unique_names(names):
    seen, ordered = set(), []
    for name in names:
        stripped = str(name).strip()
        if stripped and stripped not in seen:
            seen.add(stripped)
            ordered.append(stripped)
    return ordered


def rewards(outcomes, f2p, p2p, apply_failed=False):
    f2p_ids = unique_names(f2p)
    p2p_ids = unique_names(p2p)

    def test_passed(name):
        return (
            name in outcomes.passed
            and name not in outcomes.failed
            and name not in outcomes.skipped
        )

    f2p_passed = 0 if apply_failed else sum(1 for name in f2p_ids if test_passed(name))
    p2p_passed = 0 if apply_failed else sum(1 for name in p2p_ids if test_passed(name))
    total = len(f2p_ids) + len(p2p_ids)
    solved = (
        not apply_failed
        and len(f2p_ids) > 0
        and f2p_passed == len(f2p_ids)
        and p2p_passed == len(p2p_ids)
    )
    result = {
        "reward": 1 if solved else 0,
        "f2p_total": len(f2p_ids),
        "f2p_passed": f2p_passed,
        "p2p_total": len(p2p_ids),
        "p2p_passed": p2p_passed,
        "f2p": f2p_passed / len(f2p_ids) if f2p_ids else 0.0,
        "p2p": p2p_passed / len(p2p_ids) if p2p_ids else 1.0,
        "partial": (f2p_passed + p2p_passed) / total if total else 0.0,
    }
    if apply_failed:
        result["apply_failed"] = 1
    return result


def log(message):
    print("[verifier] %s" % message)
    sys.stdout.flush()


def tests_dir():
    return os.environ.get("TESTS_DIR", "/tests")


def verifier_dir():
    return os.environ.get("VERIFIER_DIR", "/logs/verifier")


def artifacts_dir():
    return os.environ.get("ARTIFACTS_DIR", "/logs/artifacts")


def load_config():
    with open(os.path.join(tests_dir(), "config.json")) as handle:
        return json.load(handle)


def app_dir(config):
    return os.environ.get("APP_DIR", config["workdir"])


def write_reward(payload):
    make_dirs(verifier_dir())
    with open(os.path.join(verifier_dir(), "reward.json"), "w") as handle:
        handle.write(json.dumps(payload, sort_keys=True))


def make_dirs(path):
    if not os.path.isdir(path):
        os.makedirs(path)


def apply_patch(path):
    returncode = subprocess.call(
        ["git", "apply", "--whitespace=nowarn", "--ignore-whitespace", path]
    )
    if returncode == 0:
        return 0
    try:
        return subprocess.call(["patch", "--batch", "--fuzz=5", "-p1", "-f", "-i", path])
    except OSError:
        log("patch tool unavailable; treating unapplied patch as a failure")
        return 1


def cmd_prepare():
    config = load_config()
    make_dirs(verifier_dir())
    make_dirs(artifacts_dir())
    os.chdir(app_dir(config))
    subprocess.call(
        ["git", "config", "--global", "--add", "safe.directory", app_dir(config)]
    )
    subprocess.call(["git", "reset", "--hard"])

    test_patch = os.path.join(tests_dir(), "test.patch")
    if apply_patch(test_patch) != 0:
        log("ERROR: test.patch failed to apply")
        return 5
    log("test.patch applied")

    model_patch = os.path.join(artifacts_dir(), "model.patch")
    if not os.path.isfile(model_patch) or os.path.getsize(model_patch) == 0:
        log("no model.patch submitted - grading pristine base state")
        return 0
    if apply_patch(model_patch) != 0:
        log("ERROR: submitted model.patch failed to apply")
        write_reward(rewards(TestOutcomes.of(), config["f2p"], config["p2p"], True))
        return 0
    log("model.patch applied (%d bytes)" % os.path.getsize(model_patch))
    return 0


def cmd_grade():
    config = load_config()
    run_log = os.path.join(verifier_dir(), "run.log")
    if os.path.isfile(run_log):
        with open(run_log, errors="replace") as handle:
            log_text = handle.read()
    else:
        log_text = ""
    outcomes = parse_test_log(config["log_parser"], log_text)
    payload = rewards(outcomes, config["f2p"], config["p2p"])
    write_reward(payload)

    def report_bucket(label, names):
        for name in unique_names(names):
            if not (
                name in outcomes.passed
                and name not in outcomes.failed
                and name not in outcomes.skipped
            ):
                log("FAILED [%s] %s" % (label, name))

    report_bucket("f2p", config["f2p"])
    report_bucket("p2p", config["p2p"])
    log(
        "F2P %d/%d P2P %d/%d PARTIAL %s BINARY %d"
        % (
            payload["f2p_passed"],
            payload["f2p_total"],
            payload["p2p_passed"],
            payload["p2p_total"],
            payload["partial"],
            payload["reward"],
        )
    )
    return 0


def main(argv):
    commands = {"prepare": cmd_prepare, "grade": cmd_grade}
    if len(argv) != 1 or argv[0] not in commands:
        print("usage: grade.py {prepare|grade}", file=sys.stderr)
        return 2
    return commands[argv[0]]()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
