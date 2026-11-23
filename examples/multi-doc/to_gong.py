"""Turn the plain example transcript into the shape of Gong's API export:
the /v2/calls/extensive response (metaData + parties) and the /v2/calls/transcript response."""
import json, re, sys

src, out = sys.argv[1], sys.argv[2]
turns = []
for line in open(src):
    m = re.match(r"\[(\d\d):(\d\d):(\d\d)\] ([^:]+): (.*)", line.strip())
    if m:
        h, mi, s, who, text = m.groups()
        turns.append(((int(h) * 3600 + int(mi) * 60 + int(s)) * 1000, who, text))

# Speech-recognition slips Gong-style transcripts really make; the key lists them.
ASR = [("the Comptroller has to approve", "the controller has to approve"),
       ("someone from the Comptroller's office", "someone from the controller's office"),
       ("check with Brenden", "check with Brendan"),
       ("Send everything to Brenden", "Send everything to Brendan")]
for i, (t, w, x) in enumerate(turns):
    for a, b in ASR:
        x = x.replace(a, b)
    turns[i] = (t, w, x)

P = {  # name -> (party id, speakerId, userId or None, email, title, affiliation)
    "Tom Okafor": ("3104582217736401552", "6927345540112087431", "4410392871150362218", "tom.okafor@halvardactuarial.example", "Bid Manager", "Internal"),
    "Priya Raman": ("3104582217736401553", "1588203947720365019", "4410392871150362231", "priya.raman@halvardactuarial.example", "Principal", "Internal"),
    "Dana Whitcomb": ("3104582217736401554", "8371920465518823046", None, "dwhitcomb@ulstercounty.example", None, "External"),
    "Marcus Fell": ("3104582217736401555", "2049957713360871254", None, "mfell@ulstercounty.example", None, "External"),
    "+1 845 555 0142": ("3104582217736401556", "7713002846159902387", None, None, None, "Unknown"),
}
parties = []
for name, (pid, spk, uid, email, title, aff) in P.items():
    p = {"id": pid}
    if email: p["emailAddress"] = email
    if not name.startswith("+"): p["name"] = name
    if title: p["title"] = title
    if uid: p["userId"] = uid
    p["speakerId"] = spk
    p["context"] = []
    p["affiliation"] = aff
    if name.startswith("+"): p["phoneNumber"] = "+1 845-555-0142"
    p["methods"] = ["Attendee"] if name.startswith("+") else ["Invitee", "Attendee"]
    parties.append(p)
# Invited, never joined: no speakerId.
parties.append({"id": "3104582217736401557", "emailAddress": "sam.lee@halvardactuarial.example", "name": "Sam Lee",
                "title": "Senior Actuary", "userId": "4410392871150362240", "context": [], "affiliation": "Internal",
                "methods": ["Invitee"]})

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
    topic = "Small Talk" if i == 0 else ("Pricing" if re.search(r"net thirty|sixty days|monthly invoices|paid on delivery|price|\bfee\b", text, re.I) else None)
    if mono and mono[-1]["speakerId"] == spk:  # Gong keeps one monologue per uninterrupted speaker
        mono[-1]["sentences"] += sents
        mono[-1]["topic"] = mono[-1]["topic"] or topic
    else:
        mono.append({"speakerId": spk, "topic": topic, "sentences": sents})
for m in mono:
    if m["topic"] is None:
        del m["topic"]
mono[-1]["topic"] = "Next Steps"

call_id = "7782342274025937895"
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
                "title": "Ulster County RFP UC26-039 - clarification call",
                "scheduled": "2026-08-12T10:00:00-04:00",
                "started": "2026-08-12T10:00:02-04:00",
                "duration": (turns[-1][0] + 3000) // 1000,
                "primaryUserId": P["Tom Okafor"][2],
                "direction": "Conference",
                "system": "Microsoft Teams",
                "scope": "External",
                "media": "Video",
                "language": "eng",
                "workspaceId": "5562739194953732039",
                "sdrDisposition": None,
                "clientUniqueId": None,
                "customData": None,
                "purpose": None,
                "meetingUrl": "https://teams.microsoft.com/l/meetup-join/example",
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
