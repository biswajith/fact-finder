"""Turn the plain example transcript into the shape of Gong's API export:
the /v2/calls/extensive response (metaData + parties) and the /v2/calls/transcript response."""
import json, os, re, sys

# One entry per example call, keyed by the readable transcript's file name.
# parties: name -> (party id, speakerId, userId or None, email, title, affiliation, methods).
# A name starting with "+" is a phone dial-in: no name or email, just phoneNumber.
# asr: speech-recognition slips Gong-style transcripts really make; KEY.md lists them.
CALLS = {
    "ulster-call-2026-08-12.txt": {
        "call_id": "7782342274025937895",
        "title": "Ulster County RFP UC26-039 - clarification call",
        "scheduled": "2026-08-12T10:00:00-04:00", "started": "2026-08-12T10:00:02-04:00",
        "system": "Microsoft Teams", "meetingUrl": "https://teams.microsoft.com/l/meetup-join/example",
        "primary": "Tom Okafor",
        "pricing": r"net thirty|sixty days|monthly invoices|paid on delivery|price|\bfee\b",
        "asr": [("the Comptroller has to approve", "the controller has to approve"),
                ("someone from the Comptroller's office", "someone from the controller's office"),
                ("check with Brenden", "check with Brendan"),
                ("Send everything to Brenden", "Send everything to Brendan")],
        "parties": {
            "Tom Okafor": ("3104582217736401552", "6927345540112087431", "4410392871150362218", "tom.okafor@halvardactuarial.example", "Bid Manager", "Internal", ["Invitee", "Attendee"]),
            "Priya Raman": ("3104582217736401553", "1588203947720365019", "4410392871150362231", "priya.raman@halvardactuarial.example", "Principal", "Internal", ["Invitee", "Attendee"]),
            "Dana Whitcomb": ("3104582217736401554", "8371920465518823046", None, "dwhitcomb@ulstercounty.example", None, "External", ["Invitee", "Attendee"]),
            "Marcus Fell": ("3104582217736401555", "2049957713360871254", None, "mfell@ulstercounty.example", None, "External", ["Invitee", "Attendee"]),
            "+1 845-555-0142": ("3104582217736401556", "7713002846159902387", None, None, None, "Unknown", ["Attendee"]),
            "Sam Lee": ("3104582217736401557", None, "4410392871150362240", "sam.lee@halvardactuarial.example", "Senior Actuary", "Internal", ["Invitee"]),
        },
        "aliases": {"+1 845 555 0142": "+1 845-555-0142"},
    },
    "durham-call-2024-07-24.txt": {
        "call_id": "5129904736618820413",
        "title": "City of Durham RFP 24-0031 - short-list briefing",
        "scheduled": "2024-07-24T14:00:00-04:00", "started": "2024-07-24T14:00:01-04:00",
        "system": "Zoom", "meetingUrl": "https://zoom.us/j/0000000000",
        "primary": "Sam Whitfield",
        "pricing": r"pricing|ninety days|hundred and eighty|\bprice",
        "asr": [("And Kronos is being retired", "And Chronos is being retired"),
                ("Attachment A is EBOP.", "Attachment A is e-bop."),
                ("Info-Tech set this call up", "InfoTech set this call up")],
        "parties": {
            "Sam Whitfield": ("8830215576104429931", "4471902285536610042", "2290417736652108815", "sam.whitfield@corvane.example", "Bid Manager", "Internal", ["Invitee", "Attendee"]),
            "Nadia Brooks": ("8830215576104429932", "9013348820176625503", "2290417736652108827", "nadia.brooks@corvane.example", "Engagement Partner", "Internal", ["Invitee", "Attendee"]),
            "Marco Delgado": ("8830215576104429933", "3365108849920174416", None, "mdelgado@infotech.example", "Advisory Director", "External", ["Invitee", "Attendee"]),
            "Renee Caldwell": ("8830215576104429934", "6602781935513340078", None, "renee.caldwell@durhamnc.example", None, "External", ["Invitee", "Attendee"]),
            "Kevin Osei": ("8830215576104429935", "1187420063398857211", None, "kevin.osei@durhamnc.example", None, "External", ["Invitee", "Attendee"]),
            "+1 919-555-0187": ("8830215576104429936", "7740029316685542190", None, None, None, "Unknown", ["Attendee"]),
            "Eli Navarro": ("8830215576104429937", None, "2290417736652108836", "eli.navarro@corvane.example", "Solution Architect", "Internal", ["Invitee"]),
        },
        "aliases": {"+1 919 555 0187": "+1 919-555-0187"},
    },
}

