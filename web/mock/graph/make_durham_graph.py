"""Write durham.graph.json: the Durham bid's labelled facts turned into an entity graph by hand.

No model call. The node types, fields and links below were written by reading every fact in
runs/_bids/durham/facts.json, the way the graph agent in SPEC-v2 would. Each node, field, list item
and link names the facts it rests on, so the page can show the citation behind every value.

    python web/mock/graph/make_durham_graph.py            # from the repository root
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
BID = ROOT / "runs" / "_bids" / "durham"
OUT = Path(__file__).with_name("durham.graph.json")

TYPES = {
    "deal":            {"name": "Deal",               "color": "#4f46e5", "shape": "star"},
    "organization":    {"name": "Organization",       "color": "#0284c7", "shape": "round-rectangle"},
    "person":          {"name": "Person",             "color": "#db2777", "shape": "ellipse"},
    "driver":          {"name": "Driver or priority", "color": "#65a30d", "shape": "round-pentagon"},
    "solution":        {"name": "Oracle solution",    "color": "#2563eb", "shape": "round-hexagon"},
    "process":         {"name": "Business process",   "color": "#0d9488", "shape": "round-rectangle"},
    "system":          {"name": "Current system",     "color": "#78716c", "shape": "barrel"},
    "phase":           {"name": "Phase",              "color": "#16a34a", "shape": "round-tag"},
    "event":           {"name": "Key date",           "color": "#d97706", "shape": "round-diamond"},
    "submission_item": {"name": "Submission item",    "color": "#7c3aed", "shape": "round-rectangle"},
    "gate":            {"name": "Gate",               "color": "#dc2626", "shape": "round-octagon"},
    "reference":       {"name": "Reference",          "color": "#c026d3", "shape": "ellipse"},
    "method":          {"name": "Evaluation method",  "color": "#ca8a04", "shape": "round-hexagon"},
    "criterion":       {"name": "Criterion",          "color": "#eab308", "shape": "round-rectangle"},
    "requirement":     {"name": "Requirement",        "color": "#059669", "shape": "round-rectangle"},
    "contract_term":   {"name": "Contract term",      "color": "#475569", "shape": "round-rectangle"},
    "insurance":       {"name": "Insurance",          "color": "#64748b", "shape": "round-rectangle"},
    "risk":            {"name": "Risk",               "color": "#e11d48", "shape": "round-triangle"},
    "action":          {"name": "Action",             "color": "#9333ea", "shape": "round-tag"},
    "question":        {"name": "Question",           "color": "#0891b2", "shape": "ellipse"},
    "competitor":      {"name": "Competitor",         "color": "#b45309", "shape": "round-rectangle"},
}

nodes: list[dict] = []
links: list[dict] = []


def F(name, value, facts, status="none", reason="", competing=None):
    """One field. status: none, auto_resolved, needs_review, decided, tentative, expired."""
    return {"name": name, "value": value, "facts": facts.split(), "status": status, "reason": reason,
            "competing": [{"value": v, "facts": f.split()} for v, f in (competing or [])]}


def L(name, items):
    return {"name": name, "items": [{"value": v, "facts": f.split()} for v, f in items]}


def N(id, type, label, sub="", facts="", fields=(), lists=(), status="live", note=""):
    nodes.append({"id": id, "type": type, "label": label, "sub": sub, "facts": facts.split(),
                  "fields": list(fields), "lists": list(lists), "status": status, "note": note})


def E(src, edge, dst, facts="", status="live"):
    links.append({"from": src, "edge": edge, "to": dst, "facts": facts.split(), "status": status})


# ---------------------------------------------------------------- the deal and the organisations
N("deal", "deal", "Oracle ERP Implementation Partner", "City of Durham · RFP #24-0031",
  "aec41fd5ff 9c9736eb87", fields=[
      F("Solicitation", "RFP #24-0031, Oracle ERP Implementation Partner", "aec41fd5ff 9c9736eb87 8eae1aef45"),
      F("Stage", "Short-listed; presentations being prepared", "a268fcc013 ca80ee2717"),
      F("Selection", "Second phase of a two-step process: Oracle already chosen, this RFP picks the implementation partner only",
        "397096b20b 62cb397108 0c4d7bb425 b53256dcd5"),
      F("Estimated value", "$7,900,000 over about 30 months", "71314dc8fd"),
      F("Our target price", "$7.5–8.2M, fixed price by phase, contingency carried in utility billing", "5022cdcd60"),
      F("Pricing now", "Indicative; short-listed firms give refined pricing before their presentation",
        "c039ed57e0 919456e8b7 d9d12183a7"),
      F("Operating Model", "Sets the system boundaries and which mega-processes get implementation support",
        "80883c58db f9d479bc85"),
      F("City aims for", "A fair, transparent process and the best, most experienced partner", "a3999015bc 33f1e2a011 68dfc9cc68"),
      F("Bid decision", "Decided to bid on 2024-05-21", "9040bcba50"),
      F("Submitted", "By email on 2024-06-07, three days early", "a97ec2be6c 93c28aea12"),
  ], lists=[L("Package we sent", [
      ("Proposal PDF", "251d70a18b"), ("Response template", "251d70a18b"), ("Pricing template", "251d70a18b"),
      ("Attachment A EBOP form", "251d70a18b"), ("UBE statement of intent", "251d70a18b"),
      ("Online diversity questionnaire", "251d70a18b")])])

N("org_durham", "organization", "City of Durham", "Buyer · North Carolina", "b4273062cb a7bc51e5ff", fields=[
    F("Population", "283,506 (2020 Census)", "4d3ffdd158"),
    F("Employees", "2,903 (2,459 full time, 258 part time, 186 seasonal)", "310b74ddf6 1d27228d84 34c8424df0 a874d1fe70 65b2392478"),
    F("Utility accounts", "About 95,000, billed monthly: water and sewer, some stormwater", "9d3849ebfe c44d8851cb c5e158a16a"),
    F("Setting", "Education, medical and research centre; Duke and Duke Health are the largest employers", "4874778f49 e0a14d5159"),
    F("Contact rule", "Since issue, all City contact goes through Info-Tech", "2c1aaf8ed6 5c770e5f98"),
    F("Accessibility", "ADA Coordinator: (919) 560-4197, ADA@durhamnc.gov, at least 48 hours ahead", "cebd372ca9"),
    F("Address", "101 City Hall Plaza, Durham, NC 27701", "8d12ca3fe3"),
])
N("org_council", "organization", "City Manager / City Council", "Awarding authority", "44cbdd7221 57e35c48b4", fields=[
    F("Role", "Awards after negotiation; not bound by the criteria or the recommendation", "57e35c48b4 44cbdd7221"),
    F("Effect", "Start date depends on their calendar", "44cbdd7221"),
])
N("dept_bms", "organization", "Budget & Management Services", "City department", "dbc3cc0c52 fa2f0b0147")
N("dept_cbs", "organization", "Customer Billing Services", "Water Management", "66fac5d4d5 fa2f0b0147")
N("dept_ubc", "organization", "Underutilized Business Compliance", "Receives submissions", "83b47824f5 ed2b1d49a4", fields=[
    F("Email", "ubcfinance@durhamnc.gov", "ca0e19546b ed2b1d49a4")])
N("dept_cc", "organization", "Contracts & Compliance", "Finance · UBE help", "311bb4f074", fields=[
    F("Phone", "(919) 560-4180", "311bb4f074")])
N("dept_risk", "organization", "Risk Management", "City department", "bf03601009 572ce87f30")
N("dept_purch", "organization", "Purchasing", "City department", "7a291cd3b8 458620c830", fields=[
    F("Email", "purchmailbox@durhamnc.gov", "7a291cd3b8")])
N("dept_tech", "organization", "Technology Solutions", "Certificate holder", "8d12ca3fe3")
N("org_infotech", "organization", "Info-Tech Research Group", "Selection advisor", "4aaad774e8 a5e91ac639", fields=[
    F("Role", "Runs the partner selection with its ERP Partner Selection methodology", "4aaad774e8 a5e91ac639 333ebf1e05 b53256dcd5"),
    F("Channel", "The sanctioned channel for City contact after submission", "711eec174e 83b47824f5"),
    F("Delivery", "Implementation follows Info-Tech's ERP implementation methodology", "2f0c14f2f9 debb73ff1b"),
])
N("org_oracle", "organization", "Oracle", "Selected software", "62cb397108 4fe6bb7014")
N("org_corvane", "organization", "Corvane Consulting", "Our firm", "b02e30631a 7da68d85a1", fields=[
    F("Qualifying references", "One (Riverbend); a second depends on signing Lakemont", "3eea54224d 2bdda47582",
      status="auto_resolved",
      reason="The deal notes rank above the call transcript. On the call we said two NC municipalities; the notes correct it to one until Lakemont is signed.",
      competing=[("Two NC municipalities, 100k–500k", "58970ce526")]),
])
N("org_lakemont", "organization", "Lakemont Utility Advisors", "Teaming candidate", "8636357da9 58a1fb6aa2",
  status="tentative", fields=[
      F("Status", "Under discussion as utility-billing teaming partner", "8636357da9", status="tentative"),
      F("Brings", "A 165k-population municipal reference", "105ff4fa3c")])

# ---------------------------------------------------------------- people
N("p_renee", "person", "Renee Caldwell", "ERP Program Manager · City", "e959263476 d54fd2fe06", fields=[
    F("Influence", "Leads the City's day-to-day work", "d54fd2fe06"),
    F("Wants", "A phased plan she can defend to Council", "d54fd2fe06 f2908fd868"),
    F("Knows us", "From a February Oracle public-sector user group", "d54fd2fe06"),
    F("Said", "30-day termination is standard City language and won't move", "fc778eb939 8bd3d6a9d2"),
])
N("p_kevin", "person", "Kevin Osei", "Owns utility billing · City", "66fac5d4d5 8cd88ce30a", fields=[
    F("Influence", "Decides whether he trusts us on utility billing", "61df5ea363"),
    F("History", "Burned by the last Munis upgrade", "8cd88ce30a"),
    F("Stance", "Skeptical of providers without utility-billing references", "8cd88ce30a"),
    F("Said", "Billing users are closer to sixty now", "b5d1056dab"),
])
N("p_lauren", "person", "Lauren", "Budget & Management Services", "dbc3cc0c52 572ce87f30", fields=[
    F("Joined", "Briefing call by phone, +1 919 555 0187", "dbc3cc0c52 9f5590d56b"),
    F("Seems", "Close to Risk Management", "572ce87f30", status="tentative"),
    F("Said", "Risk may require $5M cyber liability; not final", "471e36c36d cf0af5168f"),
])
N("p_marco", "person", "Marco Delgado", "Advisory Director · Info-Tech", "3804ec7042 f955903203", fields=[
    F("Role", "City's selection advisor; runs the process and the scoring sheets", "3804ec7042 f955903203"),
    F("Style", "Everything goes through him; strict about process", "f955903203"),
])
N("p_ahmed", "person", "Ahmed Ebrahim", "Info-Tech", "ca0e19546b", fields=[
    F("Email", "aebrahim@infotech.com", "ca0e19546b ed2b1d49a4")])
N("p_nadia", "person", "Nadia Brooks", "Engagement Partner · Corvane", "b02e30631a")
N("p_sam", "person", "Sam Whitfield", "Bid Manager · Corvane", "7da68d85a1")

# ---------------------------------------------------------------- why they buy
N("drv_disparate", "driver", "Disparate, unintegrated systems", "RFP driver",
  "47388aae4a 1a5dda8b7c 1ca72d924b f173bde1ce 9fa97f45fe c9bcf57636 fad03203a3")
N("drv_truth", "driver", "No single source of truth", "RFP driver", "4dc3bca943 2fe52a38ec 73512a8aa3 addcb2b40d 9de664f264")
N("drv_manual", "driver", "Manual work and re-keying", "RFP driver", "c3ec948d17 2ecea12dca")
N("drv_reports", "driver", "Timely reports across departments", "RFP driver", "fa2f0b0147")
N("drv_future", "driver", "Efficiency and future needs", "RFP driver", "2222002b20 46e4625820 6d5a09283d")
N("hb_billing", "driver", "Utility billing done right", "Hot button", "61df5ea363")
N("hb_payroll", "driver", "Payroll live on 1 January", "Hot button · clean tax year", "47197b92dc 94d64e2304")
N("hb_phased", "driver", "Phased plan with City staff time", "Hot button · staff are thin", "f2908fd868 11c4764f44")

# ---------------------------------------------------------------- what they buy
N("sol_erp", "solution", "Oracle Fusion ERP", "Finance, procurement, supply chain", "e6ebf0a7ce", lists=[L("Cloud services", [
    ("Enterprise Resource Planning", "e6ebf0a7ce"), ("Procurement", "0b217b6180"), ("Supply Chain Execution", "474bff8d17"),
    ("Risk Management", "aadf87465d"), ("WebCenter Forms Recognition", "8551ecea3a")])])
N("sol_hcm", "solution", "Oracle Fusion HCM", "HR, payroll, time", "ec894552f9", lists=[L("Cloud services", [
    ("HCM Base", "ec894552f9"), ("HR Help Desk", "8a89159edb"), ("Recruiting", "57e8dcfbeb"),
    ("Workforce Health and Safety Incidents", "95e9f79902"), ("HCM Communicate", "e726c88bd8"),
    ("Talent Management", "ea100c755b"), ("Workforce Compensation", "ff850fa880"), ("Payroll for United States", "0553cc8c39"),
    ("Time and Labor", "bd5e5eb566"), ("Learning", "34407ae3ee")])])
N("sol_epm", "solution", "Oracle EPM", "Budget and forecast", "1ed50048ed", lists=[L("Cloud services", [
    ("EPM Enterprise", "1ed50048ed"), ("Additional Application for EPM", "bfe6657e87")])])
N("sol_util", "solution", "Oracle Utilities Customer Cloud", "Utility billing · B90577", "4efa6d457b 3a23612984")
N("sol_platform", "solution", "Platform and security", "Oracle cloud", "3eeeb0f052", lists=[L("Cloud services", [
    ("HIPAA Advanced Security", "87a078053f"), ("Database Vault and Break Glass", "c03eef7f0f"),
    ("PaaS and IaaS Universal Credits", "3eeeb0f052")])])

N("proc_r2r", "process", "Record to Report", "Finance & accounting", "7943e4cd69", fields=[
    F("Full users", "35", "7943e4cd69"), F("Limited users", "247", "7943e4cd69")])
N("proc_p2p", "process", "Procure to Pay", "Purchasing", "3fd5dea92c", fields=[
    F("Full users", "13", "3fd5dea92c"), F("Limited users", "353", "3fd5dea92c")])
N("proc_a2d", "process", "Acquire to Dispose", "Asset management", "4223eb113c", fields=[
    F("Full users", "62", "4223eb113c"), F("Limited users", "17", "4223eb113c")])
N("proc_p2perf", "process", "Plan to Perform", "Budget & forecast", "d2d235c1a0", fields=[
    F("Full users", "164", "d2d235c1a0"), F("Limited users", "105", "d2d235c1a0")])
N("proc_hrcore", "process", "HR – Core", "Records, positions, benefits", "b8cf9fb069", fields=[
    F("Full users", "100", "b8cf9fb069"), F("Limited users", "2,900", "b8cf9fb069")])
N("proc_talent", "process", "HR – Talent", "Recruit, onboard, perform, learn", "72d8dcd9ac", fields=[
    F("Full users", "3,000", "72d8dcd9ac"), F("Limited users", "120", "72d8dcd9ac")])
N("proc_wfm", "process", "HR – Workforce", "Time and attendance", "f60aed10f6", fields=[
    F("Users", "3,000", "f60aed10f6")])
N("proc_m2c", "process", "Meter to Cash", "Utility billing / CIS", "00301ff043", fields=[
    F("Full users", "40", "00301ff043 1cc6ab4292 521519dd7d", status="auto_resolved",
      reason="The RFP outranks the call. The RFP table stands unless the City changes it in writing; we price 40 and state 60 as an assumption.",
      competing=[("About 60 (call centre team added)", "b5d1056dab f89f4caf17")]),
    F("Limited users", "50", "00301ff043"),
    F("Pricing approach", "Price 40, state 60 as an assumption", "a9b379a7c0 458d6f388a f89f4caf17"),
])

N("sys_munis", "system", "Tyler Munis", "Finance, HR, assets, budget", "9052a2e88e", fields=[
    F("Used for", "Finance and procurement, assets, core HR, time, budgeting",
      "9052a2e88e 8fddc70352 6d6aa3a09e 93c8eb7603 eca792cced"),
    F("History to migrate", "Seven years of financial history", "4d9485c4e5 37a38eb52e"),
])
N("sys_munis_util", "system", "Tyler Munis Utility", "Utility services", "a88d23a13d")
N("sys_kronos", "system", "Kronos", "Time and attendance", "93c8eb7603", fields=[
    F("Disposition", "Being retired; Oracle Time and Labor replaces it", "fe4684fe91 822a53cc23 37a38eb52e",
      status="auto_resolved",
      reason="The RFP lists Kronos in use; the call says it is being retired. Both are true today, so the value moves on to 'retiring'.",
      competing=[("In use for time and attendance", "93c8eb7603")])])
N("sys_talent", "system", "NeoGov, Cornerstone, Saba", "HR talent", "fabb2d3c7e")
N("sys_assets", "system", "AssetWorks, Facility Dude, CityWorks", "Assets", "8fddc70352")
N("sys_budget", "system", "SharePoint and Excel", "Budgeting", "eca792cced")
N("sys_other", "system", "Other City software", "Appendix B", "48da10ccd8", lists=[L("Applications", [
    (n, "48da10ccd8") for n in ["WasteWorks", "Faster", "Neighborly", "NextGen", "OnBase", "Boss", "Grayco",
                                "FuelMaster", "CivicPlus", "Paymentus", "ESRI"]])])

N("ph1", "phase", "Phase 1 · Finance & Procurement", "City's first choice", "11c4764f44 56178940ad")
N("ph2", "phase", "Phase 2 · HCM & Payroll", "Largest workstream", "11c4764f44 56178940ad 65b2392478", fields=[
    F("Go-live target", "1 January 2026", "94d64e2304 47197b92dc 56178940ad 79165f7699", status="tentative",
      reason="'January 2026 if that's realistic.' Council timing could squeeze it.")])
N("ph3", "phase", "Phase 3 · Utility billing", "Riskiest workstream", "11c4764f44 65b2392478", fields=[
    F("Contingency", "Carried here in our price", "5022cdcd60")])

# ---------------------------------------------------------------- key dates
N("ev_issued", "event", "RFP issued", "2024-05-10", "fa9327572d 4005ad3dda", fields=[F("Date", "2024-05-10", "fa9327572d 4005ad3dda")])
N("ev_biddecision", "event", "We decided to bid", "2024-05-21", "9040bcba50", fields=[F("Date", "2024-05-21", "9040bcba50")])
N("ev_questions", "event", "Questions close", "2024-05-24 · 14:00 ET", "4bffa5f44f", fields=[
    F("Date", "2024-05-24 14:00 ET", "4bffa5f44f 6f2651c1d9 a05b9a4177"),
    F("Rule", "No answers to addenda questions received later", "6f2651c1d9")])
N("ev_submitted", "event", "We submitted", "2024-06-07", "a97ec2be6c", fields=[F("Date", "2024-06-07", "a97ec2be6c 93c28aea12")])
N("ev_due", "event", "Proposals due", "2024-06-10 · 14:00 ET", "816716ee8a ca0e19546b", fields=[
    F("Date", "2024-06-10 14:00 ET", "816716ee8a fa9327572d ca0e19546b 93c28aea12", status="auto_resolved",
      reason="The RFP (2.6 and 3.15) says 2 pm. One deal-notes line says 5 pm; a later line in the same notes corrects it to 2 pm.",
      competing=[("2024-06-10 17:00 ET", "a05b9a4177")]),
    F("City may", "Change dates or waive deadlines at its discretion", "2085220473 c5e04b9275")])
N("ev_shortlist", "event", "Short-listed", "2024-07-12", "ca80ee2717", fields=[
    F("Date", "2024-07-12", "ca80ee2717"), F("RFP estimate", "About 30 days after proposals are due", "214e617f88")])
N("ev_briefing", "event", "Short-list briefing call", "2024-07-24 · 14:00 ET", "26bb3a210c cf76672882", fields=[
    F("Date", "2024-07-24 14:00–14:05 ET", "26bb3a210c cf76672882"),
    F("Attended", "Info-Tech, Renee Caldwell, Kevin Osei, Lauren by phone", "348e346a3a")])
N("ev_teaming", "event", "Decide second reference or teaming", "by 2024-08-09", "7a4930ee48", fields=[
    F("Date", "2024-08-09", "7a4930ee48")])
N("ev_refs", "event", "Reference calls", "August 2024", "278d1d9dd2 4dd8e9f177", fields=[
    F("When", "August 2024", "278d1d9dd2 4dd8e9f177"),
    F("Be ready", "Contact names on request", "278d1d9dd2 66dca6f58d")])
N("ev_agenda", "event", "Presentation agenda arrives", "≈ 2 weeks before", "d9b7a6455c", fields=[
    F("When", "About two weeks before the presentations", "d9b7a6455c 10c0bfe9cb d5e5ddfa1f")])
N("ev_pricing", "event", "Refined pricing due", "1 week before our slot", "54a643bf67 7a851b62a1", fields=[
    F("When", "One week before our presentation slot", "54a643bf67 7a851b62a1"),
    F("Template", "The same pricing template, updated", "67a6c2e376")])
N("ev_dryruns", "event", "Two dry runs", "before 2024-09-16", "a6947105fe")
N("ev_present", "event", "Partner presentations", "week of 2024-09-16", "3443eaedb4 10c0bfe9cb", fields=[
    F("Date", "Week of 2024-09-16, City Hall", "3443eaedb4 10c0bfe9cb", status="auto_resolved",
      reason="The RFP gave no date ('TBD'). The briefing call and the deal notes set the week of 16 September.",
      competing=[("To be determined", "18c28476e2 0bb953965b")]),
    F("Format", "3 hours in person, demo included, recorded; 90 minutes of scripted scenarios",
      "1b2076fe3b d7e0dedfb6 66f0aaad44 8a75f1da95 35b4d52433 10c0bfe9cb"),
    F("RFP estimate", "About 60 days after short-list notice", "15507d567c"),
    F("Must attend", "Shortlisted proponents must present to City subject experts", "ad6c714b69")])
N("ev_recommend", "event", "Final partner recommendation", "≈ 30 days after presentations", "24ee732d76", fields=[
    F("When", "About 30 days after the presentations (≈ mid-October 2024)", "24ee732d76")])
N("ev_award", "event", "Final award", "≈ 90 days after recommendation", "96e28c6819", fields=[
    F("When", "About 90 days after the recommendation (≈ January 2025)", "96e28c6819"),
    F("Depends on", "City Manager or Council calendar", "44cbdd7221")])
N("ev_pricevalid", "event", "Our prices stop being valid", "2024-12-07", "fb8ab68edf", fields=[
    F("Date", "2024-12-07 (180 days after the due date)", "fb8ab68edf bd63d6113a")])
N("ev_payroll", "event", "Payroll go-live target", "2026-01-01", "94d64e2304 56178940ad", status="tentative", fields=[
    F("Date", "2026-01-01", "94d64e2304 56178940ad 79165f7699", status="tentative")])

# ---------------------------------------------------------------- how to submit
N("sub_email", "submission_item", "Email submission", "Due 2024-06-10 14:00 ET", "ca0e19546b 1c6d01d9b3", fields=[
    F("To", "ubcfinance@durhamnc.gov", "ca0e19546b ed2b1d49a4"),
    F("Copy", "Ahmed Ebrahim, aebrahim@infotech.com", "ca0e19546b"),
    F("Subject", "RFP #24-0031 – Proposal Submission - (proponent name)", "ca0e19546b"),
    F("Proposals", "One per proponent, whatever the subcontractors", "3834708573")])
N("sub_proposal", "submission_item", "Proposal document", "PDF or Word", "81a4023023 15dadd25eb", fields=[
    F("Format", "PDF or Microsoft Word; follow the RFP's format; extra material in an appendix",
      "81a4023023 0985665bb2 b5395e5a21 92fc8494e5 13706b7d71")],
  lists=[L("Must contain", [
      ("Executive summary and marketing collateral", "15dadd25eb"),
      ("Contact information", "595a05b410 f3c73a0fcf"),
      ("Legal name, entity type, state, signers", "d689d021bd 51f6c9ba95 89edd5fe11 32c3f7f2ac 9b9b9b879d"),
      ("NC certificate of authority if out of state", "cd70ddafdd"),
      ("Solution overview and components", "7ce0c3c60f"),
      ("Assumptions about City actions", "121725e816"),
      ("Conflicts of interest", "b9e19553d1"),
      ("Contract objections", "4eff890a54"),
      ("Availability for the presentation weeks", "a316367fdf")])])
N("sub_response", "submission_item", "Proponent Response Template", "Excel · Sections 4 and 6", "7109273f6e e04ed8513a 5451f5214b b17a6efed4")
N("sub_pricing", "submission_item", "Proponent Pricing Template", "Excel · Section 7", "e5ef2ca1af 8fb2d53eac e94c6cffb1 2197ff18f6")
N("sub_ebop", "submission_item", "EBOP form", "Equal Business Opportunity Program", "f91e57c3c1 7a1d0204b4 fd0c630980", fields=[
    F("Attachment", "A", "fd0c630980 7a1d0204b4 f91e57c3c1 182b60b7a9 9754edad98 0096c0c6ce", status="decided",
      reason="Section 3.17 calls it Attachment B. Marco Delgado confirmed on the call that 3.15 is right (A) and will tell all firms in writing.",
      competing=[("B", "136053243b")]),
    F("Complete", "Print it, or fill it in on the Contracts & Compliance page", "94b697ee61 07def574ff")])
N("sub_ube", "submission_item", "UBE Statement of Intent", "Separate document", "5727042881", lists=[L("Answers", [
    ("How we promote equitable contracting for Underutilized Businesses", "5a6c503ec8"),
    ("What we have done to give them opportunities", "cb377a43ae")])])
N("sub_diversity", "submission_item", "Workforce Diversity Questionnaire", "Online form", "407f7d96ca b4ae1ad950 de407a3b26", fields=[
    F("Required", "Before any contract is signed; recommended with the proposal", "e1b3883af0 a7d6bfa5e5"),
    F("Page limits", "Not counted", "9e0a5e099c"),
    F("Paper copy", "Email purchmailbox@durhamnc.gov", "7a291cd3b8")])
N("sub_tradesecret", "submission_item", "Trade-secret marking", "Optional", "2fb19c6050 25afc2d271", fields=[
    F("Rule", "Mark 'trade secrets' when first disclosed, keep it separate, only in good faith",
      "2fb19c6050 25afc2d271 e9e3f0f2b8 ab44150a1c c8a00a00c1")])
N("sub_partners", "submission_item", "Partnership disclosure", "Primary proponent", "c0142ad3f6 8be1c78be7", fields=[
    F("Rule", "Disclose all partners and subcontractors; one primary proponent; each partner's scope and role",
      "c0142ad3f6 8be1c78be7 3f474e3a80 8049a8feb5 efc5ce2bb3 54cf4b9b03")])

# ---------------------------------------------------------------- gates
N("gate_oracle", "gate", "Oracle-approved partner", "Mandatory · 3.21", "ef7005ef02 6af3a21476", fields=[
    F("Rule", "In good standing, authorised in the US to implement Oracle Fusion", "ef7005ef02 6af3a21476")])
N("gate_experience", "gate", "Municipal experience", "Mandatory · 3.21", "d6a3608bc1 1ca4a8bd86", fields=[
    F("Rule", "Similar scope in the last 5 years: a comparable US city and two municipalities of 100k–500k; NC preferred",
      "d6a3608bc1 1ca4a8bd86 6af3a21476 2bdda47582"),
    F("Our position", "At risk: Riverbend qualifies, Pine Hollow does not; Lakemont's 165k reference is pending",
      "2bdda47582 105ff4fa3c 3eea54224d", status="needs_review",
      reason="A mandatory gate that rests on a teaming deal not yet signed. A person must choose: sign Lakemont, or use the fallback.")])
N("gate_all", "gate", "Meet 100% of mandatory requirements", "3.21 · 3.15", "e4e2b0057f 88dd4507f9")
N("gate_nclaw", "gate", "Comply with North Carolina business law", "3.15", "48cf16991b")
N("disq_contact", "gate", "Contacting City staff directly", "May disqualify", "3a0ac06205 ed2b1d49a4 5c770e5f98")
N("disq_understanding", "gate", "Not understanding the RFP", "May disqualify, even after award", "d72c744a26 9664090f0a 67086c2a14")
N("disq_instructions", "gate", "Not following instructions", "May reject", "11cf07195c c84c3888cd")
N("disq_qualified", "gate", "Not shown qualified", "May reject", "b2c74b4d7b 13c86bba84")
N("disq_lists", "gate", "On NC boycott or Iran lists", "Contract void", "581c4c575b 1516899cf9")

N("ref_riverbend", "reference", "Riverbend", "Qualifies", "2bdda47582")
N("ref_pinehollow", "reference", "Pine Hollow", "Does not qualify", "2bdda47582", status="removed",
  note="Shown faded: it cannot count towards the experience gate.")
N("ref_lakemont", "reference", "Lakemont's 165k municipality", "Pending teaming", "105ff4fa3c", status="tentative")

# ---------------------------------------------------------------- scoring
N("method", "method", "Best value award", "Most advantageous, not lowest price", "01677e8786 ba02021708", fields=[
    F("Method", "Most advantageous proposal, price and other factors; not bound to the lowest price",
      "01677e8786 ba02021708 27c405735f"),
    F("Evaluates", "Competence, compliance, format and enterprise", "b1e2b9f33b 54fddc0a6e"),
    F("Discretion", "The City may set or change criteria and procedure", "00f1bb5436 36b38c91a6"),
    F("Watch", "Following the process is read as a sign of the future relationship", "6b5167f065"),
    F("May ask for", "Interviews, presentations, samples, demonstrations", "a0d4c5b859"),
    F("Notice", "Selected and unselected proponents told by email", "45bf3fa2d7 0c319b6357"),
    F("After presentations", "Negotiations with the selected proponent(s)", "511d3001aa"),
  ], lists=[L("Other factors", [
      ("Government and Oracle experience, collaboration, methodology, viability, references, price", "b4a6b07d5a"),
      ("Approach and understanding of City objectives", "696e2ed7c7"), ("Methodology and track record", "94b920654a"),
      ("Functionality, usability, performance, integration", "0d1403ad0c"), ("Similar local government experience", "24b7c19a62"),
      ("Customer reference feedback", "60374f0ba2"), ("Compliance with City terms", "4b753dfac5"),
      ("Integration with City systems", "c6eba4d539"), ("Ongoing training and support", "c0f046f071")])])
for cid, name, fid, looks in [
    ("crit_understanding", "Project understanding", "e7bd611a9e", "City challenges, risks, priorities, scope"),
    ("crit_pm", "Project management", "af28387c9a", "Methodology, staff skills, implementation and training plan"),
    ("crit_impl", "Implementation approach", "fa32fca003", "Discovery, data migration, interfaces, testing, support"),
    ("crit_exp", "Experience & qualifications", "30434119e7", "Viability, Oracle experience, 2 municipalities 100k–500k, references"),
    ("crit_cost", "Cost", "05b912c9b4", "Indicative cost, support and training, breakdown, all modules"),
]:
    N(cid, "criterion", name, "No points stated", fid, fields=[F("Looks at", looks, fid), F("Weight", "No points stated", fid)])

# ---------------------------------------------------------------- requirements
N("req_scope", "requirement", "Scope of work", "4.2 · must", "bdfe312d94 f855a68741", fields=[
    F("Deliver", "Design, install, implement, configure, UAT, train, integrate and connect the approved Oracle ERP",
      "bdfe312d94 bbd359a8b5 db7ca2e370 b6318d5f86"),
    F("Also", "Best-practice guidance, process re-engineering, project management, migration, reports", "f855a68741"),
    F("Delivered by", "Experienced Oracle ERP experts with comparable projects", "f2653676ca"),
    F("Approach", "Left to the bidder", "cd45758841")])
N("req_expertise", "requirement", "Oracle local-government expertise", "1.1 · 4.2 · must", "298e956131 2e4e3fe02c", fields=[
    F("Rule", "Proven Oracle implementation in local government, especially utility billing",
      "298e956131 2e4e3fe02c 2c4f1e11ff 72ff60c95f")])
N("req_method", "requirement", "Implementation methodology", "4.2.1", "218fcd97bc", lists=[L("Describe", [
    ("Project management approach and methodology", "218fcd97bc"), ("Realistic phasing; phased or big bang", "224050df9f 8230f7ba06"),
    ("Assumptions and dependencies", "d92c24be7f"), ("Team structure and lead-resource bios", "58e10a80e2"),
    ("Module plan with City staff commitment", "1c9b2bb519"), ("Critical path", "a9ea3081c1"), ("Risk plan", "dbe055d091"),
    ("Tracking and collaboration tools", "233f484044"), ("Regular review meetings", "040b6be100"),
    ("Change management", "f3c7bf012e"), ("Communications and crisis plan", "b666eb6e1a c6ad796ae9"),
    ("Current-process analysis and requirements", "d27e8e9504 597982bd68 27ee82d9f5"),
    ("Deployment, release, back-out plan", "54b5074bca"), ("Post-go-live support and upgrades", "6cf252f716 2442bdae66 4ac8400ac5")])])
N("req_migration", "requirement", "Data migration", "4.2.1 · call", "b10fe91d3f 4d9485c4e5", fields=[
    F("History", "Seven years of financial history from Munis; open items and balances for the rest",
      "4d9485c4e5 5fdd54b228 37a38eb52e bd25230c32"),
    F("Describe", "Prerequisites, City and our roles, validation and cleansing", "b10fe91d3f 7bc092258b"),
    F("Cutover", "Kronos to Oracle Time and Labor", "822a53cc23")])
N("req_integration", "requirement", "Integrations", "4.2.2 · must", "6cc17c0ff8 7e88d51f2f", fields=[
    F("Rule", "Build, code and test interfaces between Oracle and other City systems", "6cc17c0ff8 7e88d51f2f"),
    F("Skills", "REST, web services, FBDI; error handling", "8a09f46a0c"),
    F("Show", "Experience or pre-built connectors for the listed software", "0095285711")])
N("req_testing", "requirement", "Testing and acceptance", "4.2.3", "0ce5cf99da 9e7d269a78", lists=[L("Describe", [
    ("Methodology, phases and roles", "0ce5cf99da a490dae5b5"), ("Success criteria and KPIs", "65e4453f27"),
    ("Dependencies, risks, mitigation", "83ad98ec99"), ("Schedule fitting City constraints", "4d311a6357 5b53ac3110"),
    ("Defects, retesting and bug tracking", "c4985c4d42 f1abf0ed1e 966d6c4664"),
    ("Knowledge transfer during testing", "ef79d26aaa"), ("Formal acceptance and sign-off", "9e7d269a78 47937e8199")])])
N("req_support", "requirement", "Support tiers and SLA", "5.1", "8ad5955677", lists=[L("Give", [
    ("Each tier's service, price, terms, hours, response and escalation", "8ad5955677 d64b05dfc0"),
    ("A standard SLA", "ac1056fd42"), ("Severity levels, resolution targets, release handling", "4678d0dcf3"),
    ("Other services: tuning, monitoring, audits", "02f41f01dc"), ("Post-implementation options are optional now", "6b47d951fb"),
    ("Support fees with documentation", "edd363b90a bbf8ec56b1")])])
N("req_training", "requirement", "Training", "5.2", "382beda405", lists=[L("Give", [
    ("Offerings for admins, users, super users", "382beda405 a4a6b1184f"), ("Preferred patterns", "328759667f"),
    ("Certification programmes", "d3f1a412e0"), ("Custom training and its pricing", "b0696efeef"),
    ("Keeping materials current", "dddb499d6d"), ("Community support", "e04eb00657"),
    ("Ongoing options after go-live", "11735ad963 0eaef7e299")])])
N("req_profile", "requirement", "Proponent profile", "6.1", "f811005660", lists=[L("Give", [
    ("Legal name, founding year, offices", "f811005660"), ("Legal status and ownership", "33dcb0babd"),
    ("Headcount: total, support, implementation", "e3b3d9bd92 04a681566b 58a7743806"),
    ("Structure and key managers", "79cbbad7ba"), ("Strengths and recognitions", "7b425b7a3c 5a1a3235cc"),
    ("Litigation in the last 5 years", "87eb103f32")])])
N("req_viability", "requirement", "Financial viability", "6.2", "1eaaa7b766", lists=[L("Give", [
    ("Documents proving viability", "1eaaa7b766"), ("Annual report if public", "c19ae38723"),
    ("Strategic alliances", "1471988b57"), ("Five-year growth", "5613844a13")])])
N("req_refs", "requirement", "References and case studies", "6.3 · 7.2", "4a60552cf6", lists=[L("Give", [
    ("Oracle ERP and local-government case studies", "4a60552cf6 98765bd01f"),
    ("Reference contacts when short-listed", "66dca6f58d"), ("Repeat business", "039fee3b35"),
    ("Three comparable projects with costs", "e52f5e3d7a")])])
N("req_pricing", "requirement", "Pricing detail", "7.1–7.5", "57a63f0227", lists=[L("Give", [
    ("All one-time costs", "57a63f0227 5a3d4056ae"), ("Every pricing field filled", "4cf37c6e50"),
    ("Hourly rates for hourly work", "a86daf3ef7"), ("Fixed-cost items with scope", "92b37c0d3e"),
    ("Structures, fees and discounts", "bf7957b8dc"), ("Managed-services options", "7e6c1f6ce9")])])
N("req_comms", "requirement", "Communication rules", "3.14 · must", "a9490bdd06", fields=[
    F("Rule", "Questions by email to the named contact, with the set subject line; only written answers count",
      "a9490bdd06 dadd546ff3 b599ebc2b8"),
    F("City replies", "Within five business days, in good faith", "dadd546ff3")])
N("req_culture", "requirement", "Partnership culture", "1.2", "6a48a22877", fields=[
    F("Rule", "Cooperate with and respect the City's culture; a business-critical relationship", "6a48a22877 0194a68ceb")])
N("req_ip", "requirement", "City logos and trademarks", "3.4", "cb2f03f43f")

# ---------------------------------------------------------------- contract
N("ct_model", "contract_term", "Model Services Contract", "Appendix A", "75ac0f9cad 5291e9dc63", fields=[
    F("Text", "Missing from the RFP we received", "b1329eabb7", status="needs_review",
      reason="The contract the City intends to use is not in the RFP text. Ask Info-Tech for Appendix A."),
    F("Objections", "State them in the proposal", "4eff890a54"),
    F("Becomes contract", "The RFP and our proposal become part of it", "030e017305"),
    F("Negotiable", "Any term, even mandatory ones", "6989243b7e")])
N("ct_term", "contract_term", "Term", "3 years + 2 × 1-year options", "a9245b6295", fields=[
    F("Length", "3 years with two one-year options", "a9245b6295 9eca128c42 25707206fe"),
    F("Options", "City expects to use both", "9229b1166e 25707206fe", status="tentative")])
N("ct_termination", "contract_term", "Termination for convenience", "30 days' notice", "a07201ed5b", fields=[
    F("Notice", "30 days, written", "a07201ed5b 8bd3d6a9d2"),
    F("Our position", "Ask for 90 days as an exception in negotiation", "fc778eb939 b5348a5ed5 51687fd32d b044194a3e",
      status="needs_review",
      reason="Renee says it won't move; Marco says raise it in negotiation; Legal wants it listed as an exception. The bid team decides.")])
N("ct_pricing", "contract_term", "Pricing model", "Fixed price, USD", "35797a92cd", fields=[
    F("Model", "Fixed price unless stated otherwise; prices in USD", "35797a92cd 96252ef2fe"),
    F("Now", "Indicative; may change in discovery or negotiation", "d9d12183a7 c039ed57e0")])
N("ct_validity", "contract_term", "Price validity", "180 days", "fb8ab68edf", fields=[
    F("Period", "180 days from the due date", "fb8ab68edf aa3e522dd4 bd63d6113a", status="auto_resolved",
      reason="The RFP sets 180 days. Our standard 90 days lost: Marco said keep 180, and the team adopted it.",
      competing=[("90 days (our standard)", "eaba339954 c8f7a0caef")]),
    F("Release", "Info-Tech may release us by letter", "9d48747426")])
N("ct_law", "contract_term", "Governing law", "North Carolina", "07bc4930d7 55743bf92b 061d26859a")
N("ct_public", "contract_term", "Public records", "Proposals are public", "957d1302f4 c7b4725710", fields=[
    F("Rule", "Proposals are generally public and become City property", "957d1302f4 c7b4725710 d22c13f426"),
    F("Trade secrets", "Protected as far as law allows", "5693a772fa 4dfbe2a153 93025cde07 d0881a1e03 4135d400a8")])
N("ct_indemnity", "contract_term", "Trade-secret indemnity", "Defend at our cost", "9dd3cba070", fields=[
    F("Duty", "Defend and indemnify the City for withholding our trade secrets, at our cost",
      "9dd3cba070 c0811e2f46 f5ed608cb9"),
    F("Proof", "City may ask us to prove we can pay; otherwise it may release the records", "1439a3d8da e55bbe158f")])
N("ct_noclaims", "contract_term", "No claims against the City", "Process risk", "f5e4fce07b 05ea7df30f", fields=[
    F("Rule", "No claims for taking part, not winning, or a cancelled award; RFP not warranted error-free",
      "f5e4fce07b 05ea7df30f 0c30327288 c9297af2ce 5fe36fb55c 5deffc85fe"),
    F("Acceptance", "Only a signed contract binds the City", "c28a055717")])
N("ct_wage", "contract_term", "Livable wage", "City value", "29f37b0dfe", fields=[
    F("Rate", "$17.60 per hour", "ebc17508d9 88c874ca27", status="expired",
      reason="Valid only to 2023-06-30. The City reset it; nobody has told us the new rate yet.",
      competing=[("New rate not given", "54c1d4d6b9 7aba9ed549")]),
    F("Ask", "Purchasing can give the current rate; Marco will get it", "458620c830 4cb664691a")])
N("ct_eeo", "contract_term", "Non-discrimination", "EEO policy", "4527f07443 fb4aba1e8e", fields=[
    F("Rule", "No discrimination on listed grounds; state it in job adverts; EEO policy in purchase orders",
      "4527f07443 fb4aba1e8e 05a78834cf 03956368ca 5ed1f7486b")])
N("ct_coverage", "contract_term", "Coverage", "All City departments", "4a96bebf2c")

N("ins_hub", "insurance", "Insurance (3.8)", "Primary, at our cost", "70f601ebcf", fields=[
    F("Basis", "Primary, at our sole expense, for the whole contract", "70f601ebcf 88544a00c6"),
    F("Certificate", "Shows limits and endorsements; 30 days' cancel notice", "1bf671a78b 8d12ca3fe3"),
    F("Notify", "Within 5 business days of any cancellation notice", "ac7d86d858")])
N("ins_cgl", "insurance", "General liability", "$1M / $2M", "223538f04b", fields=[
    F("Limits", "$1,000,000 per occurrence, $2,000,000 aggregate", "223538f04b"),
    F("Terms", "City additional insured; no listed exclusions", "9cb6df17a7 0401545930")])
N("ins_auto", "insurance", "Automobile liability", "$1M CSL", "ad4c2dfb8f", fields=[
    F("Limits", "$1,000,000 combined single limit", "ad4c2dfb8f"),
    F("Only if", "Vehicles are used or brought on site", "0e359f552b 47faf969c0 752e61cf2a")])
N("ins_umbrella", "insurance", "Umbrella / excess", "≥ highest limit", "2e31bd4794 d6686119e6")
N("ins_wc", "insurance", "Workers' comp + employers", "$1M", "ad54a502dd c84c542b2e")
N("ins_cyber", "insurance", "Cyber liability", "$5M · not final", "bf03601009 471e36c36d", status="tentative", fields=[
    F("Limit", "$5,000,000", "bf03601009 471e36c36d cf0af5168f", status="tentative",
      reason="Lauren said Risk Management may require it. It is not in section 3.8; Marco said price to 3.8 until it comes in writing."),
    F("For now", "Price to section 3.8", "d850b792a5 356e7a1635")])

# ---------------------------------------------------------------- risks, actions, competitors, questions
N("risk_ub", "risk", "Utility billing scope and data quality", "Riskiest workstream", "2297f2bec5 65b2392478")
N("risk_council", "risk", "Council timing", "Could squeeze Jan 2026 payroll", "8fe1cc9178", status="tentative")
N("risk_refgap", "risk", "Reference gap", "Mandatory gate at stake", "2bdda47582 3eea54224d")
N("risk_term", "risk", "30-day termination", "On a multi-year job", "fc778eb939 b044194a3e")
N("risk_kevin", "risk", "Kevin's trust", "Burned by Munis", "8cd88ce30a 61df5ea363")
N("risk_record", "risk", "Presentations are recorded", "All on the record", "66f0aaad44 8a75f1da95")
N("risk_users", "risk", "More users than priced", "60 vs 40", "b5d1056dab f89f4caf17")

N("act_lakemont", "action", "Sign Lakemont teaming or use fallback", "Owner Nadia Brooks", "105ff4fa3c 58a1fb6aa2")
N("act_refdecide", "action", "Decide second reference or teaming", "By 2024-08-09", "7a4930ee48")
N("act_fixrefs", "action", "Fix the reference count", "Before references are called", "3eea54224d")
N("act_legal", "action", "Legal review: validity and termination", "Model contract", "5a095df90d eaba339954 b044194a3e")
N("act_dryruns", "action", "Two presentation dry runs", "Before 2024-09-16", "a6947105fe")
N("act_wage", "action", "Get the current livable wage", "Owner Marco Delgado", "4cb664691a")
N("act_intel", "action", "Do not use Brightline price rumour", "Unconfirmed", "4156ea8ad5")
N("act_refnames", "action", "Have reference contacts ready", "August calls", "278d1d9dd2")

N("comp_brightline", "competitor", "Brightline", "Regional Oracle partner", "cc707d93a4", fields=[
    F("Rumoured price", "About $9M", "4156ea8ad5", status="tentative",
      reason="From our Oracle representative, unconfirmed. The notes say not to use it.")])
N("comp_national", "competitor", "Two national integrators", "Large municipal lists", "cc707d93a4 90cf786230", fields=[
    F("Weakness", "Weak utility-billing references", "90cf786230")])

QUESTIONS = [
    ("q_appA", "Where is Appendix A, the model contract?", "b1329eabb7", "open", "ct_model"),
    ("q_appB", "Where is Appendix B, the application list?", "3087129800 4fbc4c06b3", "open", "sys_other"),
    ("q_inventory", "Where is the Proponent Application Inventory?", "21e2a044a1", "open", "req_integration"),
    ("q_bom", "What does 4.1 'Refer to' point at?", "b8893a5f8f", "open", "sol_erp"),
    ("q_mandatory", "Are mandatory requirements negotiable?", "739526e4c0 6989243b7e", "open", "gate_all"),
    ("q_ebop", "Is EBOP Attachment A or B?", "413a720531 182b60b7a9", "answered", "sub_ebop"),
    ("q_diversity", "Is the diversity form Attachment A?", "04512038ab e042936fc3", "answered", "sub_diversity"),
    ("q_wage", "What is the current livable wage?", "d1fcf80437 54c1d4d6b9 458620c830", "open", "ct_wage"),
    ("q_cyber", "Do we need cyber liability cover?", "356e7a1635 d850b792a5", "answered", "ins_cyber"),
    ("q_users", "Price 40 or 60 billing users?", "a9b379a7c0 521519dd7d", "answered", "proc_m2c"),
    ("q_hold", "Can we hold prices for 90 days?", "c8f7a0caef aa3e522dd4", "answered", "ct_validity"),
    ("q_demo", "Do 3 hours include the demo?", "d7e0dedfb6", "answered", "ev_present"),
]
ANSWERS = {
    "q_ebop": "Marco: 3.15 is right, it is Attachment A. Notes to all firms will say so.",
    "q_diversity": "It follows from the EBOP answer: the questionnaire is the online form; the team followed 3.15.",
    "q_cyber": "Marco: price to section 3.8; a new requirement would come in writing.",
    "q_users": "Price the RFP's 40 and state 60 as an assumption.",
    "q_hold": "Marco: keep the RFP's 180 days.",
    "q_demo": "Renee: three hours including everything.",
}
for qid, label, facts, state, about in QUESTIONS:
    fields = [F("Answer", ANSWERS[qid], facts)] if qid in ANSWERS else [F("Status", "Not yet asked in writing", facts, status="needs_review",
                                                                           reason="Open clarification for the buyer.")]
    N(qid, "question", label, "Answered" if state == "answered" else "Open", facts, fields=fields)
    E(qid, "about", about, facts)

# ---------------------------------------------------------------- links
for src, edge, dst, facts in [
    ("deal", "buyer", "org_durham", "b4273062cb"), ("deal", "advisor", "org_infotech", "4aaad774e8"),
    ("deal", "software", "org_oracle", "62cb397108"), ("deal", "bidder", "org_corvane", "b02e30631a"),
    ("org_infotech", "advises", "org_durham", "4aaad774e8"), ("org_council", "part of", "org_durham", "57e35c48b4"),
    ("dept_bms", "part of", "org_durham", "fa2f0b0147"), ("dept_cbs", "part of", "org_durham", "fa2f0b0147"),
    ("dept_ubc", "part of", "org_durham", "83b47824f5"), ("dept_cc", "part of", "org_durham", "311bb4f074"),
    ("dept_risk", "part of", "org_durham", "bf03601009"), ("dept_purch", "part of", "org_durham", "7a291cd3b8"),
    ("dept_tech", "part of", "org_durham", "8d12ca3fe3"),
    ("p_renee", "works at", "org_durham", "e959263476"), ("p_kevin", "works at", "dept_cbs", "66fac5d4d5"),
    ("p_lauren", "works at", "dept_bms", "dbc3cc0c52"), ("p_marco", "works at", "org_infotech", "3804ec7042"),
    ("p_ahmed", "works at", "org_infotech", "ca0e19546b"), ("p_nadia", "works at", "org_corvane", "b02e30631a"),
    ("p_sam", "works at", "org_corvane", "7da68d85a1"),
    ("p_marco", "runs", "method", "f955903203"), ("p_kevin", "owns", "proc_m2c", "8cd88ce30a"),
    ("p_renee", "wants", "hb_phased", "d54fd2fe06"), ("p_kevin", "cares about", "hb_billing", "61df5ea363"),
    ("org_council", "awards", "ev_award", "44cbdd7221"), ("org_lakemont", "offers", "ref_lakemont", "105ff4fa3c"),
    ("org_corvane", "teaming with", "org_lakemont", "8636357da9"),
    ("org_durham", "driven by", "drv_disparate", "47388aae4a"), ("org_durham", "driven by", "drv_truth", "4dc3bca943"),
    ("org_durham", "driven by", "drv_manual", "c3ec948d17"), ("org_durham", "driven by", "drv_reports", "fa2f0b0147"),
    ("org_durham", "driven by", "drv_future", "2222002b20"), ("org_durham", "hot button", "hb_payroll", "47197b92dc"),
    ("org_durham", "hot button", "hb_billing", "61df5ea363"), ("org_durham", "hot button", "hb_phased", "f2908fd868"),
    ("hb_payroll", "targets", "ev_payroll", "94d64e2304"),
    ("org_oracle", "supplies", "sol_erp", "4fe6bb7014"), ("org_oracle", "supplies", "sol_hcm", "4fe6bb7014"),
    ("org_oracle", "supplies", "sol_epm", "4fe6bb7014"), ("org_oracle", "supplies", "sol_util", "4fe6bb7014"),
    ("org_oracle", "supplies", "sol_platform", "4fe6bb7014"),
    ("proc_r2r", "runs on", "sol_erp", "7943e4cd69"), ("proc_p2p", "runs on", "sol_erp", "3fd5dea92c"),
    ("proc_a2d", "runs on", "sol_erp", "4223eb113c"), ("proc_p2perf", "runs on", "sol_epm", "d2d235c1a0"),
    ("proc_hrcore", "runs on", "sol_hcm", "b8cf9fb069"), ("proc_talent", "runs on", "sol_hcm", "72d8dcd9ac"),
    ("proc_wfm", "runs on", "sol_hcm", "f60aed10f6"), ("proc_m2c", "runs on", "sol_util", "00301ff043"),
    ("sol_erp", "replaces", "sys_munis", "9052a2e88e"), ("sol_hcm", "replaces", "sys_kronos", "822a53cc23"),
    ("sol_hcm", "replaces", "sys_talent", "fabb2d3c7e"), ("sol_erp", "replaces", "sys_assets", "8fddc70352"),
    ("sol_epm", "replaces", "sys_budget", "eca792cced"), ("sol_util", "replaces", "sys_munis_util", "a88d23a13d"),
    ("req_integration", "connects to", "sys_other", "6cc17c0ff8"),
    ("ph1", "covers", "proc_r2r", "11c4764f44"), ("ph1", "covers", "proc_p2p", "11c4764f44"),
    ("ph1", "covers", "proc_a2d", "11c4764f44"), ("ph1", "covers", "proc_p2perf", "11c4764f44"),
    ("ph2", "covers", "proc_hrcore", "11c4764f44"), ("ph2", "covers", "proc_talent", "11c4764f44"),
    ("ph2", "covers", "proc_wfm", "11c4764f44"), ("ph3", "covers", "proc_m2c", "11c4764f44"),
    ("ph1", "then", "ph2", "56178940ad"), ("ph2", "then", "ph3", "56178940ad"), ("ph2", "targets", "ev_payroll", "56178940ad"),
    ("deal", "phased as", "ph1", "56178940ad"),
    ("ev_issued", "then", "ev_biddecision", "fa9327572d"), ("ev_biddecision", "then", "ev_questions", "4bffa5f44f"),
    ("ev_questions", "then", "ev_submitted", "a97ec2be6c"), ("ev_submitted", "then", "ev_due", "816716ee8a"),
    ("ev_due", "then", "ev_shortlist", "214e617f88"), ("ev_shortlist", "then", "ev_briefing", "cf76672882"),
    ("ev_briefing", "then", "ev_teaming", "7a4930ee48"), ("ev_teaming", "then", "ev_refs", "4dd8e9f177"),
    ("ev_refs", "then", "ev_agenda", "d9b7a6455c"), ("ev_agenda", "then", "ev_pricing", "54a643bf67"),
    ("ev_pricing", "then", "ev_dryruns", "a6947105fe"), ("ev_dryruns", "then", "ev_present", "3443eaedb4"),
    ("ev_present", "then", "ev_recommend", "24ee732d76"), ("ev_recommend", "then", "ev_pricevalid", "fb8ab68edf"),
    ("ev_pricevalid", "then", "ev_award", "96e28c6819"), ("ev_award", "then", "ev_payroll", "8fe1cc9178"),
    ("ev_pricevalid", "180 days after", "ev_due", "fb8ab68edf"), ("ev_pricing", "anchored to", "ev_present", "54a643bf67"),
    ("deal", "key date", "ev_due", "816716ee8a"),
    ("deal", "submit", "sub_email", "ca0e19546b"), ("ev_due", "deadline for", "sub_email", "ca0e19546b"),
    ("sub_email", "goes to", "dept_ubc", "ca0e19546b"), ("sub_email", "copies", "p_ahmed", "ca0e19546b"),
    ("sub_email", "carries", "sub_proposal", "1c6d01d9b3"), ("sub_email", "carries", "sub_response", "7109273f6e"),
    ("sub_email", "carries", "sub_pricing", "e5ef2ca1af"), ("sub_email", "carries", "sub_ebop", "7a1d0204b4"),
    ("sub_email", "carries", "sub_ube", "5727042881"), ("deal", "submit", "sub_diversity", "de407a3b26"),
    ("sub_proposal", "may include", "sub_tradesecret", "2fb19c6050"), ("sub_proposal", "includes", "sub_partners", "c0142ad3f6"),
    ("dept_cc", "helps with", "sub_ebop", "311bb4f074"), ("ev_pricing", "updates", "sub_pricing", "67a6c2e376"),
    ("deal", "must pass", "gate_oracle", "ef7005ef02"), ("deal", "must pass", "gate_experience", "d6a3608bc1"),
    ("deal", "must pass", "gate_all", "e4e2b0057f"), ("deal", "must pass", "gate_nclaw", "48cf16991b"),
    ("deal", "must avoid", "disq_contact", "3a0ac06205"), ("deal", "must avoid", "disq_understanding", "d72c744a26"),
    ("deal", "must avoid", "disq_instructions", "11cf07195c"), ("deal", "must avoid", "disq_qualified", "b2c74b4d7b"),
    ("deal", "must avoid", "disq_lists", "581c4c575b"),
    ("ref_riverbend", "satisfies", "gate_experience", "2bdda47582"), ("ref_pinehollow", "fails", "gate_experience", "2bdda47582"),
    ("ref_lakemont", "would satisfy", "gate_experience", "105ff4fa3c"), ("org_corvane", "reference", "ref_riverbend", "2bdda47582"),
    ("org_corvane", "reference", "ref_pinehollow", "2bdda47582"), ("req_refs", "evidence for", "gate_experience", "4a60552cf6"),
    ("req_expertise", "evidence for", "gate_experience", "298e956131"),
    ("deal", "scored by", "method", "01677e8786"), ("method", "criterion", "crit_understanding", "e7bd611a9e"),
    ("method", "criterion", "crit_pm", "af28387c9a"), ("method", "criterion", "crit_impl", "fa32fca003"),
    ("method", "criterion", "crit_exp", "30434119e7"), ("method", "criterion", "crit_cost", "05b912c9b4"),
    ("method", "stage", "ev_present", "ad6c714b69"), ("method", "stage", "ev_refs", "60374f0ba2"),
    ("method", "ends in", "ev_award", "57e35c48b4"), ("crit_cost", "priced by", "sub_pricing", "05b912c9b4"),
    ("crit_exp", "checks", "gate_experience", "30434119e7"), ("crit_impl", "covers", "req_migration", "fa32fca003"),
    ("crit_pm", "covers", "req_method", "af28387c9a"),
    ("deal", "requires", "req_scope", "bdfe312d94"), ("deal", "requires", "req_expertise", "298e956131"),
    ("req_scope", "includes", "req_method", "218fcd97bc"), ("req_scope", "includes", "req_migration", "b10fe91d3f"),
    ("req_scope", "includes", "req_integration", "6cc17c0ff8"), ("req_scope", "includes", "req_testing", "0ce5cf99da"),
    ("req_scope", "includes", "req_support", "8ad5955677"), ("req_scope", "includes", "req_training", "382beda405"),
    ("req_scope", "implements", "sol_erp", "bdfe312d94"), ("req_scope", "implements", "sol_hcm", "bdfe312d94"),
    ("req_scope", "implements", "sol_epm", "bdfe312d94"), ("req_scope", "implements", "sol_util", "bdfe312d94"),
    ("sub_response", "answers", "req_profile", "5451f5214b"), ("sub_response", "answers", "req_viability", "5451f5214b"),
    ("sub_response", "answers", "req_refs", "5451f5214b"), ("sub_response", "answers", "req_scope", "e04ed8513a"),
    ("sub_pricing", "answers", "req_pricing", "8fb2d53eac"), ("deal", "requires", "req_comms", "a9490bdd06"),
    ("deal", "requires", "req_culture", "6a48a22877"), ("deal", "requires", "req_ip", "cb2f03f43f"),
    ("req_migration", "from", "sys_munis", "4d9485c4e5"), ("req_migration", "cutover", "sys_kronos", "822a53cc23"),
    ("req_comms", "guards", "disq_contact", "5c770e5f98"),
    ("deal", "contract", "ct_model", "75ac0f9cad"),
    *[("ct_model", "includes", t, "75ac0f9cad") for t in
      ["ct_term", "ct_termination", "ct_pricing", "ct_validity", "ct_law", "ct_public", "ct_indemnity", "ct_noclaims",
       "ct_wage", "ct_eeo", "ct_coverage", "ins_hub"]],
    *[("ins_hub", "requires", t, "70f601ebcf") for t in ["ins_cgl", "ins_auto", "ins_umbrella", "ins_wc"]],
    ("dept_risk", "may require", "ins_cyber", "bf03601009"), ("p_lauren", "close to", "dept_risk", "572ce87f30"),
    ("dept_tech", "holds certificate", "ins_hub", "8d12ca3fe3"), ("ct_validity", "sets", "ev_pricevalid", "fb8ab68edf"),
    ("ct_pricing", "shapes", "sub_pricing", "35797a92cd"), ("ct_indemnity", "covers", "sub_tradesecret", "9dd3cba070"),
    ("dept_purch", "knows", "ct_wage", "458620c830"),
    ("risk_ub", "threatens", "ph3", "2297f2bec5"), ("risk_council", "threatens", "ev_payroll", "8fe1cc9178"),
    ("org_council", "causes", "risk_council", "44cbdd7221"), ("risk_refgap", "threatens", "gate_experience", "2bdda47582"),
    ("risk_term", "about", "ct_termination", "fc778eb939"), ("risk_kevin", "about", "p_kevin", "8cd88ce30a"),
    ("risk_record", "about", "ev_present", "66f0aaad44"), ("risk_users", "about", "proc_m2c", "b5d1056dab"),
    ("comp_national", "weak where", "risk_kevin", "90cf786230"),
    ("act_lakemont", "owner", "p_nadia", "105ff4fa3c"), ("act_lakemont", "closes", "risk_refgap", "105ff4fa3c"),
    ("act_lakemont", "signs", "org_lakemont", "58a1fb6aa2"), ("act_refdecide", "due", "ev_teaming", "7a4930ee48"),
    ("act_refdecide", "closes", "risk_refgap", "7a4930ee48"), ("act_fixrefs", "before", "ev_refs", "3eea54224d"),
    ("act_fixrefs", "closes", "risk_refgap", "3eea54224d"), ("act_legal", "reviews", "ct_validity", "5a095df90d"),
    ("act_legal", "reviews", "ct_termination", "5a095df90d"), ("act_legal", "closes", "risk_term", "b044194a3e"),
    ("act_dryruns", "before", "ev_present", "a6947105fe"), ("act_dryruns", "closes", "risk_record", "a6947105fe"),
    ("act_wage", "owner", "p_marco", "4cb664691a"), ("act_wage", "answers", "q_wage", "4cb664691a"),
    ("act_intel", "about", "comp_brightline", "4156ea8ad5"), ("act_refnames", "before", "ev_refs", "278d1d9dd2"),
    ("comp_brightline", "competes for", "deal", "cc707d93a4"), ("comp_national", "competes for", "deal", "cc707d93a4"),
    ("p_marco", "answered", "q_ebop", "182b60b7a9"), ("p_marco", "answered", "q_cyber", "d850b792a5"),
    ("p_marco", "answered", "q_hold", "aa3e522dd4"), ("p_renee", "answered", "q_demo", "d7e0dedfb6"),
    ("p_kevin", "raised", "risk_users", "b5d1056dab"),
]:
    E(src, edge, dst, facts)

# ---------------------------------------------------------------- lenses: the summary sections, as graph views
LENSES = [
    {"key": "buyer", "title": "Buyer information", "icon": "building", "rows": [
        ("Buyer", "City of Durham, NC (pop. 283,506); Info-Tech Research Group runs the selection.", ["org_durham", "org_infotech", "org_council"]),
        ("Solicitation", "RFP #24-0031, Oracle ERP Implementation Partner: phase two of two, partner only.", ["deal"]),
        ("What they are buying", "Implementation of Oracle Fusion ERP, HCM with payroll, EPM and Utilities Customer Cloud.",
         ["sol_erp", "sol_hcm", "sol_epm", "sol_util", "sol_platform", "org_oracle"]),
        ("Why", "Disparate systems, no single source of truth, manual re-keying, weak reporting.",
         ["drv_disparate", "drv_truth", "drv_manual", "drv_reports", "drv_future"]),
        ("Hot buttons", "Utility billing done right; payroll live 1 January; a phased plan that names City staff time.",
         ["hb_billing", "hb_payroll", "hb_phased"]),
        ("Scale", "2,903 employees; ~95,000 utility accounts; 3,000 HR users; 40 Meter to Cash users (60 in reality).",
         ["org_durham", "proc_r2r", "proc_p2p", "proc_a2d", "proc_p2perf", "proc_hrcore", "proc_talent", "proc_wfm", "proc_m2c"]),
        ("Current situation", "Tyler Munis across finance, HR and billing; Kronos being retired; NeoGov, Cornerstone, Saba.",
         ["sys_munis", "sys_munis_util", "sys_kronos", "sys_talent", "sys_assets", "sys_budget", "sys_other"]),
        ("Budget", "Estimated $7.9M over ~30 months; our target $7.5–8.2M fixed price by phase.", ["deal"]),
        ("Contacts", "All contact through Info-Tech: Marco Delgado; submissions copy Ahmed Ebrahim.",
         ["p_marco", "p_ahmed", "dept_ubc", "p_renee", "p_kevin", "p_lauren"]),
    ]},
    {"key": "submission", "title": "Submission instructions", "icon": "send", "rows": [
        ("Deadline", "2024-06-10 at 14:00 ET (one note said 5 pm; the RFP wins).", ["ev_due"]),
        ("How to submit", "Email ubcfinance@durhamnc.gov, copy aebrahim@infotech.com, set subject line.", ["sub_email", "dept_ubc", "p_ahmed"]),
        ("Format", "PDF or Word proposal; Excel response and pricing templates; follow the RFP order.",
         ["sub_proposal", "sub_response", "sub_pricing"]),
        ("What to include", "Executive summary, contact and legal details, solution overview, assumptions, partnerships.",
         ["sub_proposal", "sub_partners", "sub_tradesecret"]),
        ("Required forms", "EBOP (Attachment A), UBE Statement of Intent, online Workforce Diversity Questionnaire.",
         ["sub_ebop", "sub_ube", "sub_diversity"]),
        ("Questions", "By email to the named contact until 2024-05-24 14:00 ET; only written answers count.",
         ["ev_questions", "req_comms"]),
    ]},
    {"key": "gates", "title": "Go/no-go gates", "icon": "shield", "rows": [
        ("Who may bid", "Oracle-approved partner authorised in the US; comply with NC business law.", ["gate_oracle", "gate_nclaw"]),
        ("Experience required", "Two municipalities of 100k–500k in 5 years. We have Riverbend; the second rests on Lakemont.",
         ["gate_experience", "ref_riverbend", "ref_pinehollow", "ref_lakemont", "org_lakemont", "risk_refgap", "act_lakemont"]),
        ("Rejected if", "Contacting City staff, missing a mandatory item, ignoring instructions, not shown qualified.",
         ["gate_all", "disq_contact", "disq_understanding", "disq_instructions", "disq_qualified", "disq_lists"]),
    ]},
    {"key": "scoring", "title": "Scoring criteria", "icon": "chart", "rows": [
        ("Method", "Most advantageous proposal, not the lowest price; the City may change criteria.", ["method"]),
        ("Criteria", "Understanding, project management, implementation, experience, cost. No points stated.",
         ["crit_understanding", "crit_pm", "crit_impl", "crit_exp", "crit_cost"]),
        ("Price", "Indicative now; refined pricing one week before our presentation slot.", ["crit_cost", "ev_pricing", "sub_pricing"]),
        ("Stages", "3-hour recorded presentation (week of 16 Sept), reference calls in August, negotiation, award.",
         ["ev_present", "ev_refs", "ev_recommend", "ev_award"]),
        ("Who decides", "Marco runs scoring; Renee leads; Kevin decides on billing trust; Council awards.",
         ["p_marco", "p_renee", "p_kevin", "p_lauren", "org_council"]),
    ]},
    {"key": "questions", "title": "Clarifications", "icon": "help", "rows": [
        ("Contradictions", "EBOP A vs B (answered: A); diversity form label; mandatory yet negotiable.",
         ["q_ebop", "q_diversity", "q_mandatory"]),
        ("Unclear points", "Appendix A and B missing; application inventory missing; 4.1 reference; livable wage rate.",
         ["q_appA", "q_appB", "q_inventory", "q_bom", "q_wage"]),
        ("Answered on the call", "Cyber cover, user counts, price validity, presentation length.",
         ["q_cyber", "q_users", "q_hold", "q_demo"]),
    ]},
    {"key": "contract", "title": "Contract terms and risks", "icon": "file", "rows": [
        ("Term and renewal", "3 years plus two one-year options; the City expects to use both.", ["ct_term"]),
        ("Pricing and payment", "Fixed price in USD; prices valid 180 days (to 2024-12-07).", ["ct_pricing", "ct_validity", "ev_pricevalid"]),
        ("Insurance and bonds", "GL $1M/$2M, auto $1M, umbrella, workers' comp $1M; $5M cyber possible.",
         ["ins_hub", "ins_cgl", "ins_auto", "ins_umbrella", "ins_wc", "ins_cyber"]),
        ("Liability and indemnity", "Defend the City over trade secrets at our cost; no claims against the City.",
         ["ct_indemnity", "ct_noclaims", "ct_public"]),
        ("Termination", "City may end on 30 days' notice; we want 90 days as an exception.", ["ct_termination", "risk_term", "act_legal"]),
        ("Other risks", "Model contract missing; livable wage rate expired; NC law.", ["ct_model", "ct_wage", "ct_law", "ct_eeo"]),
    ]},
    {"key": "requirements", "title": "Requirements", "icon": "list", "rows": [
        ("Scope of work", "Design, configure, test, train, integrate and migrate the approved Oracle ERP.", ["req_scope"]),
        ("Mandatory requirements", "Oracle partner, municipal experience, 100% of mandatory items.",
         ["gate_oracle", "gate_experience", "gate_all", "req_expertise"]),
        ("Technical requirements", "Interfaces to City systems; 7 years of Munis history; Kronos cutover; testing.",
         ["req_integration", "req_migration", "req_testing"]),
        ("Deliverables", "Methodology, plans, support tiers and SLA, training offerings.",
         ["req_method", "req_support", "req_training"]),
        ("Staffing and key personnel", "Team structure and lead-resource bios; headcounts.", ["req_method", "req_profile"]),
        ("Other requirements", "Viability, references, pricing detail, communication rules, culture.",
         ["req_viability", "req_refs", "req_pricing", "req_comms", "req_culture", "req_ip"]),
    ]},
    {"key": "dates", "title": "Key dates", "icon": "calendar", "rows": [
        (n["label"], n["sub"], [n["id"]]) for n in nodes if n["type"] == "event"
    ]},
    {"key": "people", "title": "People and influence", "icon": "users", "rows": [
        ("Buyer side", "Renee leads; Kevin owns billing; Lauren is close to Risk.", ["p_renee", "p_kevin", "p_lauren", "org_durham"]),
        ("Process", "Marco runs everything; Ahmed receives submissions.", ["p_marco", "p_ahmed", "org_infotech"]),
        ("Our team", "Nadia owns teaming; Sam runs the bid.", ["p_nadia", "p_sam", "org_corvane", "org_lakemont"]),
        ("Competition", "Brightline (rumoured ~$9M) and two nationals with weak billing references.",
         ["comp_brightline", "comp_national"]),
    ]},
    {"key": "risks", "title": "Risks and actions", "icon": "alert", "rows": [
        ("Risks", "Reference gap, utility billing, Council timing, termination, Kevin's trust, recording, user count.",
         [n["id"] for n in nodes if n["type"] == "risk"]),
        ("Actions", "Lakemont teaming, reference decision by 8/9, legal review, dry runs, livable wage.",
         [n["id"] for n in nodes if n["type"] == "action"]),
    ]},
]


def main() -> None:
    facts = json.loads((BID / "facts.json").read_text())
    bid = json.loads((BID / "bid.json").read_text())
    by_short = {f["fact_id"][2:]: f for f in facts}
    # Timeline order: documents by issue date.
    docs = sorted(bid["documents"], key=lambda d: d.get("issue_date") or "")
    step = {d["no"]: i for i, d in enumerate(docs)}
    names = {"rfp": "RFP", "call-transcript": "Briefing call", "deal-notes": "Deal notes"}

    used: set[str] = set()
    missing: list[str] = []

    def check(ids: list[str], where: str) -> list[str]:
        for i in ids:
            (used.add(i) if i in by_short else missing.append(f"{where}: {i}"))
        return ids

    ids = {n["id"] for n in nodes}
    for n in nodes:
        check(n["facts"], n["id"])
        for f in n["fields"]:
            check(f["facts"], f"{n['id']}.{f['name']}")
            for c in f["competing"]:
                check(c["facts"], f"{n['id']}.{f['name']}~")
        for lst in n["lists"]:
            for it in lst["items"]:
                check(it["facts"], f"{n['id']}.{lst['name']}")
    for l in links:
        check(l["facts"], f"{l['from']}->{l['to']}")
        for end in (l["from"], l["to"]):
            if end not in ids:
                missing.append(f"link end {end}")
    if missing:
        sys.exit("unknown ids:\n  " + "\n  ".join(missing))

    out_facts = {}
    for short, f in by_short.items():
        c = f["citations"][0] if f["citations"] else {}
        out_facts[short] = {
            "text": f["text"], "category": f["category"], "flags": f["flags"], "doc": f["doc_no"],
            "step": step[f["doc_no"]], "page": c.get("page_label", ""), "section": c.get("section", ""),
            "quote": (c.get("text") or "")[:400], "speaker": c.get("speaker", ""), "used": short in used,
        }
    graph = {
        "bid": {"id": bid["bid_id"], "name": bid["name"]},
        "documents": [{"no": d["no"], "step": step[d["no"]], "name": names.get(d["playbook"], d["file_name"]),
                       "file": d["file_name"], "playbook": d["playbook"], "issued": d.get("issue_date")} for d in docs],
        "types": TYPES, "nodes": nodes, "links": links, "facts": out_facts,
        "lenses": [{**l, "rows": [{"row": r, "text": t, "nodes": ns} for r, t, ns in l["rows"]]} for l in LENSES],
    }
    OUT.write_text(json.dumps(graph, indent=1, ensure_ascii=False))
    print(f"{len(nodes)} nodes, {len(links)} links, {len(used)}/{len(facts)} facts placed -> {OUT}")


if __name__ == "__main__":
    main()
