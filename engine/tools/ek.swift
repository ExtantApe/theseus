// ek.swift: Calendar + Reminders bridge for Theseus (Apple EventKit).
// Built by install.sh:  swiftc -O engine/tools/ek.swift -o bin/ek
//
// Reads expand recurring events properly (AppleScript does not), and see every
// calendar on this Mac — iCloud, Exchange/Outlook, Google, and anything that
// Skylight two-way syncs into iCloud.
//
// Commands (all output JSON):
//   ek access
//   ek calendars
//   ek events   --from 2026-11-03 --to 2026-11-10 [--cal "Work,Family"]
//   ek add-event --title T --start "2026-11-05 14:00" [--end ...|--minutes 60]
//                [--cal Name] [--location L] [--notes N] [--allday] [--alert 15]
//   ek lists
//   ek reminders [--list "A,B"] [--completed-since 2026-10-01] [--all-lists]
//   ek add-reminder --title T [--list Name] [--due "2026-11-05 09:00"|--due 2026-11-05]
//                   [--notes N] [--priority high|medium|low|none] [--url U]
//                   [--recur "FREQ=WEEKLY;INTERVAL=2;BYDAY=FR"]   (needs --due)
//   ek complete   --id ID      ek uncomplete --id ID
//   ek update     --id ID [--title T] [--due D|--clear-due] [--notes N] [--list L] [--priority P]
//                 [--recur RRULE|--clear-recur]   (replaces the repeat rule)
//   ek delete     --id ID --confirm        (reminders only; prefer complete)
import Foundation
import EventKit

let store = EKEventStore()
var args = Array(CommandLine.arguments.dropFirst())
let command = args.isEmpty ? "help" : args.removeFirst()

func opt(_ k: String) -> String? {
    if let i = args.firstIndex(of: "--" + k), i + 1 < args.count { return args[i + 1] }
    return nil
}
func flag(_ k: String) -> Bool { args.contains("--" + k) }

func emit(_ obj: Any) {
    let data = try! JSONSerialization.data(withJSONObject: obj, options: [.prettyPrinted, .sortedKeys])
    FileHandle.standardOutput.write(data)
    FileHandle.standardOutput.write("\n".data(using: .utf8)!)
}
func fail(_ msg: String, code: Int32 = 1) -> Never {
    FileHandle.standardError.write(("ek error: " + msg + "\n").data(using: .utf8)!)
    exit(code)
}

// ---------- dates
let isoOut: DateFormatter = {
    let f = DateFormatter(); f.locale = Locale(identifier: "en_US_POSIX")
    f.dateFormat = "yyyy-MM-dd'T'HH:mm:ssXXX"; return f
}()
func iso(_ d: Date?) -> Any { nn(d.map { isoOut.string(from: $0) }) }
func nn(_ v: Any?) -> Any { v ?? NSNull() }

/// Returns (date, hasTime)
func parseDate(_ s: String) -> (Date, Bool)? {
    let s = s.trimmingCharacters(in: .whitespaces)
    let lower = s.lowercased()
    let cal = Calendar.current
    if lower == "today" { return (cal.startOfDay(for: Date()), false) }
    if lower == "tomorrow" { return (cal.date(byAdding: .day, value: 1, to: cal.startOfDay(for: Date()))!, false) }
    if lower == "now" { return (Date(), true) }
    if lower.hasSuffix("d"), let n = Int(lower.dropLast()) {           // "60d" = 60 days ago
        return (cal.date(byAdding: .day, value: -n, to: cal.startOfDay(for: Date()))!, false)
    }
    let i = ISO8601DateFormatter()
    if let d = i.date(from: s) { return (d, true) }
    let withTime = ["yyyy-MM-dd HH:mm", "yyyy-MM-dd'T'HH:mm", "yyyy-MM-dd HH:mm:ss", "yyyy-MM-dd'T'HH:mm:ss"]
    for fmt in withTime {
        let f = DateFormatter(); f.locale = Locale(identifier: "en_US_POSIX"); f.timeZone = .current; f.dateFormat = fmt
        if let d = f.date(from: s) { return (d, true) }
    }
    let f = DateFormatter(); f.locale = Locale(identifier: "en_US_POSIX"); f.timeZone = .current; f.dateFormat = "yyyy-MM-dd"
    if let d = f.date(from: s) { return (d, false) }
    return nil
}
func needDate(_ k: String) -> (Date, Bool) {
    guard let s = opt(k) else { fail("--\(k) is required") }
    guard let parsed = parseDate(s) else { fail("could not parse --\(k) '\(s)' (use YYYY-MM-DD or 'YYYY-MM-DD HH:MM')") }
    return parsed
}

