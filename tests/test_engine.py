"""Tests for the engine's safety and bookkeeping. Stdlib only: python3 tests/test_engine.py. Everything runs in a throwaway workspace."""
import datetime as dt
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "engine/tools"
sys.path.insert(0, str(TOOLS))
sys.dont_write_bytecode = True
import schedule as sched  # noqa: E402


class Guard(unittest.TestCase):
    def setUp(self):
        self.ws = Path(tempfile.mkdtemp(prefix="theseus-guard-"))
        self.addCleanup(shutil.rmtree, self.ws, True)
        (self.ws / "config.json").write_text(json.dumps({"unattended_read_connectors": ["clickup", "skylight"]}))

    def run_guard(self, payload, raw=None, cwd=None):
        env = {**os.environ, "CLAUDE_PROJECT_DIR": str(self.ws)}
        return subprocess.run(["/usr/bin/python3", str(TOOLS / "send_guard.py")], input=raw if raw is not None else json.dumps(payload),
                              capture_output=True, text=True, env=env, cwd=cwd or self.ws)

    def decision(self, tool, tool_input=None):
        p = self.run_guard({"tool_name": tool, "tool_input": tool_input or {}})
        self.assertEqual(p.returncode, 0, p.stderr)
        return json.loads(p.stdout)["hookSpecificOutput"]["permissionDecision"] if p.stdout.strip() else None

    def composio(self, *slugs):
        return self.decision("mcp__claude_ai_Composio__COMPOSIO_MULTI_EXECUTE_TOOL", {"tools": [{"tool_slug": s} for s in slugs]})

    def test_read_words_do_not_excuse_a_write(self):
        for slug in ("GITHUB_FIND_OR_CREATE_ISSUE", "MAILCHIMP_LIST_ADD_MEMBER", "GET_OR_CREATE", "SHEETS_GET_AND_UPDATE"):
            self.assertEqual(self.composio(slug), "ask", slug)

    def test_composio_sends_and_deletes_are_refused(self):
        for slug in ("GMAIL_SEND_EMAIL", "GMAIL_REPLY_TO_THREAD", "SLACK_CHAT_POST_MESSAGE", "SLACKBOT_SENDS_A_MESSAGE", "OUTLOOK_DELETE_MESSAGE", "GMAIL_TRASH_MESSAGE"):
            self.assertEqual(self.composio(slug), "deny", slug)

    def test_one_bad_action_refuses_the_batch(self):
        self.assertEqual(self.composio("GMAIL_FETCH_EMAILS", "GMAIL_SEND_EMAIL"), "deny")

    def test_composio_reads_go_to_the_normal_rules(self):
        self.assertIsNone(self.composio("GMAIL_FETCH_EMAILS", "GOOGLECALENDAR_EVENTS_LIST"))

    def test_composio_shells_ask(self):
        self.assertEqual(self.decision("mcp__claude_ai_Composio__COMPOSIO_REMOTE_BASH_TOOL"), "ask")

    def test_empty_batch_is_blocked(self):
        self.assertEqual(self.run_guard({"tool_name": "mcp__x__COMPOSIO_MULTI_EXECUTE_TOOL", "tool_input": {"tools": []}}).returncode, 2)

    def test_it_fails_closed(self):
        for raw in ("", "not json", "[]", '{"tool_input": {}}', '{"tool_name": "mcp__x__COMPOSIO_MULTI_EXECUTE_TOOL"}',
                    '{"tool_name": "mcp__x__COMPOSIO_MULTI_EXECUTE_TOOL", "tool_input": {"tools": [1]}}'):
            self.assertEqual(self.run_guard(None, raw=raw).returncode, 2, raw)

    def test_works_from_any_folder(self):
        p = self.run_guard({"tool_name": "mcp__clickup__clickup_send_chat_message", "tool_input": {}}, cwd="/")
        self.assertEqual(json.loads(p.stdout)["hookSpecificOutput"]["permissionDecision"], "deny")

    def test_clickup_and_skylight_reads_are_allowed(self):
        for t in ("mcp__clickup__clickup_get_task", "mcp__clickup__clickup_filter_tasks", "mcp__skylight__skylight_list_chores", "mcp__clickup__clickup_get_chat_channel_messages"):
            self.assertEqual(self.decision(t), "allow", t)

    def test_connectors_cannot_send(self):
        for t in ("mcp__clickup__clickup_send_chat_message", "mcp__clickup__clickup_create_comment", "mcp__clickup__clickup_create_task_comment",
                  "mcp__clickup__clickup_react_to_chat_message", "mcp__skylight__skylight_add_message_comment", "mcp__slack__slack_post_message",
                  "mcp__claude_ai_Gmail__send_email"):
            self.assertEqual(self.decision(t), "deny", t)

    def test_changes_need_a_person(self):
        for t in ("mcp__clickup__clickup_delete_task", "mcp__clickup__clickup_update_task", "mcp__clickup__clickup_execute_operator",
                  "mcp__skylight__skylight_delete_event", "mcp__skylight__skylight_complete_chore", "mcp__skylight__skylight_add_list_item"):
            self.assertIsNone(self.decision(t), t)

    def test_gmail_draft_is_not_a_send(self):
        self.assertIsNone(self.decision("mcp__claude_ai_Gmail__create_email_draft"))

    def test_reads_from_unlisted_connectors_get_no_pass(self):
        self.assertIsNone(self.decision("mcp__other__get_thing"))

    def test_the_imessage_channel_can_answer_you(self):
        self.assertIsNone(self.decision("mcp__plugin_imessage_imessage__reply"))

    def test_other_tools_are_ignored(self):
        self.assertIsNone(self.decision("Read"))

    def test_settings_run_the_guard_on_every_connector(self):
        cfg = json.loads((ROOT / "engine/templates/settings.json").read_text())
        hook = cfg["hooks"]["PreToolUse"][0]
        self.assertEqual(hook["matcher"], "mcp__.*")
        self.assertIn("|| exit 2", hook["hooks"][0]["command"])
        self.assertFalse([r for r in cfg["permissions"]["allow"] if r.startswith("mcp__")])


