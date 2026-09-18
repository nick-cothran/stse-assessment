"""
INCOSE Requirements Analyzer — A-Criteria Edition
Evaluates each requirement against A2–A10 criteria from incose_rules.json.

Structural design:
- AI only identifies: which criteria are violated + the exact affected_text substring.
- Recommendations are generated PROGRAMMATICALLY per criterion (no AI free-text generation).
- Parallel execution via ThreadPoolExecutor for speed.
"""

import anthropic
import openai as openai_lib
import urllib.request
import json
import uuid
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
import base64

@dataclass
class AnalysisContext:
    system_context: str = ""
    conops: str = ""
    image_bytes: bytes | None = None 
    image_file_type: str | None = None

# ---------------------------------------------------------------------------
# Load A-criteria definitions from incose_rules.json
# ---------------------------------------------------------------------------

_CRITERIA_PATH = Path(__file__).parent / 'incose_rules.json'


def _load_criteria() -> Dict:
    with open(_CRITERIA_PATH, 'r') as f:
        data = json.load(f)
    return { c["criterion_id"]: c for c in data['individual_criteria'] } 

CRITERIA = _load_criteria()
CONTEXTUAL_CRITERIA = [c for _, c in CRITERIA.items() if c.get("type") == "contextual"]
STRUCTURAL_CRITERIA = [c for _, c in CRITERIA.items() if c.get("type") == "structural"]
CRITERIA_ORDER = list(CRITERIA.keys())
CRITERIA_NAMES = {cid: c['name'] for cid, c in CRITERIA.items()}


# ---------------------------------------------------------------------------
# Prompt — AI only classifies violations and identifies affected_text
# ---------------------------------------------------------------------------

def _build_criteria_text(criteria_type: str) -> str:
    lines = []
    criteria = (CONTEXTUAL_CRITERIA if criteria_type == "contextual"
                 else STRUCTURAL_CRITERIA if criteria_type == "structural" 
                 else [])

    for c in criteria:
        subrules = "\n".join(
            f"  {sr}" for sr in c.get("sub_rules", [])
        )

        lines.append(f"{c['criterion_id']} — {c['name']}\nDescription: {c['description']}\n\nSub-rules:\n{subrules}")

    return "\n\n---\n\n".join(lines)

def _build_output_example(first_criterion: dict, requirements: List[Dict]):
    first_id = requirements[0]["id"]
    second_example = ""
    if len(requirements) > 1: # avoid accessing invalid index if only one requirement (happens sometimes in batching)
        second_id = requirements[1]["id"]
        second_example = f',\n    "{second_id}": []'

    return f"""Return ONLY valid JSON.
{{
  "individualEvaluations": {{
    "{first_id}": [
      {{
        "criterion_id": "{first_criterion['criterion_id']}",
        "name": "{first_criterion['name']}",
        "explanation": "Short explanation on why the violation exists.",
        "affected_text": "should be user-friendly and easy to use by all operators",
        "suggested_replacement": "shall provide an interface conforming to [stakeholder need reference]"
      }}
    ]{second_example}
  }}
}}"""

def _build_structural_prompt(requirements: List[Dict]): 
    return f"""You are a requirements quality evaluator. You will receive a list of requirements with their IDs.

Your task is to perform individual requirement evaluation.

Evaluate each requirement individually against ALL of these quality criteria (A6 and A10). Be CRITICAL and THOROUGH when identifying violations for each criterion.

For each requirement, include all the criteria that are violated.

Be thorough and critical during the evaluation. For each criterion, if violation exist, return one object per criterion, including:
• criterion_id: criterion ID
• name: criterion name
• explanation: short explanation on why the violation exists (1–2 sentences)
• affected_text: the EXACT verbatim substring from the requirement that causes the violation
• suggested_replacement: a concise improved replacement for ONLY that substring. Do not rewrite the whole requirement. 

The criteria and their sub-rules are as follows. For each criterion, use both the criterion DESCRIPTION and the SUB-RULES as a checklist to guide your judgment. If the description or any sub-rule is violated, the criterion is violated. Evaluate each criterion independently for each of the requirements.

{_build_criteria_text("structural")}

Do not return sub-rule IDs or sub-rule-level reasoning. Sub-rules are used only as a checklist to guide the criterion-level judgment.
Include every requirement ID in individualEvaluations. If no A6 or A10 violation exists for a requirement, return an empty array for that requirement. So, an empty array for a requirement is how you indicate that the requirement has no violations of A6 or A10.

{_build_output_example(STRUCTURAL_CRITERIA[0], requirements)}"""