// ---------- access
func requestAccess(_ type: EKEntityType) -> Bool {
    let sem = DispatchSemaphore(value: 0)
    var granted = false
    let done: (Bool, Error?) -> Void = { g, _ in granted = g; sem.signal() }
    if #available(macOS 14.0, *) {
        if type == .event { store.requestFullAccessToEvents(completion: done) }
        else { store.requestFullAccessToReminders(completion: done) }
    } else {
        store.requestAccess(to: type, completion: done)
    }
    _ = sem.wait(timeout: .now() + 120)
    return granted
}
func ensure(_ type: EKEntityType) {
    if !requestAccess(type) {
        let what = type == .event ? "Calendars" : "Reminders"
        fail("no access to \(what). System Settings → Privacy & Security → \(what) → enable your terminal app " +
             "(Terminal/iTerm/etc.; for scheduled runs also enable /bin/bash or 'ek' if listed). Then rerun.", code: 2)
    }
}

// ---------- helpers
func calendarsNamed(_ csv: String?, type: EKEntityType) -> [EKCalendar]? {
    guard let csv = csv else { return nil }
    let wanted = csv.split(separator: ",").map { $0.trimmingCharacters(in: .whitespaces).lowercased() }
    let cals = store.calendars(for: type).filter { wanted.contains($0.title.lowercased()) || wanted.contains($0.calendarIdentifier.lowercased()) }
    if cals.isEmpty { fail("no \(type == .event ? "calendar" : "list") matches '\(csv)'") }
    return cals
}
func calDict(_ c: EKCalendar) -> [String: Any] {
    ["id": c.calendarIdentifier, "title": c.title, "source": c.source?.title ?? "",
     "writable": c.allowsContentModifications, "type": c.type.rawValue]
}
func priorityValue(_ s: String?) -> Int? {
    guard let s = s?.lowercased() else { return nil }
    switch s { case "high", "1": return 1; case "medium", "5": return 5; case "low", "9": return 9; case "none", "0": return 0
    default: return Int(s) }
}
func priorityName(_ p: Int) -> String { p == 0 ? "none" : (p <= 4 ? "high" : (p == 5 ? "medium" : "low")) }

