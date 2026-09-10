#!/usr/bin/env python3
"""Parser and notes-stamp tests for tool findings (no GUI server)."""

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import htb_helper as engine


WINDOWS_PING = """
Pinging 9.9.9.9 with 32 bytes of data:
Reply from 9.9.9.9: bytes=32 time=24ms TTL=56
Reply from 9.9.9.9: bytes=32 time=21ms TTL=56

Ping statistics for 9.9.9.9:
    Packets: Sent = 9, Received = 9, Lost = 0 (0% loss),
Approximate round trip times in milli-seconds:
    Minimum = 21ms, Maximum = 25ms, Average = 22ms
"""

UNIX_PING = """
PING 9.9.9.9 (9.9.9.9) 56(84) bytes of data.
64 bytes from 9.9.9.9: icmp_seq=1 ttl=56 time=22.1 ms
--- 9.9.9.9 ping statistics ---
4 packets transmitted, 4 received, 0% packet loss, time 3005ms
rtt min/avg/max/mdev = 21.012/22.341/25.100/1.523 ms
"""

NMAP_FILTERED = """
# Nmap 7.99 scan initiated
Nmap scan report for dns9.quad9.net (9.9.9.9)
Host is up.

PORT     STATE    SERVICE VERSION
1234/tcp filtered hotline

# Nmap done at Tue Sep  8 20:50:31 2026 -- 1 IP address (1 host up) scanned in 3.31 seconds
"""

SENT_NOTE_PLACEHOLDER = """# lab

[21:08] [TOOL] ping
- Command: `ping -n 9 9.9.9.9`
- Why: Check whether the target answers ICMP.
- Summary: Sent to terminal (ping). Output: logs/ping_20260908_210805.txt
- Findings:
  - Capture file: logs/ping_20260908_210805.txt. Review the terminal output for findings.
- Output: logs/ping_20260908_210805.txt
"""

SENT_NOTE_WAITING = """# lab

[21:08] [TOOL] ping
- Command: `ping -n 9 9.9.9.9`
- Why: Check whether the target answers ICMP.
- Summary: Sent to terminal (ping). Output: logs/ping_20260908_210805.txt
- Output: logs/ping_20260908_210805.txt
"""


class IdentifyToolTests(unittest.TestCase):
    def test_ping_argv(self):
        self.assertEqual(engine.identify_tool(["ping", "-n", "4", "9.9.9.9"]), "ping")

    def test_ping_exe(self):
        self.assertEqual(
            engine.identify_tool([r"C:\Windows\System32\ping.exe", "-n", "4", "9.9.9.9"]),
            "ping",
        )

    def test_nmap_exe(self):
        self.assertEqual(engine.identify_tool(["nmap.exe", "-Pn", "-sV", "10.10.10.10"]), "nmap")


class PingParserTests(unittest.TestCase):
    def test_windows_ping_findings(self):
        findings = engine.parse_ping_output(WINDOWS_PING)
        blob = " ".join(findings).lower()
        self.assertTrue(findings)
        self.assertIn("9/9", blob.replace(" ", ""))
        self.assertIn("0%", blob)
        self.assertIn("22ms", blob.replace(" ", ""))

    def test_unix_ping_findings(self):
        findings = engine.parse_ping_output(UNIX_PING)
        blob = " ".join(findings).lower()
        self.assertTrue(findings)
        self.assertIn("4/4", blob.replace(" ", ""))
        self.assertIn("0%", blob)

    def test_analyze_ping_is_not_generic(self):
        summary, findings, _meta = engine.analyze_tool_output("ping", WINDOWS_PING, 0)
        self.assertTrue(findings)
        self.assertNotIn("no structured findings were parsed", summary.lower())


class NmapCompleteTests(unittest.TestCase):
    def test_nmap_filtered_port(self):
        summary, findings, _meta = engine.analyze_tool_output("nmap", NMAP_FILTERED, 0)
        blob = " ".join(findings).lower()
        self.assertIn("host is up", blob)
        self.assertIn("1234/tcp", blob)
        self.assertIn("filtered", blob)
        self.assertTrue(engine.capture_output_complete("nmap", NMAP_FILTERED))

    def test_ping_complete(self):
        self.assertTrue(engine.capture_output_complete("ping", WINDOWS_PING))
        self.assertFalse(engine.capture_output_complete("ping", "Pinging 9.9.9.9 with 32 bytes of data:"))


class PatchNotesTests(unittest.TestCase):
    def test_replaces_placeholder(self):
        summary = "9.9.9.9 ICMP: 9/9 received, 0 lost (0% loss)"
        findings = [summary, "Round trip: min 21ms, max 25ms, avg 22ms"]
        updated, changed = engine.patch_tool_note_findings(
            SENT_NOTE_PLACEHOLDER,
            "logs/ping_20260908_210805.txt",
            summary,
            findings,
        )
        self.assertTrue(changed)
        self.assertNotIn("Review the terminal output for findings", updated)
        self.assertIn("9/9 received", updated)
        self.assertIn("Round trip: min 21ms", updated)

    def test_inserts_findings_when_waiting(self):
        summary = "9.9.9.9 ICMP: 9/9 received, 0 lost (0% loss)"
        findings = [summary]
        updated, changed = engine.patch_tool_note_findings(
            SENT_NOTE_WAITING,
            "logs/ping_20260908_210805.txt",
            summary,
            findings,
        )
        self.assertTrue(changed)
        self.assertIn("- Findings:", updated)
        self.assertIn("9/9 received", updated)
        self.assertIn("- Summary: 9.9.9.9 ICMP", updated)


class ScreenshotMilestoneTests(unittest.TestCase):
    def test_cli_milestones_exist(self):
        keys = set(engine.SCREENSHOT_MILESTONES)
        self.assertGreaterEqual(
            keys,
            {
                "initial_recon",
                "initial_foothold",
                "vulnerability_evidence",
                "privilege_escalation",
                "user_flag",
                "root_admin_flag",
                "other",
            },
        )


if __name__ == "__main__":
    unittest.main()
