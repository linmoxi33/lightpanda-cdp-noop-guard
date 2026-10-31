#!/usr/bin/env python3
"""Behaviour tests for lightpanda-cdp-noop-guard. Run: python3 -m unittest discover -s tests -v"""
import json
import os
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CLI = os.path.join(ROOT, "bin", "lightpanda-cdp-noop-guard")
EXAMPLES = os.path.join(ROOT, "examples", "in")


def run(args, stdin=None):
    proc = subprocess.run([sys.executable, CLI] + args, capture_output=True, text=True, input=stdin)
    return proc.returncode, proc.stdout, proc.stderr


def write_tmp(content, suffix=".jsonl"):
    fd, path = tempfile.mkstemp(suffix=suffix)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(content)
    return path


class CleanTraceTests(unittest.TestCase):
    def test_clean_trace_exits_zero(self):
        code, out, _ = run([os.path.join(EXAMPLES, "clean-session.jsonl")])
        self.assertEqual(code, 0)
        self.assertIn("PASS", out)

    def test_clean_json_verdict_pass(self):
        code, out, _ = run([os.path.join(EXAMPLES, "clean-session.jsonl"), "--json"])
        self.assertEqual(code, 0)
        report = json.loads(out)
        self.assertEqual(report["verdict"], "pass")
        self.assertEqual(report["error_hits"], 0)


class NoopDetectionTests(unittest.TestCase):
    def test_noop_trace_exits_one(self):
        code, out, _ = run([os.path.join(EXAMPLES, "playwright-darkmode.jsonl")])
        self.assertEqual(code, 1)
        self.assertIn("Emulation.setEmulatedMedia", out)

    def test_json_reports_two_error_hits(self):
        code, out, _ = run([os.path.join(EXAMPLES, "playwright-darkmode.jsonl"), "--json"])
        self.assertEqual(code, 1)
        report = json.loads(out)
        self.assertEqual(report["error_hits"], 2)
        self.assertEqual(report["verdict"], "fail")
        self.assertEqual(report["total_calls"], 6)

    def test_hit_carries_pinned_source_url(self):
        _, out, _ = run([os.path.join(EXAMPLES, "playwright-darkmode.jsonl"), "--json"])
        report = json.loads(out)
        urls = [h["source_url"] for h in report["hits"]]
        self.assertTrue(all(u.startswith("https://github.com/lightpanda-io/browser/blob/") for u in urls))
        self.assertTrue(any(u.endswith("#L62") for u in urls))

    def test_repeated_calls_are_counted(self):
        path = write_tmp('{"method":"Emulation.setEmulatedMedia"}\n'
                         '{"method":"Emulation.setEmulatedMedia"}\n'
                         '{"method":"Emulation.setTouchEmulationEnabled"}\n')
        code, out, _ = run([path, "--json"])
        self.assertEqual(code, 1)
        report = json.loads(out)
        self.assertEqual(report["hits"][0]["count"], 2)
        os.unlink(path)

    def test_wrapped_message_form_is_supported(self):
        path = write_tmp('{"direction":"send","message":{"method":"Browser.setWindowBounds"}}\n')
        code, out, _ = run([path, "--json"])
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(out)["hits"][0]["method"], "Browser.setWindowBounds")
        os.unlink(path)


class StrictModeTests(unittest.TestCase):
    def test_partial_is_warning_by_default(self):
        code, out, _ = run([os.path.join(EXAMPLES, "cookie-partial.json")])
        self.assertEqual(code, 0)
        self.assertIn("WARN", out)

    def test_strict_escalates_warning_to_failure(self):
        code, out, _ = run([os.path.join(EXAMPLES, "cookie-partial.json"), "--strict", "--json"])
        self.assertEqual(code, 1)
        report = json.loads(out)
        self.assertEqual(report["warning_hits"], 2)
        self.assertEqual(report["verdict"], "fail")

    def test_json_array_input_is_accepted(self):
        code, out, _ = run([os.path.join(EXAMPLES, "cookie-partial.json"), "--json"])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["total_calls"], 3)


class InputErrorTests(unittest.TestCase):
    def test_missing_trace_argument_exits_two(self):
        code, _, err = run([])
        self.assertEqual(code, 2)
        self.assertIn("missing TRACE", err)

    def test_nonexistent_trace_exits_two(self):
        code, _, err = run(["/tmp/definitely-not-here-1234.jsonl"])
        self.assertEqual(code, 2)
        self.assertIn("cannot read trace", err)

    def test_empty_trace_exits_two(self):
        path = write_tmp("")
        code, _, err = run([path])
        self.assertEqual(code, 2)
        self.assertIn("empty", err)
        os.unlink(path)

    def test_malformed_jsonl_exits_two(self):
        path = write_tmp('{"method":"Page.navigate"}\nnot json\n')
        code, _, err = run([path])
        self.assertEqual(code, 2)
        self.assertIn("not valid JSON", err)
        os.unlink(path)

    def test_record_without_method_exits_two(self):
        path = write_tmp('{"id":1,"params":{}}\n')
        code, _, err = run([path])
        self.assertEqual(code, 2)
        self.assertIn("no string 'method'", err)
        os.unlink(path)

    def test_unknown_option_exits_two(self):
        code, _, err = run([os.path.join(EXAMPLES, "clean-session.jsonl"), "--nope"])
        self.assertEqual(code, 2)
        self.assertIn("unknown option", err)

    def test_missing_manifest_exits_two(self):
        code, _, err = run([os.path.join(EXAMPLES, "clean-session.jsonl"), "--manifest", "/tmp/nope.json"])
        self.assertEqual(code, 2)
        self.assertIn("cannot read manifest", err)


if __name__ == "__main__":
    unittest.main()