class Workspace(unittest.TestCase):
    def setUp(self):
        self.ws = Path(tempfile.mkdtemp(prefix="theseus-ws-"))
        self.addCleanup(shutil.rmtree, self.ws, True)
        (self.ws / "data").mkdir()
        (self.ws / "logs").mkdir()
        self.env = {**os.environ, "THESEUS_HOME": str(self.ws), "HOME": str(self.ws), "PYTHONDONTWRITEBYTECODE": "1"}
        # Morning and nightly runs far from any likely test time, in any case at a fixed minute: changes.py only skips within 10 minutes of them.
        now = dt.datetime.now()
        far = f"{(now.hour + 12) % 24:02d}:00"
        cfg = {"integrations": {}, "checks": {"only_while_awake": False, "min_minutes_between_claude_runs": 15, "full_refresh_every_minutes": 6000},
               "schedule": {"style": "regimented", "groups": [{"name": "All", "days": sched.DAYS, "wake": "12:00", "bed": "23:59"}],
                            "morning_fixed": far, "nightly_fixed": far}}
        (self.ws / "config.json").write_text(json.dumps(cfg))

    def tool(self, name, *args):
        return subprocess.run(["/usr/bin/python3", str(TOOLS / name), *args], capture_output=True, text=True, env=self.env, cwd=self.ws)

    def state(self):
        return json.loads((self.ws / "data/check-state.json").read_text())

    def edit(self, text='{"action":"complete"}\n'):
        with open(self.ws / "data/app-edits.jsonl", "a") as f:
            f.write(text)

    # changes.py ---------------------------------------------------------

    def settled(self):
        self.tool("changes.py", "--force")
        self.tool("changes.py", "--ack")

    def cool(self):
        st = self.state()
        st["last_claude"] = 0
        (self.ws / "data/check-state.json").write_text(json.dumps(st))

    def test_a_change_survives_a_run_that_never_finished(self):
        self.settled()
        self.edit()
        self.cool()
        self.assertEqual(self.tool("changes.py").returncode, 0)   # starts a run, which dies without --ack
        self.assertEqual(self.tool("changes.py").returncode, 10)  # cooling down
        self.assertIn("app", self.state()["claimed"])
        self.cool()
        self.assertEqual(self.tool("changes.py").returncode, 0)   # tried again, not left for the hourly refresh

    def test_ack_finishes_it(self):
        self.settled()
        self.edit()
        self.cool()
        self.tool("changes.py")
        self.tool("changes.py", "--ack")
        self.cool()
        self.assertEqual(self.tool("changes.py").returncode, 10)

    def test_a_change_during_a_run_is_not_lost_by_its_ack(self):
        self.settled()
        self.edit()
        self.cool()
        self.tool("changes.py")                                   # run starts for the first edit
        self.edit('{"action":"move"}\n')
        self.tool("changes.py")                                   # sees the second edit while cooling down
        self.tool("changes.py", "--ack")                          # first run finishes
        self.cool()
        self.assertEqual(self.tool("changes.py").returncode, 0)

    def test_state_is_never_half_written(self):
        self.settled()
        self.assertFalse(list((self.ws / "data").glob(".check-state*")))

    # app_edits.py -------------------------------------------------------

    def test_what_arrives_during_a_sync_is_kept(self):
        self.edit()
        self.assertEqual(len(json.loads(self.tool("app_edits.py", "take").stdout)["events"]), 1)
        self.edit('{"action":"move"}\n')
        self.tool("app_edits.py", "done")
        self.assertIn("move", (self.ws / "data/app-edits.jsonl").read_text())
        self.assertEqual(json.loads(self.tool("app_edits.py", "take").stdout)["events"], [{"action": "move"}])

    def test_a_batch_from_a_dead_run_comes_back(self):
        self.edit()
        self.tool("app_edits.py", "take")
        self.edit('{"action":"move"}\n')
        self.assertEqual(len(json.loads(self.tool("app_edits.py", "take").stdout)["events"]), 2)

    def test_done_files_it(self):
        self.edit()
        self.tool("app_edits.py", "take")
        self.tool("app_edits.py", "done")
        self.assertEqual(json.loads(self.tool("app_edits.py", "take").stdout)["events"], [])
        self.assertIn("complete", next((self.ws / "data/archive").glob("app-edits-*.jsonl")).read_text())

    # schedule.py --------------------------------------------------------

    def plan(self, morning="06:00", nightly="21:30", wake="06:10"):
        return {"schedule": {"style": "regimented", "groups": [{"name": "All", "days": sched.DAYS, "wake": wake, "bed": "23:59"}],
                             "morning_fixed": morning, "nightly_fixed": nightly}}

    def test_due_at_the_time(self):
        self.assertEqual(sched.due(self.plan(), self.ws, dt.datetime(2026, 11, 4, 6, 0)), "morning")

    def test_a_sleeping_mac_catches_up_when_it_wakes(self):
        self.assertEqual(sched.due(self.plan(), self.ws, dt.datetime(2026, 11, 4, 9, 45)), "morning")

    def test_too_late_is_skipped(self):
        self.assertIsNone(sched.due(self.plan(), self.ws, dt.datetime(2026, 11, 4, 12, 0)))

    def test_only_the_latest_runs_after_a_long_sleep(self):
        self.assertEqual(sched.due(self.plan(nightly="05:00", wake="04:00"), self.ws, dt.datetime(2026, 11, 4, 6, 30)), "morning")

    def test_a_restart_does_not_send_it_twice(self):
        (self.ws / "logs/app-morning-2026-11-04_0600.out").write_text("x")
        self.assertIsNone(sched.due(self.plan(), self.ws, dt.datetime(2026, 11, 4, 6, 5)))

    def test_a_run_by_launchd_counts_too(self):
        (self.ws / "logs/morning-2026-11-04_0600.out").write_text("x")
        self.assertIsNone(sched.due(self.plan(), self.ws, dt.datetime(2026, 11, 4, 6, 5)))

    def test_yesterdays_run_does_not_count_for_today(self):
        (self.ws / "logs/morning-2026-11-03_0600.out").write_text("x")
        self.assertEqual(sched.due(self.plan(), self.ws, dt.datetime(2026, 11, 4, 6, 5)), "morning")

    def test_evening_run_after_midnight_fires_on_the_right_night(self):
        c = self.plan(nightly="00:30")
        self.assertEqual(sched.scheduled_at(c, dt.date(2026, 11, 3), "nightly"), dt.datetime(2026, 11, 4, 0, 30))
        self.assertEqual(sched.due(c, self.ws, dt.datetime(2026, 11, 4, 0, 31)), "nightly")

    def test_evening_run_after_midnight_runs_once(self):
        c = self.plan(nightly="00:30")
        (self.ws / "logs/app-nightly-2026-11-04_0030.out").write_text("x")
        self.assertIsNone(sched.due(c, self.ws, dt.datetime(2026, 11, 4, 0, 35)))

    # notes and contacts --------------------------------------------------

    def test_contacts_fall_back_to_saved_copies(self):
        cache = self.ws / "cache"
        cache.mkdir()
        con = sqlite3.connect(cache / "contacts-1.db")
        con.executescript("""CREATE TABLE ZABCDRECORD (Z_PK, ZFIRSTNAME, ZLASTNAME, ZNICKNAME, ZORGANIZATION);
            CREATE TABLE ZABCDPHONENUMBER (ZOWNER, ZFULLNUMBER); CREATE TABLE ZABCDEMAILADDRESS (ZOWNER, ZADDRESS);
            INSERT INTO ZABCDRECORD VALUES (1, 'Sam', 'Rivera', NULL, NULL); INSERT INTO ZABCDPHONENUMBER VALUES (1, '+1 555 555 0100');""")
        con.commit()
        con.close()
        code = "import sys; sys.path.insert(0, %r); import imsg; c = imsg.Contacts(); print('Sam Rivera' in c.by_key.values())" % str(TOOLS)
        p = subprocess.run(["/usr/bin/python3", "-c", code], capture_output=True, text=True, env=self.env, cwd=self.ws)
        self.assertEqual(p.stdout.strip(), "True", p.stderr)

    def test_notes_only_counts_a_real_not_found_as_missing(self):
        src = (TOOLS / "notes.py").read_text()
        self.assertIn("if (notFound(e)) return JSON.stringify({ missing: true }); throw e;", src)
        self.assertIn("if (!notFound(e)) throw e;", src)

    def test_list_counts_are_recounted_and_ids_hidden(self):
        code = ("import sys; sys.path.insert(0, %r); import notes\n"
                "md = '# List\\n_Updated Mon 1/1 6:00am · 9 NOW_\\n\\n## 🔥 NOW\\n- [ ] a · id:t1\\n- [x] b\\n## ⏭ NEXT\\n- [ ] c\\n- [ ] d\\n'\n"
                "out = notes.fresh_counts(md); print(out.splitlines()[1]); print(notes.md_to_html('- [x] a · was:figure-out · id:t1'))" % str(TOOLS))
        p = subprocess.run(["/usr/bin/python3", "-c", code], capture_output=True, text=True, env=self.env, cwd=self.ws)
        self.assertIn("· 1 NOW · 2 NEXT_", p.stdout, p.stderr)
        self.assertNotIn("was:", p.stdout)
        self.assertNotIn("id:", p.stdout)


