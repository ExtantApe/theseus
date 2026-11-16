"""Tests for the Skylight sync (D212): the matching and conflict rules, chores by date, and the stdio client.
Stdlib only: python3 tests/test_skylight_sync.py. Nothing here talks to Skylight or Reminders."""
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "engine/tools"))
sys.dont_write_bytecode = True
import skylight_sync as ss  # noqa: E402

CFG = {"grocery_reminders_list": ["Fry’s", "Sam’s Club"]}


def sky(i, label, done=False, section="Fry’s", updated=None):
    return {"id": i, "label": label, "done": done, "section": section, "updated": updated}


def rem(i, title, done=False, lst="Fry’s", modified=None):
    return {"id": i, "title": title, "done": done, "list": lst, "modified": modified}


def link(s, r, title, store="Fry’s", sky_done=False, rem_done=False, label=None):
    return {"sky": s, "rem": r, "store": store, "label": label or title, "title": title, "sky_done": sky_done, "rem_done": rem_done}


def plan(*a, **k):
    """plan_groceries without the orphans, for the tests that don't look at them."""
    actions, links, notes, _ = ss.plan_groceries(*a, **k)
    return actions, links, notes


def kinds(actions):
    return [a[0] for a in actions]


class Matching(unittest.TestCase):
    def test_quantities_case_and_curly_quotes_dont_count(self):
        for a, b in [("Milk (2)", "milk"), ("2 x Eggs", "eggs"), ("Bananas x3", "bananas"), ("Trader Joe’s salsa", "trader joe's salsa"),
                     ("  Bread  ", "bread"), ("3 limes", "limes")]:
            self.assertEqual(ss.norm(a), ss.norm(b), a)

    def test_different_items_stay_different(self):
        self.assertNotEqual(ss.norm("7up"), ss.norm("up"))
        self.assertNotEqual(ss.norm("Milk"), ss.norm("Oat milk"))

    def test_local_date_reads_dates_and_times(self):
        self.assertEqual(ss.local_date("2026-11-15"), "2026-11-15")
        self.assertIsNone(ss.local_date(None))
        self.assertIsNone(ss.local_date("not a date"))


class GroceriesFirstPass(unittest.TestCase):
    def test_same_item_on_both_sides_is_linked_without_writes(self):
        actions, links, notes = plan(CFG, [], [sky("s1", "Milk (2)")], [rem("r1", "milk")])
        self.assertEqual(actions, [])
        self.assertEqual((links[0]["sky"], links[0]["rem"]), ("s1", "r1"))

    def test_a_skylight_item_is_added_to_its_store_list(self):
        actions, links, _ = plan(CFG, [], [sky("s1", "Rotisserie chicken", section="Sam’s Club")], [])
        self.assertEqual(actions, [("rem_add", "Sam’s Club", "Rotisserie chicken")])
        self.assertEqual(links[0]["pending"], 0)

    def test_an_item_with_no_section_goes_to_the_first_store_and_gets_that_section(self):
        actions, _, _ = plan(CFG, [], [sky("s1", "Apples", section=None)], [])
        self.assertIn(("sky_section", "s1", "Fry’s"), actions)
        self.assertIn(("rem_add", "Fry’s", "Apples"), actions)

    def test_a_reminder_is_added_to_skylight_in_its_store_section(self):
        actions, _, _ = plan(CFG, [], [], [rem("r1", "Paper towels", lst="Sam’s Club")])
        self.assertEqual(actions, [("sky_add", "Paper towels", "Sam’s Club")])

    def test_matching_respects_the_store(self):
        actions, _, _ = plan(CFG, [], [sky("s1", "Milk", section="Sam’s Club")], [rem("r1", "Milk", lst="Fry’s")])
        self.assertIn(("rem_add", "Sam’s Club", "Milk"), actions)
        self.assertIn(("sky_add", "Milk", "Fry’s"), actions)

    def test_done_items_are_not_copied_on_a_first_pass(self):
        actions, links, _ = plan(CFG, [], [sky("s1", "Old", done=True)], [rem("r1", "Older", done=True)])
        self.assertEqual(actions, [])
        self.assertEqual(links, [])

    def test_store_sections_can_be_mapped(self):
        cfg = {**CFG, "grocery_store_sections": {"Fry’s": "Frys"}}
        actions, links, _ = plan(cfg, [], [sky("s1", "Milk", section="Frys")], [rem("r1", "Milk")])
        self.assertEqual(actions, [])
        self.assertEqual(len(links), 1)


