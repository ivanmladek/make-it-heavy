# Hands-On Projects for Competition Preparation

## Project 1: Referential Game with Emergent Language

### Setup
- Create environment with 2-3 agents
- Task: One agent (sender) sees target object, sends message
- Other agent (receiver) maps message to correct object from choices

### Implementation Approach
```python
import torch
import torch.nn as nn
import numpy as np
from collections import deque

class EmergentLanguageGame:
    def __init__(self, num_objects=10, message_length=5, vocab_size=10):
        self.num_objects = num_objects
        self.message_length = message_length
        self.vocab_size = vocab_size
        
        # Initialize agents
        self.sender = SenderNetwork(num_objects, message_length * vocab_size)
        self.receiver = ReceiverNetwork(message_length * vocab_size, num_objects)
        
    def training_loop(self, num_episodes=10000):
        optimizer = torch.optim.Adam(
            list(self.sender.parameters()) + list(self.receiver.parameters()), 
            lr=0.001
        )
        
        success_history = deque(maxlen=1000)
        
        for episode in range(num_episodes):
            # Random target object
            target_obj = np.random.randint(self.num_objects)
            distractors = [
                np.random.choice([i for i in range(self.num_objects) if i != target_obj])
                for _ in range(np.random.randint(1, 4))
            ]
            
            # Sender generates message
            sender_logits = self.sender.forward(torch.eye(self.num_objects)[target_obj])
            message = torch.nn.functional.gumbel_softmax(
                sender_logits.view(-1, self.vocab_size), 
                tau=1.0, 
                hard=True
            ).flatten()
            
            # Receiver predicts from objects
            receiver_logits = self.receiver.forward(message)
            objects = [target_obj] + distractors
            prediction = receiver_logits[torch.tensor(objects)]
            
            # Calculate loss and update
            loss = self.bce_loss(prediction, torch.tensor([1.0] + [0.0] * len(distractors)))
            optimizer.zero_grad()
            loss.backward()
            optimizer.step()
            
            # Track success
            success = torch.argmax(prediction) == 0
            success_history.append(success.item())
            
            if episode % 1000 == 0:
                print(f"Episode {episode}: Success rate = {np.mean(success_history):.3f}")


## Project 2: Multi-Agent Cooperation Game
- Create 3-4 agents that must learn to communicate to solve coordination problem
- Implement curriculum learning starting with simple communication protocols
- Gradually increase complexity by adding constraints, noise, or adversaries

## Project 3: Language Evolution Simulator
- Create environment where agents evolve language over generations
- Track vocabulary emergence, syntax development, and semantic grounding
- Implement population dynamics: reproduction, mutation, selection pressure on communication

## Evaluation Metrics to Track
- **Communication accuracy**: How well messages achieve intended goals
- **Compression efficiency**: Message length vs information content
- **Convergence speed**: How quickly agents develop shared language
- **Robustness**: Performance under message corruption/time pressure
- **Generalization**: Does language work across novel combinations