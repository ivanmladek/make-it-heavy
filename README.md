# Multi-Agent Runner

This project implements a multi-agent system designed to explore emergent communication and collaborative problem-solving among AI agents. The system uses a round-robin architecture where four different AI models take turns communicating through a shared channel to solve an information-sharing game.

## Overview

The main implementation is in [`multi_agent_runner.py`](multi_agent_runner.py), which sets up an environment where four AI agents must collaborate to reconstruct a hidden 2x2 grid. Each cell in the grid has a color and shape, and each agent receives partial information about the grid. The agents must communicate effectively to share their knowledge and reconstruct the complete grid.

## Round-Robin Architecture

The system uses a round-robin scheduling approach where each agent takes turns in a fixed order:

```
Turn 1 → Agent 1 (Model 1)
          ↓
Turn 2 → Agent 2 (Model 2)
          ↓
Turn 3 → Agent 3 (Model 3)
          ↓
Turn 4 → Agent 4 (Model 4)
          ↓
Turn 5 → Agent 1 (Model 1)
          ↓
         ...
```

This continues for 24 turns, giving each agent 6 opportunities to contribute to solving the puzzle.

## AI Models Used

The system utilizes four different AI models, each with distinct capabilities:

1. **Model 1**: `moonshotai/kimi-k2`
   - A large language model from Moonshot AI
   - Used for Agent 1 in the round-robin sequence

2. **Model 2**: `openrouter/horizon-alpha`
   - An experimental model from OpenRouter
   - Used for Agent 2 in the round-robin sequence

3. **Model 3**: `qwen/qwen3-coder:free`
   - A coding-focused model from Tongyi Lab
   - Used for Agent 3 in the round-robin sequence

4. **Model 4**: `z-ai/glm-4.5`
   - A model from Zhipu AI
   - Used for Agent 4 in the round-robin sequence

## Game Mechanics

The agents participate in an asymmetric knowledge game where:

1. A hidden 2x2 grid is created with each cell having a color and shape
2. Each agent receives partial facts about the grid with some overlap and omissions
3. Agents communicate through a constrained channel with:
   - Bandwidth limitations (message length capped)
   - Noise injection (character drop probability)
   - Special handling for proposal messages
4. The goal is to reconstruct the complete grid through effective communication
5. Agents can propose solutions using a specific JSON format

## Communication Channel

The system uses a [`MessageChannel`](multi_agent_runner.py:18) class that:
- Limits message length to encourage concise communication
- Introduces noise to simulate real-world communication constraints
- Allows special proposal messages to bypass noise and bandwidth constraints
- Maintains a transcript of all communications

## Key Features

- **Emergent Communication**: Agents develop their own shorthand and protocols for efficient information sharing
- **Role Assignment**: Each agent has a specific role (Schema Guardian, Fact Broadcaster, Consistency Checker, Proposer/Closer)
- **Quorum System**: Requires multiple confirmations for facts before accepting them as canonical
- **Confidence Tracking**: Maintains confidence scores for different pieces of information
- **Adaptive Noise**: Noise levels change throughout the game to encourage protocol formation early and protect closure late

## Running the System

To run the multi-agent system:

1. Ensure you have the required dependencies installed (see [`requirements.txt`](requirements.txt))
2. Configure the models in [`config.yaml`](config.yaml)
3. Run the main script:
   ```bash
   python multi_agent_runner.py
   ```

The system will output the conversation transcript, channel statistics, and a final synthesized report analyzing the emergent communication patterns.