src, out = sys.argv[1], sys.argv[2]
C = CALLS[os.path.basename(src)]
P = C["parties"]
turns = []
for line in open(src):
    m = re.match(r"\[(\d\d):(\d\d):(\d\d)\] ([^:]+): (.*)", line.strip())
    if m:
        h, mi, s, who, text = m.groups()
        for a, b in C["asr"]:
            text = text.replace(a, b)
        turns.append(((int(h) * 3600 + int(mi) * 60 + int(s)) * 1000, C["aliases"].get(who, who), text))

parties = []
for name, (pid, spk, uid, email, title, aff, methods) in P.items():
    p = {"id": pid}
    if email: p["emailAddress"] = email
    if not name.startswith("+"): p["name"] = name
    if title: p["title"] = title
    if uid: p["userId"] = uid
    if spk: p["speakerId"] = spk  # invited but never joined: no speakerId
    p["context"] = []
    p["affiliation"] = aff
    if name.startswith("+"): p["phoneNumber"] = name
    p["methods"] = methods
    parties.append(p)

def sentences(text):
    return [s for s in re.split(r"(?<=[.?!])\s+", text) if s]

mono = []
for i, (start, who, text) in enumerate(turns):
    nxt = turns[i + 1][0] if i + 1 < len(turns) else start + 4000
    parts = sentences(text)
    want = [int(len(x.split()) / 2.7 * 1000) + 250 for x in parts]
    room = (nxt - 150) - (start + 180) - 120 * (len(parts) - 1)
    k = min(1.0, room / sum(want))  # squeeze to fit before the next speaker
    t, sents = start + 180, []
    for x, w in zip(parts, want):
        end = t + max(200, int(w * k))
        sents.append({"start": t, "end": end, "text": x})
        t = end + 120
    spk = P[who][1]
    topic = "Small Talk" if i == 0 else ("Pricing" if re.search(C["pricing"], text, re.I) else None)
    if mono and mono[-1]["speakerId"] == spk:  # Gong keeps one monologue per uninterrupted speaker
        mono[-1]["sentences"] += sents
        mono[-1]["topic"] = mono[-1]["topic"] or topic
    else:
        mono.append({"speakerId": spk, "topic": topic, "sentences": sents})
for m in mono:
    if m["topic"] is None:
        del m["topic"]
mono[-1]["topic"] = "Next Steps"

call_id = C["call_id"]
doc = {
    "_note": "Made-up example in the shape of Gong's public API (v2). 'extensive' is the response of "
             "POST /v2/calls/extensive with parties exposed; 'transcript' is the response of POST /v2/calls/transcript. "
             "start and end are milliseconds from the start of the call; duration is seconds. "
             "Join transcript speakerId to parties[].speakerId to get names and affiliation.",
    "extensive": {
        "requestId": "4al018gzaztcr8nbukw",
        "records": {"totalRecords": 1, "currentPageSize": 1, "currentPageNumber": 0},
        "calls": [{
            "metaData": {
                "id": call_id,
                "url": f"https://app.gong.io/call?id={call_id}",
                "title": C["title"],
                "scheduled": C["scheduled"],
                "started": C["started"],
                "duration": (turns[-1][0] + 3000) // 1000,
                "primaryUserId": P[C["primary"]][2],
                "direction": "Conference",
                "system": C["system"],
                "scope": "External",
                "media": "Video",
                "language": "eng",
                "workspaceId": "5562739194953732039",
                "sdrDisposition": None,
                "clientUniqueId": None,
                "customData": None,
                "purpose": None,
                "meetingUrl": C["meetingUrl"],
                "isPrivate": False,
                "calendarEventId": "AAMkAGI2TG93AAA=",
            },
            "parties": parties,
        }],
    },
    "transcript": {
        "requestId": "7xq2mz0kp4r1c9vbn3d",
        "records": {"totalRecords": 1, "currentPageSize": 1, "currentPageNumber": 0},
        "callTranscripts": [{"callId": call_id, "transcript": mono}],
    },
}
json.dump(doc, open(out, "w"), indent=2)
print(len(turns), "turns ->", len(mono), "monologues,", sum(len(m["sentences"]) for m in mono), "sentences")
