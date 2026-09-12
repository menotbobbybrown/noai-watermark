"""Heuristic C2PA payload summaries; no signature or trust validation."""

import re
from typing import Any
from constants import C2PA_ACTIONS, C2PA_AI_TOOLS, C2PA_ISSUERS

def parse_c2pa_payload(chunk_data: bytes, c2pa_info: dict[str, Any]) -> None:
    """Parse C2PA chunk data and populate info dictionary."""
    # Debug: log raw chunk info
    c2pa_info["_raw_chunk_size"] = len(chunk_data)

    # Find issuers
    issuers = []
    for sig, name in C2PA_ISSUERS.items():
        if sig in chunk_data:
            issuers.append(name)
    if issuers:
        c2pa_info["issuer"] = ", ".join(sorted(set(issuers)))

    # Find AI tools
    ai_tools = []
    for sig, name in C2PA_AI_TOOLS.items():
        if sig in chunk_data:
            ai_tools.append(name)
    if ai_tools:
        c2pa_info["ai_tool"] = ", ".join(sorted(set(ai_tools)))

    # Extract software agent (multiple patterns)
    patterns = [
        rb"softwareAgent.*?dname([^\x00]+?)(?:q|l|m|n)",
        rb"software_agent[^\x00]*?([A-Za-z0-9_\-\.]+)",
        rb"Software[^\x00]*?([A-Za-z0-9_\-\. ]+)",
    ]
    for pattern in patterns:
        match = re.search(pattern, chunk_data, re.DOTALL | re.IGNORECASE)
        if match:
            agent = match.group(1).decode("utf-8", errors="ignore").strip()
            if agent and len(agent) < 100:
                c2pa_info["software_agent"] = agent
                break

    # Extract claim generator (multiple patterns)
    claim_patterns = [
        rb"claim_generator[^\x00]*?([A-Za-z0-9_\-\.\/\:]+)",
        rb"claimGenerator[^\x00]*?([A-Za-z0-9_\-\.\/\:]+)",
        rb"dname([^\x00]{3,50})(?:q|l|m|n|i)",
    ]
    for pattern in claim_patterns:
        match = re.search(pattern, chunk_data, re.DOTALL | re.IGNORECASE)
        if match:
            gen_name = match.group(1).decode("utf-8", errors="ignore").strip()
            # Filter out common false positives
            if gen_name and len(gen_name) < 100 and not gen_name.startswith(("\\x", "\\\\x")):
                c2pa_info["claim_generator"] = gen_name
                break

    # Find actions
    actions = []
    for sig, name in C2PA_ACTIONS.items():
        if sig in chunk_data:
            actions.append(name)
    if actions:
        c2pa_info["actions"] = ", ".join(actions)

    # Find timestamps
    timestamp_matches = re.findall(rb"(\d{14}Z)", chunk_data)
    if timestamp_matches:
        c2pa_info["timestamp"] = timestamp_matches[0].decode("utf-8")
        if len(timestamp_matches) > 1:
            c2pa_info["timestamps"] = [t.decode("utf-8") for t in timestamp_matches[:3]]

    # Find digital source type
    if b"trainedAlgorithmicMedia" in chunk_data:
        c2pa_info["source_type"] = "trainedAlgorithmicMedia (AI-generated)"
    elif b"algorithmicMedia" in chunk_data:
        c2pa_info["source_type"] = "algorithmicMedia"
    elif b"compositeWithTrainedAlgorithmicMedia" in chunk_data:
        c2pa_info["source_type"] = "compositeWithTrainedAlgorithmicMedia (AI-enhanced)"
