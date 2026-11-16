"""Tests for leave-by times (K660). Stdlib only: python3 tests/test_eta.py. Nothing here asks Apple Maps or reads a calendar."""
import datetime as dt
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "engine/tools"))
sys.dont_write_bytecode = True
import eta  # noqa: E402

TZ = dt.timezone(dt.timedelta(hours=-7))
NOW = dt.datetime(2026, 11, 17, 8, 0, tzinfo=TZ)


def ev(title, hour, location="", minute=0, **extra):
    start = dt.datetime(2026, 11, 17, hour, minute, tzinfo=TZ)
    return {"title": title, "start": start.isoformat(), "location": location, "all_day": False, "my_status": None, "geo": None, **extra}


class Fake:
    """Stands in for bin/ek: returns the events, and a travel time for each lookup."""

    def __init__(self, events, minutes=25, fail=False, me=None):
        self.events, self.minutes, self.fail, self.lookups, self.me, self.asked_me = events, minutes, fail, [], me, []

    def __call__(self, *args):
        if args[0] == "events":
            return self.events
        if args[0] == "me-address":
            self.asked_me.append(args)
            return self.me
        self.lookups.append(args)
        if self.fail:
            raise RuntimeError("Apple Maps couldn't find it")
        return {"minutes": self.minutes}