def _build_contextual_prompt(requirements: List[Dict]):
     return f"""You are a requirements quality evaluator. You will receive a list of requirements with their IDs, along with Project Context, Concept of Operations (ConOps) information, and a reference image of the ConOps.

When completing the following tasks, carefully consider the provided Project Context, Concept of Operations, and reference image to determine if requirements align with the project goals, needs, and operational constraints.

Your task is to perform individual requirement evaluation.

Evaluate each requirement individually against ALL of these quality criteria (A2, A3, A4, A5, and A9). Be CRITICAL and THOROUGH when identifying violations for each criterion.

For each requirement, include all the criteria that are violated.

Be thorough and critical during the evaluation. For each criterion, if violations exist, return one object per criterion, including:
• criterion_id: criterion ID
• name: criterion name
• explanation: short explanation on why the violation exists (1–2 sentences)
• affected_text: the EXACT verbatim substring from the requirement that causes the violation
• suggested_replacement: a concise improved replacement for ONLY that substring. Do not rewrite the whole requirement. 

The criteria and their sub-rules are as follows. For each criterion, use both the criterion DESCRIPTION and the SUB-RULES as a checklist to guide your judgment. If the description or any sub-rule is violated, the criterion is violated. Evaluate each criterion independently for each of the requirements.

{_build_criteria_text("contextual")}

Do not return sub-rule IDs or sub-rule-level reasoning. Sub-rules are used only as a checklist to guide the criterion-level judgment.
Include every requirement ID in individualEvaluations. If no A2, A3, A4, A5, or A9 violation exists for a requirement, return an empty array for that requirement.So, an empty array for a requirement is how you indicate that the requirement has no violations of A2, A3, A4, A5, or A9.

{_build_output_example(CONTEXTUAL_CRITERIA[0], requirements)}"""

def _build_requirement_prompt(requirements: list[Dict]):
    requirements_text = "\n".join(f"{r['id']}: {r['text']}" for r in requirements)
    return f"Requirements to evaluate:\n{requirements_text}"

def _build_context_prompt(context: str):
    parts = []

    if context.system_context:
        parts.append(
            f"Project Context:\n{context.system_context.strip()}"
        )

    if context.conops:
        parts.append(
            f"Concept of Operations:\n{context.conops.strip()}"
        )

    if context.image_bytes:
        parts.append(
            "The attached image is the Concept of Operations figure for this system. "
            "Treat it as part of the provided project context and use it together "
            "with the text when evaluating the requirements."
        )

    return "\n\n".join(parts)

# ---------------------------------------------------------------------------
# Single-requirement analysis
# ---------------------------------------------------------------------------

def get_provider() -> str:
    """Read AI_PROVIDER from env. Defaults to anthropic."""
    return os.getenv("AI_PROVIDER", "anthropic").strip().lower()


def _call_ai(user_prompt: str, system_prompt: str, num_requirements: int, provider: str = None, api_key: str = None, context: AnalysisContext | None = None) -> str:
    """Route to Anthropic, OpenAI, or Ollama. Uses env vars by default."""

    provider = (provider or get_provider()).lower()

    max_tokens = min(500 + num_requirements * 1500, 120000)

    img_b64 = None
    if context and context.image_bytes:
        img_b64 = base64.b64encode(context.image_bytes).decode("utf-8")

    if provider == "anthropic":
        anthropic_model = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-5")
        key = api_key or os.getenv("ANTHROPIC_API_KEY", "").strip()
        if not key:
            raise ValueError("ANTHROPIC_API_KEY is not set")
        
        user_content = []
        if img_b64:
            user_content.append({
                "type": "image",
                "source" : {
                    "type": "base64",
                    "media_type": context.image_file_type,
                    "data": img_b64
                }
            })
        user_content.append({
                            "type": "text",
                            "text": user_prompt,
                        })
        
        client = anthropic.Anthropic(api_key=key)
        response = client.messages.create(
            model=anthropic_model,
            max_tokens=max_tokens,
            system=[
                {
                    "type": "text",
                    "text": system_prompt,
                    "cache_control": {"type": "ephemeral"}
                }
            ],
            messages=[{"role": "user", "content": user_content}],
        )
        return response.content[0].text.strip()

    elif provider == "openai":
        openai_model = os.getenv("OPENAI_MODEL", "gpt-4o")
        key = api_key or os.getenv("OPENAI_API_KEY", "").strip()
        if not key:
            raise ValueError("OPENAI_API_KEY is not set in .env")

        user_content = [
            {
                "type": "text",
                "text": user_prompt
            }
        ]
        if img_b64:
            user_content.append({
                "type": "image_url",
                "image_url": {
                    "url": (
                        f"data:{context.image_file_type};base64,{img_b64}"
                    )
                }
            })

        
        client = openai_lib.OpenAI(api_key=key)
        response = client.chat.completions.create(
            model=openai_model,
            max_completion_tokens=max_tokens,
            response_format={"type": "json_object"},
            messages=[
                {
                    "role": "system",
                    "content": system_prompt
                },
                {
                    "role": "user", 
                    "content": user_content
                }
            ],
        )
        return response.choices[0].message.content.strip()

    elif provider == "ollama": # local model option 
        ollama_url = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434")
        ollama_model = os.getenv("OLLAMA_MODEL", "llama3")

        user_content = {"role": "user",
                        "content": user_prompt}
        if img_b64:
            user_content["images"] = [img_b64]

        payload = json.dumps({
            "model": ollama_model,
            "format": "json",
            "messages": [
                {
                    "role": "system",
                    "content": system_prompt
                },
                user_content
            ],
            "stream": False,
            "options": {
                "temperature": 0.1,
                "num_predict": max_tokens,
                "num_ctx": 4096
            }
        }).encode("utf-8")
        req = urllib.request.Request(
            f"{ollama_url}/api/chat",
            data=payload,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=600) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return data["message"]["content"].strip()

    else:
        raise ValueError(f"Unknown AI_PROVIDER: '{provider}'. Must be anthropic, openai, or ollama.")