class GroceriesDone(unittest.TestCase):
    def test_done_in_skylight_is_copied(self):
        actions, links, _ = plan(CFG, [link("s1", "r1", "Milk")], [sky("s1", "Milk", done=True)], [rem("r1", "Milk")])
        self.assertEqual(actions, [("rem_done", "r1", True)])
        self.assertTrue(links[0]["rem_done"])

    def test_done_in_reminders_is_copied(self):
        actions, _, _ = plan(CFG, [link("s1", "r1", "Milk")], [sky("s1", "Milk")], [rem("r1", "Milk", done=True)])
        self.assertEqual(actions, [("sky_done", "s1", True)])

    def test_reopened_on_one_side_is_copied(self):
        prev = link("s1", "r1", "Milk", sky_done=True, rem_done=True)
        actions, _, _ = plan(CFG, [prev], [sky("s1", "Milk", done=False)], [rem("r1", "Milk", done=True)])
        self.assertEqual(actions, [("rem_done", "r1", False)])

    def test_done_beats_not_done_when_both_sides_changed(self):
        prev = link("s1", "r1", "Milk", sky_done=True, rem_done=False)
        # Skylight reopened it while Reminders ticked it: done wins.
        actions, links, _ = plan(CFG, [prev], [sky("s1", "Milk", done=False)], [rem("r1", "Milk", done=True)])
        self.assertEqual(actions, [("sky_done", "s1", True)])
        self.assertTrue(links[0]["sky_done"] and links[0]["rem_done"])

    def test_out_of_step_with_no_recorded_change_goes_to_done(self):
        prev = link("s1", "r1", "Milk", sky_done=True, rem_done=False)
        actions, _, _ = plan(CFG, [prev], [sky("s1", "Milk", done=True)], [rem("r1", "Milk", done=False)])
        self.assertEqual(actions, [("rem_done", "r1", True)])


class GroceriesTitles(unittest.TestCase):
    def test_a_rename_on_one_side_is_copied(self):
        a1, _, _ = plan(CFG, [link("s1", "r1", "Milk")], [sky("s1", "Whole milk")], [rem("r1", "Milk")])
        self.assertEqual(a1, [("rem_title", "r1", "Whole milk")])
        a2, _, _ = plan(CFG, [link("s1", "r1", "Milk")], [sky("s1", "Milk")], [rem("r1", "Oat milk")])
        self.assertEqual(a2, [("sky_label", "s1", "Oat milk")])

    def test_renamed_on_both_sides_the_newer_wins(self):
        s = sky("s1", "Whole milk", updated="2026-11-15T10:05:00-07:00")
        r = rem("r1", "Oat milk", modified="2026-11-15T10:00:00-07:00")
        actions, _, _ = plan(CFG, [link("s1", "r1", "Milk")], [s], [r])
        self.assertEqual(actions, [("rem_title", "r1", "Whole milk")])
        r2 = rem("r1", "Oat milk", modified="2026-11-15T10:10:00-07:00")
        actions, _, _ = plan(CFG, [link("s1", "r1", "Milk")], [s], [r2])
        self.assertEqual(actions, [("sky_label", "s1", "Oat milk")])

    def test_renamed_on_both_sides_without_times_keeps_both_and_says_so(self):
        actions, links, notes = plan(CFG, [link("s1", "r1", "Milk")], [sky("s1", "Whole milk")], [rem("r1", "Oat milk", modified="2026-11-15T10:00:00Z")])
        self.assertEqual(actions, [])
        self.assertEqual(len(notes), 1)
        # Recorded as seen, so the same conflict isn't raised every pass.
        self.assertEqual((links[0]["label"], links[0]["title"]), ("Whole milk", "Oat milk"))


