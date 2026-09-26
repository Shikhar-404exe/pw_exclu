"""
Synthetic corpus generator for STRAIN.

Generates ~300 rental agreements with a deliberately constructed evolutionary
history. All output labelled as synthetic. Every document records its true
parent, generation, mutation log, and a synthetic date.

Usage:
    python scripts/seed_corpus.py

Output:
    data/documents/*.txt   — raw document text files
    data/ground_truth.json — full lineage metadata
    data/samples/          — 3 human-readable sample documents
    data/strain.db         — seeded and fully indexed database
"""
from __future__ import annotations

import json
import random
import re
import sys
import uuid
from copy import deepcopy
from datetime import date, timedelta
from pathlib import Path

# Add repo root to path
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

DATA_DIR = REPO_ROOT / "data"
DOCS_DIR = DATA_DIR / "documents"
SAMPLES_DIR = DATA_DIR / "samples"
GT_PATH = DATA_DIR / "ground_truth.json"

DATA_DIR.mkdir(exist_ok=True)
DOCS_DIR.mkdir(exist_ok=True)
SAMPLES_DIR.mkdir(exist_ok=True)

# ─── Seed the RNG for reproducibility ────────────────────────────────────────
random.seed(42)

# ─── Party name pools ─────────────────────────────────────────────────────────
LANDLORD_NAMES = [
    "Mr. Ramesh Kumar Sharma", "Ms. Priya Subramaniam", "Mr. Vikram Singh Rathore",
    "Mrs. Lakshmi Narayanan", "Mr. Arun Mehta", "Ms. Sunita Patel",
    "Mr. Deepak Joshi", "Mrs. Anita Gupta", "Mr. Suresh Iyer",
    "Ms. Kavita Reddy", "Mr. Rajesh Chatterjee", "Mrs. Meena Krishnamurthy",
]
TENANT_NAMES = [
    "Mr. Ankit Verma", "Ms. Pooja Desai", "Mr. Rohit Nair",
    "Mrs. Sneha Pillai", "Mr. Amit Tiwari", "Ms. Ritu Saxena",
    "Mr. Vijay Krishnan", "Mrs. Divya Menon", "Mr. Sanjay Rao",
    "Ms. Neha Bhatt", "Mr. Kunal Mishra", "Mrs. Pratha Kumari",
]
CITIES = [
    "Mumbai", "Pune", "Bangalore", "Chennai", "Hyderabad",
    "Delhi", "Kolkata", "Ahmedabad", "Jaipur", "Nagpur",
]
LOCALITIES = {
    "Mumbai": ["Andheri West", "Bandra East", "Powai", "Malad"],
    "Pune": ["Kothrud", "Viman Nagar", "Wakad", "Hinjewadi"],
    "Bangalore": ["Koramangala", "Indiranagar", "Whitefield", "HSR Layout"],
    "Chennai": ["Anna Nagar", "T. Nagar", "Velachery", "Adyar"],
    "Hyderabad": ["Madhapur", "Banjara Hills", "Kondapur", "Gachibowli"],
    "Delhi": ["Lajpat Nagar", "Dwarka", "Rohini", "Vasant Kunj"],
    "Kolkata": ["Salt Lake", "Park Street", "New Town", "Ballygunge"],
    "Ahmedabad": ["Navrangpura", "Satellite", "Prahlad Nagar", "Bodakdev"],
    "Jaipur": ["Vaishali Nagar", "Civil Lines", "Malviya Nagar", "C-Scheme"],
    "Nagpur": ["Dharampeth", "Sitabuldi", "Sadar", "Civil Lines"],
}

# ─── Numbering schemes ─────────────────────────────────────────────────────────
NUMBERING_SCHEMES = [
    "numeric_dot",   # 1. 2. 3.
    "numeric_paren", # 1) 2) 3)
    "clause_header", # CLAUSE 1: CLAUSE 2:
    "roman_upper",   # I. II. III.
    "alpha_paren",   # (a) (b) (c)
]


def _number(scheme: str, n: int) -> str:
    if scheme == "numeric_dot":
        return f"{n}."
    elif scheme == "numeric_paren":
        return f"{n})"
    elif scheme == "clause_header":
        return f"CLAUSE {n}:"
    elif scheme == "roman_upper":
        romans = ["I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX",
                  "X", "XI", "XII", "XIII", "XIV", "XV", "XVI", "XVII", "XVIII"]
        return f"{romans[min(n-1, len(romans)-1)]}."
    elif scheme == "alpha_paren":
        alpha = "abcdefghijklmnopqrstuvwxyz"
        return f"({alpha[min(n-1, 25)]})"
    return f"{n}."


# ─── Ancestor templates — 6 families × 18 clauses ────────────────────────────