class Eta(unittest.TestCase):
    def setUp(self):
        self.ws = Path(tempfile.mkdtemp(prefix="theseus-eta-"))
        self.addCleanup(shutil.rmtree, self.ws, True)
        self.old = eta.CACHE
        eta.CACHE = self.ws / "data/eta-cache.json"
        self.addCleanup(setattr, eta, "CACHE", self.old)
        self.cfg = {"eta_from": "1 Made Up St, Somewhere"}

    def run_plan(self, fake, now=NOW, cfg=None):
        return eta.plan(NOW.date(), self.cfg if cfg is None else cfg, now=now, ask=fake)

    def test_leave_by_is_start_minus_travel_and_buffer(self):
        r = self.run_plan(Fake([ev("Dentist", 10, "Made Up Dental")], minutes=25))
        t = r["trips"][0]
        self.assertEqual(t["leave_by"], "2026-11-17T09:25-07:00")
        self.assertFalse(t["late"])
        self.assertIn("Leave by 9:25 am for Dentist (25 min car + 10)", eta.text(r))

    def test_asks_for_the_arrival_time_so_traffic_is_predicted(self):
        fake = Fake([ev("Dentist", 10, "Made Up Dental")])
        self.run_plan(fake)
        args = fake.lookups[0]
        self.assertIn("--arrive", args)
        self.assertEqual(args[args.index("--arrive") + 1], "2026-11-17 10:00")
        self.assertEqual(args[args.index("--to") + 1], "Made Up Dental")

    def test_uses_the_events_map_location_when_it_has_one(self):
        fake = Fake([ev("Game", 11, "Field 3", geo={"lat": 33.1, "lon": -111.9})])
        self.run_plan(fake, cfg={"eta_from": "33.0, -112.0"})
        args = fake.lookups[0]
        self.assertEqual(args[args.index("--to-geo") + 1], "33.1,-111.9")
        self.assertEqual(args[args.index("--from-geo") + 1], "33.0, -112.0")

    def test_skips_events_that_need_no_trip(self):
        events = [ev("All day", 0, "Somewhere", all_day=True), ev("Call", 9, "https://zoom.us/j/1"), ev("Standup", 9, "Online"),
                  ev("Declined", 10, "Made Up Cafe", my_status=3), ev("No place", 11), ev("Home thing", 12, "1 made up st, somewhere"),
                  ev("Already started", 7, "Made Up Gym")]
        fake = Fake(events)
        r = self.run_plan(fake)
        self.assertEqual(r["trips"], [])
        self.assertEqual(fake.lookups, [])

    def test_without_a_starting_point_nothing_is_looked_up(self):
        fake = Fake([ev("Dentist", 10, "Made Up Dental")])
        r = self.run_plan(fake, cfg={})
        self.assertEqual(fake.lookups, [])
        self.assertIn("eta_from", r["note"])

    def test_one_lookup_per_event_per_day(self):
        fake = Fake([ev("Dentist", 15, "Made Up Dental")])
        self.run_plan(fake)
        self.run_plan(fake, now=NOW + dt.timedelta(hours=3))
        self.assertEqual(len(fake.lookups), 1)

    def test_looked_up_again_close_to_the_start_for_fresh_traffic(self):
        fake = Fake([ev("Dentist", 15, "Made Up Dental")])
        self.run_plan(fake)
        r = self.run_plan(fake, now=NOW + dt.timedelta(hours=5, minutes=30))
        self.assertEqual(len(fake.lookups), 2)
        self.assertEqual(r["trips"][0]["checked"], (NOW + dt.timedelta(hours=5, minutes=30)).isoformat(timespec="minutes"))

    def test_the_daily_limit_is_kept_and_said(self):
        events = [ev(f"Thing {h}", h, f"Place {h}") for h in range(9, 15)]
        fake = Fake(events)
        r = self.run_plan(fake, cfg={**self.cfg, "eta_daily_lookups": 3})
        self.assertEqual(len(fake.lookups), 3)
        self.assertEqual(len(r["trips"]), 3)
        self.assertIn("3 Apple Maps lookups", r["note"])

    def test_a_new_day_starts_a_new_count(self):
        fake = Fake([ev("Dentist", 15, "Made Up Dental")])
        self.run_plan(fake, cfg={**self.cfg, "eta_daily_lookups": 1})
        eta.CACHE.write_text(eta.CACHE.read_text().replace("2026-11-17", "2026-11-16"))
        self.run_plan(fake, cfg={**self.cfg, "eta_daily_lookups": 1})
        self.assertEqual(len(fake.lookups), 2)

    def test_a_failed_lookup_is_reported_not_guessed(self):
        r = self.run_plan(Fake([ev("Dentist", 10, "Nowhere Real")], fail=True))
        self.assertEqual(r["trips"], [])
        self.assertIn("No travel time for 'Dentist'", r["note"])

    def test_leave_now_when_its_already_past_the_leave_by_time(self):
        r = self.run_plan(Fake([ev("Dentist", 8, "Made Up Dental", minute=20)], minutes=25))
        self.assertTrue(r["trips"][0]["late"])
        self.assertIn("Leave now", eta.text(r))

    def test_home_from_the_contacts_card(self):
        fake = Fake([ev("Dentist", 10, "Made Up Dental")], me={"found": True, "address": "1 Made Up St, Somewhere", "label": "home"})
        r = self.run_plan(fake, cfg={"eta_from": "contacts:home"})
        self.assertEqual(fake.asked_me[0], ("me-address", "--label", "home"))
        args = fake.lookups[0]
        self.assertEqual(args[args.index("--from") + 1], "1 Made Up St, Somewhere")
        self.assertEqual(len(r["trips"]), 1)

    def test_no_home_address_on_the_card_is_said_not_guessed(self):
        fake = Fake([ev("Dentist", 10, "Made Up Dental")], me={"found": False, "reason": "your Contacts card has no home address"})
        r = self.run_plan(fake, cfg={"eta_from": "contacts:home"})
        self.assertEqual(fake.lookups, [])
        self.assertEqual(r["trips"], [])
        self.assertIn("no home address", r["note"])
        self.assertIn("Add it to your card", r["note"])

    def test_the_home_address_is_never_saved(self):
        fake = Fake([ev("Dentist", 10, "Made Up Dental")], me={"found": True, "address": "1 Made Up St, Somewhere", "label": "home"})
        self.run_plan(fake, cfg={"eta_from": "contacts:home"})
        self.assertNotIn("Made Up St", eta.CACHE.read_text())

    def test_the_cache_holds_no_places_or_titles(self):
        self.run_plan(Fake([ev("Dentist", 10, "Made Up Dental")]))
        saved = eta.CACHE.read_text()
        self.assertNotIn("Dental", saved)
        self.assertNotIn("Dentist", saved)
        self.assertNotIn("Made Up St", saved)


if __name__ == "__main__":
    unittest.main()