def analyze_requirements_typed(requirements: List[Dict], criteria_type: str, context: AnalysisContext, provider: str = None, api_key: str = None) -> Dict:
    criteria_order = [c["criterion_id"] for c in (
                CONTEXTUAL_CRITERIA 
                if criteria_type == "contextual" 
                else STRUCTURAL_CRITERIA)]

    call_context = None
    try:
        if criteria_type == "structural":
            system_prompt = _build_structural_prompt(requirements)
            user_prompt = _build_requirement_prompt(requirements)

        elif criteria_type == "contextual":
            system_prompt = _build_contextual_prompt(requirements)
            user_prompt = f"{_build_context_prompt(context)}\n{_build_requirement_prompt(requirements)}"
            call_context = context # pass in context only to contextual 
        else: 
            return _error_result(requirements, f"Invalid criteria type", criteria_order)
        
        result_text = _call_ai(user_prompt, system_prompt, len(requirements), provider, api_key, call_context)
        if result_text.startswith("```"):
            lines = result_text.split("\n")
            inner = lines[1:]
            if inner and inner[-1].strip() == "```":
                inner = inner[:-1]
            result_text = "\n".join(inner)

        result = json.loads(result_text)
        evals = result.get("individualEvaluations", {})

        req_text_by_id = {r["id"]: r["text"] for r in requirements}
        overall_evaluation = {}
        expected_reqs = {r["id"] for r in requirements}
        present_reqs = set()

        for req_id in evals:
            cleaned = []
            present = set()
            if req_id not in expected_reqs: 
                continue # discard invalid requirements 
            present_reqs.add(req_id)
            curr_evals = evals[req_id]
            for ev in curr_evals:
                cid = ev.get("criterion_id", "")
                if cid not in criteria_order:
                    continue
                present.add(cid)

                affected_text = ev.get("affected_text") or None

                suggested = ev.get("suggested_replacement") or None
                # Fallback: if violated but no suggestion, flag it clearly
                if not suggested:
                    suggested = "[No suggestion provided — review manually]"

                cleaned.append({
                    "criterion_id": cid,
                    "criterion_name": CRITERIA_NAMES.get(cid, ""),
                    "explanation": ev.get("explanation", ""),
                    "satisfied": False,
                    "affected_text": affected_text,
                    "suggested_replacement": suggested,
                })
            for cid in criteria_order:
                if cid not in present:
                    cleaned.append({
                        "criterion_id": cid,
                        "criterion_name": CRITERIA_NAMES.get(cid, ""),
                        "satisfied": True,
                        "explanation": "No violation found.",
                        "affected_text": None,
                        "suggested_replacement": None,
                    })
            cleaned.sort(key=lambda e: criteria_order.index(e["criterion_id"]))

            overall_evaluation[req_id] = {"req_id": req_id,
                                             "original_text": req_text_by_id[req_id],
                                             "criteria_evaluations": cleaned}
            
        missing_reqs = expected_reqs - present_reqs
        for missing in missing_reqs: # return an error for each requirement that the AI missed
            overall_evaluation[missing] = _req_missing_result(missing, req_text_by_id[missing], criteria_order)

        return overall_evaluation

    except json.JSONDecodeError as e:
        return _error_result(requirements, f"Failed to parse AI response: {e}", criteria_order)
    except Exception as e:
        print("error: ", str(e))
        return _error_result(requirements, f"Analysis failed: {e}", criteria_order)

def _req_missing_result(req_id: str, text: str, criteria: list[Dict]) -> Dict:
    return {
        "req_id": req_id,
        "original_text": text,
        "criteria_evaluations": [
            {
                "criterion_id": cid,
                "criterion_name": CRITERIA_NAMES.get(cid, ""),
                "satisfied": True,
                "explanation": "Could not evaluate — analysis failed.",
                "affected_text": None,
                "suggested_replacement": None,
            }
            for cid in criteria
        ],
    }