class GroceriesDeletionsAndStores(unittest.TestCase):
    def test_deleted_on_one_side_unlinks_and_never_deletes_the_other(self):
        for sky_side, rem_side in [([], [rem("r1", "Milk")]), ([sky("s1", "Milk")], [])]:
            actions, links, notes = plan(CFG, [link("s1", "r1", "Milk")], sky_side, rem_side)
            self.assertFalse(any("delete" in k for k in kinds(actions)))
            self.assertFalse(any(ln.get("sky") == "s1" and ln.get("rem") == "r1" for ln in links))
            self.assertEqual(len(notes), 1)
            self.assertEqual(actions, [], "the survivor isn't re-created on the side it was deleted from")

    def test_the_survivor_of_a_delete_stays_single_on_later_passes(self):
        _, links, _, single = ss.plan_groceries(CFG, [link("s1", "r1", "Milk")], [], [rem("r1", "Milk")])
        self.assertEqual(single, ["r1"])
        actions, links, notes, single = ss.plan_groceries(CFG, links, [], [rem("r1", "Milk")], single)
        self.assertEqual((actions, notes, single), ([], [], ["r1"]))
        # Once the survivor is gone too, it's forgotten.
        self.assertEqual(ss.plan_groceries(CFG, links, [], [], single)[3], [])

    def test_a_finished_item_that_drops_off_both_sides_goes_quietly(self):
        actions, links, notes = plan(CFG, [link("s1", "r1", "Milk", sky_done=True, rem_done=True)], [], [])
        self.assertEqual((actions, links, notes), ([], [], []))

    def test_moving_the_skylight_section_moves_the_reminder(self):
        actions, links, _ = plan(CFG, [link("s1", "r1", "Milk")], [sky("s1", "Milk", section="Sam’s Club")], [rem("r1", "Milk")])
        self.assertEqual(actions, [("rem_list", "r1", "Sam’s Club")])
        self.assertEqual(links[0]["store"], "Sam’s Club")

    def test_moving_the_reminder_sets_the_skylight_section(self):
        actions, _, _ = plan(CFG, [link("s1", "r1", "Milk")], [sky("s1", "Milk")], [rem("r1", "Milk", lst="Sam’s Club")])
        self.assertEqual(actions, [("sky_section", "s1", "Sam’s Club")])

    def test_no_plan_ever_deletes(self):
        cases = [([], [sky("s1", "A")], [rem("r1", "B")]), ([link("s1", "r1", "A")], [], [])]
        for links, s, r in cases:
            actions, _, _ = plan(CFG, links, s, r)
            self.assertTrue(all(k in {"rem_done", "rem_title", "rem_list", "rem_add", "sky_done", "sky_label", "sky_section", "sky_add"} for k in kinds(actions)))


def chore_rem(rid, due, done=False, recurring=True):
    return {"id": rid, "title": "Feed cat", "done": done, "due": due, "recurring": recurring}