ANCESTOR_TEMPLATES = {
    "template_residential_balanced": {
        "template_id": "T1",
        "description": "Balanced residential agreement — standard tenant-friendly baseline",
        "clauses": [
            {"heading": "RENT PAYMENT", "text": "The monthly rent for the premises shall be Rs. 15,000 (Rupees Fifteen Thousand only), payable on or before the 5th day of each calendar month. Payment shall be made by bank transfer to the Landlord's designated account. A grace period of 7 (seven) days shall apply before any late payment penalty is triggered."},
            {"heading": "SECURITY DEPOSIT", "text": "The Tenant shall pay a refundable security deposit of Rs. 45,000 (Rupees Forty-Five Thousand only), equivalent to three months' rent. The deposit shall be returned in full within 30 (thirty) days of the Tenant vacating the premises, after deduction of any documented outstanding dues. Interest on the deposit shall be paid at the prevailing bank savings rate."},
            {"heading": "LOCK-IN PERIOD", "text": "This Agreement shall have a lock-in period of 11 (eleven) months from the commencement date. Either party may terminate the agreement before the expiry of the lock-in period by giving 60 (sixty) days' written notice and paying an early termination fee equivalent to 2 (two) months' rent."},
            {"heading": "NOTICE PERIOD", "text": "After the lock-in period, either party may terminate this Agreement by providing 30 (thirty) days' written notice to the other party. Notice shall be deemed valid if delivered by registered post or email with acknowledgement."},
            {"heading": "REPAIRS AND MAINTENANCE", "text": "The Landlord shall be responsible for all major structural repairs including plumbing, electrical wiring, roof, and external walls. The Tenant shall be responsible for day-to-day maintenance of interior fixtures, fittings, and appliances provided by the Landlord. Any repair costing more than Rs. 1,000 that is the Tenant's responsibility shall require the Landlord's written consent before commencement."},
            {"heading": "LANDLORD'S RIGHT OF ENTRY", "text": "The Landlord or authorised agent shall have the right to inspect the premises with a minimum of 48 (forty-eight) hours' prior written notice to the Tenant. Emergency entry may occur without prior notice only in circumstances of imminent risk to life or property, and shall be documented in writing within 24 hours."},
            {"heading": "SUBLETTING", "text": "The Tenant shall not sublet the whole or any part of the premises without the prior written consent of the Landlord. Such consent shall not be unreasonably withheld. Any subletting in breach of this clause shall be grounds for termination with 30 days' notice."},
            {"heading": "PERMITTED USE", "text": "The premises shall be used exclusively for residential purposes by the Tenant and immediate family members. Commercial activities, running a business from the premises, or use for any unlawful purpose is strictly prohibited."},
            {"heading": "UTILITIES", "text": "The Tenant shall be solely responsible for payment of all utility bills including electricity, water, gas, and internet/telephone services. These bills shall be paid directly to the respective service providers and shall not become the Landlord's obligation under any circumstance."},
            {"heading": "RENT ESCALATION", "text": "The rent shall be subject to an annual escalation of 5% (five percent) on the anniversary of the commencement date. Such escalation shall be applied only after the completion of the initial lock-in period and shall be communicated to the Tenant in writing at least 30 (thirty) days in advance."},
            {"heading": "ALTERATIONS", "text": "The Tenant shall not make any structural alterations or permanent modifications to the premises without the Landlord's prior written consent. Minor cosmetic changes such as painting or hanging artwork shall be permitted. At the end of the tenancy, the Tenant shall restore the premises to its original condition, reasonable wear and tear excepted."},
            {"heading": "PETS", "text": "Pets may be kept in the premises with the prior written consent of the Landlord. The Landlord's consent shall not be unreasonably withheld for small domesticated animals. The Tenant shall be responsible for any damage caused by pets."},
            {"heading": "TERMINATION FOR CAUSE", "text": "Either party may terminate this Agreement with 30 (thirty) days' notice upon material breach by the other party. The breaching party shall have 15 (fifteen) days after receipt of written notice to cure the breach before termination takes effect."},
            {"heading": "DISPUTE RESOLUTION", "text": "Any dispute arising out of or in connection with this Agreement shall first be referred to mediation. If mediation fails, the dispute shall be referred to arbitration under the Arbitration and Conciliation Act, 1996. The arbitrator shall be mutually appointed by both parties. The seat of arbitration shall be the city where the premises are located."},
            {"heading": "HANDOVER CONDITION", "text": "The Tenant shall return the premises in the same condition as at the commencement of tenancy, reasonable wear and tear excepted. A joint inspection shall be conducted at the time of handover. Any disputed deductions shall be resolved through the dispute resolution mechanism specified above."},
            {"heading": "GOVERNING LAW", "text": "This Agreement shall be governed by and construed in accordance with the laws of India, including applicable State Rent Control legislation. Any provision found to be contrary to applicable law shall be severed and the remaining provisions shall continue in full force."},
            {"heading": "STAMP DUTY", "text": "This Agreement shall be duly stamped and registered in accordance with the provisions of the Indian Stamp Act, 1899 and the Registration Act, 1908. The cost of stamp duty and registration shall be borne equally by the Landlord and the Tenant unless otherwise agreed."},
            {"heading": "ENTIRE AGREEMENT", "text": "This Agreement constitutes the entire understanding between the parties with respect to the subject matter hereof and supersedes all prior negotiations, representations, warranties, and understandings. No amendment shall be valid unless in writing and signed by both parties."},
        ]
    },
    "template_commercial_standard": {
        "template_id": "T2",
        "description": "Slightly landlord-leaning but still lawful — broker template variant",
        "clauses": [
            {"heading": "RENT PAYMENT", "text": "The monthly rent shall be Rs. 18,000 (Rupees Eighteen Thousand only), payable in advance on or before the 1st day of each month. In case of delay beyond the due date, the Tenant shall pay interest at 12% per annum on the outstanding amount. No grace period shall be applicable."},
            {"heading": "SECURITY DEPOSIT", "text": "A security deposit of Rs. 54,000 (Rupees Fifty-Four Thousand only) shall be paid by the Tenant prior to taking possession. The deposit is refundable within 45 (forty-five) days of vacant possession, subject to deductions for any outstanding rent, damages, or unpaid utilities. No interest shall be payable on the deposit."},
            {"heading": "LOCK-IN PERIOD", "text": "This Agreement carries a mandatory lock-in period of 11 (eleven) months. In the event the Tenant vacates before the expiry of the lock-in period, the Tenant shall forfeit 3 (three) months' rent as liquidated damages, in addition to any outstanding rent."},
            {"heading": "NOTICE PERIOD", "text": "After the lock-in period, either party may terminate by giving 30 (thirty) days' advance written notice. The Tenant's notice shall be valid only if given in writing and delivered to the Landlord personally or by registered post."},
            {"heading": "REPAIRS AND MAINTENANCE", "text": "The Tenant shall maintain the premises in good condition throughout the tenancy. The Tenant shall be responsible for all minor and major repairs arising from usage, including plumbing and electrical issues, unless such issues arise due to the inherent structural defects of the building. The Landlord's liability for repairs is limited to structural defects pre-existing at the time of handover."},
            {"heading": "LANDLORD'S RIGHT OF ENTRY", "text": "The Landlord reserves the right to inspect the premises at any reasonable time with 24 (twenty-four) hours' prior notice. During the last 2 (two) months of the tenancy, the Landlord may show the premises to prospective tenants with the Tenant's consent, which shall not be unreasonably withheld."},
            {"heading": "SUBLETTING", "text": "The Tenant shall not sublet, assign, or part with possession of the whole or any portion of the premises under any circumstances. Any violation of this clause shall entitle the Landlord to terminate the Agreement immediately and forfeit the security deposit."},
            {"heading": "PERMITTED USE", "text": "The premises shall be used for residential purposes only. The Tenant shall not carry on any trade, business, or profession from the premises. Violation shall entitle the Landlord to terminate without notice."},
            {"heading": "UTILITIES", "text": "All utility charges including electricity, water, gas, and society maintenance charges shall be borne by the Tenant. Failure to pay utility bills within 10 (ten) days of due date shall be treated as a default."},
            {"heading": "RENT ESCALATION", "text": "Rent shall be subject to enhancement at a flat rate of 10% (ten percent) per annum at the beginning of each renewal period. This escalation is automatic and shall not require further notice."},
            {"heading": "ALTERATIONS", "text": "No alterations, additions, or improvements of any kind whatsoever shall be made by the Tenant without the prior written consent of the Landlord. Any alterations made without consent may be reversed by the Landlord at the Tenant's expense."},
            {"heading": "PETS", "text": "No pets or animals of any kind shall be kept in the premises. Violation of this clause shall be treated as a material breach and entitle the Landlord to terminate immediately."},
            {"heading": "TERMINATION FOR CAUSE", "text": "In the event of any breach by the Tenant, the Landlord shall be entitled to terminate this Agreement by giving 7 (seven) days' notice. The Landlord's determination of breach shall be final for the purposes of triggering this clause."},
            {"heading": "DISPUTE RESOLUTION", "text": "All disputes arising from this Agreement shall be subject to the exclusive jurisdiction of courts in the city where the premises are located. The Tenant waives any right to seek redress in any other forum."},
            {"heading": "HANDOVER CONDITION", "text": "The Tenant shall return the premises in the same condition as received, painted and with all fixtures in working order, failing which the Landlord shall be entitled to make deductions from the deposit to restore the premises, and recover any shortfall from the Tenant."},
            {"heading": "GOVERNING LAW", "text": "This Agreement shall be governed by the laws of India. Any dispute shall be settled by courts of competent jurisdiction in the city where the premises are situated."},
            {"heading": "STAMP DUTY", "text": "All stamp duty and registration costs shall be borne by the Tenant. The Tenant shall complete registration formalities within 30 (thirty) days of execution of this Agreement."},
            {"heading": "ENTIRE AGREEMENT", "text": "This Agreement constitutes the entire agreement between the parties. No oral representations shall be binding. Variations must be in writing and signed by the Landlord."},
        ]
    },
    "template_modern_digital": {
        "template_id": "T3",
        "description": "Modern startup-era template — uses digital notice, online payment",
        "clauses": [
            {"heading": "Monthly Rent", "text": "The monthly licence fee for occupation of the premises is Rs. 22,000, payable by the 3rd of each month via NEFT/RTGS/UPI transfer to the account designated by the Licensor. Payments made after the 3rd but before the 10th carry a late fee of Rs. 500. Payments after the 10th carry a late fee of Rs. 1,500."},
            {"heading": "Security Deposit", "text": "An interest-free refundable security deposit of Rs. 44,000 is payable prior to possession. The deposit shall be refunded within 21 days of the Licensee handing over vacant possession, after adjustment for any outstanding dues and documented damage beyond fair wear and tear."},
            {"heading": "Lock-in Period", "text": "A lock-in period of 11 months applies from the commencement date. Early departure by either party during this period requires 45 days' written notice and payment of 1.5 months' licence fee as an early exit fee."},
            {"heading": "Notice Period", "text": "Post lock-in, either party may terminate this Licence by giving 30 days' notice via registered post or email with delivery confirmation. Email notice is valid at the time of sender's dispatch confirmation."},
            {"heading": "Maintenance", "text": "The Licensor is responsible for structural repairs and major electrical/plumbing work. The Licensee is responsible for upkeep of interiors, appliances, fixtures, and pest control. Any repair above Rs. 2,000 in the Licensee's scope requires prior notification to the Licensor."},
            {"heading": "Right of Entry", "text": "The Licensor or authorised representative shall be entitled to visit the premises with 24 hours' prior notice via phone or email. Visits may be made without notice in genuine emergencies, which must be documented."},
            {"heading": "Sub-licensing", "text": "Sub-licensing or sharing of premises with individuals not named in this Agreement is not permitted without prior written approval. Airbnb or similar short-term rentals are expressly prohibited."},
            {"heading": "Use of Premises", "text": "The premises shall be used strictly for residential purposes. No commercial, professional, storage, or manufacturing activity shall be conducted therein."},
            {"heading": "Utility Bills", "text": "Electricity, water (if metered), gas, broadband and OTT subscriptions (if applicable) are solely the Licensee's responsibility. Society maintenance charges and property tax are the Licensor's responsibility."},
            {"heading": "Rent Enhancement", "text": "Licence fee shall increase by 5% annually on each anniversary of the commencement date. The Licensor shall send a written intimation 15 days before each anniversary."},
            {"heading": "Modifications", "text": "No structural modifications shall be undertaken without written consent. Cosmetic changes (painting, wall hangings, etc.) do not require formal consent but shall be restored to original on exit."},
            {"heading": "Pets Policy", "text": "Small pets (cats, small dogs under 10 kg) are permitted subject to prior written intimation to the Licensor. The Licensee is liable for any damage caused by pets and for professional cleaning on exit."},
            {"heading": "Breach and Cure", "text": "On any breach, the non-breaching party shall issue a written notice specifying the breach. The defaulting party shall have 10 days to cure. If uncured, the non-breaching party may terminate by giving a further 7 days' notice."},
            {"heading": "Dispute Resolution", "text": "Disputes shall be resolved through mutual discussion. If unresolved within 30 days, either party may approach the appropriate Rent Authority or Consumer Forum. Arbitration may be opted by mutual consent."},
            {"heading": "Handover Protocol", "text": "A joint move-out inspection shall be conducted within 3 days of the Licensee's notice to vacate. A written condition report shall be prepared. Deposit deductions shall be itemised and communicated within 10 days of handover."},
            {"heading": "Governing Law", "text": "This Agreement is governed by the laws of India and the applicable State tenancy or leave-and-licence legislation."},
            {"heading": "Stamp Duty and Registration", "text": "Stamp duty and registration charges shall be shared equally. The Licensor shall initiate the registration process within 30 days of execution."},
            {"heading": "Integration Clause", "text": "This document is the complete and sole agreement between the parties. Previous discussions, representations, or agreements are superseded. Amendments require a written addendum signed by both parties."},
        ]
    },
    "template_landlord_aggressive": {
        "template_id": "T4",
        "description": "Aggressive landlord-drafted template — high virulence ancestor",
        "clauses": [
            {"heading": "RENT", "text": "The monthly rent shall be Rs. 20,000, payable strictly on the 1st of each month. Any delay beyond the 1st shall attract compound interest at 24% per annum from the due date. The Landlord shall not be required to demand payment; it is the Tenant's obligation to pay proactively."},
            {"heading": "DEPOSIT", "text": "The Tenant shall deposit Rs. 1,20,000 (six months' rent) as a non-interest-bearing security deposit before taking possession. The deposit may be forfeited in full at the Landlord's sole discretion upon any breach of this Agreement."},
            {"heading": "LOCK-IN", "text": "The lock-in period shall be 11 months from commencement. If the Tenant vacates before the lock-in expiry for any reason whatsoever, the Tenant shall forfeit the entire security deposit in addition to paying rent for the remaining lock-in period."},
            {"heading": "NOTICE", "text": "The Tenant shall give not less than 60 (sixty) days' written notice before vacating. The Landlord may give 7 (seven) days' notice for termination on any grounds the Landlord deems sufficient. This asymmetric notice period is acknowledged and accepted by the Tenant."},
            {"heading": "REPAIRS", "text": "All repairs, whether structural or cosmetic, major or minor, shall be the sole responsibility of the Tenant during the tenancy. The Landlord shall have no liability for any defect, failure, or disrepair in the premises unless caused by the Landlord's own wilful act."},
            {"heading": "ENTRY", "text": "The Landlord shall have the right to enter the premises at any time without prior notice to inspect, carry out repairs, or show the property to prospective tenants. The Tenant shall ensure access is available at all times. Refusal of entry shall be a material breach."},
            {"heading": "SUBLETTING", "text": "Subletting of any nature is strictly prohibited. Any breach shall result in immediate termination and forfeiture of the entire security deposit. The Tenant shall be liable for any additional rent received from any sub-tenant."},
            {"heading": "USE", "text": "The premises shall be used only as a residence for the Tenant and spouse. No children, relatives, or other persons shall reside in the premises without the Landlord's written consent, which may be withheld at the Landlord's absolute discretion."},
            {"heading": "UTILITIES", "text": "All utilities and outgoings without exception, including society maintenance, property tax, and any municipal levies, shall be borne entirely by the Tenant throughout the tenancy. The Tenant shall indemnify the Landlord against any default in these payments."},
            {"heading": "ESCALATION", "text": "Rent shall escalate by 15% per annum on each anniversary of this Agreement. This escalation is mandatory and non-negotiable. Failure to agree to the escalated rent shall entitle the Landlord to terminate with 15 days' notice."},
            {"heading": "ALTERATIONS", "text": "No alteration, modification, or change of any nature shall be made by the Tenant. The Tenant shall not even drive nails into walls for hanging pictures without prior written approval. Any breach shall entitle the Landlord to recover restoration costs plus Rs. 10,000 as liquidated damages."},
            {"heading": "PETS", "text": "No pets of any species shall be permitted in the premises. Any discovery of pets shall entitle the Landlord to terminate immediately and forfeit the security deposit."},
            {"heading": "TERMINATION", "text": "The Landlord may terminate this Agreement at any time with 7 (seven) days' notice for any reason whatsoever. The Tenant may terminate only after the lock-in period with 60 days' notice and payment of all sums due under this Agreement."},
            {"heading": "DISPUTES", "text": "All disputes shall be decided solely by an arbitrator nominated by the Landlord. The arbitrator's decision shall be final and binding. The Tenant waives all rights to approach any court, consumer forum, or rent authority in connection with this Agreement."},
            {"heading": "HANDOVER", "text": "The Tenant shall repaint the entire premises at Tenant's cost before handover. All fixtures and appliances shall be replaced if damaged, missing, or showing any wear beyond new condition. The Landlord's assessment of required work shall be final."},
            {"heading": "LAW", "text": "This Agreement is governed by Indian law. Disputes shall be in courts designated by the Landlord."},
            {"heading": "COSTS", "text": "All costs of stamping, registration, legal fees, and incidentals shall be borne solely by the Tenant."},
            {"heading": "ENTIRE AGREEMENT", "text": "This Agreement is the complete agreement. No variation shall be valid unless signed by the Landlord. Any oral assurance given by the Landlord is not binding unless confirmed in writing."},
        ]
    },
    "template_tenant_friendly": {
        "template_id": "T5",
        "description": "Tenant-protective template — produced by tenant advocacy groups",
        "clauses": [
            {"heading": "RENT", "text": "The monthly rent of Rs. 12,000 shall be payable by the 7th of each month. If the 7th falls on a public holiday or weekend, payment by the next working day shall be deemed timely. The Landlord shall provide a signed receipt for each payment within 3 days of receipt."},
            {"heading": "SECURITY DEPOSIT", "text": "A refundable security deposit of Rs. 24,000 (two months' rent) shall be held by the Landlord in a designated account. Interest on the deposit at the prevailing State Bank of India savings rate shall be credited annually to the Tenant. The deposit shall be returned within 15 days of vacating, with written itemisation of any deductions."},
            {"heading": "LOCK-IN", "text": "A mutual lock-in period of 6 (six) months applies. Either party may exit during the lock-in with 30 days' notice and payment of one month's rent as the sole early exit charge."},
            {"heading": "NOTICE", "text": "Either party may terminate this Agreement at any time after the lock-in period by giving 30 (thirty) days' written notice. Notice may be given by registered post, email, or WhatsApp message with read receipt."},
            {"heading": "REPAIRS", "text": "The Landlord shall carry out all structural, plumbing, and electrical repairs within 15 working days of receiving written notice from the Tenant. If the Landlord fails to do so, the Tenant may arrange the repair and deduct the reasonable cost from the next month's rent, after providing 7 days' written warning."},
            {"heading": "RIGHT OF ENTRY", "text": "The Landlord may enter the premises only with a minimum of 72 (seventy-two) hours' prior written notice and at a time mutually agreed upon. The Tenant may refuse entry at their discretion if proper notice has not been given."},
            {"heading": "SUBLETTING", "text": "The Tenant may sublet one room with prior written notice to the Landlord. Full subletting of the premises requires written consent, which shall be given or refused within 7 days of the request."},
            {"heading": "USE", "text": "The premises shall be used as the Tenant's primary residence. The Tenant may work from home and conduct minimal professional activity that does not interfere with neighbours or breach society rules."},
            {"heading": "UTILITIES", "text": "Electricity and cooking gas shall be the Tenant's responsibility. Water charges (if separately metered), society maintenance, and property tax shall be the Landlord's responsibility."},
            {"heading": "ESCALATION", "text": "Rent may be revised after the first 12 months only by mutual written agreement. The revision shall not exceed 5% per annum. No unilateral escalation shall be valid."},
            {"heading": "ALTERATIONS", "text": "The Tenant may make cosmetic changes including painting, fixtures, and shelving. Structural changes require written consent. All Tenant-made improvements shall remain as part of the premises on exit unless the Tenant elects to restore."},
            {"heading": "PETS", "text": "Pets are permitted subject to society rules. The Tenant shall be responsible for any pet-related damage and professional cleaning costs on exit."},
            {"heading": "BREACH", "text": "A breach notice must be given in writing with full particulars. The party in breach shall have 21 (twenty-one) days to cure. If the breach is cured, no further action may be taken on that specific breach."},
            {"heading": "DISPUTE RESOLUTION", "text": "Disputes shall first be attempted to be resolved between the parties directly within 15 days. Thereafter, either party may approach the relevant Rent Authority, Consumer Forum, or any court of competent jurisdiction."},
            {"heading": "HANDOVER", "text": "Handover shall be by joint inspection. The Tenant's liability is limited to documented damage beyond ordinary wear and tear. Normal wear and tear, ageing, and weathering shall not be charged to the Tenant."},
            {"heading": "GOVERNING LAW", "text": "This Agreement is governed by applicable Indian law, including State rent control and tenancy protection legislation, which shall prevail over any clause in this Agreement that is inconsistent therewith."},
            {"heading": "COSTS", "text": "Stamp duty and registration charges shall be shared equally. Each party shall bear their own legal fees for preparation of this Agreement."},
            {"heading": "ENTIRE AGREEMENT", "text": "This Agreement represents the full agreement of the parties. Both parties have had the opportunity to seek legal guidance before signing. Either party may append signed addenda to this Agreement."},
        ]
    },
    "template_ngo_model": {
        "template_id": "T6",
        "description": "NGO / legal aid model agreement — maximally rights-preserving",
        "clauses": [
            {"heading": "Rent and Payment", "text": "The monthly rent shall be Rs. 10,000, payable by the 10th of each month. The Tenant shall not be liable for any charge, fee, or penalty other than rent unless expressly agreed in a written addendum. The Landlord shall acknowledge all payments in writing."},
            {"heading": "Security Deposit", "text": "A refundable security deposit of Rs. 20,000 shall be held by the Landlord. The deposit shall not be used by the Landlord during the tenancy for any purpose. It shall be returned in full within 10 days of vacation unless documented deductions are agreed in writing. Disputed deductions shall be referred to the Rent Authority."},
            {"heading": "Duration and Lock-in", "text": "This Agreement is for a period of 11 months with no mandatory lock-in. Either party may terminate with 30 days' notice at any time, without payment of any penalty."},
            {"heading": "Notice for Termination", "text": "Termination notice shall be given equally by either party: 30 days in writing. Notice shall be valid when delivered personally, by registered post, or by email with confirmed receipt. Disputes about notice validity shall be resolved by the Rent Authority."},
            {"heading": "Maintenance and Repairs", "text": "The Landlord shall maintain the premises in a habitable condition. All structural and essential services (plumbing, electrical) shall be repaired by the Landlord within 7 days of written notice. If unrepaired, the Tenant may repair and offset cost against rent."},
            {"heading": "Entry by Landlord", "text": "The Landlord shall enter only with the Tenant's consent or with 72 hours' written notice. No entry is permitted at night or on public holidays except in declared emergencies. All entries shall be logged."},
            {"heading": "Subletting", "text": "The Tenant may sublet with 14 days' written notice to the Landlord. The Landlord may object in writing within 7 days with specific grounds. If no objection is received, consent is deemed given."},
            {"heading": "Use of Premises", "text": "The Tenant may use the premises for any lawful residential purpose including working from home, tutoring, and similar light non-commercial uses that do not cause nuisance."},
            {"heading": "Utilities and Outgoings", "text": "Electricity and gas shall be the Tenant's responsibility. All other outgoings including society fees, property tax, and water tax shall be the Landlord's responsibility."},
            {"heading": "Rent Increase", "text": "Rent may not be increased during the term of this Agreement. Any increase for the renewal period shall require a minimum of 60 days' written notice and shall not exceed the CPI inflation rate."},
            {"heading": "Modifications", "text": "The Tenant may make any non-structural modifications. On exit, the Tenant may choose to retain improvements or restore to original. The Landlord may not charge for normal wear and tear or for improvements left behind."},
            {"heading": "Animals", "text": "The Tenant may keep domestic animals subject to applicable society rules. The Landlord may not prohibit domesticated pets without written justification relating to the premises or society rules."},
            {"heading": "Default and Remedies", "text": "Default shall be remedied before any termination action. A 30-day cure period applies to all defaults. No remedy by the Landlord, other than termination after proper notice, is available without a court order."},
            {"heading": "Dispute Resolution", "text": "All disputes shall be resolved by the Rent Authority established under applicable State law. Parties waive no statutory rights by entering this Agreement."},
            {"heading": "Handover", "text": "On vacation, a joint inspection shall document the condition. The Tenant's liability is limited to repair of damage beyond ordinary wear and tear as mutually agreed. No unilateral deductions shall be made."},
            {"heading": "Applicable Law", "text": "This Agreement shall be subject to all applicable State and Central legislation protecting tenants' rights. Any clause inconsistent with such legislation shall be void."},
            {"heading": "Registration and Costs", "text": "Registration shall be completed within 30 days at the Landlord's initiative. All costs shall be shared equally. The Tenant shall receive a certified copy."},
            {"heading": "Completeness", "text": "This Agreement is complete. No term shall be implied to the Tenant's detriment. Any doubt shall be resolved in favour of the Tenant as the weaker contracting party."},
        ]
    },
}

