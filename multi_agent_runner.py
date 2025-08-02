import os
import json
import time
import random
import string
import yaml
import re
from typing import List, Dict, Any, Optional, Tuple, Set, DefaultDict
from collections import defaultdict
from agent import OpenRouterAgent
from orchestrator import TaskOrchestrator

# =========================
# Information Sharing and Integration Game (Console)
# Category D per competition brief
# =========================

class MessageChannel:
    """In-memory message bus with adjustable bandwidth cap and noise injection to encourage emergent shorthand.
       Proposals starting with PROPOSE= bypass noise/cap to avoid JSON corruption while keeping pressure on normal turns."""
    def __init__(self, max_len: int = 200, char_drop_pct: float = 0.05, seed: Optional[int] = None):
        self.max_len = max_len
        self.char_drop_pct = char_drop_pct
        self.rng = random.Random(seed)
        self.transcript: List[Dict[str, Any]] = []

    def _apply_bandwidth_cap(self, msg: str) -> str:
        if len(msg) > self.max_len:
            return msg[: self.max_len]
        return msg

    def _apply_noise(self, msg: str) -> str:
        if not msg:
            return msg
        keep = []
        for ch in msg:
            if ch in "\n\r\t":
                keep.append(ch)
                continue
            if self.rng.random() < self.char_drop_pct:
                continue
            keep.append(ch)
        return "".join(keep)

    def send(self, agent_name: str, turn_index: int, raw_message: str):
        # Proposal lane bypass remains for final PROPOSE line
        if raw_message.strip().startswith("PROPOSE="):
            capped = raw_message
            noised = raw_message
        else:
            capped = self._apply_bandwidth_cap(raw_message)
            noised = self._apply_noise(capped)
        entry = {
            "turn": turn_index,
            "from": agent_name,
            "raw": raw_message,
            "capped": capped,
            "noised": noised,
        }
        self.transcript.append(entry)
        print(f"[{agent_name}] {noised}")

    def get_history_text(self) -> str:
        lines = []
        for e in self.transcript:
            lines.append(f"{e['from']}@{e['turn']}: {e['noised']}")
        return "\n".join(lines)

    def stats(self) -> Dict[str, Any]:
        if not self.transcript:
            return {"avg_len": 0, "avg_len_raw": 0, "n_messages": 0}
        n = len(self.transcript)
        avg_len = sum(len(e["noised"]) for e in self.transcript) / n
        avg_len_raw = sum(len(e["raw"]) for e in self.transcript) / n
        text = " ".join(e["noised"] for e in self.transcript)
        tokens = text.split()
        unig = {}
        for t in tokens:
            unig[t] = unig.get(t, 0) + 1
        top_terms = sorted(unig.items(), key=lambda x: x[1], reverse=True)[:10]
        return {
            "n_messages": n,
            "avg_len": avg_len,
            "avg_len_raw": avg_len_raw,
            "top_terms": top_terms,
        }