class Chores(unittest.TestCase):
    MAP = {"links": [{"title": "Feed cat", "reminder": "R", "chores": ["C1"]}]}
    MULTI = {"links": [{"title": "Dishes", "reminder": "R", "chores": ["C1", "C2"]}]}

    def test_a_repeating_reminder_done_completes_only_that_dates_occurrence(self):
        occ = {("C1", "2026-11-14"): False, ("C1", "2026-11-21"): False}
        actions, seen, _ = ss.plan_chores(self.MAP, {"R": chore_rem("R", "2026-11-21")}, occ, {"R": {"due": "2026-11-14"}})
        self.assertEqual(actions, [("chore_done", "C1", "2026-11-14")])
        self.assertEqual(seen["R"]["due"], "2026-11-21")

    def test_a_late_skylight_completion_doesnt_tick_the_next_occurrence(self):
        # Last Saturday's occurrence was done late in Skylight; the reminder has already moved on to this Saturday.
        occ = {("C1", "2026-11-14"): True, ("C1", "2026-11-21"): False}
        actions, _, _ = ss.plan_chores(self.MAP, {"R": chore_rem("R", "2026-11-21")}, occ, {"R": {"due": "2026-11-21"}})
        self.assertEqual(actions, [])

    def test_done_in_skylight_for_the_reminders_date_completes_the_reminder(self):
        occ = {("C1", "2026-11-21"): True}
        actions, _, _ = ss.plan_chores(self.MAP, {"R": chore_rem("R", "2026-11-21")}, occ, {"R": {"due": "2026-11-21"}})
        self.assertEqual(actions, [("rem_done", "R", True)])

    def test_several_chores_complete_the_reminder_only_when_all_are_done(self):
        rems = {"R": chore_rem("R", "2026-11-21")}
        some = {("C1", "2026-11-21"): True, ("C2", "2026-11-21"): False}
        self.assertEqual(ss.plan_chores(self.MULTI, rems, some, {})[0], [])
        missing = {("C1", "2026-11-21"): True}
        self.assertEqual(ss.plan_chores(self.MULTI, rems, missing, {})[0], [])
        both = {("C1", "2026-11-21"): True, ("C2", "2026-11-21"): True}
        self.assertEqual(ss.plan_chores(self.MULTI, rems, both, {})[0], [("rem_done", "R", True)])

    def test_a_reminder_done_marks_every_linked_chore(self):
        occ = {("C1", "2026-11-14"): False, ("C2", "2026-11-14"): True}
        actions, _, _ = ss.plan_chores(self.MULTI, {"R": chore_rem("R", "2026-11-21")}, occ, {"R": {"due": "2026-11-14"}})
        self.assertEqual(actions, [("chore_done", "C1", "2026-11-14")])

    def test_a_one_off_reminder_ticked_completes_its_dates_occurrence(self):
        occ = {("C1", "2026-11-20"): False}
        actions, _, _ = ss.plan_chores(self.MAP, {"R": chore_rem("R", "2026-11-20", done=True, recurring=False)}, occ, {"R": {"due": "2026-11-20", "done": False}})
        self.assertEqual(actions, [("chore_done", "C1", "2026-11-20")])

    def test_no_occurrence_means_nothing_is_created(self):
        actions, _, _ = ss.plan_chores(self.MAP, {"R": chore_rem("R", "2026-11-21")}, {}, {"R": {"due": "2026-11-14"}})
        self.assertEqual(actions, [])

    def test_a_missing_reminder_is_reported_and_the_chore_left_alone(self):
        actions, _, notes = ss.plan_chores(self.MAP, {}, {("C1", "2026-11-21"): True}, {})
        self.assertEqual(actions, [])
        self.assertEqual(len(notes), 1)

    def test_the_first_pass_records_without_completing_anything_on_skylight(self):
        occ = {("C1", "2026-11-14"): False}
        actions, seen, _ = ss.plan_chores(self.MAP, {"R": chore_rem("R", "2026-11-21")}, occ, {})
        self.assertEqual(actions, [])
        self.assertEqual(seen["R"]["due"], "2026-11-21")

    def test_the_documented_map_keys_work_too(self):
        old_style = {"links": [{"reminder_id": "R", "chore_ids": ["C1"]}]}
        actions, _, _ = ss.plan_chores(old_style, {"R": chore_rem("R", "2026-11-21")}, {("C1", "2026-11-21"): True}, {})
        self.assertEqual(actions, [("rem_done", "R", True)])

    def test_occurrences_read_skylight_rows(self):
        rows = [{"id": "C1", "start": "2026-11-21", "status": "complete"}, {"id": "C1", "start": "2026-11-22", "status": "pending"}, {"id": "", "start": "2026-11-22"}]
        self.assertEqual(ss.occurrences(rows), {("C1", "2026-11-21"): True, ("C1", "2026-11-22"): False})


FAKE_MCP = r'''
import json, os, sys
for line in sys.stdin:
    msg = json.loads(line)
    if "id" not in msg:
        continue
    if msg["method"] == "initialize":
        res = {"protocolVersion": "2025-06-18", "capabilities": {}, "serverInfo": {"name": "fake", "version": "0"}}
    elif msg["method"] == "tools/call":
        name = msg["params"]["name"]
        seen = {"email": os.environ.get("SKYLIGHT_EMAIL"), "token_file": os.environ.get("SKYLIGHT_TOKEN_FILE")}
        if name == "expired":
            res = {"isError": True, "content": [{"type": "text", "text": "Skylight login challenge: a code was emailed"}]}
        elif name == "broken":
            res = {"isError": True, "content": [{"type": "text", "text": "500 from Skylight"}]}
        else:
            res = {"content": [{"type": "text", "text": json.dumps({"tool": name, "args": msg["params"]["arguments"], "env": seen})}]}
    print(json.dumps({"jsonrpc": "2.0", "id": msg["id"], "result": res}), flush=True)
'''