# ─── Mutation operators ────────────────────────────────────────────────────────

def _tighten_deadline(text: str, rng: random.Random) -> tuple[str, str]:
    """Shorten time periods in the text."""
    pat = re.compile(r"\b(\d+)\s*(day|days|month|months|week|weeks)\b", re.IGNORECASE)
    matches = list(pat.finditer(text))
    if not matches:
        return text, "reword_cosmetic"
    m = rng.choice(matches)
    old_val = int(m.group(1))
    new_val = max(1, int(old_val * rng.uniform(0.3, 0.6)))
    new_text = text[:m.start(1)] + str(new_val) + text[m.end(1):]
    return new_text, f"tighten_deadline:{old_val}->{new_val} {m.group(2)}"


def _shift_obligation(text: str, rng: random.Random) -> tuple[str, str]:
    """Shift repair/maintenance obligation from landlord to tenant."""
    replacements = [
        (r"\bLandlord shall\b", "Tenant shall"),
        (r"\bLandlord is responsible\b", "Tenant is responsible"),
        (r"\blessor shall\b", "lessee shall"),
        (r"\bLicensor shall\b", "Licensee shall"),
        (r"\bLandlord.*?responsible for all major\b", "Tenant shall be responsible for"),
    ]
    for pattern, replacement in replacements:
        if re.search(pattern, text, re.IGNORECASE):
            new_text = re.sub(pattern, replacement, text, count=1, flags=re.IGNORECASE)
            return new_text, "shift_obligation:landlord->tenant"
    return text, "reword_cosmetic"