def _error_result(requirements: List[Dict], error_msg: str, criteria: list[Dict]) -> Dict:
    return {
        requirement["id"] : {     
            "req_id": requirement["id"],
            "original_text": requirement["text"],
            "error": error_msg,
            "criteria_evaluations": [
                {
                    "criterion_id": cid,
                    "criterion_name": CRITERIA_NAMES.get(cid, ""),
                    "satisfied": True,
                    "explanation": "Could not evaluate — analysis failed.",
                    "affected_text": None,
                    "suggested_replacement": None,
                }
                for cid in criteria
            ],
            "suggested_full_text": requirement["text"],
        } for requirement in requirements
        
    }


def _batch_requirements(requirements: List[Dict],
    criteria_type: str,
    context: AnalysisContext,
    provider: str = None,
    api_key: str = None,
    batch_size: int = 10) -> Dict:

    batches = [requirements[i:i+batch_size] for i in range(0, len(requirements), batch_size)]

    combined_results = {}

    for batch_number, batch in enumerate(batches, start=1):
        print(
            f"{criteria_type} batch "
            f"{batch_number}/{len(batches)} "
            f"({len(batch)} requirements)"
        )

        batch_result = analyze_requirements_typed(
            batch,
            criteria_type,
            context,
            provider,
            api_key,
        )

        combined_results.update(batch_result)

    return combined_results



def analyze_all_requirements(
    requirements: List[Dict],
    context: AnalysisContext,
    session_id: str = None,
    provider: str = None,
    api_key: str = None,
) -> Dict:
    """Calls LLM in parallel for online API services (Claude, OpenAI), and calls sequentially for Ollama. Ollama does
    not use parallelization for performance reasons, as well as to improve local prompt caching."""
    if not session_id:
        session_id = str(uuid.uuid4())[:8]

    analyzed: List[Optional[Dict]] = [None] * len(requirements)

    if not requirements:
         return {
                "session_id": session_id,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "context": context.system_context,
                "conops": context.conops,
                "requirements": analyzed,
            }

    actual_provider = (provider or get_provider()).lower()
    # no parallelization for ollama 
    if actual_provider == "ollama":
        num_workers = 1
    else: 
        num_workers = 2

    BATCH_SIZE = 2

    with ThreadPoolExecutor(max_workers=num_workers) as executor:
        structural_future = executor.submit(_batch_requirements, requirements, "structural", context, provider, api_key, BATCH_SIZE)
        contextual_future = executor.submit(_batch_requirements, requirements, "contextual", context, provider, api_key, BATCH_SIZE)

        try: 
            structural_result = structural_future.result()
            contextual_result = contextual_future.result()
            # add results together and add to analyzed 
            analyzed = _merge_result_categories(requirements, structural_result, contextual_result)
            for req in analyzed:
                n = sum(1 for ev in req.get("criteria_evaluations", []) if not ev.get("satisfied", True))
                print(f"  [{req['req_id']}] done — {n} criteria violated")
        except Exception as e:
            analyzed = list(_error_result(requirements, str(e), [cid for cid in CRITERIA_ORDER if cid not in ("A1", "A11")]).values())

    return {
        "session_id": session_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "context": context.system_context,
        "conops": context.conops,
        "requirements": analyzed,
    }

def _merge_result_categories(requirements, structural_result, contextual_result):
    merged = []
    for requirement in requirements:
        req_id = requirement["id"]

        structural = structural_result.get(req_id, {})
        contextual = contextual_result.get(req_id, {})
        structural_evals = structural.get("criteria_evaluations", [])
        contextual_evals = contextual.get("criteria_evaluations", [])
        evaluations = structural_evals + contextual_evals

        # error system needs to be reworked, I put this here, but the error field is not being used 
        errors = []
        if structural.get("error"):
            errors.append(structural["error"])
        if contextual.get("error"):
            errors.append(contextual["error"])

        has_violation = any(not ev.get("satisfied", True) for ev in evaluations)
        if not has_violation and not errors: # A1 if no violations
            a1 = CRITERIA["A1"]
            evaluations = [{
                "criterion_id": "A1",
                "criterion_name": a1["name"],
                "satisfied": True,
                "explanation": "No violations found.",
                "affected_text": None,
                "suggested_replacement": None
            }]

        evaluations.sort(key=lambda e: CRITERIA_ORDER.index(e["criterion_id"]) if e["criterion_id"] in CRITERIA_ORDER else len(CRITERIA_ORDER))

        result = {
            "req_id": req_id,
            "original_text": requirement["text"],
            "criteria_evaluations": evaluations,
        }

        if errors:
            result["error"] = " | ".join(errors)

        merged.append(result)
    return merged