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
    """In-memory message bus with bandwidth cap and noise injection to encourage emergent shorthand."""
    def __init__(self, max_len: int = 120, char_drop_pct: float = 0.10, seed: Optional[int] = None):
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
                # drop char
                continue
            keep.append(ch)
        return "".join(keep)

    def send(self, agent_name: str, turn_index: int, raw_message: str):
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
        # Token reuse proxy: n-gram frequency
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
    - There is a hidden 2x2 grid with four cells having attributes Color and Shape.
    - Each agent privately sees 2-3 partial facts; collectively they can reconstruct the full grid mapping.
    Objective:
    - Agents must share and integrate info to output the complete mapping by the end of the round.
    """

    COLORS = ["Red", "Blue", "Green", "Yellow"]
    SHAPES = ["Circle", "Square", "Triangle", "Star"]
    CELLS = ["A1", "A2", "B1", "B2"]

    def __init__(self, seed: Optional[int] = None):
        self.rng = random.Random(seed)
        # Generate a random mapping: each cell has a color and shape (no duplicates by attribute set)
        self.solution: Dict[str, Dict[str, str]] = {}
        chosen_colors = self.rng.sample(self.COLORS, 4)
        chosen_shapes = self.rng.sample(self.SHAPES, 4)
        for idx, cell in enumerate(self.CELLS):
            self.solution[cell] = {
                "Color": chosen_colors[idx],
                "Shape": chosen_shapes[idx],
            }

    def sample_private_facts(self, n_agents: int = 4) -> List[List[str]]:
        """
        Produce asymmetric, partially overlapping fact sets per agent.
        Facts formatted simply to avoid prescribing protocol structure.
        """
        facts: List[str] = []
        # Generate atomic facts
        for cell, attrs in self.solution.items():
            facts.append(f"{cell}.Color={attrs['Color']}")
            facts.append(f"{cell}.Shape={attrs['Shape']}")
        self.rng.shuffle(facts)

        # Distribute with overlap
        per_agent: List[List[str]] = [[] for _ in range(n_agents)]
        for i, fact in enumerate(facts):
            per_agent[i % n_agents].append(fact)

        # Add noise: hide a few facts from random agents to enforce necessity of communication
        for agent_facts in per_agent:
            hide_k = self.rng.randint(1, 2)
            for _ in range(hide_k):
                if agent_facts:
                    agent_facts.pop(self.rng.randrange(0, len(agent_facts)))

        return per_agent

    def render_public_brief(self) -> str:
        return (
            "You are one of four autonomous agents collaborating to reconstruct a hidden 2x2 grid.\n"
            "Grid cells: A1, A2, B1, B2. Each cell has two attributes: Color and Shape.\n"
            "Goal: Share minimal, high-signal messages so the team can output the full mapping at the end.\n"
            "Constraints: You can only speak during your turn. Messages are capped and noised.\n"
            "Do not assume a fixed protocol; evolve concise, robust notation as needed.\n"
            "When ready to propose final mapping, output a single line starting with PROPOSE= followed by JSON."
        )

    def is_valid_proposal(self, text: str) -> Optional[Dict[str, Any]]:
        """
        Detects a final mapping proposal of the form:
        PROPOSE={"A1":{"Color":"Red","Shape":"Circle"}, ...}
        Returns parsed dict if valid JSON and structurally correct; else None.
        """
        marker = "PROPOSE="
        idx = text.find(marker)
        if idx == -1:
            return None
        payload = text[idx + len(marker):].strip()
        try:
            obj = json.loads(payload)
        except Exception:
            return None
        # weak structural check
        if not isinstance(obj, dict):
            return None
        for cell in self.CELLS:
            if cell not in obj:
                return None
            if not isinstance(obj[cell], dict):
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
        self.channel = MessageChannel(
            max_len=120,
            char_drop_pct=0.10,
            seed=seed,
        )
        # Prepare four model IDs from config
        om = self.config["openrouter"]
        self.model_ids = [
            om.get("model1"),
            om.get("model2"),
            om.get("model3"),
            om.get("model4"),
        ]
        # Initialize agents
        self.agents = [OpenRouterAgent(silent=True) for _ in range(4)]
        # Public brief once
        self.public_brief = self.env.render_public_brief()
        # Private facts
        self.private_facts = self.env.sample_private_facts(n_agents=4)
        # Turns
        self.turns_total = 8  # 2 full cycles of A1..A4
        self.names = ["Agent1", "Agent2", "Agent3", "Agent4"]

    def _build_prompt_for_agent(self, idx: int) -> str:
        """
        Construct the user message for the agent's turn, including:
        - Public brief
        - Their private facts
        - History (previous messages with noise already applied)
        - Constraints reminder
        - Explicit instruction to output either a concise message or a final PROPOSE line
        """
        history = self.channel.get_history_text()
        facts = "\n".join(self.private_facts[idx]) if self.private_facts[idx] else "(no private facts visible)"
        return (
            f"{self.public_brief}\n\n"
            f"YOUR PRIVATE FACTS:\n{facts}\n\n"
            f"TRANSCRIPT SO FAR (noised):\n{history if history else '(none)'}\n\n"
            "Instructions:\n"
            "- If you are not confident the team has enough info, send a short, information-dense message.\n"
            "- Prefer compact symbols/notation over verbose sentences when possible.\n"
            "- If you believe the team can now produce a complete mapping, output:\n"
            "  PROPOSE={\"A1\":{\"Color\":\"...\",\"Shape\":\"...\"},\"A2\":{...},\"B1\":{...},\"B2\":{...}}\n"
            "- Do not include any other text on the PROPOSE line.\n"
        )

    def _extract_first_line(self, text: str) -> str:
        # Use first assistant content block
        if not text:
            return ""
        # Keep as-is; bandwidth cap and noise applied by channel
        return text.strip()

    def play(self):
        print("=== Information Sharing and Integration: Console Game ===")
        print("Four agents will take turns. Messages are bandwidth-capped and noised to encourage emergent shorthand.\n")

        proposal_accepted = False
        proposal_best_score = 0.0
        proposal_best: Optional[Dict[str, Any]] = None

        for t in range(1, self.turns_total + 1):
            turn_idx = (t - 1) % 4
            agent = self.agents[turn_idx]
            model = self.model_ids[turn_idx]
            name = self.names[turn_idx]

            user_prompt = self._build_prompt_for_agent(turn_idx)
            # Run single-turn with the specified model; rely on agent.max_iterations but we only keep first response text
            reply_full = agent.run(user_prompt, model=model)
            reply_line = self._extract_first_line(reply_full)

            # Send through channel (applies cap and noise)
            self.channel.send(name, t, reply_line)

            # Check for a valid proposal inside the noised text (we must check raw to avoid JSON corruption by noise too)
            last_entry = self.channel.transcript[-1]
            candidate = self.env.is_valid_proposal(last_entry["raw"]) or self.env.is_valid_proposal(last_entry["noised"])
            if candidate:
                score = self.env.score_proposal(candidate)
                if score >= proposal_best_score:
                    proposal_best_score = score
                    proposal_best = candidate
                    if score == 1.0:
                        proposal_accepted = True
                        print("\nFinal mapping proposed with 100% score. Ending early.\n")
                        break

        # Round complete; if no perfect mapping, accept best-so-far if exists
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

        # Synthesis pass: reuse orchestrator to generate a final narrative summary using all four models
        try:
            orch = TaskOrchestrator(silent=True)
            # Provide a synthesis request that includes transcript and, if present, the best proposal and its score
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
    # Seed can be overridden via ENV if needed
    seed_env = os.getenv("EMERGENT_GAME_SEED")
    seed = int(seed_env) if seed_env and seed_env.isdigit() else None
    game = MultiAgentConsoleGame(config_path="config.yaml", seed=seed)
    game.play()


if __name__ == "__main__":
    main()