def _remove_cure_period(text: str, rng: random.Random) -> tuple[str, str]:
    """Remove cure/remedy period language."""
    patterns = [
        r"\s*(?:The (?:breaching|defaulting) party|Either party) shall have \d+ \(?\w+\)? days? (?:after receipt of written notice )?to cure (?:the breach|default)[^\.]*.\.?",
        r"\s*A cure period of \d+ days? applies?[^\.]*.\.?",
        r"\s*If (?:the breach is|uncured), no further action[^\.]*.\.?",
        r"\s*If uncured(?:, (?:the Landlord|the non-breaching party))[^\.]*.\.?",
    ]
    for pat in patterns:
        m = re.search(pat, text, re.IGNORECASE | re.DOTALL)
        if m:
            new_text = text[:m.start()].rstrip() + " " + text[m.end():].lstrip()
            return new_text.strip(), "remove_cure_period"
    return text, "reword_cosmetic"


def _add_penalty(text: str, rng: random.Random) -> tuple[str, str]:
    """Add or increase a penalty clause."""
    penalty_addition = rng.choice([
        f" Any breach shall attract a penalty of Rs. {rng.choice([5000, 10000, 15000, 25000]):,} as liquidated damages payable immediately.",
        " Violation shall entitle the Landlord to forfeit the security deposit in full without notice.",
        f" A non-refundable penalty of {rng.choice([1, 2, 3]):d} months' rent shall apply for any breach of this clause.",
    ])
    new_text = text.rstrip(".") + penalty_addition
    return new_text, "add_penalty"