func reminderDict(_ r: EKReminder) -> [String: Any] {
    var due: Any = NSNull(); var dueHasTime = false
    if let dc = r.dueDateComponents, let d = Calendar.current.date(from: dc) {
        due = iso(d); dueHasTime = dc.hour != nil
    }
    return ["id": r.calendarItemIdentifier, "title": r.title ?? "", "list": r.calendar?.title ?? "",
            "notes": r.notes ?? "", "due": due, "due_has_time": dueHasTime,
            "priority": priorityName(r.priority), "completed": r.isCompleted,
            "completed_at": iso(r.completionDate), "created": iso(r.creationDate),
            "modified": iso(r.lastModifiedDate), "url": nn(r.url?.absoluteString),
            "recurring": r.hasRecurrenceRules,
            "recurrence": r.recurrenceRules?.first.map(rruleString) ?? "",
            "alarms": (r.alarms ?? []).map { a in a.absoluteDate.map { isoOut.string(from: $0) } ?? "relative \(Int(a.relativeOffset / 60))m" }]
}
func fetchReminders(_ pred: NSPredicate) -> [EKReminder] {
    let sem = DispatchSemaphore(value: 0)
    var out: [EKReminder] = []
    store.fetchReminders(matching: pred) { r in out = r ?? []; sem.signal() }
    _ = sem.wait(timeout: .now() + 120)
    return out
}
func reminder(byId id: String) -> EKReminder {
    guard let r = store.calendarItem(withIdentifier: id) as? EKReminder else { fail("no reminder with id \(id)") }
    return r
}
func setDue(_ r: EKReminder, _ s: String) {
    guard let parsed = parseDate(s) else { fail("could not parse due '\(s)'") }
    let (d, hasTime) = parsed
    let comps: Set<Calendar.Component> = hasTime ? [.year, .month, .day, .hour, .minute] : [.year, .month, .day]
    r.dueDateComponents = Calendar.current.dateComponents(comps, from: d)
    r.alarms?.forEach { r.removeAlarm($0) }
    if hasTime { r.addAlarm(EKAlarm(absoluteDate: d)) }   // makes the phone actually notify
}
// Builds an RRULE string from the rule's own fields (stable across macOS versions).
func rruleString(_ rule: EKRecurrenceRule) -> String {
    let freqs: [EKRecurrenceFrequency: String] = [.daily: "DAILY", .weekly: "WEEKLY", .monthly: "MONTHLY", .yearly: "YEARLY"]
    let codes: [EKWeekday: String] = [.sunday: "SU", .monday: "MO", .tuesday: "TU", .wednesday: "WE",
                                      .thursday: "TH", .friday: "FR", .saturday: "SA"]
    var parts = ["FREQ=\(freqs[rule.frequency] ?? "DAILY")"]
    if rule.interval > 1 { parts.append("INTERVAL=\(rule.interval)") }
    if let days = rule.daysOfTheWeek, !days.isEmpty {
        parts.append("BYDAY=" + days.map { d in (d.weekNumber != 0 ? "\(d.weekNumber)" : "") + (codes[d.dayOfTheWeek] ?? "") }.joined(separator: ","))
    }
    if let pos = rule.setPositions, !pos.isEmpty { parts.append("BYSETPOS=" + pos.map { "\($0)" }.joined(separator: ",")) }
    if let end = rule.recurrenceEnd {
        if let d = end.endDate { parts.append("UNTIL=" + isoOut.string(from: d)) } else if end.occurrenceCount > 0 { parts.append("COUNT=\(end.occurrenceCount)") }
    }
    return parts.joined(separator: ";")
}
// Parses the small RRULE subset used for reminders: FREQ, INTERVAL, BYDAY (MO or 1WE), BYSETPOS.
func parseRecur(_ s: String) -> EKRecurrenceRule {
    var parts: [String: String] = [:]
    for piece in s.replacingOccurrences(of: "RRULE:", with: "").split(separator: ";") {
        let kv = piece.split(separator: "=", maxSplits: 1).map(String.init)
        if kv.count == 2 { parts[kv[0].uppercased()] = kv[1].uppercased() }
    }
    let freqs: [String: EKRecurrenceFrequency] = ["DAILY": .daily, "WEEKLY": .weekly, "MONTHLY": .monthly, "YEARLY": .yearly]
    guard let f = parts["FREQ"], let freq = freqs[f] else { fail("--recur needs FREQ=DAILY|WEEKLY|MONTHLY|YEARLY") }
    let weekdays: [String: EKWeekday] = ["SU": .sunday, "MO": .monday, "TU": .tuesday, "WE": .wednesday,
                                         "TH": .thursday, "FR": .friday, "SA": .saturday]
    var days: [EKRecurrenceDayOfWeek]? = nil
    if let by = parts["BYDAY"] {
        days = by.split(separator: ",").map { tok -> EKRecurrenceDayOfWeek in
            let t = String(tok); let code = String(t.suffix(2))
            guard let wd = weekdays[code] else { fail("bad BYDAY '\(t)'") }
            if let week = Int(t.dropLast(2)) { return EKRecurrenceDayOfWeek(wd, weekNumber: week) }
            return EKRecurrenceDayOfWeek(wd)
        }
    }
    let positions: [NSNumber]? = parts["BYSETPOS"].map { $0.split(separator: ",").compactMap { Int($0) }.map { NSNumber(value: $0) } }
    return EKRecurrenceRule(recurrenceWith: freq, interval: Int(parts["INTERVAL"] ?? "1") ?? 1,
                            daysOfTheWeek: days, daysOfTheMonth: nil, monthsOfTheYear: nil,
                            weeksOfTheYear: nil, daysOfTheYear: nil, setPositions: positions, end: nil)
}
func setRecur(_ r: EKReminder, _ s: String) {
    r.recurrenceRules?.forEach { r.removeRecurrenceRule($0) }
    r.addRecurrenceRule(parseRecur(s))
}
func save(_ r: EKReminder) {
    do { try store.save(r, commit: true) } catch { fail("save failed: \(error.localizedDescription)") }
}