class Client(unittest.TestCase):
    def setUp(self):
        self.ws = Path(tempfile.mkdtemp(prefix="theseus-sky-"))
        self.addCleanup(shutil.rmtree, self.ws, True)
        self.fake = self.ws / "fake_mcp.py"
        self.fake.write_text(FAKE_MCP)
        self._old = (ss.WS, ss.TOKENS)
        ss.WS, ss.TOKENS = self.ws, self.ws / "data/.skylight-tokens.json"
        self.addCleanup(lambda: setattr(ss, "WS", self._old[0]) or setattr(ss, "TOKENS", self._old[1]))

    def client(self):
        sk = ss.Skylight(command=[sys.executable, "-I", str(self.fake)], env={"SKYLIGHT_EMAIL": "someone@example.com", "SKYLIGHT_PASSWORD": "pw"})
        self.addCleanup(sk.close)
        return sk

    def test_calls_a_tool_with_its_arguments_and_its_own_token_file(self):
        out = self.client().call("skylight_get_list_items", listId="L1")
        self.assertEqual(out["tool"], "skylight_get_list_items")
        self.assertEqual(out["args"], {"listId": "L1"})
        self.assertEqual(out["env"]["email"], "someone@example.com")
        self.assertEqual(out["env"]["token_file"], str(self.ws / "data/.skylight-tokens.json"))

    def test_an_expired_login_stops_with_a_message_for_a_person(self):
        with self.assertRaises(ss.SyncError) as e:
            self.client().call("expired")
        self.assertIn("sign in again", str(e.exception))

    def test_other_errors_say_which_call_failed(self):
        with self.assertRaises(ss.SyncError) as e:
            self.client().call("broken")
        self.assertIn("broken", str(e.exception))


class Housekeeping(unittest.TestCase):
    def setUp(self):
        self.ws = Path(tempfile.mkdtemp(prefix="theseus-sky-"))
        self.addCleanup(shutil.rmtree, self.ws, True)
        self.saved = {k: getattr(ss, k) for k in ("WS", "STATE", "LOG", "WRITE_LOG", "LOCK")}
        ss.WS, ss.STATE, ss.LOG = self.ws, self.ws / "data/skylight-sync.json", self.ws / "logs/skylight-sync.log"
        ss.WRITE_LOG, ss.LOCK = self.ws / "data/log.md", self.ws / "data/.skylight-sync.lock"
        self.addCleanup(lambda: [setattr(ss, k, v) for k, v in self.saved.items()])

    def test_it_does_nothing_unless_switched_on(self):
        (self.ws / "config.json").write_text(json.dumps({"skylight": True}))
        self.assertEqual(ss.run(), 0)
        self.assertFalse(ss.STATE.exists())
        self.assertFalse(ss.LOG.exists())

    def test_alerts_are_kept_once_each(self):
        st = {}
        ss.add_alerts(st, ["Log in again", "Log in again"])
        ss.add_alerts(st, ["Log in again"])
        self.assertEqual(len(st["alerts"]), 1)

    def test_the_agent_holds_no_credentials(self):
        plist = ss.agent_plist()
        self.assertIn("<integer>120</integer>", plist)
        self.assertNotIn("SKYLIGHT_PASSWORD", plist)
        self.assertNotIn("SKYLIGHT_EMAIL", plist)

    def test_a_dry_run_writes_nothing(self):
        did = ss.apply([("rem_done", "r1", True), ("sky_add", "Milk", "Fry’s")], None, None, [], dry=True)
        self.assertEqual(len(did), 2)
        self.assertFalse(ss.WRITE_LOG.exists())


if __name__ == "__main__":
    unittest.main()