def _broaden_landlord_discretion(text: str, rng: random.Random) -> tuple[str, str]:
    """Add landlord discretion language."""
    additions = [
        " at the Landlord's sole and absolute discretion",
        " as determined solely by the Landlord",
        " subject to the Landlord's prior written approval, which may be withheld at the Landlord's absolute discretion",
        " without being required to assign any reasons therefor",
    ]
    # Find a suitable insertion point
    insert_phrases = [
        r"(The Landlord (?:may|shall|reserves the right))",
        r"(consent (?:shall be|shall not be|is|is not))",
        r"(the Landlord's (?:right|determination|decision))",
    ]
    for pat in insert_phrases:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            addition = rng.choice(additions)
            end = m.end()
            new_text = text[:end] + addition + text[end:]
            return new_text, "broaden_landlord_discretion"
    # Fallback: append to text
    addition = rng.choice(additions)
    return text + addition, "broaden_landlord_discretion"


def _reword_cosmetic(text: str, rng: random.Random) -> tuple[str, str]:
    """Harmless paraphrase — changes surface wording but not substance."""
    replacements = [
        ("shall", rng.choice(["will", "must", "is required to", "agrees to"])),
        ("premises", rng.choice(["property", "accommodation", "dwelling unit", "flat"])),
        ("Tenant", rng.choice(["Lessee", "Licensee", "Occupant", "Resident"])),
        ("Landlord", rng.choice(["Lessor", "Licensor", "Owner", "Property Owner"])),
        ("agreement", rng.choice(["contract", "arrangement", "deed", "deed of tenancy"])),
        ("security deposit", rng.choice(["caution deposit", "refundable deposit", "advance deposit"])),
        ("monthly rent", rng.choice(["monthly rental", "licence fee", "rent amount", "rental charge"])),
    ]
    new_text = text
    changed = []
    for old, new in rng.sample(replacements, min(3, len(replacements))):
        if old in new_text:
            new_text = new_text.replace(old, new, 1)
            changed.append(f"{old}->{new}")
    if changed:
        return new_text, f"reword_cosmetic:{'|'.join(changed[:2])}"
    return new_text, "reword_cosmetic"