class Install(unittest.TestCase):
    def setUp(self):
        self.ws = Path(tempfile.mkdtemp(prefix="theseus-install-"))
        self.addCleanup(shutil.rmtree, self.ws, True)
        self.env = {**os.environ, "THESEUS_HOME": str(self.ws / "T"), "HOME": str(self.ws), "THESEUS_SKIP_MAC": "1"}

    def script(self, fn):
        """Runs one function from install.sh, after the part that defines them."""
        src = (ROOT / "engine/install.sh").read_text()
        defs = src[:src.index('case "$MODE" in')]
        return subprocess.run(["/bin/bash", "-c", defs + "\n" + fn], capture_output=True, text=True, env=self.env)

    def workspace(self, allow, cfg=None):
        ws = self.ws / "T"
        (ws / ".claude").mkdir(parents=True)
        (ws / ".claude/settings.local.json").write_text(json.dumps({"permissions": {"allow": allow}}))
        (ws / "config.json").write_text(json.dumps(cfg if cfg is not None else {"zeta": 1, "alpha": 2}, indent=2))
        return ws

    def test_whole_connector_allows_become_read_only(self):
        keep = "mcp__claude_ai_Composio__COMPOSIO_SEARCH_TOOLS"
        ws = self.workspace(["mcp__clickup", "mcp__skylight", keep, "mcp__plugin"])
        p = self.script("migrate_connectors")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(json.loads((ws / ".claude/settings.local.json").read_text())["permissions"]["allow"], [keep])
        cfg = json.loads((ws / "config.json").read_text())
        self.assertEqual(cfg["unattended_read_connectors"], ["clickup", "skylight"])
        self.assertEqual(list(cfg)[:2], ["zeta", "alpha"])

    def test_a_connector_you_removed_stays_removed(self):
        ws = self.workspace(["mcp__claude_ai_Composio__COMPOSIO_SEARCH_TOOLS"], {"unattended_read_connectors": []})
        self.script("migrate_connectors")
        self.assertEqual(json.loads((ws / "config.json").read_text())["unattended_read_connectors"], [])

    def test_installers_stay_identical(self):
        strip = lambda t: "\n".join(l for l in t.splitlines() if not l.startswith("SRC="))  # noqa: E731
        self.assertEqual(strip((ROOT / "install.sh").read_text()), strip((ROOT / "engine/install.sh").read_text()))


class Versions(unittest.TestCase):
    def test_everything_says_the_same_version(self):
        v = (ROOT / "engine/VERSION").read_text().strip()
        self.assertEqual(json.loads((ROOT / ".claude-plugin/plugin.json").read_text())["version"], v)
        self.assertEqual(json.loads((ROOT / "apps/desktop/src-tauri/tauri.conf.json").read_text())["version"], v)
        self.assertEqual(json.loads((ROOT / "apps/desktop/package.json").read_text())["version"], v)
        self.assertIn(f'version = "{v}"', (ROOT / "apps/desktop/src-tauri/Cargo.toml").read_text())


if __name__ == "__main__":
    unittest.main(verbosity=1)