// ---------- commands
switch command {
case "access":
    emit(["calendars": requestAccess(.event), "reminders": requestAccess(.reminder)])

case "calendars":
    ensure(.event)
    emit(store.calendars(for: .event).map(calDict))

case "lists":
    ensure(.reminder)
    emit(store.calendars(for: .reminder).map(calDict))

case "events":
    ensure(.event)
    let (from, _) = opt("from") != nil ? needDate("from") : (Calendar.current.startOfDay(for: Date()), false)
    var to: Date
    if opt("to") != nil {
        let (t, hasTime) = needDate("to")
        to = hasTime ? t : Calendar.current.date(byAdding: .day, value: 1, to: t)!   // date-only "to" is inclusive
    } else { to = Calendar.current.date(byAdding: .day, value: 1, to: from)! }
    let cals = calendarsNamed(opt("cal"), type: .event)
    let pred = store.predicateForEvents(withStart: from, end: to, calendars: cals)
    let evs = store.events(matching: pred).sorted { $0.startDate < $1.startDate }
    emit(evs.map { e -> [String: Any] in
        ["id": e.eventIdentifier ?? "", "title": e.title ?? "", "calendar": e.calendar?.title ?? "",
         "start": iso(e.startDate), "end": iso(e.endDate), "all_day": e.isAllDay,
         "location": e.location ?? "", "notes": String((e.notes ?? "").prefix(500)),
         "url": nn(e.url?.absoluteString), "recurring": e.hasRecurrenceRules,
         "attendees": (e.attendees ?? []).count,
         "organizer": nn(e.organizer?.name),
         "my_status": nn(e.attendees?.first(where: { $0.isCurrentUser })?.participantStatus.rawValue)]
    })

case "add-event":
    ensure(.event)
    guard let title = opt("title") else { fail("--title is required") }
    let (start, hasTime) = needDate("start")
    let ev = EKEvent(eventStore: store)
    ev.title = title
    ev.isAllDay = flag("allday") || !hasTime
    ev.startDate = start
    if let _ = opt("end") { ev.endDate = needDate("end").0 }
    else if ev.isAllDay { ev.endDate = start }
    else { ev.endDate = start.addingTimeInterval(Double(Int(opt("minutes") ?? "60") ?? 60) * 60) }
    if let c = calendarsNamed(opt("cal"), type: .event)?.first { ev.calendar = c }
    else { ev.calendar = store.defaultCalendarForNewEvents }
    if !(ev.calendar?.allowsContentModifications ?? false) { fail("calendar '\(ev.calendar?.title ?? "?")' is read-only") }
    ev.location = opt("location"); ev.notes = opt("notes")
    if let a = opt("alert"), let m = Double(a) { ev.addAlarm(EKAlarm(relativeOffset: -m * 60)) }
    do { try store.save(ev, span: .thisEvent, commit: true) } catch { fail("save failed: \(error.localizedDescription)") }
    emit(["created": true, "id": ev.eventIdentifier ?? "", "calendar": ev.calendar.title,
          "start": iso(ev.startDate), "end": iso(ev.endDate), "all_day": ev.isAllDay])

case "reminders":
    ensure(.reminder)
    let lists = calendarsNamed(opt("list"), type: .reminder)
    var out = fetchReminders(store.predicateForIncompleteReminders(withDueDateStarting: nil, ending: nil, calendars: lists))
    if let since = opt("completed-since") {
        guard let parsed = parseDate(since) else { fail("bad --completed-since") }
        let d = parsed.0
        out += fetchReminders(store.predicateForCompletedReminders(withCompletionDateStarting: d, ending: nil, calendars: lists))
    }
    emit(out.map(reminderDict))

case "add-reminder":
    ensure(.reminder)
    guard let title = opt("title") else { fail("--title is required") }
    let r = EKReminder(eventStore: store)
    r.title = title
    if let l = calendarsNamed(opt("list"), type: .reminder)?.first { r.calendar = l }
    else { r.calendar = store.defaultCalendarForNewReminders() }
    if let d = opt("due") { setDue(r, d) }
    r.notes = opt("notes")
    if let p = priorityValue(opt("priority")) { r.priority = p }
    if let u = opt("url") { r.url = URL(string: u) }
    if let rule = opt("recur") {
        guard r.dueDateComponents != nil else { fail("--recur needs --due") }
        setRecur(r, rule)
    }
    save(r)
    var made = reminderDict(r); made["created"] = true
    emit(made)

case "complete", "uncomplete":
    ensure(.reminder)
    guard let id = opt("id") else { fail("--id is required") }
    let r = reminder(byId: id)
    r.isCompleted = (command == "complete")
    save(r)
    emit(reminderDict(r))

case "update":
    ensure(.reminder)
    guard let id = opt("id") else { fail("--id is required") }
    let r = reminder(byId: id)
    if let t = opt("title") { r.title = t }
    if flag("clear-due") { r.dueDateComponents = nil; r.alarms?.forEach { r.removeAlarm($0) } }
    if let d = opt("due") { setDue(r, d) }
    if let n = opt("notes") { r.notes = n }
    if let p = priorityValue(opt("priority")) { r.priority = p }
    if let l = calendarsNamed(opt("list"), type: .reminder)?.first { r.calendar = l }
    if flag("clear-recur") { r.recurrenceRules?.forEach { r.removeRecurrenceRule($0) } }
    if let rule = opt("recur") { setRecur(r, rule) }
    save(r)
    emit(reminderDict(r))

case "delete":
    ensure(.reminder)
    guard let id = opt("id"), flag("confirm") else { fail("delete needs --id ID --confirm (prefer `complete`)") }
    let r = reminder(byId: id)
    let snapshot = reminderDict(r)
    do { try store.remove(r, commit: true) } catch { fail("delete failed: \(error.localizedDescription)") }
    emit(["deleted": true, "reminder": snapshot])

default:
    print("""
    ek — Calendar & Reminders bridge. Commands:
      access | calendars | events | add-event | lists | reminders | add-reminder |
      complete | uncomplete | update | delete
    See the header of tools/ek.swift for options.
    """)
}