def _soften(text: str, rng: random.Random) -> tuple[str, str]:
    """Make the clause more tenant-friendly."""
    softenings = [
        (r"(\d+)\s*days?", lambda m: str(int(int(m.group(1)) * 1.5))),
        (r"sole discretion", "reasonable discretion"),
        (r"without notice", "with 24 hours' notice"),
        (r"immediately", "within 7 days"),
        (r"forfeit(?:ed)?", "may deduct from"),
        (r"absolute discretion", "reasonable and documented grounds"),
        (r"shall be final", "shall be subject to review"),
        (r"no grace period", "a grace period of 5 days shall apply"),
        (r"24% per annum", "the applicable bank lending rate"),
    ]
    new_text = text
    for pattern, replacement in softenings:
        m = re.search(pattern, new_text, re.IGNORECASE)
        if m:
            rep = replacement(m) if callable(replacement) else replacement
            new_text = new_text[:m.start()] + rep + new_text[m.end():]
            return new_text, f"soften:{pattern[:30]}"
    return text, "reword_cosmetic"


OPERATORS = {
    "tighten_deadline": _tighten_deadline,
    "shift_obligation": _shift_obligation,
    "remove_cure_period": _remove_cure_period,
    "add_penalty": _add_penalty,
    "broaden_landlord_discretion": _broaden_landlord_discretion,
    "reword_cosmetic": _reword_cosmetic,
    "soften": _soften,
}

# Template determines which operators are likely
TEMPLATE_OPERATOR_WEIGHTS = {
    "T1": {"tighten_deadline": 1, "reword_cosmetic": 4, "add_penalty": 1, "soften": 2},
    "T2": {"tighten_deadline": 2, "shift_obligation": 2, "add_penalty": 2, "reword_cosmetic": 3, "broaden_landlord_discretion": 1},
    "T3": {"reword_cosmetic": 4, "tighten_deadline": 1, "add_penalty": 1, "soften": 2},
    "T4": {"add_penalty": 3, "broaden_landlord_discretion": 3, "tighten_deadline": 2, "remove_cure_period": 2},
    "T5": {"soften": 3, "reword_cosmetic": 3, "tighten_deadline": 1, "shift_obligation": 1},
    "T6": {"soften": 4, "reword_cosmetic": 3, "tighten_deadline": 1},
}


def _choose_operator(template_id: str, rng: random.Random) -> str:
    weights = TEMPLATE_OPERATOR_WEIGHTS.get(template_id, {"reword_cosmetic": 5})
    ops = list(weights.keys())
    wts = [weights[o] for o in ops]
    return rng.choices(ops, weights=wts)[0]


def _add_typos(text: str, rng: random.Random, rate: float = 0.02) -> str:
    """Introduce realistic typos at the given character rate."""
    chars = list(text)
    n_typos = max(0, int(len(chars) * rate))
    for _ in range(n_typos):
        idx = rng.randint(0, len(chars) - 1)
        c = chars[idx]
        # Swap with adjacent character
        if c.isalpha() and idx < len(chars) - 1 and chars[idx + 1].isalpha():
            chars[idx], chars[idx + 1] = chars[idx + 1], chars[idx]
    return "".join(chars)