class InfoSharingEnvironment:
    """
    Asymmetric knowledge game:
    - Hidden 2x2 grid: A1, A2, B1, B2 each has Color and Shape.
    - Each agent privately sees partial facts with overlap and omissions.
    Objective:
    - Evolve concise notation and propose full grid via PROPOSE=JSON.
    """

    COLORS = ["Red", "Blue", "Green", "Yellow"]
    SHAPES = ["Circle", "Square", "Triangle", "Star"]
    CELLS = ["A1", "A2", "B1", "B2"]

    def __init__(self, seed: Optional[int] = None):
        self.rng = random.Random(seed)
        self.solution: Dict[str, Dict[str, str]] = {}
        chosen_colors = self.rng.sample(self.COLORS, 4)
        chosen_shapes = self.rng.sample(self.SHAPES, 4)
        for idx, cell in enumerate(self.CELLS):
            self.solution[cell] = {"Color": chosen_colors[idx], "Shape": chosen_shapes[idx]}
        # Canonicalization maps (edit-distance-1/common typos)
        self.color_alias = {
            "Yelow": "Yellow",
            "Ble": "Blue",
            "Gree": "Green",
            "Gren": "Green",
            "Blu": "Blue",
            "Redd": "Red",
            "Rd": "Red",
        }
        self.shape_alias = {
            "Sqare": "Square",
            "Suare": "Square",
            "Tri": "Triangle",
            "Triange": "Triangle",
            "Trangle": "Triangle",
            "Tiagle": "Triangle",
            "Hexagn": "Hexagon",
            "Hexagone": "Hexagon",
            "Circl": "Circle",
            "Circlee": "Circle",
        }

    def sample_private_facts(self, n_agents: int = 4) -> List[List[str]]:
        facts: List[str] = []
        for cell, attrs in self.solution.items():
            facts.append(f"{cell}.C={attrs['Color']}")
            facts.append(f"{cell}.S={attrs['Shape']}")
        self.rng.shuffle(facts)
        per_agent: List[List[str]] = [[] for _ in range(n_agents)]
        for i, fact in enumerate(facts):
            per_agent[i % n_agents].append(fact)
        for agent_facts in per_agent:
            hide_k = self.rng.randint(1, 2)
            for _ in range(hide_k):
                if agent_facts:
                    agent_facts.pop(self.rng.randrange(0, len(agent_facts)))
        return per_agent

    def render_public_brief(self) -> str:
        return (
            "You are 1 of 4 agents coordinating to reconstruct a 2x2 grid: A1, A2, B1, B2.\n"
            "Each cell has Color (C) and Shape (S). Communicate using concise notation.\n"
            "Suggested compact schema: cell.attr=value (e.g., A2.C=Red, B1.S=Circle). Use ? for unknown.\n"
            "Constraint: Turn-taking. Messages are capped and slightly noised. Evolve robust shorthand.\n"
            "To propose a final solution, output a single line starting with:\n"
            "PROPOSE={\"A1\":{\"Color\":\"...\",\"Shape\":\"...\"},\"A2\":{...},\"B1\":{...},\"B2\":{...}}\n"
        )

    def _canon_value(self, slot: str, value: str) -> Optional[str]:
        if slot.endswith(".C") or slot == "Color":
            if value in self.COLORS:
                return value
            return self.color_alias.get(value, None)
        if slot.endswith(".S") or slot == "Shape":
            if value in self.SHAPES:
                return value
            return self.shape_alias.get(value, None)
        return value

    def is_valid_proposal(self, text: str) -> Optional[Dict[str, Any]]:
        marker = "PROPOSE="
        idx = text.find(marker)
        if idx == -1:
            return None
        payload = text[idx + len(marker):].strip()
        try:
            obj = json.loads(payload)
        except Exception:
            return None
        if not isinstance(obj, dict):
            return None
        for cell in self.CELLS:
            if cell not in obj or not isinstance(obj[cell], dict):
                return None
            if "Color" not in obj[cell] or "Shape" not in obj[cell]:
                return None
            # Canonicalize proposal enums if they are aliasable
            col = obj[cell].get("Color")
            shp = obj[cell].get("Shape")
            col_c = self._canon_value("Color", col) or col
            shp_c = self._canon_value("Shape", shp) or shp
            obj[cell]["Color"] = col_c
            obj[cell]["Shape"] = shp_c
        return obj

    def score_proposal(self, proposal: Dict[str, Any]) -> float:
        correct = 0
        total = len(self.CELLS) * 2
        for cell in self.CELLS:
            if proposal[cell].get("Color") == self.solution[cell]["Color"]:
                correct += 1
            if proposal[cell].get("Shape") == self.solution[cell]["Shape"]:
                correct += 1
        return correct / total


