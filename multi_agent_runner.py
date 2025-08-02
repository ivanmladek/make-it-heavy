import os
import json
import time
import random
import string
import yaml
from typing import List, Dict, Any, Optional
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
        return (
            f"{self.public_brief}\n"
            f"{role_hint}\n"
            f"YOUR PRIVATE FACTS:\n{facts}\n\n"
            f"TRANSCRIPT SO FAR (noised):\n{history if history else '(none)'}\n\n"
            "Guidance:\n"
            "- Only state NEW or CORRECTED facts; avoid repeating unchanged items.\n"
            "- Use compact schema (A1.C=Red | B2.S=Star). Use '|' as a separator.\n"
            "- When you share a NEW slot, REPEAT it exactly twice in your next turn for robustness.\n"
            "- Confirm slotwise using 'CONFIRM cell.attr=value' (e.g., 'CONFIRM B1.S=Circle'); avoid generic OK.\n"
            "- Always list Unknown fields at the end, ordered by importance: 'UNKNOWN: A1.S, B2.C, ...'.\n"
            "- Turn budgeting:\n"
            "  * Early (turns 1–6): dump private facts compactly.\n"
            "  * Mid (turns 7–16): consolidate + confirm; focus only on Unknown list.\n"
            "  * Late (turns 17+): if ≥7/8 known, Closer attempts PROPOSE=; else focus one-slot-per-turn.\n"
            "- Late-turn emphasis (turns 20–22): Focus only on ONE unknown slot; do not restate known slots except to confirm a change.\n"
            "- Near-final check (turns 20–22): emit a compact table with status tags [OK/UNK/REVISE]:\n"
            "  TABLE: A1.C=?, A1.S=?, A2.C=?, A2.S=?, B1.C=?, B1.S=?, B2.C=?, B2.S=?\n"
            "  Then push the Closer to issue PROPOSE=.\n"
            "- After any proposal (even partial), reflect back slotwise correctness as DELTA corrections next turn.\n"
            "- When enough info is shared, output a single PROPOSE=... JSON line with no extra text.\n"
            + lock_hint
        )

    def _extract_first_line(self, text: str) -> str:
        return (text or "").strip()

    def play(self):
        print("=== Information Sharing and Integration: Console Game ===")
        print("Relaxed bandwidth/noise and extended turns to encourage emergent protocol formation.\n")

        proposal_best_score = 0.0
        proposal_best: Optional[Dict[str, Any]] = None

        for t in range(1, self.turns_total + 1):
            # Dynamic noise schedule: stabilize early, test robustness later
            if t <= (self.turns_total // 2):
                self.channel.char_drop_pct = 0.03
            else:
                self.channel.char_drop_pct = 0.05

            turn_idx = (t - 1) % 4
            agent = self.agents[turn_idx]
            model = self.model_ids[turn_idx]
            name = self.names[turn_idx]

            user_prompt = self._build_prompt_for_agent(turn_idx)
            reply_full = agent.run(user_prompt, model=model)
            reply_line = self._extract_first_line(reply_full)

            self._maybe_lock_schema(reply_line)
            self.channel.send(name, t, reply_line)

            last_entry = self.channel.transcript[-1]
            candidate = self.env.is_valid_proposal(last_entry["raw"]) or self.env.is_valid_proposal(last_entry["noised"])
            if candidate:
                score = self.env.score_proposal(candidate)
                if score >= proposal_best_score:
                    proposal_best_score = score
                    proposal_best = candidate
                if score == 1.0:
                    print("\nPerfect proposal received. Ending early.\n")
                    break

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