def _render_document(
    clauses: list[dict],
    numbering_scheme: str,
    landlord_name: str,
    tenant_name: str,
    city: str,
    locality: str,
    rent: int,
    deposit: int,
    commencement: date,
    doc_id: str,
    synthetic: bool = True,
) -> str:
    """Render a full lease document from clause list."""
    header = f"""RENTAL AGREEMENT

[SYNTHETIC DOCUMENT — FOR DEMONSTRATION PURPOSES ONLY]

THIS RENTAL AGREEMENT is entered into on {commencement.strftime('%d %B %Y')} at {city}.

BETWEEN:

{landlord_name}, hereinafter referred to as the "Landlord" / "PARTY A"

AND

{tenant_name}, hereinafter referred to as the "Tenant" / "PARTY B"

PROPERTY: Flat No. ___, {locality}, {city}
COMMENCEMENT DATE: {commencement.strftime('%d/%m/%Y')}
MONTHLY RENT: Rs. {rent:,}/-
SECURITY DEPOSIT: Rs. {deposit:,}/-

TERMS AND CONDITIONS:

"""
    body_lines = []
    for i, clause in enumerate(clauses, 1):
        num = _number(numbering_scheme, i)
        heading = clause.get("heading", "")
        text = clause.get("text", "")
        # Replace generic amounts/parties with document-specific ones
        text = text.replace("Rs. 15,000", f"Rs. {rent:,}").replace("Rs. 18,000", f"Rs. {rent:,}")
        text = text.replace("Rs. 22,000", f"Rs. {rent:,}").replace("Rs. 20,000", f"Rs. {rent:,}")
        text = text.replace("Rs. 12,000", f"Rs. {rent:,}").replace("Rs. 10,000", f"Rs. {rent:,}")
        text = text.replace("Rs. 45,000", f"Rs. {deposit:,}").replace("Rs. 54,000", f"Rs. {deposit:,}")
        text = text.replace("Rs. 44,000", f"Rs. {deposit:,}").replace("Rs. 1,20,000", f"Rs. {deposit:,}")
        text = text.replace("Rs. 24,000", f"Rs. {deposit:,}").replace("Rs. 20,000", f"Rs. {deposit:,}")
        body_lines.append(f"{num} {heading}\n{text}\n")

    footer = f"""
SIGNATURES:

Landlord: {landlord_name}
Date: _______________

Tenant: {tenant_name}
Date: _______________

[SYNTHETIC DOCUMENT — Generated for STRAIN demonstration. All parties, amounts, and addresses are fictional.]
Document ID: {doc_id}
"""
    return header + "\n".join(body_lines) + footer


# ─── Main corpus generation ────────────────────────────────────────────────────

def generate_corpus() -> list[dict]:
    """Generate ~300 synthetic documents with evolutionary lineage."""
    rng = random.Random(42)
    all_docs = []

    # Generation 0: ancestors (6 templates × 1 document each = 6 docs)
    gen0_docs = []
    for tmpl in ANCESTOR_TEMPLATES.values():
        doc_id = f"doc-{tmpl['template_id']}-g0"
        landlord = rng.choice(LANDLORD_NAMES)
        tenant = rng.choice(TENANT_NAMES)
        city = rng.choice(CITIES)
        locality = rng.choice(LOCALITIES[city])
        rent = rng.choice([8000, 10000, 12000, 15000, 18000, 20000, 22000, 25000])
        deposit = rent * rng.randint(2, 4)
        commencement = date(2018, rng.randint(1, 12), rng.randint(1, 28))
        numbering_scheme = rng.choice(NUMBERING_SCHEMES)

        clauses = deepcopy(tmpl["clauses"])
        rendered = _render_document(
            clauses, numbering_scheme, landlord, tenant, city, locality,
            rent, deposit, commencement, doc_id
        )

        doc_record = {
            "doc_id": doc_id,
            "parent_id": None,
            "generation": 0,
            "template_id": tmpl["template_id"],
            "numbering_scheme": numbering_scheme,
            "synthetic_date": commencement.isoformat(),
            "city": city,
            "parties": {"landlord": landlord, "tenant": tenant},
            "rent": rent,
            "deposit": deposit,
            "mutation_log": [],
            "clauses": clauses,
            "rendered_text": rendered,
        }
        all_docs.append(doc_record)
        gen0_docs.append(doc_record)

    # Generations 1-5: evolve corpus
    prev_gen = gen0_docs
    for gen in range(1, 6):
        next_gen = []
        target_count = 60  # fixed 60 docs per generation → 300 + 6 ancestors = 306 total

        for _ in range(target_count):
            # Pick a parent from previous generation
            parent = rng.choice(prev_gen)
            doc_id = f"doc-{uuid.uuid4().hex[:8]}-g{gen}"

            # Pick 1-3 clauses to mutate
            clauses = deepcopy(parent["clauses"])
            n_mutations = rng.randint(1, 3)
            mutation_log = []
            clause_indices = rng.sample(range(len(clauses)), min(n_mutations, len(clauses)))

            for idx in clause_indices:
                op_name = _choose_operator(parent["template_id"], rng)
                op_fn = OPERATORS[op_name]
                old_text = clauses[idx]["text"]
                new_text, description = op_fn(old_text, rng)
                # Apply typos at 2% rate for realism
                if rng.random() < 0.25:
                    new_text = _add_typos(new_text, rng, rate=0.015)
                clauses[idx]["text"] = new_text
                mutation_log.append({
                    "clause_ordinal": idx,
                    "clause_heading": clauses[idx].get("heading", ""),
                    "operator": op_name,
                    "description": description,
                })

            # Occasionally reorder clauses
            if rng.random() < 0.15:
                non_essential = list(range(2, len(clauses) - 3))
                if non_essential:
                    rng.shuffle(non_essential)
                    # Reorder a subset
                    subset = non_essential[:4]
                    shuffled = deepcopy([clauses[i] for i in subset])
                    rng.shuffle(shuffled)
                    for i, si in enumerate(subset):
                        clauses[si] = shuffled[i]
                    mutation_log.append({
                        "clause_ordinal": -1,
                        "clause_heading": "multiple",
                        "operator": "reorder",
                        "description": "clause_reordering",
                    })

            # New party names, city, date
            landlord = rng.choice(LANDLORD_NAMES)
            tenant = rng.choice(TENANT_NAMES)
            city = rng.choice(CITIES)
            locality = rng.choice(LOCALITIES[city])
            rent = rng.choice([8000, 10000, 12000, 15000, 18000, 20000, 22000, 25000, 30000])
            deposit = rent * rng.randint(2, 4)
            # Dates advance with generation
            base_date = date(2018 + gen, 1, 1)
            commencement = base_date + timedelta(days=rng.randint(0, 350))
            numbering_scheme = rng.choice(NUMBERING_SCHEMES)

            rendered = _render_document(
                clauses, numbering_scheme, landlord, tenant, city, locality,
                rent, deposit, commencement, doc_id
            )

            doc_record = {
                "doc_id": doc_id,
                "parent_id": parent["doc_id"],
                "generation": gen,
                "template_id": parent["template_id"],
                "numbering_scheme": numbering_scheme,
                "synthetic_date": commencement.isoformat(),
                "city": city,
                "parties": {"landlord": landlord, "tenant": tenant},
                "rent": rent,
                "deposit": deposit,
                "mutation_log": mutation_log,
                "clauses": clauses,
                "rendered_text": rendered,
            }
            all_docs.append(doc_record)
            next_gen.append(doc_record)

        prev_gen = next_gen

    return all_docs