class MultiAgentConsoleGame:
    def __init__(self, config_path: str = "config.yaml", seed: Optional[int] = None):
        with open(config_path, "r") as f:
            self.config = yaml.safe_load(f)
        self.env = InfoSharingEnvironment(seed=seed)
        # Relax constraints: longer cap, less noise to allow richer protocols to form, plus proposal bypass
        self.channel = MessageChannel(max_len=200, char_drop_pct=0.05, seed=seed)
        om = self.config["openrouter"]
        self.model_ids = [om.get("model1"), om.get("model2"), om.get("model3"), om.get("model4")]
        self.agents = [OpenRouterAgent(silent=True) for _ in range(4)]
        self.public_brief = self.env.render_public_brief()
        self.private_facts = self.env.sample_private_facts(n_agents=4)
        self.turns_total = 24
        self.names = ["Agent1", "Agent2", "Agent3", "Agent4"]
        self.schema_locked = False
        self.schema_votes = 0
        self.canonical_schema = "A1.C,A1.S|A2.C,A2.S|B1.C,B1.S|B2.C,B2.S"

        # Server-side canonical state and confirmation tracking
        # canonical_state: slot -> value (e.g., "A1.C" -> "Green")
        self.canonical_state: Dict[str, Optional[str]] = {
            f"{cell}.C": None for cell in self.env.CELLS
        }
        self.canonical_state.update({f"{cell}.S": None for cell in self.env.CELLS})
        # confirmations: slot -> value -> set of agent names confirming
        self.confirmations: DefaultDict[str, DefaultDict[str, Set[str]]] = defaultdict(lambda: defaultdict(set))
        # shadow candidate from PREPARE_* detection
        self.shadow_candidate: Optional[Dict[str, Any]] = None
        # last machine feedback to include in prompts
        self.last_feedback: str = ""

    def _maybe_lock_schema(self, text: str):
        if "SCHEMA" in text.upper():
            self.schema_votes += 1
        if not self.schema_locked and self.schema_votes >= 3:
            self.schema_locked = True

    def _build_prompt_for_agent(self, idx: int) -> str:
        history = self.channel.get_history_text()
        facts = "\n".join(self.private_facts[idx]) if self.private_facts[idx] else "(no private facts visible)"
        lock_hint = ""
        if self.schema_locked:
            lock_hint = (
                f"\nSCHEMA LOCKED: Use canonical keys exactly: {self.canonical_schema}.\n"
                "Normalize malformed keys to this schema before sending.\n"
                "Repeat any newly asserted slot exactly twice in your next turn."
            )
        # Light role alignment (no structural change)
        role_map = {
            0: "ROLE=Schema Guardian + Aggregator",
            1: "ROLE=Fact Broadcaster",
            2: "ROLE=Consistency Checker",
            3: "ROLE=Proposer/Closer",
        }
        role_hint = role_map.get(idx, "")
        late_emphasis = (
            "- Late-turn emphasis (turns 20–22): Focus only on ONE unknown slot; do not restate known slots except to confirm a change.\n"
            "- Near-final check (turns 20–22): emit a compact table with status tags [OK/UNK/REVISE]:\n"
            "  TABLE: A1.C=?, A1.S=?, A2.C=?, A2.S=?, B1.C=?, B1.S=?, B2.C=?, B2.S=?\n"
            "  Then push the Closer to issue PREPARE_PROPOSAL on the next turn and final PROPOSE= after that.\n"
        )
        pre_proposal_contract = (
            "Proposal contract:\n"
            "- Before issuing PROPOSE=, the Proposer/Closer must verify:\n"
            "  * All 8 slots listed with status [OK] (no UNK/REVISE).\n"
            "  * Each slot has TWO independent confirmations (not counting the original proposer).\n"
            "- Use PREPARE_PROPOSAL={...} one turn BEFORE the final proposal (this line will be noised).\n"
            "- On the NEXT turn, issue the final PROPOSE= JSON (this line is un-noised and must be the only content on the line).\n"
        )
        one_slot_assignments = (
            "One-slot repair loop (when ≥6/8 slots are [OK]):\n"
            "- Assign responsibilities explicitly for the remaining unknowns, e.g.:\n"
            "  * Agent2: provide best evidence for B2.S\n"
            "  * Agent3: request/confirm B2.S from Agent2\n"
            "  * Agent1: recheck table and mark B2.S [OK/REVISE]\n"
            "  * Agent4 (Closer): prepare PREPARE_PROPOSAL if all [OK] next turn\n"
        )
        mid_game_feedback = (
            "Mid-game feedback rule:\n"
            "- After any PREPARE_PROPOSAL or malformed PROPOSE, reflect explicitly on the very next turn which slots are correct/incorrect in plain language, then update the table and proceed with the one-slot repair loop.\n"
        )
        # Compose CANONICAL_STATE and QUORUM_STATUS blocks for stronger closure pressure
        canonical_lines = []
        for cell in self.env.CELLS:
            c = self.canonical_state[f"{cell}.C"] or "?"
            s = self.canonical_state[f"{cell}.S"] or "?"
            canonical_lines.append(f"{cell}.C={c} | {cell}.S={s}")
        canonical_block = "CANONICAL_STATE:\n" + "\n".join(canonical_lines)

        quorum_lines = []
        for cell in self.env.CELLS:
            for attr, key in [("Color", f"{cell}.C"), ("Shape", f"{cell}.S")]:
                cur = self.canonical_state[key]
                if cur:
                    count = len(self.confirmations[key][cur])
                    quorum_lines.append(f"{key}={cur} quorum={count}")
                else:
                    quorum_lines.append(f"{key}=? quorum=0")
        quorum_block = "QUORUM_STATUS:\n" + "\n".join(quorum_lines)

        forced_finalization_hint = ""
        if self._quorum_all_met():
            forced_finalization_hint = "\nFORCED_FINALIZATION: All quorums met. If you are Agent4 on turn 23, you MUST issue the final PROPOSE= JSON exactly as per canonical state.\n"

        # Create machine feedback string separately to avoid backslash issue in f-string
        if self.last_feedback:
            machine_feedback = "MACHINE_FEEDBACK:\n" + self.last_feedback + "\n\n"
        else:
            machine_feedback = ""
            
        return (
            f"{self.public_brief}\n"
            f"{role_hint}\n"
            f"YOUR PRIVATE FACTS:\n{facts}\n\n"
            f"TRANSCRIPT SO FAR (noised):\n{history if history else '(none)'}\n\n"
            f"{canonical_block}\n\n"
            f"{quorum_block}\n\n"
            f"{machine_feedback}"
            "Guidance:\n"
            "- Only state NEW or CORRECTED facts; avoid repeating unchanged items.\n"
            "- Use compact schema (A1.C=Red | B2.S=Star). Use '|' as a separator.\n"
            "- When you share a NEW slot, REPEAT it exactly twice in your next turn for robustness.\n"
            "- Confirm slotwise using 'CONFIRM cell.attr=value' (e.g., 'CONFIRM B1.S=Circle'); avoid generic OK.\n"
            "- Always list Unknown fields at the end, ordered by importance: 'UNKNOWN: A1.S, B2.C, ...'.\n"
            "- Turn budgeting:\n"
            "  * Early (turns 1–6): dump private facts compactly.\n"
            "  * Mid (turns 7–16): consolidate + confirm; focus only on Unknown list.\n"
            "  * Late (turns 17+): if ≥7/8 known, Closer attempts PREPARE_PROPOSAL then PROPOSE=; else focus one-slot-per-turn.\n"
            "- After any proposal (even partial), reflect back slotwise correctness as DELTA corrections next turn.\n"
            f"{late_emphasis}"
            f"{one_slot_assignments}"
            f"{pre_proposal_contract}"
            f"{mid_game_feedback}"
            "- When enough info is shared, output a single PROPOSE=... JSON line with no extra text.\n"
            f"{lock_hint}"
            f"{forced_finalization_hint}"
        )

    def _extract_first_line(self, text: str) -> str:
        return (text or "").strip()

    # === New helpers: parsing, canonicalization, quorum, and feedback ===

    def _parse_claims_and_confirms(self, speaker: str, text: str) -> List[Tuple[str, str, str]]:
        """
        Parse claims and confirmations in compact form:
        - Direct claim: A1.C=Green or A2.S=Circle
        - Confirmation: CONFIRM A1.C=Green
        Returns list of (kind, slot, value) where kind in {"CLAIM","CONFIRM"}.
        """
        results: List[Tuple[str, str, str]] = []
        if not text:
            return results
        # Normalize whitespace
        t = text.replace("\n", " ")
        # Confirmations
        for m in re.finditer(r"\bCONFIRM\s+([AB][12])\.(C|S)\s*=\s*([A-Za-z]+)", t, flags=re.IGNORECASE):
            cell, attr, val = m.group(1).upper(), m.group(2).upper(), m.group(3)
            slot = f"{cell}.{attr}"
            val = val.capitalize()
            canon = self.env._canon_value(slot, val)
            if canon:
                results.append(("CONFIRM", slot, canon))
        # Direct claims (avoid matching inside CONFIRM we already captured)
        for m in re.finditer(r"\b([AB][12])\.(C|S)\s*=\s*([A-Za-z]+)", t):
            cell, attr, val = m.group(1).upper(), m.group(2).upper(), m.group(3)
            slot = f"{cell}.{attr}"
            val = val.capitalize()
            canon = self.env._canon_value(slot, val)
            if canon:
                results.append(("CLAIM", slot, canon))
        return results

    def _update_canonical_and_quorum(self, speaker: str, parsed: List[Tuple[str, str, str]]):
        for kind, slot, value in parsed:
            if kind == "CLAIM":
                # adopt claim as tentative canonical if empty; don't override a different non-empty value
                if self.canonical_state.get(slot) is None:
                    self.canonical_state[slot] = value
            elif kind == "CONFIRM":
                self.confirmations[slot][value].add(speaker)
                # ensure canonical aligns to the most-confirmed value
                current = self.canonical_state.get(slot)
                if current is None:
                    self.canonical_state[slot] = value
                else:
                    # if confirmations favor another value, switch
                    counts = {val: len(peers) for val, peers in self.confirmations[slot].items()}
                    best_val = max(counts.items(), key=lambda x: x[1])[0]
                    if best_val != current and counts[best_val] >= 2:
                        self.canonical_state[slot] = best_val

    def _quorum_for_slot(self, slot: str) -> int:
        val = self.canonical_state.get(slot)
        if not val:
            return 0
        return len(self.confirmations[slot][val])

    def _quorum_all_met(self) -> bool:
        for cell in self.env.CELLS:
            for key in (f"{cell}.C", f"{cell}.S"):
                if self._quorum_for_slot(key) < 2:
                    return False
        return True

    def _parse_table_update(self, text: str):
        """
        Parse TABLE lines like:
        TABLE: A1.C=Green [OK], A1.S=Square [OK], ...
        Update canonical_state when [OK] is present.
        """
        if "TABLE:" not in text:
            return
        line = text.split("TABLE:", 1)[1]
        # Split on commas
        parts = re.split(r"[,\n]+", line)
        for p in parts:
            m = re.search(r"\b([AB][12])\.(C|S)\s*=\s*([A-Za-z]+)\s*\[(OK|UNK|REVISE)\]", p, flags=re.IGNORECASE)
            if not m:
                continue
            cell, attr, val, status = m.group(1).upper(), m.group(2).upper(), m.group(3), m.group(4).upper()
            slot = f"{cell}.{attr}"
            val = val.capitalize()
            canon = self.env._canon_value(slot, val)
            if canon and status == "OK":
                # adopt as canonical and treat as an implicit confirmation by "TABLE"
                self.canonical_state[slot] = canon
                self.confirmations[slot][canon].add("TABLE")

    def _detect_prepare_candidate(self, text: str) -> Optional[Dict[str, Any]]:
        """
        Detect PREPARE_* lines with fuzzy prefix and try to extract JSON payload if present.
        Accepts variants like PREPAREPROPOSAL, PREPARE_PROPOSAL, PREPARE-PROPOSAL, PREPARE_POPOSAL, etc.
        """
        if not text:
            return None
        if re.search(r"\bPREPARE[-_ ]?PROPOSAL", text, flags=re.IGNORECASE) is None:
            return None
        m = re.search(r"\{.*\}", text, flags=re.DOTALL)
        if not m:
            return None
        try:
            obj = json.loads(m.group(0))
        except Exception:
            return None
        # Canonicalize if possible
        try:
            for cell in self.env.CELLS:
                if cell in obj and isinstance(obj[cell], dict):
                    c = obj[cell].get("Color")
                    s = obj[cell].get("Shape")
                    c2 = self.env._canon_value("Color", c) or c
                    s2 = self.env._canon_value("Shape", s) or s
                    obj[cell]["Color"] = c2
                    obj[cell]["Shape"] = s2
        except Exception:
            pass
        return obj

    def _machine_feedback_after_prepare_or_malformed(self, candidate: Optional[Dict[str, Any]]):
        """
        Produce slot-by-slot correctness and quorum needs.
        """
        lines = []
        if candidate:
            lines.append("Feedback on PREPARE_PROPOSAL candidate:")
            score = self.env.score_proposal(candidate)
            lines.append(f"- Candidate score vs solution: {score*100:.1f}%")
            for cell in self.env.CELLS:
                want_c = self.env.solution[cell]["Color"]
                want_s = self.env.solution[cell]["Shape"]
                got_c = candidate.get(cell, {}).get("Color")
                got_s = candidate.get(cell, {}).get("Shape")
                lines.append(f"  {cell}.C: want={want_c} got={got_c} -> {'OK' if want_c==got_c else 'REVISE'}")
                lines.append(f"  {cell}.S: want={want_s} got={got_s} -> {'OK' if want_s==got_s else 'REVISE'}")
        else:
            lines.append("Malformed PROPOSE detected or PREPARE without JSON; focusing repair.")
        # Quorum needs
        needs = []
        for cell in self.env.CELLS:
            for key in (f"{cell}.C", f"{cell}.S"):
                val = self.canonical_state.get(key)
                q = self._quorum_for_slot(key)
                if val and q < 2:
                    # find who hasn't confirmed yet
                    confirmers = self.confirmations[key][val]
                    missing = [n for n in self.names if n not in confirmers]
                    needs.append((key, val, q, missing))
        if needs:
            lines.append("Quorum needs (require 2 independent confirmations per slot):")
            for key, val, q, missing in needs:
                # Prefer next agent by turn order, but we list candidates
                lines.append(f"- Need confirmation for {key}={val} (quorum={q}). Candidates: {', '.join(missing)}")
        else:
            lines.append("All quorums satisfied; ready for final PROPOSE on Agent4 turn 23.")
        self.last_feedback = "\n".join(lines)

    def play(self):
        print("=== Information Sharing and Integration: Console Game ===")
        print("Relaxed bandwidth/noise and extended turns to encourage emergent protocol formation.\n")
        # Reset machine feedback at start
        self.last_feedback = ""

        proposal_best_score = 0.0
        proposal_best: Optional[Dict[str, Any]] = None

        for t in range(1, self.turns_total + 1):
            # Dynamic noise schedule: stabilize early, test robustness mid, protect closure late
            if t <= (self.turns_total // 2):
                self.channel.char_drop_pct = 0.03     # early: stabilize
            elif t <= (self.turns_total - 4):
                self.channel.char_drop_pct = 0.05     # mid: robustness
            else:
                self.channel.char_drop_pct = 0.01     # late closure: ultra-low noise for confirmations/proposals

            turn_idx = (t - 1) % 4
            agent = self.agents[turn_idx]
            model = self.model_ids[turn_idx]
            name = self.names[turn_idx]

            user_prompt = self._build_prompt_for_agent(turn_idx)
            reply_full = agent.run(user_prompt, model=model)
            reply_line = self._extract_first_line(reply_full)
            # Parse TABLE to update canonical state
            self._parse_table_update(reply_line)
            # Parse claims and confirmations; update quorum/canonical
            parsed = self._parse_claims_and_confirms(name, reply_line)
            self._update_canonical_and_quorum(name, parsed)

            self._maybe_lock_schema(reply_line)
            self.channel.send(name, t, reply_line)

            # Detect PREPARE_* candidate or malformed PROPOSE to generate machine feedback
            prepare_obj = self._detect_prepare_candidate(reply_line)
            propose_obj = self.env.is_valid_proposal(reply_line) or self.env.is_valid_proposal(self.channel.transcript[-1]["noised"])
            malformed_propose = (("PROPOSE=" in reply_line) and (propose_obj is None))
            if prepare_obj is not None:
                self.shadow_candidate = prepare_obj
                self._machine_feedback_after_prepare_or_malformed(self.shadow_candidate)
            elif malformed_propose:
                self._machine_feedback_after_prepare_or_malformed(None)
            else:
                # Clear feedback unless we are still missing quorum
                if not self._quorum_all_met():
                    # maintain last feedback to keep pressure
                    pass
                else:
                    self.last_feedback = ""

            last_entry = self.channel.transcript[-1]
            candidate = self.env.is_valid_proposal(last_entry["raw"]) or self.env.is_valid_proposal(last_entry["noised"])
            # Enforce quorum: accept proposal only if quorum satisfied for all slots
            if candidate and self._quorum_all_met():
                score = self.env.score_proposal(candidate)
                if score >= proposal_best_score:
                    proposal_best_score = score
                    proposal_best = candidate
                if score == 1.0:
                    print("\nPerfect proposal received. Ending early.\n")
                    break
            elif candidate and not self._quorum_all_met():
                # Reject proposal silently but produce targeted feedback
                self._machine_feedback_after_prepare_or_malformed(candidate)

            # Forced finalization directive: if by end of turn 22 quorums are met, force Agent4 to propose on 23
            if t == 22 and self._quorum_all_met():
                self.last_feedback = "All slots have quorum≥2. Agent4 must issue final PROPOSE= JSON on next turn using CANONICAL_STATE exactly."

        print("\n=== Round Complete ===\n")
        print("Transcript:")
        print(self.channel.get_history_text())
        print("\nChannel stats:")
        print(json.dumps(self.channel.stats(), indent=2))

        if proposal_best is not None:
            print("\nBest proposal received:")
            print(json.dumps(proposal_best, indent=2))
            print(f"Score: {proposal_best_score*100:.1f}%")
        else:
            print("\nNo valid proposal received.")

        try:
            orch = TaskOrchestrator(silent=True)
            synthesis_input = [
                "Synthesize the multi-agent interaction below into a concise final report that evaluates semantic/pragmatic emergent language properties (grounding, compositionality, consistency, efficiency, signaling/listening, symmetry).",
                "",
                "Transcript:",
                self.channel.get_history_text(),
                "",
                "Channel stats JSON:",
                json.dumps(self.channel.stats()),
            ]
            if proposal_best is not None:
                synthesis_input += [
                    "",
                    "Best Proposal JSON:",
                    json.dumps(proposal_best),
                    f"Score: {proposal_best_score*100:.1f}%",
                ]
            final_report = orch.orchestrate("\n".join(synthesis_input))
            print("\n=== Final Synthesized Report ===\n")
            print(final_report)
        except Exception as e:
            print(f"\n[WARN] Synthesis failed: {e}")


def main():
    seed_env = os.getenv("EMERGENT_GAME_SEED")
    seed = int(seed_env) if seed_env and seed_env.isdigit() else None
    game = MultiAgentConsoleGame(config_path="config.yaml", seed=seed)
    game.play()


if __name__ == "__main__":
    main()