def save_corpus(docs: list[dict]) -> None:
    """Save documents to disk and write ground truth JSON."""
    # Write individual text files
    for doc in docs:
        path = DOCS_DIR / f"{doc['doc_id']}.txt"
        path.write_text(doc["rendered_text"], encoding="utf-8")

    # Write ground truth (without full rendered text to keep it manageable)
    gt_records = [{
        "doc_id": doc["doc_id"],
        "parent_id": doc["parent_id"],
        "generation": doc["generation"],
        "template_id": doc["template_id"],
        "numbering_scheme": doc["numbering_scheme"],
        "synthetic_date": doc["synthetic_date"],
        "city": doc["city"],
        "parties": doc["parties"],
        "mutation_log": doc["mutation_log"],
    } for doc in docs]

    with open(GT_PATH, "w", encoding="utf-8") as f:
        json.dump(gt_records, f, indent=2, ensure_ascii=False)

    print(f"[OK] Generated {len(docs)} documents in {DOCS_DIR}")
    print(f"[OK] Ground truth written to {GT_PATH}")

    # Write 3 samples — one from T1 (balanced), T4 (aggressive), T5 (tenant-friendly)
    sample_ids = [
        ("sample_balanced_agreement.txt", "T1"),
        ("sample_landlord_aggressive.txt", "T4"),
        ("sample_tenant_friendly.txt", "T5"),
    ]
    for filename, tmpl_id in sample_ids:
        gen5_docs = [d for d in docs if d["template_id"] == tmpl_id and d["generation"] == 5]
        if not gen5_docs:
            gen5_docs = [d for d in docs if d["template_id"] == tmpl_id]
        if gen5_docs:
            sample_doc = gen5_docs[0]
            (SAMPLES_DIR / filename).write_text(sample_doc["rendered_text"], encoding="utf-8")

    print(f"[OK] Sample documents written to {SAMPLES_DIR}")


def ingest_corpus_to_db(docs: list[dict]) -> None:
    """Load corpus into the database and run the full pipeline."""
    print("\nIngesting corpus into database...")

    from sqlmodel import Session, select

    from strain.backend.store.store import (
        Clause,
        Document,
        create_db_and_tables,
        engine,
    )

    create_db_and_tables()

    from strain.backend.pipeline.segment import segment

    with Session(engine) as session:
        # Clear existing synthetic documents
        existing = session.exec(select(Document).where(Document.synthetic)).all()
        if existing:
            existing_ids = {d.doc_id for d in existing}
            existing_clauses = session.exec(
                select(Clause).where(Clause.doc_id.in_(existing_ids))  # type: ignore[arg-type]
            ).all()
            for c in existing_clauses:
                session.delete(c)
            for d in existing:
                session.delete(d)
            session.commit()
            print(f"  Cleared {len(existing)} existing synthetic documents")

        for i, doc_data in enumerate(docs):
            if i % 50 == 0:
                print(f"  Processing document {i+1}/{len(docs)}...")

            doc = Document(
                doc_id=doc_data["doc_id"],
                filename=f"{doc_data['doc_id']}.txt",
                synthetic=True,
                generation=doc_data["generation"],
                template_id=doc_data["template_id"],
                parent_doc_id=doc_data["parent_id"],
                synthetic_date=doc_data["synthetic_date"],
                mutation_log_json=json.dumps(doc_data["mutation_log"]),
                raw_text=doc_data["rendered_text"],
            )
            session.add(doc)

            clauses = segment(doc_data["rendered_text"], doc_data["doc_id"])
            for cr in clauses:
                clause = Clause(
                    clause_id=cr.clause_id,
                    doc_id=cr.doc_id,
                    ordinal=cr.ordinal,
                    heading=cr.heading,
                    text=cr.text,
                    normalised_text=cr.normalised_text,
                )
                session.add(clause)

        session.commit()
        total_clauses = len(session.exec(select(Clause)).all())
        print(f"[OK] Ingested {len(docs)} documents, {total_clauses} clauses")


def run_pipeline(session) -> None:
    """Run embed → cluster → phylogeny → label → virulence pipeline."""
    from strain.backend.pipeline.analyse import (
        build_phylogeny,
        label_all_edges,
        score_all_clauses,
    )
    from strain.backend.pipeline.cluster import cluster_clauses
    from strain.backend.pipeline.embed import embed_clauses

    print("\nRunning embedding pipeline (this may take a while on first run)...")
    embed_clauses(session)
    print("[OK] Embeddings complete")

    print("Clustering into strains...")
    cluster_clauses(session)
    print("[OK] Clustering complete")

    print("Building phylogeny trees...")
    build_phylogeny(session)
    print("[OK] Phylogeny complete")

    print("Labelling mutation edges...")
    label_all_edges(session)
    print("[OK] Mutation labels complete")

    print("Computing virulence scores...")
    score_all_clauses(session)
    print("[OK] Virulence scores complete")


def main() -> None:
    print("STRAIN Corpus Generator")
    print("=" * 50)
    print("NOTE: This corpus is entirely synthetic.")
    print("All parties, amounts, addresses, and dates are fictional.")
    print("=" * 50)

    print("\nGenerating synthetic documents...")
    docs = generate_corpus()
    print(f"Generated {len(docs)} documents across {max(d['generation'] for d in docs) + 1} generations")

    print("\nSaving documents to disk...")
    save_corpus(docs)

    print("\nIngesting into database...")
    ingest_corpus_to_db(docs)

    print("\nRunning pipeline...")
    from sqlmodel import Session

    from strain.backend.store.store import engine
    with Session(engine) as session:
        run_pipeline(session)

    print("\n" + "=" * 50)
    print("[OK] Corpus generation complete!")
    print(f"  Documents: {len(docs)}")
    print(f"  Database: {REPO_ROOT / 'data' / 'strain.db'}")
    print(f"  Ground truth: {GT_PATH}")
    print("\nNext: run 'make backend' and 'make frontend' to start the app")


if __name__ == "__main__":
    main()
